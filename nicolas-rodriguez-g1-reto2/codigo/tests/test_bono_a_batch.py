"""Bono A - optimizacion global por lotes (algoritmo hungaro) vs. asignacion
codiciosa (greedy), y respeto de la capacidad de cada repartidor dentro del lote."""
from __future__ import annotations

from app.batch_optimizer import solve_batch_assignment
from app.rules_engine import compute_base_cost
from tests.conftest import fast_config, make_order

PRICING_CFG = fast_config()["pricing"]


def _cost(order, courier):
    return compute_base_cost(order, courier, PRICING_CFG)


def test_batch_respects_capacity_as_multiple_slots():
    """Un repartidor con capacidad para 2 puede recibir 2 pedidos del mismo
    lote, pero no un 3ro (ese queda como no asignable en este lote y vuelve
    al flujo normal QUEUED/REJECTED)."""
    orders = [make_order(f"ord_{i}", pickup_zone="centro", distance_km=1.0) for i in range(3)]
    couriers = [{"courier_id": "cour_1", "zone": "centro", "active_orders": 0, "max_capacity": 2}]

    solved = solve_batch_assignment(orders, couriers, _cost)

    assigned = [oid for oid, a in solved.items() if a["courier_id"] is not None]
    unassigned = [oid for oid, a in solved.items() if a["courier_id"] is None]
    assert len(assigned) == 2
    assert len(unassigned) == 1
    assert all(solved[oid]["courier_id"] == "cour_1" for oid in assigned)


def test_batch_beats_greedy_when_greedy_strands_a_far_order():
    """Ejemplo numerico clasico de por que la asignacion por lotes supera a la
    codiciosa (requisito del Bono A). Usa una matriz de costos explicita para
    que el ejemplo sea nitido y sin empates; el principio es el mismo que
    aplica ``compute_base_cost`` en produccion (ver
    ``docs/BONO_A_LOTES.md`` para el desarrollo completo con numeros reales
    del motor).

    Matriz de costos (COP simplificados):

    ::

                        cour_near   cour_far
        order_close         1           4
        order_far           2          50

    ``order_close`` y ``order_far`` llegan casi al mismo tiempo. ``cour_near``
    es muy barato para ambos pedidos; ``cour_far`` es aceptable para
    ``order_close`` pero carisimo para ``order_far`` (esta lejos de esa
    zona).

    El greedy procesa ``order_close`` primero (llego primero) y, mirando solo
    ese pedido, elige a ``cour_near`` porque es el mas barato disponible en
    ese instante (1 < 4) -- una decision localmente razonable. Eso deja a
    ``order_far`` varado con el unico repartidor que queda, ``cour_far``, al
    costo mas alto de toda la matriz (50). Costo total del greedy: 1 + 50 = 51.

    El lote ve ambos pedidos a la vez y encuentra que intercambiar las
    asignaciones (``order_close`` -> ``cour_far``, ``order_far`` ->
    ``cour_near``) da un costo total mucho menor: 4 + 2 = 6. El lote nunca
    deja "varado" a un pedido con el peor repartidor disponible si existe una
    redistribucion global mas barata.
    """
    cost_table = {
        ("order_close", "cour_near"): 1.0,
        ("order_close", "cour_far"): 4.0,
        ("order_far", "cour_near"): 2.0,
        ("order_far", "cour_far"): 50.0,
    }

    def cost_fn(order: dict, courier: dict) -> float:
        return cost_table[(order["order_id"], courier["courier_id"])]

    orders = [make_order("order_close"), make_order("order_far")]  # orden de llegada real
    couriers = [
        {"courier_id": "cour_near", "zone": "centro", "active_orders": 0, "max_capacity": 1},
        {"courier_id": "cour_far", "zone": "centro", "active_orders": 0, "max_capacity": 1},
    ]

    # --- Greedy: procesa un pedido a la vez, sin ver los que vienen despues ---
    greedy_cost = 0.0
    remaining = {c["courier_id"]: dict(c) for c in couriers}
    for order in orders:
        candidates = [c for c in remaining.values() if c["active_orders"] < c["max_capacity"]]
        best = min(candidates, key=lambda c: cost_fn(order, c))
        greedy_cost += cost_fn(order, best)
        remaining[best["courier_id"]]["active_orders"] += 1

    # --- Lote: ve todos los pedidos y repartidores a la vez (algoritmo hungaro) ---
    solved = solve_batch_assignment(orders, couriers, cost_fn)
    batch_cost = sum(a["cost"] for a in solved.values())

    assert greedy_cost == 51.0
    assert batch_cost == 6.0
    assert batch_cost < greedy_cost
    assert solved["order_close"]["courier_id"] == "cour_far"
    assert solved["order_far"]["courier_id"] == "cour_near"


def test_engine_assign_batch_end_to_end(engine_factory):
    """Integracion completa: ``FlowMatchEngine.assign_batch`` reserva cupos,
    marca las razones como 'batch_optimized' y cobra tarifa por cada pedido asignado."""
    couriers = [
        {"courier_id": "cour_1", "zone": "centro", "active_orders": 0, "max_capacity": 2},
        {"courier_id": "cour_2", "zone": "norte", "active_orders": 0, "max_capacity": 2},
    ]
    engine = engine_factory(couriers=couriers)
    orders = [
        make_order("b1", pickup_zone="centro", distance_km=2.0),
        make_order("b2", pickup_zone="norte", distance_km=1.5),
        make_order("b3", pickup_zone="centro", distance_km=4.0),
    ]

    results = engine.assign_batch(orders, now=5000.0)

    assert len(results) == 3
    assigned = [r for r in results if r["status"] == "ASSIGNED"]
    assert len(assigned) == 3  # capacidad total = 4, alcanza para los 3
    for r in assigned:
        assert any(reason["rule"] == "batch_optimized" for reason in r["reasons"])
        assert r["cost"] is not None

    # La capacidad realmente se reservo en el store compartido.
    total_active = sum(c["active_orders"] for c in engine.store.snapshot())
    assert total_active == 3
