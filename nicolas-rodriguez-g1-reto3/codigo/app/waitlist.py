"""
Bono A - Sala de espera justa (Fair Waitlist).

Estrategia de cola para evitar que miles de usuarios golpeen simultáneamente
el motor de reservas.

Fairness:
- FIFO: los usuarios se atienden en orden de llegada.
- Anti-monopolio: un usuario solo puede estar una vez en la cola por evento.
- Abandono: si un usuario abandona (cancela), se remueve y el siguiente avanza.
- Timeout: si un usuario no completa su reserva en un tiempo configurable, se remueve.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from .schemas import WaitlistEntry, utc_now_iso


class FairWaitlist:
    def __init__(self, entry_timeout_seconds: int = 60):
        self._lock = threading.Lock()
        self._queue: deque[WaitlistEntry] = deque()
        self._event_queues: dict[str, list[str]] = {}  # event_id -> [user_ids]
        self._entry_timeout = entry_timeout_seconds
        self._next_position = 1

    def join(self, user_id: str, event_id: str, seat_ids: list[str]) -> dict[str, Any]:
        with self._lock:
            # Anti-monopolio: un usuario solo puede estar una vez por evento
            event_users = self._event_queues.setdefault(event_id, [])
            if user_id in event_users:
                return {
                    "ok": False,
                    "message": f"Usuario {user_id} ya está en la cola del evento {event_id}",
                }

            entry = WaitlistEntry(
                position=self._next_position,
                user_id=user_id,
                event_id=event_id,
                seat_ids=seat_ids,
            )
            self._next_position += 1
            self._queue.append(entry)
            event_users.append(user_id)

            return {
                "ok": True,
                "position": entry.position,
                "user_id": user_id,
                "event_id": event_id,
                "message": f"Usuario {user_id} en posición {entry.position}",
            }

    def get_next(self) -> WaitlistEntry | None:
        """Obtener el siguiente usuario en la cola (sin remover)."""
        with self._lock:
            self._cleanup_expired()
            if self._queue:
                return self._queue[0]
            return None

    def pop_next(self) -> WaitlistEntry | None:
        """Remover y retornar el siguiente usuario en la cola."""
        with self._lock:
            self._cleanup_expired()
            if self._queue:
                entry = self._queue.popleft()
                event_users = self._event_queues.get(entry.event_id, [])
                if entry.user_id in event_users:
                    event_users.remove(entry.user_id)
                return entry
            return None

    def leave(self, user_id: str, event_id: str) -> dict[str, Any]:
        """Usuario abandona la cola."""
        with self._lock:
            event_users = self._event_queues.get(event_id, [])
            if user_id not in event_users:
                return {"ok": False, "message": "Usuario no está en la cola"}

            for i, entry in enumerate(self._queue):
                if entry.user_id == user_id and entry.event_id == event_id:
                    del self._queue[i]
                    break

            event_users.remove(user_id)
            return {"ok": True, "message": f"Usuario {user_id} removido de la cola"}

    def get_queue(self) -> list[dict[str, Any]]:
        with self._lock:
            self._cleanup_expired()
            return [
                {
                    "position": e.position,
                    "user_id": e.user_id,
                    "event_id": e.event_id,
                    "seat_ids": e.seat_ids,
                    "joined_at": e.joined_at,
                }
                for e in self._queue
            ]

    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def _cleanup_expired(self) -> None:
        """Remover entradas expiradas. Debe llamarse dentro del lock."""
        now = datetime.now(timezone.utc)
        timeout = timedelta(seconds=self._entry_timeout)
        to_remove = []
        for entry in self._queue:
            joined = datetime.fromisoformat(entry.joined_at)
            if now - joined > timeout:
                to_remove.append(entry)

        for entry in to_remove:
            self._queue.remove(entry)
            event_users = self._event_queues.get(entry.event_id, [])
            if entry.user_id in event_users:
                event_users.remove(entry.user_id)

    def reset(self) -> None:
        with self._lock:
            self._queue.clear()
            self._event_queues.clear()
            self._next_position = 1
