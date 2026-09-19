"""Fase 1 - asignacion base por prioridad (misma zona, capacidad, menor carga)."""
from __future__ import annotations

from tests.conftest import make_order


def test_spec_example_assigns_cour_a(engine_factory):
    """Reproduce el ejemplo exacto del enunciado (Fase 1): pedido en 'centro',
    cour_A (1/3, en zona) debe ganarle a cour_C (3/3, lleno) y a cour_B (fuera de zona).
    """
    couriers = [
        {"courier_id": "cour_A", "zone": "centro", "active_orders": 1, "max_capacity": 3},
        {"courier_id": "cour_B", "zone": "norte", "active_orders": 0, "max_capacity": 3},
        {"courier_id": "cour_C", "zone": "centro", "active_orders": 3, "max_capacity": 3},
    ]
    engine = engine_factory(couriers=couriers)
    order = make_order("ord_00234", pickup_zone="centro", distance_km=3.2, priority="express")

    result = engine.assign_single(order, now=1701177480.0)

    assert result["status"] == "ASSIGNED"
    assert result["assigned_courier"] == "cour_A"
    rules = [r["rule"] for r in result["reasons"]]
    assert "same_zone_preferred" in rules
    assert "capacity_ok" in rules
    assert "least_loaded" in rules
    # cour_C fue descartado por estar lleno -> debe quedar mencionado en la explicacion.
    capacity_detail = next(r["detail"] for r in result["reasons"] if r["rule"] == "capacity_ok")
    assert "cour_C" in capacity_detail


def test_active_orders_updates_after_assignment(engine_factory):
    engine = engine_factory()
    before = engine.store.get("cour_A")["active_orders"]

    order = make_order("ord_1", pickup_zone="centro", distance_km=1.0)
    result = engine.assign_single(order, now=1000.0)

    after = engine.store.get(result["assigned_courier"])["active_orders"]
    assert after == before + 1


def test_full_courier_is_skipped_in_favor_of_capacity(engine_factory):
    couriers = [
        {"courier_id": "cour_full", "zone": "centro", "active_orders": 2, "max_capacity": 2},
        {"courier_id": "cour_free", "zone": "centro", "active_orders": 0, "max_capacity": 2},
    ]
    engine = engine_factory(couriers=couriers)
    order = make_order("ord_2", pickup_zone="centro")

    result = engine.assign_single(order, now=1000.0)

    assert result["status"] == "ASSIGNED"
    assert result["assigned_courier"] == "cour_free"


def test_all_couriers_full_results_in_queued_before_surge(engine_factory):
    couriers = [
        {"courier_id": "cour_full", "zone": "centro", "active_orders": 2, "max_capacity": 2},
    ]
    engine = engine_factory(couriers=couriers)
    order = make_order("ord_3", pickup_zone="centro")

    result = engine.assign_single(order, now=1000.0)

    assert result["status"] == "QUEUED"
    assert result["assigned_courier"] is None
    assert any(r["rule"] == "all_couriers_at_capacity" for r in result["reasons"])


def test_least_loaded_prefers_lower_active_orders(engine_factory):
    couriers = [
        {"courier_id": "cour_busy", "zone": "centro", "active_orders": 2, "max_capacity": 3},
        {"courier_id": "cour_idle", "zone": "centro", "active_orders": 0, "max_capacity": 3},
    ]
    engine = engine_factory(couriers=couriers)
    order = make_order("ord_4", pickup_zone="centro")

    result = engine.assign_single(order, now=1000.0)

    assert result["assigned_courier"] == "cour_idle"


def test_same_zone_rule_can_be_disabled_via_config(engine_factory):
    """El Fase 1 pide que cada regla se pueda activar/desactivar por config."""
    couriers = [
        {"courier_id": "cour_out_of_zone_idle", "zone": "norte", "active_orders": 0, "max_capacity": 3},
        {"courier_id": "cour_in_zone_busy", "zone": "centro", "active_orders": 2, "max_capacity": 3},
    ]
    engine = engine_factory(config_overrides={"rules": {"same_zone_preferred": False}}, couriers=couriers)
    order = make_order("ord_5", pickup_zone="centro")

    result = engine.assign_single(order, now=1000.0)

    # Sin preferencia de zona, gana el de menor carga aunque este fuera de zona.
    assert result["assigned_courier"] == "cour_out_of_zone_idle"
    assert not any(r["rule"] == "same_zone_preferred" for r in result["reasons"])
