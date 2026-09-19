"""Bono A - Optimizacion global por lotes.

En vez de asignar pedido a pedido de forma codiciosa (greedy), agrupa los
pedidos de una ventana corta y resuelve la asignacion conjunta
pedido<->repartidor que minimiza el **costo total** del lote, usando el
algoritmo hungaro (``scipy.optimize.linear_sum_assignment``) sobre una matriz
de costos.

Cada repartidor se expande en tantas "ranuras" (columnas de la matriz) como
capacidad libre tenga, para modelar que un mismo repartidor puede recibir mas
de un pedido del lote sin exceder ``max_capacity``. Los pares
pedido/repartidor que violarian alguna restriccion dura reciben un costo
altisimo (``UNASSIGNABLE_COST``) para que el solver los evite salvo que no
quede otra alternativa; si aun asi el mejor costo disponible es ese valor
centinela, se trata como "no asignable en este lote" y el pedido vuelve al
flujo normal (``engine.assign_single``) para clasificarlo como QUEUED o
REJECTED segun corresponda.

Por que el lote supera al greedy: el greedy decide con la informacion de un
solo pedido a la vez, así que puede "gastar" el repartidor mas cercano en un
pedido cercano barato y dejar varado a un pedido lejano con el unico
repartidor que quedaba libre en otra zona (costo alto). El lote ve todos los
pedidos y repartidores a la vez y encuentra el emparejamiento de **costo
total minimo**, así que puede preferir intercambiar asignaciones para que
ningun pedido quede con el peor costo posible. Ver ``docs/BONO_A_LOTES.md``
para un ejemplo numerico concreto.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
from scipy.optimize import linear_sum_assignment

UNASSIGNABLE_COST = 1_000_000.0

CostFn = Callable[[dict, dict], float]


def _expand_courier_slots(couriers: list[dict]) -> list[str]:
    """Expande cada repartidor en tantas 'ranuras' como capacidad libre tenga."""
    slots: list[str] = []
    for c in couriers:
        free = max(0, int(c["max_capacity"]) - int(c["active_orders"]))
        slots.extend([c["courier_id"]] * free)
    return slots


def solve_batch_assignment(orders: list[dict], couriers: list[dict], cost_fn: CostFn) -> dict[str, dict]:
    """Devuelve, por ``order_id``, ``{"courier_id": str|None, "cost": float|None}``
    con la asignacion conjunta de costo total minimo para el lote.
    """
    result = {o["order_id"]: {"courier_id": None, "cost": None} for o in orders}

    slots = _expand_courier_slots(couriers)
    couriers_by_id = {c["courier_id"]: c for c in couriers}

    if not orders or not slots:
        return result

    cost_matrix = np.full((len(orders), len(slots)), UNASSIGNABLE_COST, dtype=float)
    for i, order in enumerate(orders):
        for j, courier_id in enumerate(slots):
            courier = couriers_by_id[courier_id]
            cost_matrix[i, j] = cost_fn(order, courier)

    row_idx, col_idx = linear_sum_assignment(cost_matrix)

    for r, c in zip(row_idx, col_idx):
        cost = cost_matrix[r, c]
        if cost >= UNASSIGNABLE_COST:
            continue
        order_id = orders[r]["order_id"]
        result[order_id] = {"courier_id": slots[c], "cost": round(float(cost), 2)}

    return result
