"""Fase 2 - Modo de contencion por saturacion sostenida.

Cuenta rachas *consecutivas* de pedidos que no encontraron repartidor por
saturacion total de capacidad (no por rate-limit ni por zona). Cuando la
racha llega al umbral configurado, activa el "modo de contencion" durante
``contention_duration_seconds``, con expiracion automatica: pasado ese
tiempo, ``is_active`` desactiva el modo y reinicia la racha por si sola, sin
que nadie tenga que "apagarlo" manualmente.

Mientras esta activo, el motor (en ``engine.py``) rechaza de inmediato los
pedidos ``normal`` sin volver a evaluar repartidores; los ``express`` siguen
intentando encolarse.
"""
from __future__ import annotations

import threading
from typing import Optional


class SurgeController:
    def __init__(self, consecutive_threshold: int, contention_duration_seconds: float) -> None:
        self.consecutive_threshold = consecutive_threshold
        self.contention_duration_seconds = contention_duration_seconds
        self._streak = 0
        self._active_until: Optional[float] = None
        self._lock = threading.Lock()

    def is_active(self, now: float) -> bool:
        with self._lock:
            if self._active_until is not None and now >= self._active_until:
                self._active_until = None
                self._streak = 0
            return self._active_until is not None

    def register_outcome(self, now: float, all_couriers_full: bool) -> bool:
        """Registra el desenlace de un intento de asignacion.

        Devuelve ``True`` si esta llamada fue la que acabo de activar el modo
        de contencion (la racha llego justo ahora al umbral).
        """
        with self._lock:
            if self._active_until is not None and now >= self._active_until:
                self._active_until = None
                self._streak = 0

            if not all_couriers_full:
                self._streak = 0
                return False

            self._streak += 1
            if self._streak >= self.consecutive_threshold and self._active_until is None:
                self._active_until = now + self.contention_duration_seconds
                return True
            return False

    def remaining_seconds(self, now: float) -> float:
        with self._lock:
            if self._active_until is None:
                return 0.0
            return max(0.0, self._active_until - now)

    def current_streak(self) -> int:
        with self._lock:
            return self._streak
