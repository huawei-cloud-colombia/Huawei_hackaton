"""Fase 2 - Control de ritmo por ventana deslizante y deteccion de avalancha de zona.

``SlidingWindowRateLimiter`` implementa una ventana deslizante real (no una
ventana fija ingenua): guarda el timestamp de cada pedido reciente por
repartidor y descarta los que ya salieron de la ventana en cada consulta, asi
el limite se evalua siempre sobre los ultimos ``window_seconds`` segundos
exactos, sin importar cuando "empezo" el minuto/ventana.

``ZoneLoadTracker`` hace lo mismo mismo por ``pickup_zone`` para detectar
avalanchas y activar el balanceo hacia zonas vecinas.
"""
from __future__ import annotations

import threading
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, window_seconds: float, max_per_window: int) -> None:
        self.window_seconds = window_seconds
        self.max_per_window = max_per_window
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> None:
        dq = self._events[key]
        while dq and now - dq[0] > self.window_seconds:
            dq.popleft()

    def is_allowed(self, key: str, now: float) -> bool:
        with self._lock:
            self._prune(key, now)
            return len(self._events[key]) < self.max_per_window

    def record(self, key: str, now: float) -> None:
        with self._lock:
            self._prune(key, now)
            self._events[key].append(now)

    def current_count(self, key: str, now: float) -> int:
        with self._lock:
            self._prune(key, now)
            return len(self._events[key])


class ZoneLoadTracker:
    def __init__(self, window_seconds: float, avalanche_threshold: int) -> None:
        self.window_seconds = window_seconds
        self.avalanche_threshold = avalanche_threshold
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, zone: str, now: float) -> None:
        dq = self._events[zone]
        while dq and now - dq[0] > self.window_seconds:
            dq.popleft()

    def record(self, zone: str, now: float) -> None:
        with self._lock:
            self._prune(zone, now)
            self._events[zone].append(now)

    def is_avalanche(self, zone: str, now: float) -> bool:
        with self._lock:
            self._prune(zone, now)
            return len(self._events[zone]) >= self.avalanche_threshold

    def current_count(self, zone: str, now: float) -> int:
        with self._lock:
            self._prune(zone, now)
            return len(self._events[zone])
