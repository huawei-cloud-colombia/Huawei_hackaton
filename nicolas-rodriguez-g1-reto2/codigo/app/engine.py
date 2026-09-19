"""FlowMatchEngine - orquestador de las Fases 1, 2 y 3 (+ Bono A de lotes).

Concurrencia (Bono B): toda la seccion critica de decision (leer estado de
repartidores, aplicar reglas, reservar el cupo elegido, actualizar
contadores de ventana deslizante / avalancha / contencion) ocurre dentro de
un unico ``threading.RLock``. Se opto por un lock global de seccion critica
(en vez de reintentos optimistas o locks finos por repartidor) porque
garantiza correccion de forma simple y facil de auditar: no hay forma de que
dos hilos vean "hay cupo" para el mismo repartidor y ambos lo reserven. El
costo es que la decision se serializa entre pedidos concurrentes; para un
motor en memoria de un solo proceso, en el orden de microsegundos por
decision, es un compromiso razonable (ver ``README.md``, seccion
"Decisiones de diseño").

La llamada al servicio de tarifas (que simula latencia de red, Fase 3) se
hace deliberadamente **fuera** de ese lock, igual que la generacion de la
explicacion en lenguaje natural del Bono C (que puede llamar a GLM 5.2 por
red): ninguna operacion de I/O lenta debe bloquear las demas decisiones de
asignacion.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from .batch_optimizer import solve_batch_assignment
from .explainability import RejectionReporter
from .glm_client import GLMClient
from .pricing import PricingClient
from .rate_limiter import SlidingWindowRateLimiter, ZoneLoadTracker
from .rules_engine import compute_base_cost, reason, select_courier
from .state import CourierStateStore
from .surge_control import SurgeController
from .validation import validate_order

MAX_QUEUE_HISTORY = 500
MAX_REPORT_HISTORY = 200


class FlowMatchEngine:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.store = CourierStateStore()
        self.rate_limiter = SlidingWindowRateLimiter(
            window_seconds=config["rate_limit"]["window_seconds"],
            max_per_window=config["rate_limit"]["max_orders_per_courier"],
        )
        self.zone_tracker = ZoneLoadTracker(
            window_seconds=config["rate_limit"]["window_seconds"],
            avalanche_threshold=config["zones"].get("avalanche_threshold", 4),
        )
        self.surge = SurgeController(
            consecutive_threshold=config["surge"]["consecutive_saturation_threshold"],
            contention_duration_seconds=config["surge"]["contention_duration_seconds"],
        )
        self.pricing = PricingClient(config)
        self.glm = GLMClient(config)
        self.rejection_reporter = RejectionReporter(self.glm)

        self._lock = threading.RLock()
        self._reports_lock = threading.Lock()
        self.waiting_queue: deque[dict] = deque(maxlen=MAX_QUEUE_HISTORY)
        self.rejection_reports: deque[dict] = deque(maxlen=MAX_REPORT_HISTORY)

    # ------------------------------------------------------------------
    # Administracion / introspeccion
    # ------------------------------------------------------------------
    def reset_couriers(self, couriers: list[dict]) -> None:
        with self._lock:
            self.store.reset(couriers)
            self.waiting_queue.clear()

    def queue_snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.waiting_queue)

    def recent_rejection_reports(self, limit: int = 20) -> list[dict]:
        with self._reports_lock:
            items = list(self.rejection_reports)[-limit:]
        return list(reversed(items))

    def surge_status(self, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        return {
            "active": self.surge.is_active(now),
            "remaining_seconds": round(self.surge.remaining_seconds(now), 1),
            "current_streak": self.surge.current_streak(),
        }

    # ------------------------------------------------------------------
    # Nucleo Fase 1 + 2 + 3
    # ------------------------------------------------------------------
    def assign_single(self, order: dict, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        order_id = order.get("order_id", "UNKNOWN")

        errors = validate_order(order, now, self.config)
        if errors:
            result = self._build_result(order_id, "REJECTED", None, errors, None, None)
            self._report_if_rejected(order, result, self.store.snapshot())
            return result

        with self._lock:
            result, snapshot_for_report = self._decide_locked(order, now)

        if "_pending_pricing_base_cost" in result:
            result = self._finalize_pricing(result)

        if result["status"] == "REJECTED":
            self._report_if_rejected(order, result, snapshot_for_report)
        return result

    def _decide_locked(self, order: dict, now: float) -> tuple[dict, Optional[list[dict]]]:
        """Debe llamarse ya bajo ``self._lock``. Devuelve (resultado, snapshot_para_reporte)."""
        order_id = order["order_id"]
        priority = order["priority"]
        pickup_zone = order["pickup_zone"]
        surge_enabled = self.config["surge"].get("enabled", True)

        for c in order.get("couriers") or []:
            self.store.upsert_if_new(c["courier_id"], c["zone"], c["active_orders"], c["max_capacity"])

        # Contencion activa: los pedidos normal se rechazan de inmediato, sin
        # recorrer de nuevo la lista de repartidores.
        if surge_enabled and self.surge.is_active(now) and priority == "normal":
            remaining = self.surge.remaining_seconds(now)
            reasons = [reason("surge_window_active", f"contention window active, ~{remaining:.0f}s remaining")]
            result = self._build_result(order_id, "REJECTED", None, reasons, None, None)
            return result, self.store.snapshot()

        couriers_snapshot = self.store.snapshot()
        if not couriers_snapshot:
            reasons = [reason("no_couriers_available", "no hay repartidores registrados en el sistema")]
            result = self._build_result(order_id, "REJECTED", None, reasons, None, None)
            return result, couriers_snapshot

        selection = select_courier(
            order=order,
            couriers=couriers_snapshot,
            now=now,
            config=self.config,
            rate_limiter=self.rate_limiter,
            zone_tracker=self.zone_tracker,
        )

        if selection.courier is not None:
            reserved = self.store.try_reserve(selection.courier["courier_id"])
            if not reserved:
                # No deberia ocurrir: la seleccion y la reserva estan bajo el
                # mismo lock. Se deja como defensa en profundidad.
                reasons = selection.reasons + [
                    reason("reservation_conflict", "capacity changed unexpectedly during assignment; order queued")
                ]
                self._enqueue(order, now)
                result = self._build_result(order_id, "QUEUED", None, reasons, None, None)
                return result, None

            self.rate_limiter.record(selection.courier["courier_id"], now)
            self.zone_tracker.record(pickup_zone, now)
            self.surge.register_outcome(now, all_couriers_full=False)

            chosen_courier = selection.courier
            base_cost = compute_base_cost(order, chosen_courier, self.config["pricing"])
            result_reasons = selection.reasons
            result = self._build_result(
                order_id, "ASSIGNED", chosen_courier["courier_id"], result_reasons, None, None
            )
            result["_pending_pricing_base_cost"] = base_cost
            return result, None

        # No hay repartidor asignable en este pase.
        self.zone_tracker.record(pickup_zone, now)
        if surge_enabled:
            self.surge.register_outcome(now, all_couriers_full=selection.all_full)
        surge_now_active = surge_enabled and self.surge.is_active(now)

        if selection.all_full:
            if surge_now_active:
                if priority == "normal":
                    reasons = [
                        reason("capacity_ok", "0 couriers with free capacity"),
                        reason(
                            "surge_protection_active",
                            f"all couriers full, queue growing for "
                            f"{self.config['surge']['consecutive_saturation_threshold']} orders "
                            f"(window={self.config['surge']['contention_duration_seconds']}s)",
                        ),
                    ]
                    result = self._build_result(order_id, "REJECTED", None, reasons, None, None)
                    return result, self.store.snapshot()
                reasons = [
                    reason("capacity_ok", "0 couriers with free capacity"),
                    reason("queued_express_during_contention", "express order attempts to queue despite active contention"),
                ]
                self._enqueue(order, now)
                result = self._build_result(order_id, "QUEUED", None, reasons, None, None)
                return result, None
            reasons = [reason("all_couriers_at_capacity", "no courier has free capacity; order queued")]
            self._enqueue(order, now)
            result = self._build_result(order_id, "QUEUED", None, reasons, None, None)
            return result, None

        # Repartidores con cupo pero todos limitados por ritmo (ventana deslizante).
        reasons = selection.reasons + [
            reason("no_courier_available_now", "eligible couriers are rate-limited this cycle; order queued")
        ]
        self._enqueue(order, now)
        result = self._build_result(order_id, "QUEUED", None, reasons, None, None)
        return result, None

    def _enqueue(self, order: dict, now: float) -> None:
        self.waiting_queue.append({
            "order_id": order.get("order_id"),
            "queued_at": now,
            "priority": order.get("priority"),
            "pickup_zone": order.get("pickup_zone"),
        })

    def _build_result(
        self,
        order_id: str,
        status: str,
        assigned_courier: Optional[str],
        reasons: list[dict],
        cost: Optional[float],
        pricing_status: Optional[str],
    ) -> dict:
        return {
            "order_id": order_id,
            "status": status,
            "assigned_courier": assigned_courier,
            "reasons": reasons,
            "cost": cost,
            "pricing_status": pricing_status,
        }

    def _finalize_pricing(self, result: dict) -> dict:
        """Resuelve el precio (fuera del lock global) para un resultado ASSIGNED
        que quedo pendiente de tarifa.
        """
        base_cost = result.pop("_pending_pricing_base_cost", None)
        if base_cost is not None:
            cost, pricing_status = self.pricing.get_cost(base_cost)
            result["cost"] = cost
            result["pricing_status"] = pricing_status
        return result

    def _report_if_rejected(self, order: dict, result: dict, couriers_snapshot: Optional[list[dict]]) -> None:
        if result["status"] != "REJECTED":
            return
        snapshot = couriers_snapshot if couriers_snapshot is not None else self.store.snapshot()
        report = self.rejection_reporter.build_report(order, result, snapshot)
        with self._reports_lock:
            self.rejection_reports.append(report)

    # ------------------------------------------------------------------
    # Bono A - asignacion optima por lotes
    # ------------------------------------------------------------------
    def assign_batch(self, orders: list[dict], now: Optional[float] = None) -> list[dict]:
        now = time.time() if now is None else now
        results: dict[str, dict] = {}
        valid_orders: list[dict] = []

        for order in orders:
            order_id = order.get("order_id", "UNKNOWN")
            errors = validate_order(order, now, self.config)
            if errors:
                result = self._build_result(order_id, "REJECTED", None, errors, None, None)
                self._report_if_rejected(order, result, self.store.snapshot())
                results[order_id] = result
            else:
                valid_orders.append(order)

        if not valid_orders:
            return [results[o.get("order_id", "UNKNOWN")] for o in orders]

        with self._lock:
            for order in valid_orders:
                for c in order.get("couriers") or []:
                    self.store.upsert_if_new(c["courier_id"], c["zone"], c["active_orders"], c["max_capacity"])
            couriers_snapshot = self.store.snapshot()

        def cost_fn(order: dict, courier: dict) -> float:
            return compute_base_cost(order, courier, self.config["pricing"])

        solved = solve_batch_assignment(valid_orders, couriers_snapshot, cost_fn)

        remaining_orders: list[dict] = []
        for order in valid_orders:
            order_id = order["order_id"]
            assignment = solved.get(order_id, {"courier_id": None, "cost": None})
            courier_id = assignment["courier_id"]
            if courier_id is None:
                remaining_orders.append(order)
                continue

            with self._lock:
                reserved = self.store.try_reserve(courier_id)
                if reserved:
                    self.rate_limiter.record(courier_id, now)
                    self.zone_tracker.record(order["pickup_zone"], now)
                    self.surge.register_outcome(now, all_couriers_full=False)

            if not reserved:
                # El cupo fue tomado por otra operacion entre el calculo del
                # lote y la reserva; se resuelve individualmente como fallback.
                remaining_orders.append(order)
                continue

            base_cost = assignment["cost"]
            cost, pricing_status = self.pricing.get_cost(base_cost)
            reasons = [reason(
                "batch_optimized",
                f"joint assignment across {len(valid_orders)} orders minimizing total cost "
                f"(Hungarian algorithm) -> {courier_id}",
            )]
            results[order_id] = self._build_result(order_id, "ASSIGNED", courier_id, reasons, cost, pricing_status)

        for order in remaining_orders:
            results[order["order_id"]] = self.assign_single(order, now=now)

        return [results[o.get("order_id", "UNKNOWN")] for o in orders]

    # ------------------------------------------------------------------
    # Fase 4 - simulacion de rafaga para la interfaz grafica
    # ------------------------------------------------------------------
    def simulate_burst(self, params: dict) -> list[dict]:
        count = int(params.get("count", 6))
        start = time.time()
        results = []
        for i in range(count):
            simulated_now = start + i * 1.2
            order = {
                "order_id": f"{params.get('order_id_prefix', 'burst')}_{i + 1:03d}",
                "timestamp": datetime.fromtimestamp(simulated_now, tz=timezone.utc).isoformat(),
                "pickup_zone": params["pickup_zone"],
                "distance_km": params.get("distance_km", 3.0),
                "priority": params.get("priority", "normal"),
            }
            results.append(self.assign_single(order, now=simulated_now))
        return results
