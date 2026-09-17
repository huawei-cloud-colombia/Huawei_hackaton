"""
NEXUS LIVE - Motor de Reservas de Alta Concurrencia.

Núcleo del sistema: SeatLock con concurrencia segura, idempotencia,
expiración automática y trazabilidad.

Mecanismo de concurrencia: threading.RLock (reentrant lock) que protege
todas las operaciones de cambio de estado de asientos. El lock es reentrant
para permitir que operaciones internas (como expiración) llamen a otros
métodos protegidos sin deadlock.
"""
from __future__ import annotations

import threading
import uuid
from datetime import timedelta
from typing import Any, Optional

from .schemas import (
    Hold,
    HoldStatus,
    PaymentResult,
    Seat,
    SeatStatus,
    TraceEvent,
    utc_now,
    utc_now_iso,
)


class SeatLockEngine:
    """Motor de reservas con concurrencia segura mediante RLock."""

    def __init__(
        self,
        hold_ttl_seconds: int = 120,
        max_seats_per_user: int = 6,
    ):
        self._lock = threading.RLock()
        self._seats: dict[str, Seat] = {}
        self._holds: dict[str, Hold] = {}
        self._trace: list[TraceEvent] = []
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._hold_ttl = hold_ttl_seconds
        self._max_seats = max_seats_per_user

    # ── Setup ──────────────────────────────────────────────

    def add_seat(self, seat: Seat) -> None:
        with self._lock:
            self._seats[seat.seat_id] = seat

    def add_seats(self, seats: list[Seat]) -> None:
        with self._lock:
            for s in seats:
                self._seats[s.seat_id] = s

    def get_seat(self, seat_id: str) -> Optional[Seat]:
        with self._lock:
            return self._seats.get(seat_id)

    def get_all_seats(self) -> list[Seat]:
        with self._lock:
            return list(self._seats.values())

    def get_hold(self, hold_id: str) -> Optional[Hold]:
        with self._lock:
            hold = self._holds.get(hold_id)
            if hold and hold.is_expired():
                self._expire_hold(hold)
            return self._holds.get(hold_id)

    def get_all_holds(self) -> list[Hold]:
        with self._lock:
            self._expire_all()
            return list(self._holds.values())

    def get_trace(self) -> list[TraceEvent]:
        with self._lock:
            return list(self._trace)

    # ── Core: Reserve ──────────────────────────────────────

    def reserve(
        self,
        user_id: str,
        event_id: str,
        seat_ids: list[str],
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Crear un HOLD sobre uno o más asientos.

        Reglas:
        - Valida user_id, seat_ids no vacíos, sin duplicados.
        - Máximo max_seats_per_user por solicitud.
        - Todos los asientos deben estar AVAILABLE (todo-o-nada).
        - Si idempotency_key ya existe con mismo payload → mismo resultado.
        - Si idempotency_key existe con payload diferente → conflicto.
        - El usuario no puede tener más de max_seats_per_user asientos en HOLDs activos.
        """
        with self._lock:
            self._expire_all()

            # Validaciones básicas
            if not user_id or not user_id.strip():
                return {"ok": False, "error": "INVALID_USER", "message": "user_id es obligatorio"}

            if not seat_ids:
                return {"ok": False, "error": "EMPTY_SEATS", "message": "seat_ids no puede ser vacío"}

            if len(set(seat_ids)) != len(seat_ids):
                return {"ok": False, "error": "DUPLICATE_SEATS", "message": "seat_ids contiene duplicados"}

            if len(seat_ids) > self._max_seats:
                return {
                    "ok": False,
                    "error": "MAX_SEATS_EXCEEDED",
                    "message": f"Máximo {self._max_seats} asientos por reserva",
                }

            # Verificar asientos existen
            for sid in seat_ids:
                if sid not in self._seats:
                    return {"ok": False, "error": "SEAT_NOT_FOUND", "message": f"Asiento {sid} no existe"}

            # Idempotencia
            if idempotency_key:
                cached = self._idempotency.get(idempotency_key)
                if cached:
                    cached_payload = cached["payload"]
                    current_payload = {"user_id": user_id, "event_id": event_id, "seat_ids": sorted(seat_ids)}
                    if cached_payload == current_payload:
                        return cached["result"]
                    else:
                        return {
                            "ok": False,
                            "error": "IDEMPOTENCY_CONFLICT",
                            "message": "Idempotency-Key reutilizada con payload diferente",
                        }

            # Verificar límite de asientos activos del usuario
            user_active_seats = self._count_user_active_seats(user_id)
            if user_active_seats + len(seat_ids) > self._max_seats:
                return {
                    "ok": False,
                    "error": "MAX_SEATS_EXCEEDED",
                    "message": f"El usuario ya tiene {user_active_seats} asientos en HOLDs activos",
                }

            # Verificar disponibilidad (todo-o-nada)
            unavailable = []
            for sid in seat_ids:
                seat = self._seats[sid]
                if seat.status != SeatStatus.AVAILABLE:
                    unavailable.append(sid)

            if unavailable:
                return {
                    "ok": False,
                    "error": "SEATS_UNAVAILABLE",
                    "message": f"Asientos no disponibles: {unavailable}",
                }

            # Crear HOLD
            hold_id = f"hold_{uuid.uuid4().hex[:8].upper()}"
            total_price = sum(self._seats[sid].price for sid in seat_ids)
            currency = self._seats[seat_ids[0]].currency
            expires_at = (utc_now() + timedelta(seconds=self._hold_ttl)).isoformat()

            hold = Hold(
                hold_id=hold_id,
                user_id=user_id,
                event_id=event_id,
                seat_ids=list(seat_ids),
                total_price=total_price,
                currency=currency,
                status=HoldStatus.ACTIVE,
                expires_at=expires_at,
            )
            self._holds[hold_id] = hold

            # Marcar asientos como HELD
            for sid in seat_ids:
                seat = self._seats[sid]
                old_status = seat.status
                seat.status = SeatStatus.HELD
                seat.held_by = user_id
                seat.hold_id = hold_id
                self._trace.append(TraceEvent(
                    hold_id=hold_id,
                    seat_id=sid,
                    user_id=user_id,
                    from_state=old_status.value,
                    to_state=SeatStatus.HELD.value,
                    reason="hold_created",
                ))

            result = {
                "ok": True,
                "hold_id": hold_id,
                "user_id": user_id,
                "event_id": event_id,
                "seat_ids": list(seat_ids),
                "total_price": total_price,
                "currency": currency,
                "status": HoldStatus.ACTIVE.value,
                "remaining_seconds": self._hold_ttl,
                "created_at": hold.created_at,
                "expires_at": hold.expires_at,
            }

            # Guardar idempotencia
            if idempotency_key:
                self._idempotency[idempotency_key] = {
                    "payload": {"user_id": user_id, "event_id": event_id, "seat_ids": sorted(seat_ids)},
                    "result": result,
                }

            return result

    # ── Core: Confirm ──────────────────────────────────────

    def confirm_hold(self, hold_id: str) -> dict[str, Any]:
        """
        Marcar un HOLD como confirmado (SOLD).
        No maneja pago - solo transición de estado.
        Retorna el estado actual del hold.
        """
        with self._lock:
            self._expire_all()

            hold = self._holds.get(hold_id)
            if not hold:
                return {"ok": False, "error": "HOLD_NOT_FOUND", "message": f"HOLD {hold_id} no existe"}

            if hold.status == HoldStatus.CONFIRMED:
                return {"ok": False, "error": "ALREADY_CONFIRMED", "message": "HOLD ya confirmado"}

            if hold.status == HoldStatus.EXPIRED:
                return {"ok": False, "error": "HOLD_EXPIRED", "message": "HOLD expirado"}

            if hold.status == HoldStatus.RELEASED:
                return {"ok": False, "error": "HOLD_RELEASED", "message": "HOLD liberado"}

            if hold.is_expired():
                self._expire_hold(hold)
                return {"ok": False, "error": "HOLD_EXPIRED", "message": "HOLD expirado"}

            # Confirmar
            hold.status = HoldStatus.CONFIRMED
            hold.confirmed_at = utc_now_iso()

            for sid in hold.seat_ids:
                seat = self._seats[sid]
                old_status = seat.status
                seat.status = SeatStatus.SOLD
                seat.hold_id = hold_id
                self._trace.append(TraceEvent(
                    hold_id=hold_id,
                    seat_id=sid,
                    user_id=hold.user_id,
                    from_state=old_status.value,
                    to_state=SeatStatus.SOLD.value,
                    reason="payment_approved",
                ))

            return {
                "ok": True,
                "hold_id": hold_id,
                "status": HoldStatus.CONFIRMED.value,
                "seat_ids": hold.seat_ids,
                "total_price": hold.total_price,
                "message": "Compra confirmada",
            }

    def release_hold(self, hold_id: str, reason: str = "released") -> dict[str, Any]:
        """Liberar un HOLD y devolver asientos a AVAILABLE."""
        with self._lock:
            hold = self._holds.get(hold_id)
            if not hold:
                return {"ok": False, "error": "HOLD_NOT_FOUND", "message": f"HOLD {hold_id} no existe"}

            if hold.status == HoldStatus.CONFIRMED:
                return {"ok": False, "error": "ALREADY_CONFIRMED", "message": "No se puede liberar un HOLD confirmado"}

            if hold.status in (HoldStatus.EXPIRED, HoldStatus.RELEASED):
                return {"ok": True, "hold_id": hold_id, "message": "HOLD ya liberado"}

            hold.status = HoldStatus.RELEASED
            for sid in hold.seat_ids:
                seat = self._seats[sid]
                if seat.status == SeatStatus.HELD:
                    old_status = seat.status
                    seat.status = SeatStatus.AVAILABLE
                    seat.held_by = None
                    seat.hold_id = None
                    self._trace.append(TraceEvent(
                        hold_id=hold_id,
                        seat_id=sid,
                        user_id=hold.user_id,
                        from_state=old_status.value,
                        to_state=SeatStatus.AVAILABLE.value,
                        reason=reason,
                    ))

            return {"ok": True, "hold_id": hold_id, "message": "HOLD liberado"}

    # ── Expiration ────────────────────────────────────────

    def _expire_hold(self, hold: Hold) -> None:
        """Marcar hold como expirado y liberar asientos. Debe llamarse dentro del lock."""
        if hold.status != HoldStatus.ACTIVE:
            return
        if not hold.is_expired():
            return

        hold.status = HoldStatus.EXPIRED
        for sid in hold.seat_ids:
            seat = self._seats.get(sid)
            if seat and seat.status == SeatStatus.HELD and seat.hold_id == hold.hold_id:
                old_status = seat.status
                seat.status = SeatStatus.AVAILABLE
                seat.held_by = None
                seat.hold_id = None
                self._trace.append(TraceEvent(
                    hold_id=hold.hold_id,
                    seat_id=sid,
                    user_id=hold.user_id,
                    from_state=old_status.value,
                    to_state=SeatStatus.AVAILABLE.value,
                    reason="hold_expired",
                ))

    def _expire_all(self) -> None:
        """Expirar todos los holds vencidos. Debe llamarse dentro del lock."""
        for hold in list(self._holds.values()):
            self._expire_hold(hold)

    def expire_now(self) -> int:
        """Forzar expiración de holds vencidos. API pública."""
        with self._lock:
            count = 0
            for hold in list(self._holds.values()):
                if hold.status == HoldStatus.ACTIVE and hold.is_expired():
                    self._expire_hold(hold)
                    count += 1
            return count

    # ── Helpers ───────────────────────────────────────────

    def _count_user_active_seats(self, user_id: str) -> int:
        """Contar asientos en HOLDs activos de un usuario. Debe llamarse dentro del lock."""
        count = 0
        for hold in self._holds.values():
            if hold.user_id == user_id and hold.status == HoldStatus.ACTIVE and not hold.is_expired():
                count += len(hold.seat_ids)
        return count

    def get_available_seats(self) -> list[Seat]:
        with self._lock:
            self._expire_all()
            return [s for s in self._seats.values() if s.status == SeatStatus.AVAILABLE]

    def get_seat_map(self) -> list[dict[str, Any]]:
        with self._lock:
            self._expire_all()
            return [
                {
                    "seat_id": s.seat_id,
                    "section": s.section,
                    "price": s.price,
                    "currency": s.currency,
                    "status": s.status.value,
                    "held_by": s.held_by,
                    "hold_id": s.hold_id,
                }
                for s in self._seats.values()
            ]

    def get_user_holds(self, user_id: str) -> list[Hold]:
        with self._lock:
            self._expire_all()
            return [h for h in self._holds.values() if h.user_id == user_id]

    def get_trace_for_hold(self, hold_id: str) -> list[TraceEvent]:
        with self._lock:
            return [t for t in self._trace if t.hold_id == hold_id]

    def reset(self) -> None:
        with self._lock:
            self._seats.clear()
            self._holds.clear()
            self._trace.clear()
            self._idempotency.clear()
