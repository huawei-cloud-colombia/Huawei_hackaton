"""
Velocity tracker con sliding window para SentinelPay Risk Engine.

Mantiene timestamps de transacciones recientes por card_id y device_id,
eliminando automaticamente los eventos fuera de la ventana.

Diseñado para evolucionar hacia procesamiento concurrente:
    - Usa threading.RLock encapsulado dentro del componente.
    - Todas las operaciones son thread-safe.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone


class VelocityTracker:
    """
    Tracker de ventanas deslizantes para deteccion de card testing.

    Mantiene:
        - _card_timestamps: card_id -> lista de timestamps UTC.
        - _device_events: device_id -> lista de (timestamp, card_id).
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._card_timestamps: dict[str, list[datetime]] = defaultdict(list)
        self._device_events: dict[str, list[tuple[datetime, str]]] = defaultdict(list)

    def record_card(self, card_id: str, timestamp: datetime) -> None:
        """Registra el timestamp de una transaccion para una tarjeta."""
        with self._lock:
            ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
            self._card_timestamps[card_id].append(ts)

    def get_card_window(
        self, card_id: str, now: datetime, window_seconds: int
    ) -> list[datetime]:
        """
        Retorna los timestamps dentro de la ventana para una tarjeta.

        Limpia automaticamente los eventos fuera de la ventana.
        Incluye todos los timestamps registrados hasta ahora.
        """
        with self._lock:
            current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            cutoff = current - timedelta(seconds=window_seconds)
            timestamps = self._card_timestamps.get(card_id, [])
            recent = [t for t in timestamps if t >= cutoff]
            self._card_timestamps[card_id] = recent
            return recent

    def record_device(self, device_id: str, card_id: str, timestamp: datetime) -> None:
        """Registra una transaccion para un dispositivo con la tarjeta usada."""
        with self._lock:
            ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
            self._device_events[device_id].append((ts, card_id))

    def get_device_window(
        self, device_id: str, now: datetime, window_seconds: int
    ) -> list[tuple[datetime, str]]:
        """
        Retorna los eventos dentro de la ventana para un dispositivo.

        Limpia automaticamente los eventos fuera de la ventana.
        """
        with self._lock:
            current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            cutoff = current - timedelta(seconds=window_seconds)
            events = self._device_events.get(device_id, [])
            recent = [(t, c) for t, c in events if t >= cutoff]
            self._device_events[device_id] = recent
            return recent

    def count_distinct_cards(
        self, device_id: str, now: datetime, window_seconds: int
    ) -> int:
        """Cuenta tarjetas distintas en la ventana del dispositivo."""
        window = self.get_device_window(device_id, now, window_seconds)
        return len(set(card for _, card in window))

    def cleanup(self, now: datetime, max_window_seconds: int = 300) -> None:
        """
        Limpia entradas antiguas y vacias para evitar crecimiento indefinido.

        Elimina timestamps mas antiguos que max_window_seconds.
        Elima entradas vacias de los diccionarios.
        """
        with self._lock:
            current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
            cutoff = current - timedelta(seconds=max_window_seconds)

            for key in list(self._card_timestamps.keys()):
                recent = [t for t in self._card_timestamps[key] if t >= cutoff]
                if recent:
                    self._card_timestamps[key] = recent
                else:
                    del self._card_timestamps[key]

            for key in list(self._device_events.keys()):
                recent = [(t, c) for t, c in self._device_events[key] if t >= cutoff]
                if recent:
                    self._device_events[key] = recent
                else:
                    del self._device_events[key]

    def get_card_count(self, card_id: str) -> int:
        """Retorna el numero total de timestamps registrados para una tarjeta."""
        with self._lock:
            return len(self._card_timestamps.get(card_id, []))

    def get_device_count(self, device_id: str) -> int:
        """Retorna el numero total de eventos registrados para un dispositivo."""
        with self._lock:
            return len(self._device_events.get(device_id, []))

    def clear(self) -> None:
        """Limpia todo el estado del tracker."""
        with self._lock:
            self._card_timestamps.clear()
            self._device_events.clear()
