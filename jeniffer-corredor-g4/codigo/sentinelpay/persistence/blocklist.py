"""
Blocklist temporal con expiracion automatica para SentinelPay Risk Engine.

Cuando una tarjeta o dispositivo supera un umbral de velocity,
se agrega a la blocklist con un timestamp de expiracion.

La blocklist expira automaticamente: no es necesario reiniciar
la aplicacion para desbloquear.

Diseñado para concurrencia: usa threading.RLock encapsulado.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone


class TemporalBlocklist:
    """
    Blocklist temporal para tarjetas y dispositivos.

    Mantiene:
        - _blocked_cards: card_id -> datetime de expiracion.
        - _blocked_devices: device_id -> datetime de expiracion.
    """

    def __init__(self, default_duration: int = 120) -> None:
        self._lock = threading.RLock()
        self._default_duration = default_duration
        self._blocked_cards: dict[str, datetime] = {}
        self._blocked_devices: dict[str, datetime] = {}

    def block_card(self, card_id: str, expiry: datetime) -> None:
        """Bloquea una tarjeta hasta la fecha de expiracion."""
        with self._lock:
            ts = expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
            existing = self._blocked_cards.get(card_id)
            if existing is None or ts > existing:
                self._blocked_cards[card_id] = ts

    def block_device(self, device_id: str, expiry: datetime) -> None:
        """Bloquea un dispositivo hasta la fecha de expiracion."""
        with self._lock:
            ts = expiry if expiry.tzinfo else expiry.replace(tzinfo=timezone.utc)
            existing = self._blocked_devices.get(device_id)
            if existing is None or ts > existing:
                self._blocked_devices[device_id] = ts

    def is_card_blocked(
        self, card_id: str, now: datetime | None = None
    ) -> bool:
        """
        Verifica si una tarjeta esta bloqueada.

        Si el bloqueo expiro, lo elimina automaticamente.
        """
        with self._lock:
            expiry = self._blocked_cards.get(card_id)
            if expiry is None:
                return False
            current = now if now and now.tzinfo else (
                (now.replace(tzinfo=timezone.utc) if now else datetime.now(timezone.utc))
            )
            if current >= expiry:
                del self._blocked_cards[card_id]
                return False
            return True

    def is_device_blocked(
        self, device_id: str, now: datetime | None = None
    ) -> bool:
        """
        Verifica si un dispositivo esta bloqueado.

        Si el bloqueo expiro, lo elimina automaticamente.
        """
        with self._lock:
            expiry = self._blocked_devices.get(device_id)
            if expiry is None:
                return False
            current = now if now and now.tzinfo else (
                (now.replace(tzinfo=timezone.utc) if now else datetime.now(timezone.utc))
            )
            if current >= expiry:
                del self._blocked_devices[device_id]
                return False
            return True

    def get_card_expiry(self, card_id: str) -> datetime | None:
        """Retorna la fecha de expiracion del bloqueo de una tarjeta."""
        with self._lock:
            return self._blocked_cards.get(card_id)

    def get_device_expiry(self, device_id: str) -> datetime | None:
        """Retorna la fecha de expiracion del bloqueo de un dispositivo."""
        with self._lock:
            return self._blocked_devices.get(device_id)

    def cleanup(self, now: datetime | None = None) -> None:
        """Elimina bloqueos expirados."""
        with self._lock:
            current = now if now and now.tzinfo else (
                (now.replace(tzinfo=timezone.utc) if now else datetime.now(timezone.utc))
            )
            self._blocked_cards = {
                k: v for k, v in self._blocked_cards.items() if v > current
            }
            self._blocked_devices = {
                k: v for k, v in self._blocked_devices.items() if v > current
            }

    def get_blocked_cards(self) -> dict[str, datetime]:
        """Retorna una copia de las tarjetas bloqueadas."""
        with self._lock:
            return dict(self._blocked_cards)

    def get_blocked_devices(self) -> dict[str, datetime]:
        """Retorna una copia de los dispositivos bloqueados."""
        with self._lock:
            return dict(self._blocked_devices)

    def clear(self) -> None:
        """Limpia toda la blocklist."""
        with self._lock:
            self._blocked_cards.clear()
            self._blocked_devices.clear()
