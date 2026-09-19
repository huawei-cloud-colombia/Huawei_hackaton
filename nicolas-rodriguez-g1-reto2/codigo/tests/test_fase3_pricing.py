"""Fase 3 - optimizacion de costo + circuit breaker con degradacion segura."""
from __future__ import annotations

import random
import time

from app.pricing import BreakerState, PricingClient
from app.rules_engine import compute_base_cost
from tests.conftest import fast_config, make_order


def _pricing_client(overrides: dict | None = None, seed: int = 7) -> PricingClient:
    cfg = fast_config(overrides)
    return PricingClient(cfg, rng=random.Random(seed))


def test_cost_formula_matches_spec_example():
    order = {"distance_km": 3.2, "pickup_zone": "centro"}
    courier = {"zone": "centro"}
    pricing_cfg = fast_config()["pricing"]
    assert compute_base_cost(order, courier, pricing_cfg) == 6800.0


def test_pricing_succeeds_when_circuit_closed_and_service_healthy():
    client = _pricing_client({"pricing": {"failure_probability": 0.0}})
    cost, status = client.get_cost(6800.0)
    assert status == "ok"
    assert 6800.0 * 0.9 <= cost <= 6800.0 * 1.1
    assert client.breaker.state == BreakerState.CLOSED


def test_circuit_opens_after_consecutive_failures_and_degrades():
    client = _pricing_client({
        "pricing": {"failure_probability": 1.0},
        "circuit_breaker": {"failure_threshold": 3, "open_duration_seconds": 15},
    })

    statuses = [client.get_cost(6800.0)[1] for _ in range(3)]
    # Los primeros 2 fallos son transitorios (circuito aun cerrado); el 3ro abre el circuito.
    assert statuses[0] == "degraded_flat_rate_transient_failure"
    assert statuses[1] == "degraded_flat_rate_transient_failure"
    assert statuses[2] == "circuit_open_degraded_flat_rate"
    assert client.breaker.state == BreakerState.OPEN

    # Mientras el circuito esta abierto, ni siquiera se intenta llamar al servicio:
    # el costo degradado es exactamente la tarifa base (sin variacion dinamica).
    cost, status = client.get_cost(6800.0)
    assert (cost, status) == (6800.0, "circuit_open_degraded_flat_rate")


def test_half_open_trial_success_closes_circuit():
    client = _pricing_client({
        "pricing": {"failure_probability": 1.0},
        "circuit_breaker": {"failure_threshold": 3, "open_duration_seconds": 15},
    })
    for _ in range(3):
        client.get_cost(6800.0)
    assert client.breaker.state == BreakerState.OPEN

    # Simula que paso el tiempo de apertura: el circuito pasa a semi-abierto.
    client.breaker.opened_at -= 16

    client.pricing_cfg = dict(client.pricing_cfg)
    client.pricing_cfg["failure_probability"] = 0.0
    cost, status = client.get_cost(6800.0)
    assert status == "half_open_trial_success"
    assert client.breaker.state == BreakerState.CLOSED


def test_half_open_trial_failure_reopens_circuit():
    client = _pricing_client({
        "pricing": {"failure_probability": 1.0},
        "circuit_breaker": {"failure_threshold": 3, "open_duration_seconds": 15},
    })
    for _ in range(3):
        client.get_cost(6800.0)
    client.breaker.opened_at -= 16  # fuerza semi-abierto

    cost, status = client.get_cost(6800.0)  # failure_probability sigue en 1.0
    assert status == "half_open_trial_failed_degraded_flat_rate"
    assert client.breaker.state == BreakerState.OPEN


def test_engine_output_matches_spec_shape_when_circuit_open(engine_factory):
    """Reproduce el formato de salida documentado en la Fase 3 (mismo pedido de
    la Fase 1) forzando el circuito abierto: mismo status/courier/reasons,
    costo = tarifa base determinista, pricing_status degradado."""
    couriers = [
        {"courier_id": "cour_A", "zone": "centro", "active_orders": 1, "max_capacity": 3},
        {"courier_id": "cour_B", "zone": "norte", "active_orders": 0, "max_capacity": 3},
        {"courier_id": "cour_C", "zone": "centro", "active_orders": 3, "max_capacity": 3},
    ]
    engine = engine_factory(couriers=couriers)
    engine.pricing.breaker.state = BreakerState.OPEN
    engine.pricing.breaker.opened_at = time.monotonic()  # recien abierto -> sigue OPEN durante la prueba

    order = make_order("ord_00234", pickup_zone="centro", distance_km=3.2, priority="express")
    result = engine.assign_single(order, now=1701177480.0)

    assert result["status"] == "ASSIGNED"
    assert result["assigned_courier"] == "cour_A"
    assert result["cost"] == 6800.0
    assert result["pricing_status"] == "circuit_open_degraded_flat_rate"
