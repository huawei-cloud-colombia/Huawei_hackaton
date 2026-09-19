"""Fase 3 - Servicio simulado de tarifa dinamica + circuit breaker.

``mock_pricing()`` imita la llamada a un microservicio externo de precios:
tiene latencia variable y una probabilidad configurable (por defecto 30%) de
fallar o de exceder el timeout.

``PricingCircuitBreaker`` implementa el patron circuit breaker clasico de 3
estados:

- CLOSED: opera con normalidad, cuenta fallos consecutivos.
- OPEN: tras ``failure_threshold`` fallos seguidos, deja de llamar al
  servicio durante ``open_duration_seconds`` y degrada de forma segura
  (usa la tarifa base fija/deterministica en vez de fallar toda la
  asignacion).
- HALF_OPEN: pasado ese tiempo, intenta una unica llamada de prueba; si
  funciona vuelve a CLOSED, si falla vuelve a abrirse.

``PricingClient`` conecta ambas piezas y es la que usa el motor: siempre
devuelve un costo (real o degradado) y nunca deja que un fallo del servicio
externo tumbe la asignacion completa.
"""
from __future__ import annotations

import random
import threading
import time
from enum import Enum
from typing import Optional


class PricingServiceError(Exception):
    """Fallo simulado del servicio externo de tarifas."""


class PricingServiceTimeout(PricingServiceError):
    """Timeout simulado del servicio externo de tarifas."""


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def mock_pricing(base_cost: float, cfg: dict, rng: Optional[random.Random] = None) -> float:
    """Simula la llamada de red a un servicio externo de tarifa dinamica.

    Devuelve ``base_cost`` con una variacion dinamica de +/-10%. Lanza
    ``PricingServiceTimeout`` o ``PricingServiceError`` segun las
    probabilidades configuradas en ``cfg`` (seccion ``pricing`` de
    ``config.json``).
    """
    rng = rng or random
    latency_s = rng.uniform(cfg["call_latency_ms_min"], cfg["call_latency_ms_max"]) / 1000.0
    if rng.random() < cfg.get("slow_call_probability", 0.0):
        latency_s = cfg["timeout_seconds"] + 0.05
    time.sleep(latency_s)
    if latency_s > cfg["timeout_seconds"]:
        raise PricingServiceTimeout(f"mock_pricing: excedio el timeout ({latency_s:.2f}s > {cfg['timeout_seconds']}s)")
    if rng.random() < cfg["failure_probability"]:
        raise PricingServiceError("mock_pricing: fallo simulado del servicio de tarifas dinamicas")
    variance = rng.uniform(-0.1, 0.1)
    return round(base_cost * (1 + variance), 2)


class PricingCircuitBreaker:
    def __init__(self, failure_threshold: int, open_duration_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.open_duration_seconds = open_duration_seconds
        self.state = BreakerState.CLOSED
        self.consecutive_failures = 0
        self.opened_at: Optional[float] = None

    def _maybe_recover(self, now: float) -> None:
        if self.state == BreakerState.OPEN and self.opened_at is not None:
            if now - self.opened_at >= self.open_duration_seconds:
                self.state = BreakerState.HALF_OPEN

    def allow_call(self, now: float) -> bool:
        self._maybe_recover(now)
        return self.state != BreakerState.OPEN

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = BreakerState.CLOSED
        self.opened_at = None

    def record_failure(self, now: float) -> None:
        self.consecutive_failures += 1
        if self.state == BreakerState.HALF_OPEN:
            self.state = BreakerState.OPEN
            self.opened_at = now
        elif self.consecutive_failures >= self.failure_threshold:
            self.state = BreakerState.OPEN
            self.opened_at = now


class PricingClient:
    """Fachada thread-safe que combina ``mock_pricing`` con el circuit breaker."""

    def __init__(self, config: dict, rng: Optional[random.Random] = None) -> None:
        self.pricing_cfg = config["pricing"]
        cb_cfg = config["circuit_breaker"]
        self.breaker = PricingCircuitBreaker(
            failure_threshold=cb_cfg["failure_threshold"],
            open_duration_seconds=cb_cfg["open_duration_seconds"],
        )
        self.rng = rng or random.Random()
        self._lock = threading.Lock()

    def get_cost(self, base_cost: float) -> tuple[float, str]:
        """Devuelve ``(cost, pricing_status)``. Nunca lanza: ante cualquier
        fallo del servicio simulado, degrada a ``base_cost`` (la tarifa fija
        interna) y lo marca en ``pricing_status``.
        """
        now = time.monotonic()
        with self._lock:
            allowed = self.breaker.allow_call(now)
            was_half_open = self.breaker.state == BreakerState.HALF_OPEN

        if not allowed:
            return round(base_cost, 2), "circuit_open_degraded_flat_rate"

        try:
            price = mock_pricing(base_cost, self.pricing_cfg, self.rng)
        except PricingServiceError:
            with self._lock:
                self.breaker.record_failure(time.monotonic())
                state = self.breaker.state
            if state == BreakerState.OPEN and was_half_open:
                return round(base_cost, 2), "half_open_trial_failed_degraded_flat_rate"
            if state == BreakerState.OPEN:
                return round(base_cost, 2), "circuit_open_degraded_flat_rate"
            return round(base_cost, 2), "degraded_flat_rate_transient_failure"
        else:
            with self._lock:
                self.breaker.record_success()
            return price, ("half_open_trial_success" if was_half_open else "ok")
