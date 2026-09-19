"""Registro en memoria del estado de los repartidores.

Es la unica fuente de verdad de ``active_orders``. Todas las mutaciones pasan
por ``try_reserve``/``release``, que son atomicas (protegidas por un
``RLock``) para que, bajo N hilos/requests concurrentes asignando al mismo
tiempo (Bono B), nunca se sobre-asigne un repartidor por encima de
``max_capacity`` ni se pierda un decremento/incremento por una condicion de
carrera de "leer -> decidir -> escribir".
"""
from __future__ import annotations

import threading
from typing import Optional


class CourierStateStore:
    def __init__(self) -> None:
        self._couriers: dict[str, dict] = {}
        self._lock = threading.RLock()

    def upsert_if_new(self, courier_id: str, zone: str, active_orders: int, max_capacity: int) -> None:
        """Registra un repartidor solo si el motor no lo conocia aun.

        Si ya existe, se ignoran zone/active_orders/max_capacity del payload:
        ``active_orders`` es manejado internamente por el motor a partir de
        las asignaciones reales (ver docstring del modulo), no por lo que
        reporte cada request.
        """
        with self._lock:
            if courier_id not in self._couriers:
                self._couriers[courier_id] = {
                    "courier_id": courier_id,
                    "zone": zone,
                    "active_orders": max(0, int(active_orders)),
                    "max_capacity": max(1, int(max_capacity)),
                }

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [dict(c) for c in self._couriers.values()]

    def get(self, courier_id: str) -> Optional[dict]:
        with self._lock:
            c = self._couriers.get(courier_id)
            return dict(c) if c else None

    def try_reserve(self, courier_id: str) -> bool:
        """Incrementa ``active_orders`` de forma atomica solo si hay cupo libre.

        Devuelve ``True`` si la reserva tuvo exito. Esta es la unica puerta de
        entrada para "ocupar" un cupo: el chequeo de capacidad y el
        incremento ocurren bajo el mismo lock, así dos hilos jamas pueden ver
        ambos "hay cupo" y reservar el mismo ultimo cupo dos veces.
        """
        with self._lock:
            c = self._couriers.get(courier_id)
            if c is None:
                return False
            if c["active_orders"] >= c["max_capacity"]:
                return False
            c["active_orders"] += 1
            return True

    def release(self, courier_id: str) -> None:
        with self._lock:
            c = self._couriers.get(courier_id)
            if c and c["active_orders"] > 0:
                c["active_orders"] -= 1

    def reset(self, couriers: list[dict]) -> None:
        with self._lock:
            self._couriers = {
                c["courier_id"]: {
                    "courier_id": c["courier_id"],
                    "zone": c["zone"],
                    "active_orders": int(c.get("active_orders", 0)),
                    "max_capacity": int(c["max_capacity"]),
                }
                for c in couriers
            }

    @property
    def lock(self) -> threading.RLock:
        return self._lock
