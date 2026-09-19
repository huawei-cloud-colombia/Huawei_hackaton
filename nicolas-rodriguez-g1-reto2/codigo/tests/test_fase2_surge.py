"""Fase 2 - ventana deslizante por repartidor, balanceo de zona y modo de
contencion por saturacion sostenida (con expiracion automatica)."""
from __future__ import annotations

from app.rules_engine import select_courier
from tests.conftest import fast_config, make_order


# ----------------------------------------------------------------------
# Limite de ritmo por repartidor (ventana deslizante)
# ----------------------------------------------------------------------
def test_courier_is_rate_limited_after_n_orders_in_window(engine_factory):
    couriers = [
        {"courier_id": "cour_fast", "zone": "centro", "active_orders": 0, "max_capacity": 100},
    ]
    engine = engine_factory(
        config_overrides={"rate_limit": {"window_seconds": 10, "max_orders_per_courier": 3}},
        couriers=couriers,
    )

    results = [
        engine.assign_single(make_order(f"ord_{i}", pickup_zone="centro"), now=1000.0 + i)
        for i in range(4)
    ]

    assert [r["status"] for r in results[:3]] == ["ASSIGNED", "ASSIGNED", "ASSIGNED"]
    # El 4to pedido llega 3s despues del primero: sigue dentro de la ventana de 10s,
    # el repartidor ya recibio 3 pedidos nuevos -> se salta por rate limit aunque tenga cupo.
    assert results[3]["status"] == "QUEUED"
    assert any(r["rule"] == "no_courier_available_now" for r in results[3]["reasons"])


def test_rate_limit_window_slides_and_frees_up(engine_factory):
    couriers = [{"courier_id": "cour_fast", "zone": "centro", "active_orders": 0, "max_capacity": 100}]
    engine = engine_factory(
        config_overrides={"rate_limit": {"window_seconds": 10, "max_orders_per_courier": 3}},
        couriers=couriers,
    )
    for i in range(3):
        engine.assign_single(make_order(f"ord_{i}", pickup_zone="centro"), now=1000.0 + i)

    # 11s despues del primer pedido, ese evento ya salio de la ventana deslizante de 10s.
    result = engine.assign_single(make_order("ord_later", pickup_zone="centro"), now=1011.0)
    assert result["status"] == "ASSIGNED"


# ----------------------------------------------------------------------
# Balanceo de zona ante avalancha (unit test directo de rules_engine)
# ----------------------------------------------------------------------
class _AlwaysAllowRateLimiter:
    def is_allowed(self, courier_id, now):
        return True


class _ForcedZoneTracker:
    def __init__(self, avalanche: bool):
        self._avalanche = avalanche

    def is_avalanche(self, zone, now):
        return self._avalanche


def _balance_config():
    return fast_config({"zones": {"neighbors": {"centro": ["norte"]}}})


def test_same_zone_preferred_when_no_avalanche():
    couriers = [
        {"courier_id": "cour_centro", "zone": "centro", "active_orders": 0, "max_capacity": 10},
        {"courier_id": "cour_norte", "zone": "norte", "active_orders": 0, "max_capacity": 10},
    ]
    order = make_order("ord_x", pickup_zone="centro")
    selection = select_courier(
        order, couriers, now=0.0, config=_balance_config(),
        rate_limiter=_AlwaysAllowRateLimiter(), zone_tracker=_ForcedZoneTracker(False),
    )
    assert selection.courier["courier_id"] == "cour_centro"
    assert any(r["rule"] == "same_zone_preferred" for r in selection.reasons)


def test_zone_balances_to_neighbor_during_avalanche():
    """Con avalancha activa en 'centro', el pool se expande a zonas vecinas
    aunque haya un repartidor en la misma zona -- y si ese vecino esta menos
    cargado, es el elegido (demuestra que el balanceo realmente mueve carga,
    no solo lo menciona en el texto)."""
    couriers = [
        {"courier_id": "cour_centro", "zone": "centro", "active_orders": 5, "max_capacity": 10},
        {"courier_id": "cour_norte", "zone": "norte", "active_orders": 0, "max_capacity": 10},
    ]
    order = make_order("ord_y", pickup_zone="centro")
    selection = select_courier(
        order, couriers, now=0.0, config=_balance_config(),
        rate_limiter=_AlwaysAllowRateLimiter(), zone_tracker=_ForcedZoneTracker(True),
    )
    assert any(r["rule"] == "zone_balance_neighbors" for r in selection.reasons)
    assert selection.courier["courier_id"] == "cour_norte"


# ----------------------------------------------------------------------
# Modo de contencion por saturacion sostenida
# ----------------------------------------------------------------------
def test_surge_protection_triggers_after_consecutive_full_streak(engine_factory):
    couriers = [
        {"courier_id": "cour_1", "zone": "centro", "active_orders": 0, "max_capacity": 1},
        {"courier_id": "cour_2", "zone": "centro", "active_orders": 0, "max_capacity": 1},
        {"courier_id": "cour_3", "zone": "centro", "active_orders": 0, "max_capacity": 1},
    ]
    engine = engine_factory(
        config_overrides={"surge": {"consecutive_saturation_threshold": 3, "contention_duration_seconds": 120}},
        couriers=couriers,
    )

    start = 2_000_000.0
    # Pedidos 1-3: llenan a los 3 repartidores.
    assigned = [engine.assign_single(make_order(f"ord_{i}", pickup_zone="centro"), now=start + i) for i in range(3)]
    assert all(r["status"] == "ASSIGNED" for r in assigned)

    # Pedidos 4 y 5: todos llenos, streak = 1, 2 -> QUEUED normal (aun sin contencion).
    r4 = engine.assign_single(make_order("ord_4", pickup_zone="centro"), now=start + 3)
    r5 = engine.assign_single(make_order("ord_5", pickup_zone="centro"), now=start + 4)
    assert r4["status"] == "QUEUED" and any(x["rule"] == "all_couriers_at_capacity" for x in r4["reasons"])
    assert r5["status"] == "QUEUED"

    # Pedido 6: streak llega a 3 -> activa contencion Y se rechaza el mismo pedido.
    r6 = engine.assign_single(make_order("ord_6", pickup_zone="centro"), now=start + 5)
    assert r6["status"] == "REJECTED"
    assert any(x["rule"] == "surge_protection_active" for x in r6["reasons"])

    # Pedido 7 (normal), dentro de la ventana de 120s: rechazo inmediato sin recalcular reglas.
    r7 = engine.assign_single(make_order("ord_7", pickup_zone="centro"), now=start + 6)
    assert r7["status"] == "REJECTED"
    assert [x["rule"] for x in r7["reasons"]] == ["surge_window_active"]

    # Pedido 8 (express) durante la contencion: intenta encolarse en vez de rechazarse.
    r8 = engine.assign_single(make_order("ord_8", pickup_zone="centro", priority="express"), now=start + 7)
    assert r8["status"] == "QUEUED"
    assert any(x["rule"] == "queued_express_during_contention" for x in r8["reasons"])


def test_surge_expires_automatically_after_window(engine_factory):
    couriers = [{"courier_id": "cour_1", "zone": "centro", "active_orders": 1, "max_capacity": 1}]
    engine = engine_factory(
        config_overrides={"surge": {"consecutive_saturation_threshold": 2, "contention_duration_seconds": 60}},
        couriers=couriers,
    )
    start = 3_000_000.0
    r1 = engine.assign_single(make_order("ord_1", pickup_zone="centro"), now=start)
    assert r1["status"] == "QUEUED"

    r2 = engine.assign_single(make_order("ord_2", pickup_zone="centro"), now=start + 1)
    assert r2["status"] == "REJECTED"
    assert engine.surge.is_active(start + 2)

    # La contencion expira 60s despues de haberse activado (en start + 1).
    r3 = engine.assign_single(make_order("ord_3", pickup_zone="centro"), now=start + 62)
    # La racha se reinicio con la expiracion: un solo evento de saturacion no
    # vuelve a disparar la contencion (umbral=2) -> QUEUED, no REJECTED.
    assert r3["status"] == "QUEUED"
    assert any(x["rule"] == "all_couriers_at_capacity" for x in r3["reasons"])
