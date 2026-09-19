"""Bono D - suite de pruebas de escenarios extremos y casos borde.

Cubre: pedido sin repartidores, distancia negativa, prioridad invalida,
timestamp futuro/mal formado, ráfaga a una sola zona, todos los repartidores
llenos de golpe, avalancha de pedidos express, y el instante exacto en que
expira la ventana de contención -- verificando siempre que el sistema nunca
sobre-asigna por encima de la capacidad.
"""
from __future__ import annotations

from tests.conftest import make_order


# ----------------------------------------------------------------------
# Casos borde de validacion (rubrica: "manejo de errores y casos borde")
# ----------------------------------------------------------------------
def test_order_without_any_courier_is_rejected(engine_factory):
    engine = engine_factory(couriers=[])
    result = engine.assign_single(make_order("ord_1"), now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "no_couriers_available" for r in result["reasons"])


def test_negative_distance_is_rejected_with_explanation(engine_factory):
    engine = engine_factory()
    order = make_order("ord_2", distance_km=-3.5)
    result = engine.assign_single(order, now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "invalid_distance_negative" for r in result["reasons"])


def test_unreasonably_large_distance_is_rejected(engine_factory):
    engine = engine_factory()
    order = make_order("ord_3", distance_km=99999)
    result = engine.assign_single(order, now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "invalid_distance_out_of_range" for r in result["reasons"])


def test_invalid_priority_is_rejected(engine_factory):
    engine = engine_factory()
    order = make_order("ord_4", priority="urgentisimo")
    result = engine.assign_single(order, now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "invalid_priority" for r in result["reasons"])


def test_malformed_timestamp_is_rejected(engine_factory):
    engine = engine_factory()
    order = make_order("ord_5", timestamp="no-es-una-fecha")
    result = engine.assign_single(order, now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "invalid_timestamp_format" for r in result["reasons"])


def test_future_timestamp_beyond_tolerance_is_rejected(engine_factory):
    engine = engine_factory()
    # now = epoch 1000; el pedido dice llegar en el año 2999 (muy por encima
    # de la tolerancia configurada de 300s).
    order = make_order("ord_6", timestamp="2999-01-01T00:00:00Z")
    result = engine.assign_single(order, now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "invalid_timestamp_future" for r in result["reasons"])


def test_missing_pickup_zone_is_rejected(engine_factory):
    engine = engine_factory()
    order = make_order("ord_7")
    order["pickup_zone"] = ""
    result = engine.assign_single(order, now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "invalid_pickup_zone" for r in result["reasons"])


def test_invalid_courier_capacity_in_payload_is_rejected(engine_factory):
    engine = engine_factory(couriers=[])
    order = make_order(
        "ord_8",
        couriers=[{"courier_id": "cour_bad", "zone": "centro", "active_orders": 0, "max_capacity": 0}],
    )
    result = engine.assign_single(order, now=1000.0)
    assert result["status"] == "REJECTED"
    assert any(r["rule"] == "invalid_courier_capacity" for r in result["reasons"])


def test_multiple_validation_errors_are_all_reported(engine_factory):
    """Varios campos invalidos a la vez -> todas las razones deben aparecer,
    no solo la primera (facilita el debugging para el equipo de soporte)."""
    engine = engine_factory()
    order = make_order("ord_9", distance_km=-1, priority="mega-urgente")
    result = engine.assign_single(order, now=1000.0)
    rules = {r["rule"] for r in result["reasons"]}
    assert "invalid_distance_negative" in rules
    assert "invalid_priority" in rules


# ----------------------------------------------------------------------
# Escenarios extremos operacionales
# ----------------------------------------------------------------------
def test_burst_to_single_zone_never_overbooks_and_eventually_surges(engine_factory):
    couriers = [
        {"courier_id": "cour_1", "zone": "centro", "active_orders": 0, "max_capacity": 1},
        {"courier_id": "cour_2", "zone": "centro", "active_orders": 0, "max_capacity": 1},
    ]
    engine = engine_factory(
        config_overrides={"surge": {"consecutive_saturation_threshold": 3, "contention_duration_seconds": 120}},
        couriers=couriers,
    )
    start = 4_000_000.0
    results = [
        engine.assign_single(make_order(f"ord_{i}", pickup_zone="centro"), now=start + i)
        for i in range(6)
    ]
    statuses = [r["status"] for r in results]

    # Los primeros 2 llenan la capacidad total (2 repartidores x 1 cupo).
    assert statuses[0] == "ASSIGNED"
    assert statuses[1] == "ASSIGNED"
    # A partir de ahi, nunca mas hay un ASSIGNED (no queda capacidad).
    assert "ASSIGNED" not in statuses[2:]
    # Pedidos 3 y 4 (streak=1,2): QUEUED. Pedido 5 (streak=3): dispara la
    # contencion y se rechaza el mismo. Pedido 6: cae dentro de la ventana ya
    # activa y se rechaza de inmediato (surge_window_active).
    assert statuses[2] == "QUEUED"
    assert statuses[3] == "QUEUED"
    assert statuses[4] == "REJECTED"
    assert statuses[5] == "REJECTED"

    for c in engine.store.snapshot():
        assert c["active_orders"] <= c["max_capacity"]


def test_all_couriers_full_at_once_from_the_start(engine_factory):
    couriers = [
        {"courier_id": "cour_1", "zone": "centro", "active_orders": 2, "max_capacity": 2},
        {"courier_id": "cour_2", "zone": "centro", "active_orders": 5, "max_capacity": 5},
    ]
    engine = engine_factory(couriers=couriers)
    result = engine.assign_single(make_order("ord_x", pickup_zone="centro"), now=1000.0)
    assert result["status"] == "QUEUED"
    assert any(r["rule"] == "all_couriers_at_capacity" for r in result["reasons"])


def test_avalanche_of_express_orders_keeps_queueing_not_rejecting(engine_factory):
    couriers = [{"courier_id": "cour_1", "zone": "centro", "active_orders": 1, "max_capacity": 1}]
    engine = engine_factory(
        config_overrides={"surge": {"consecutive_saturation_threshold": 2, "contention_duration_seconds": 120}},
        couriers=couriers,
    )
    start = 5_000_000.0
    results = [
        engine.assign_single(make_order(f"ord_{i}", pickup_zone="centro", priority="express"), now=start + i)
        for i in range(5)
    ]
    # Ningun pedido express se rechaza por contencion: siempre intenta encolarse.
    assert all(r["status"] == "QUEUED" for r in results)
    assert not any(r["status"] == "REJECTED" for r in results)


def test_order_arriving_exactly_when_contention_expires(engine_factory):
    couriers = [{"courier_id": "cour_1", "zone": "centro", "active_orders": 1, "max_capacity": 1}]
    engine = engine_factory(
        config_overrides={"surge": {"consecutive_saturation_threshold": 2, "contention_duration_seconds": 60}},
        couriers=couriers,
    )
    start = 6_000_000.0
    engine.assign_single(make_order("ord_1", pickup_zone="centro"), now=start)
    r_trigger = engine.assign_single(make_order("ord_2", pickup_zone="centro"), now=start + 1)
    assert r_trigger["status"] == "REJECTED"
    active_until = start + 1 + 60

    # Justo en el segundo exacto de expiracion: ya no debe rechazar por surge_window_active.
    r_boundary = engine.assign_single(make_order("ord_3", pickup_zone="centro"), now=active_until)
    assert r_boundary["status"] != "REJECTED" or "surge_window_active" not in {
        r["rule"] for r in r_boundary["reasons"]
    }


def test_zero_couriers_registered_then_seeded_by_first_order(engine_factory):
    """El primer pedido puede sembrar el registro de repartidores via su
    campo 'couriers'; pedidos posteriores ya no necesitan reenviarlo."""
    engine = engine_factory(couriers=[])
    order_1 = make_order(
        "ord_1",
        pickup_zone="centro",
        couriers=[{"courier_id": "cour_new", "zone": "centro", "active_orders": 0, "max_capacity": 1}],
    )
    result_1 = engine.assign_single(order_1, now=1000.0)
    assert result_1["status"] == "ASSIGNED"
    assert result_1["assigned_courier"] == "cour_new"

    # Segundo pedido, sin reenviar couriers: ya no hay cupo (capacidad 1, ya ocupado).
    order_2 = make_order("ord_2", pickup_zone="centro")
    result_2 = engine.assign_single(order_2, now=1001.0)
    assert result_2["status"] == "QUEUED"
