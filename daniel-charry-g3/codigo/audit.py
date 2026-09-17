"""
audit.py — Sistema de trazabilidad y auditoría.
Registra cada cambio de estado para poder reconstruir la vida de una reserva.
"""

from datetime import datetime, timezone
from typing import List, Optional
import json
import os

from models import AuditEvent


class AuditLog:
    """Registro de auditoría en memoria con exportación a archivo."""

    def __init__(self):
        self._events: List[AuditEvent] = []

    def record(
        self,
        reason: str,
        hold_id: Optional[str] = None,
        user_id: Optional[str] = None,
        seat_id: Optional[str] = None,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> AuditEvent:
        """Registra un evento de auditoría."""
        event = AuditEvent(
            hold_id=hold_id,
            user_id=user_id,
            seat_id=seat_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
            extra=extra,
        )
        self._events.append(event)
        return event

    def get_all(self) -> List[AuditEvent]:
        """Retorna todos los eventos."""
        return list(self._events)

    def get_by_hold(self, hold_id: str) -> List[AuditEvent]:
        """Retorna todos los eventos de un hold específico."""
        return [e for e in self._events if e.hold_id == hold_id]

    def get_by_seat(self, seat_id: str) -> List[AuditEvent]:
        """Retorna todos los eventos de un asiento específico."""
        return [e for e in self._events if e.seat_id == seat_id]

    def export_json(self, filepath: str = "audit_export.json") -> str:
        """Exporta todos los eventos a un archivo JSON."""
        data = [e.model_dump(mode="json") for e in self._events]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        return filepath

    def clear(self):
        """Limpia todos los eventos."""
        self._events.clear()


# Instancia global
audit_log = AuditLog()
