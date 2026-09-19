"""Bono B - concurrencia segura.

Prueba de carga real (no solo afirmada): N hilos asignando pedidos al mismo
tiempo contra el mismo estado compartido de repartidores nunca deben
sobre-asignar un repartidor por encima de su ``max_capacity`` ni descuadrar
el conteo de ``active_orders``.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from tests.conftest import make_order


def _no_surge_overrides() -> dict:
    # Aislar la prueba de concurrencia de la logica de Fase 2: aqui solo
    # interesa la seccion critica de capacidad.
    return {
        "rate_limit": {"max_orders_per_courier": 1_000_000},
        "surge": {"consecutive_saturation_threshold": 1_000_000},
    }


def test_concurrent_assignment_never_overbooks_capacity(engine_factory):
    couriers = [
        {"courier_id": "cour_1", "zone": "centro", "active_orders": 0, "max_capacity": 5},
        {"courier_id": "cour_2", "zone": "centro", "active_orders": 0, "max_capacity": 5},
    ]
    engine = engine_factory(config_overrides=_no_surge_overrides(), couriers=couriers)
    total_capacity = sum(c["max_capacity"] for c in couriers)
    n_requests = 60
    barrier = threading.Barrier(n_requests)

    def _assign(i: int) -> dict:
        barrier.wait()  # todos los hilos arrancan a la vez: maximiza el solapamiento real
        order = make_order(f"ord_{i}", pickup_zone="centro", distance_km=1.0)
        return engine.assign_single(order)

    with ThreadPoolExecutor(max_workers=n_requests) as pool:
        futures = [pool.submit(_assign, i) for i in range(n_requests)]
        results = [f.result() for f in as_completed(futures)]

    assigned = [r for r in results if r["status"] == "ASSIGNED"]
    queued = [r for r in results if r["status"] == "QUEUED"]

    assert len(assigned) == total_capacity
    assert len(assigned) + len(queued) == n_requests
    assert len({r["order_id"] for r in assigned}) == len(assigned)  # sin duplicados/doble asignacion

    couriers_final = engine.store.snapshot()
    for c in couriers_final:
        assert 0 <= c["active_orders"] <= c["max_capacity"]
    assert sum(c["active_orders"] for c in couriers_final) == len(assigned)


def test_concurrent_assignment_stress_many_couriers(engine_factory):
    """Prueba de carga mas amplia: 10 repartidores, 200 pedidos concurrentes."""
    couriers = [
        {"courier_id": f"cour_{i}", "zone": "centro", "active_orders": 0, "max_capacity": 3}
        for i in range(10)
    ]
    engine = engine_factory(config_overrides=_no_surge_overrides(), couriers=couriers)
    total_capacity = sum(c["max_capacity"] for c in couriers)  # 30
    n_requests = 200

    def _assign(i: int) -> dict:
        order = make_order(f"ord_{i}", pickup_zone="centro", distance_km=1.0)
        return engine.assign_single(order)

    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(_assign, range(n_requests)))

    assigned = [r for r in results if r["status"] == "ASSIGNED"]
    assert len(assigned) == total_capacity

    couriers_final = engine.store.snapshot()
    for c in couriers_final:
        assert c["active_orders"] <= c["max_capacity"]
    assert sum(c["active_orders"] for c in couriers_final) == total_capacity


def test_concurrent_release_and_reserve_stay_consistent(engine_factory):
    """Reserva y libera cupos concurrentemente: el conteo final debe
    corresponder exactamente a reservas menos liberaciones, sin perder
    incrementos/decrementos por condiciones de carrera."""
    couriers = [{"courier_id": "cour_1", "zone": "centro", "active_orders": 0, "max_capacity": 1_000_000}]
    engine = engine_factory(config_overrides=_no_surge_overrides(), couriers=couriers)

    def _reserve_then_release():
        ok = engine.store.try_reserve("cour_1")
        assert ok
        engine.store.release("cour_1")

    with ThreadPoolExecutor(max_workers=50) as pool:
        futures = [pool.submit(_reserve_then_release) for _ in range(500)]
        for f in as_completed(futures):
            f.result()

    assert engine.store.get("cour_1")["active_orders"] == 0
