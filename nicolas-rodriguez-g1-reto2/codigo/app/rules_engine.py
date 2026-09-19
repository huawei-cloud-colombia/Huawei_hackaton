"""Fase 1 + Fase 2 - Cadena de reglas para elegir el mejor repartidor.

``select_courier`` aplica, en orden y de forma configurable via
``config.json`` (seccion ``rules``/``rate_limit``/``zones``):

1. **capacity_ok**: descarta repartidores en su ``max_capacity``.
2. **rate_limit_window**: descarta repartidores que ya recibieron
   ``max_orders_per_courier`` pedidos en la ventana deslizante de
   ``window_seconds`` (Fase 2).
3. **same_zone_preferred** / **zone_balance_neighbors**: prefiere
   repartidores en la misma ``pickup_zone``; si la zona esta en avalancha
   (varios pedidos recientes), balancea hacia zonas vecinas (Fase 2).
4. **least_loaded** (+ **cost_minimized** como desempate, Fase 3): entre los
   candidatos finales, prefiere al de menor ``active_orders``; si hay empate,
   desempata minimizando el costo estimado del envio.

Cada paso agrega una entrada a ``reasons[]`` para que la decision sea
trazable a una regla especifica (requisito de explicabilidad de la rubrica).
No reserva el cupo: eso lo hace el llamador (``engine.py``) de forma atomica
sobre ``CourierStateStore``, bajo el mismo lock que hizo la seleccion, para
evitar condiciones de carrera (Bono B).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def reason(rule: str, detail: str) -> dict:
    return {"rule": rule, "detail": detail}


def _order_word(n: float) -> str:
    return "active order" if n == 1 else "active orders"


@dataclass
class Selection:
    courier: Optional[dict]
    reasons: list[dict] = field(default_factory=list)
    all_full: bool = False


def compute_base_cost(order: dict, courier: dict, pricing_cfg: dict) -> float:
    """Tarifa base determinista (formula interna, sin el ajuste dinamico
    del servicio externo): tarifa fija + distancia + recargo si el
    repartidor debe desplazarse desde otra zona para recoger el pedido.
    """
    base = pricing_cfg["base_fare_cop"] + pricing_cfg["rate_per_km_cop"] * float(order["distance_km"])
    if courier["zone"] != order["pickup_zone"]:
        base += pricing_cfg["cross_zone_surcharge_cop"]
    return round(base, 2)


def _capacity_detail(pool: list[dict], full: list[dict]) -> str:
    if not full:
        return f"{len(pool)} courier(s) with free capacity"
    skipped = ", ".join(f"{c['courier_id']} {c['active_orders']}/{c['max_capacity']} full" for c in full)
    return f"{len(pool)} candidate(s) with free capacity (skipped: {skipped})"


def select_courier(
    order: dict,
    couriers: list[dict],
    now: float,
    config: dict,
    rate_limiter,
    zone_tracker,
) -> Selection:
    rules_cfg = config["rules"]
    pickup_zone = order["pickup_zone"]

    # 1. Capacidad -----------------------------------------------------
    capacity_enforced = rules_cfg.get("capacity_enforced", True)
    if capacity_enforced:
        valid = [c for c in couriers if c["active_orders"] < c["max_capacity"]]
    else:
        valid = list(couriers)
    valid_ids = {c["courier_id"] for c in valid}
    full = [c for c in couriers if c["courier_id"] not in valid_ids]

    if not valid:
        return Selection(courier=None, reasons=[], all_full=True)

    pool = valid

    # 2. Ritmo por repartidor (ventana deslizante) ----------------------
    rate_limit_reason = None
    if config["rate_limit"].get("enabled", True):
        allowed_ids = {c["courier_id"] for c in pool if rate_limiter.is_allowed(c["courier_id"], now)}
        limited = [c for c in pool if c["courier_id"] not in allowed_ids]
        if limited:
            rate_limit_reason = reason(
                "rate_limit_window",
                f"{len(limited)} courier(s) skipped: reached "
                f"{config['rate_limit']['max_orders_per_courier']} orders in last "
                f"{config['rate_limit']['window_seconds']}s window "
                f"({', '.join(c['courier_id'] for c in limited)})",
            )
        pool = [c for c in pool if c["courier_id"] in allowed_ids]

    if not pool:
        return Selection(courier=None, reasons=[rate_limit_reason] if rate_limit_reason else [], all_full=False)

    # 3. Zona: preferencia por misma zona / balanceo a zonas vecinas ----
    zone_reason = None
    if rules_cfg.get("same_zone_preferred", True):
        same_zone = [c for c in pool if c["zone"] == pickup_zone]
        is_avalanche = zone_tracker.is_avalanche(pickup_zone, now)
        if same_zone and not is_avalanche:
            pool = same_zone
            zone_reason = reason(
                "same_zone_preferred",
                f"{len(same_zone)} courier(s) in pickup_zone={pickup_zone}: "
                f"{', '.join(c['courier_id'] for c in same_zone)}",
            )
        elif is_avalanche:
            neighbors = config["zones"]["neighbors"].get(pickup_zone, [])
            same_ids = {c["courier_id"] for c in same_zone}
            neighbor_ids = {c["courier_id"] for c in pool if c["zone"] in neighbors}
            combined_ids = same_ids | neighbor_ids
            combined = [c for c in pool if c["courier_id"] in combined_ids]
            if combined:
                pool = combined
                zone_reason = reason(
                    "zone_balance_neighbors",
                    f"pickup_zone={pickup_zone} is avalanched; balancing across "
                    f"{pickup_zone} + neighbor zones {neighbors}",
                )
            else:
                zone_reason = reason(
                    "zone_balance_fallback_any_zone",
                    f"pickup_zone={pickup_zone} avalanched and no couriers in zone/neighbors; "
                    f"using any available zone",
                )
        else:
            zone_reason = reason(
                "same_zone_unavailable",
                f"no courier currently in pickup_zone={pickup_zone}; considering any zone",
            )

    capacity_reason = reason("capacity_ok", _capacity_detail(pool, full))

    # 4. Menor carga primero (+ costo como desempate, Fase 3) -----------
    pool_sorted = sorted(pool, key=lambda c: (c["active_orders"], c["courier_id"]))
    min_load = pool_sorted[0]["active_orders"]
    tied = [c for c in pool_sorted if c["active_orders"] == min_load]

    load_reasons: list[dict] = []
    if len(tied) > 1 and config.get("optimization", {}).get("cost_minimization_enabled", True):
        tied_by_cost = sorted(
            tied, key=lambda c: (compute_base_cost(order, c, config["pricing"]), c["courier_id"])
        )
        chosen = tied_by_cost[0]
        load_reasons.append(reason(
            "least_loaded",
            f"tie among {[c['courier_id'] for c in tied]} at {min_load} {_order_word(min_load)}",
        ))
        load_reasons.append(reason(
            "cost_minimized",
            f"{chosen['courier_id']} chosen: lowest estimated cost among tied couriers "
            f"({compute_base_cost(order, chosen, config['pricing']):.0f} COP)",
        ))
    else:
        chosen = pool_sorted[0]
        load_reasons.append(reason(
            "least_loaded",
            f"{chosen['courier_id']} chosen ({chosen['active_orders']} {_order_word(chosen['active_orders'])}, "
            f"lowest among valid)",
        ))

    reasons: list[dict] = []
    if zone_reason:
        reasons.append(zone_reason)
    reasons.append(capacity_reason)
    if rate_limit_reason:
        reasons.append(rate_limit_reason)
    reasons.extend(load_reasons)

    return Selection(courier=chosen, reasons=reasons, all_full=False)
