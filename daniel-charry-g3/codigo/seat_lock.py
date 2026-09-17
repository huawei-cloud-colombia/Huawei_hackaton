"""
seat_lock.py — Motor de reservas NEXUS LIVE (SeatLock).

Núcleo del sistema: gestiona asientos, reservas temporales (HOLD),
expiración automática, concurrencia segura e idempotencia.

Estrategia de concurrencia:
  - asyncio.Lock global para operación atómica de reserva todo-o-nada.
  - Garantiza que 100 solicitudes concurrentes sobre 1 asiento → 1 ganador.

Estrategia de idempotencia:
  - Diccionario Idempotency-Key → (payload_hash, resultado).
  - Misma clave + mismo payload → mismo resultado.
  - Misma clave + payload diferente → IDEMPOTENCY_CONFLICT.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from config import config
from models import (
    SeatStatus, HoldStatus, PaymentResult,
    SeatInfo, HoldInfo, ReserveRequest, ReserveResponse,
    ConfirmResponse, AuditEvent,
)
from audit import audit_log


class Seat:
    """Asiento individual."""

    def __init__(self, seat_id: str, section: str, price: int, currency: str):
        self.seat_id = seat_id
        self.section = section
        self.price = price
        self.currency = currency
        self.status = SeatStatus.AVAILABLE
        self.hold_id: Optional[str] = None

    def to_info(self) -> SeatInfo:
        return SeatInfo(
            seat_id=self.seat_id,
            section=self.section,
            price=self.price,
            currency=self.currency,
            status=self.status,
        )


class Hold:
    """Reserva temporal."""

    def __init__(
        self,
        hold_id: str,
        user_id: str,
        event_id: str,
        seat_ids: List[str],
        total: int,
        currency: str,
        ttl_seconds: int,
    ):
        self.hold_id = hold_id
        self.user_id = user_id
        self.event_id = event_id
        self.seat_ids = seat_ids
        self.total = total
        self.currency = currency
        self.created_at = datetime.now(timezone.utc)
        self.expires_at = self.created_at + timedelta(seconds=ttl_seconds)
        self.status = HoldStatus.ACTIVE

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at and self.status == HoldStatus.ACTIVE

    @property
    def time_remaining(self) -> int:
        if self.status != HoldStatus.ACTIVE:
            return 0
        remaining = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(remaining))

    def to_info(self) -> HoldInfo:
        return HoldInfo(
            hold_id=self.hold_id,
            user_id=self.user_id,
            event_id=self.event_id,
            seat_ids=self.seat_ids,
            status=self.status,
            total=self.total,
            currency=self.currency,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )


class SeatLockEngine:
    """Motor principal de reservas con concurrencia segura e idempotencia."""

    def __init__(self):
        self._seats: Dict[str, Seat] = {}
        self._holds: Dict[str, Hold] = {}
        self._idempotency: Dict[str, Tuple[str, dict]] = {}
        self._global_lock = asyncio.Lock()
        self._init_seats()

    def _init_seats(self):
        """Inicializa el catálogo de asientos desde la configuración."""
        for section_name, (prefix, count, price) in config.seat_sections.items():
            for i in range(1, count + 1):
                seat_id = f"{prefix}-{i:03d}"
                self._seats[seat_id] = Seat(
                    seat_id=seat_id,
                    section=section_name,
                    price=price,
                    currency=config.currency,
                )

    # ─── Utilidades ───────────────────────────────────────────

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        """Hash normalizado del payload para comparación de idempotencia."""
        normalized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(normalized.encode()).hexdigest()

    @staticmethod
    def _gen_hold_id() -> str:
        return f"hold_{uuid.uuid4().hex[:8].upper()}"

    def _user_active_seat_count(self, user_id: str) -> int:
        """Cuenta asientos en reservas activas de un usuario."""
        count = 0
        for hold in self._holds.values():
            if hold.user_id == user_id and hold.status == HoldStatus.ACTIVE and not hold.is_expired:
                count += len(hold.seat_ids)
        return count

    # ─── Expiración ───────────────────────────────────────────

    def expire_holds(self) -> int:
        """Expira todos los HOLDs vencidos. Retorna cuántos expiraron."""
        expired_count = 0
        for hold in list(self._holds.values()):
            if hold.is_expired:
                hold.status = HoldStatus.EXPIRED
                for seat_id in hold.seat_ids:
                    seat = self._seats.get(seat_id)
                    if seat and seat.status == SeatStatus.HELD and seat.hold_id == hold.hold_id:
                        seat.status = SeatStatus.AVAILABLE
                        seat.hold_id = None
                        audit_log.record(
                            reason="hold_expired",
                            hold_id=hold.hold_id,
                            user_id=hold.user_id,
                            seat_id=seat_id,
                            from_state=SeatStatus.HELD.value,
                            to_state=SeatStatus.AVAILABLE.value,
                        )
                expired_count += 1
        return expired_count

    # ─── Consultas ────────────────────────────────────────────

    def get_all_seats(self) -> List[SeatInfo]:
        self.expire_holds()
        return [s.to_info() for s in self._seats.values()]

    def get_available_seats(self) -> List[SeatInfo]:
        self.expire_holds()
        return [s.to_info() for s in self._seats.values() if s.status == SeatStatus.AVAILABLE]

    def get_seat(self, seat_id: str) -> Optional[Seat]:
        return self._seats.get(seat_id)

    def get_hold(self, hold_id: str) -> Optional[Hold]:
        hold = self._holds.get(hold_id)
        if hold and hold.is_expired:
            self.expire_holds()
        return self._holds.get(hold_id)

    def get_all_holds(self) -> List[Hold]:
        self.expire_holds()
        return list(self._holds.values())

    # ─── Reserva (HOLD) ───────────────────────────────────────

    async def reserve(
        self,
        request: ReserveRequest,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """
        Crea una reserva temporal (HOLD).
        Retorna dict con 'success' bool y datos o error.
        """
        self.expire_holds()

        # ── Validación de idempotencia ──
        payload_dict = request.model_dump()
        payload_hash = self._hash_payload(payload_dict)

        if idempotency_key and idempotency_key in self._idempotency:
            stored_hash, stored_result = self._idempotency[idempotency_key]
            if stored_hash == payload_hash:
                return stored_result  # Replay exacto
            else:
                return {
                    "success": False,
                    "error": "IDEMPOTENCY_CONFLICT",
                    "reason": "idempotency_key_reused_with_different_payload",
                }

        async with self._global_lock:
            # ── Validaciones de entrada ──
            seat_ids = request.seat_ids

            # Duplicados en la solicitud
            if len(seat_ids) != len(set(seat_ids)):
                result = {
                    "success": False,
                    "error": "DUPLICATE_SEAT",
                    "reason": "seat_ids contains duplicates",
                }
                if idempotency_key:
                    self._idempotency[idempotency_key] = (payload_hash, result)
                return result

            # Asientos inexistentes
            missing = [sid for sid in seat_ids if sid not in self._seats]
            if missing:
                result = {
                    "success": False,
                    "error": "SEAT_NOT_FOUND",
                    "reason": f"seats not found: {missing}",
                }
                if idempotency_key:
                    self._idempotency[idempotency_key] = (payload_hash, result)
                return result

            # Disponibilidad (todo-o-nada)
            unavailable = [
                sid for sid in seat_ids
                if self._seats[sid].status != SeatStatus.AVAILABLE
            ]
            if unavailable:
                result = {
                    "success": False,
                    "error": "SEAT_NOT_AVAILABLE",
                    "reason": f"seats not available: {unavailable}",
                }
                if idempotency_key:
                    self._idempotency[idempotency_key] = (payload_hash, result)
                return result

            # Límite por usuario
            current_count = self._user_active_seat_count(request.user_id)
            if current_count + len(seat_ids) > config.max_seats_per_user:
                result = {
                    "success": False,
                    "error": "SEAT_LIMIT_EXCEEDED",
                    "reason": f"user has {current_count} active seats, max is {config.max_seats_per_user}",
                }
                if idempotency_key:
                    self._idempotency[idempotency_key] = (payload_hash, result)
                return result

            # ── Crear HOLD ──
            hold_id = self._gen_hold_id()
            total = sum(self._seats[sid].price for sid in seat_ids)
            currency = self._seats[seat_ids[0]].currency

            hold = Hold(
                hold_id=hold_id,
                user_id=request.user_id,
                event_id=request.event_id,
                seat_ids=seat_ids,
                total=total,
                currency=currency,
                ttl_seconds=config.hold_ttl_seconds,
            )
            self._holds[hold_id] = hold

            # Marcar asientos como HELD
            for sid in seat_ids:
                seat = self._seats[sid]
                seat.status = SeatStatus.HELD
                seat.hold_id = hold_id
                audit_log.record(
                    reason="hold_created",
                    hold_id=hold_id,
                    user_id=request.user_id,
                    seat_id=sid,
                    from_state=SeatStatus.AVAILABLE.value,
                    to_state=SeatStatus.HELD.value,
                )

            result = {
                "success": True,
                "hold_id": hold_id,
                "user_id": request.user_id,
                "event_id": request.event_id,
                "seat_ids": seat_ids,
                "status": "HELD",
                "total": total,
                "currency": currency,
                "expires_at": hold.expires_at.isoformat(),
            }

            if idempotency_key:
                self._idempotency[idempotency_key] = (payload_hash, result)

            return result

    # ─── Liberar HOLD ─────────────────────────────────────────

    async def release_hold(self, hold_id: str) -> dict:
        """Libera un HOLD manualmente."""
        async with self._global_lock:
            hold = self._holds.get(hold_id)
            if not hold:
                return {"success": False, "error": "HOLD_NOT_FOUND", "reason": f"hold {hold_id} not found"}

            if hold.status != HoldStatus.ACTIVE:
                return {"success": False, "error": "HOLD_NOT_ACTIVE", "reason": f"hold status is {hold.status.value}"}

            hold.status = HoldStatus.RELEASED
            for sid in hold.seat_ids:
                seat = self._seats.get(sid)
                if seat and seat.status == SeatStatus.HELD and seat.hold_id == hold_id:
                    seat.status = SeatStatus.AVAILABLE
                    seat.hold_id = None
                    audit_log.record(
                        reason="hold_released",
                        hold_id=hold_id,
                        user_id=hold.user_id,
                        seat_id=sid,
                        from_state=SeatStatus.HELD.value,
                        to_state=SeatStatus.AVAILABLE.value,
                    )

            return {"success": True, "hold_id": hold_id, "status": "RELEASED"}

    # ─── Confirmar compra (HELD → SOLD) ───────────────────────

    async def confirm_hold(self, hold_id: str, payment_result: PaymentResult) -> dict:
        """
        Confirma un HOLD tras resultado de pago.
        APPROVED → SOLD, DECLINED → libera, ERROR/TIMEOUT → mantiene HOLD.
        """
        async with self._global_lock:
            hold = self._holds.get(hold_id)
            if not hold:
                return {"success": False, "error": "HOLD_NOT_FOUND", "reason": f"hold {hold_id} not found"}

            if hold.status == HoldStatus.CONFIRMED:
                return {"success": False, "error": "HOLD_ALREADY_CONFIRMED", "reason": "hold already sold"}

            if hold.status in (HoldStatus.EXPIRED, HoldStatus.RELEASED):
                return {"success": False, "error": "HOLD_NOT_ACTIVE", "reason": f"hold status is {hold.status.value}"}

            if hold.is_expired:
                hold.status = HoldStatus.EXPIRED
                return {"success": False, "error": "HOLD_EXPIRED", "reason": "hold has expired"}

            if payment_result == PaymentResult.APPROVED:
                # HELD → SOLD
                hold.status = HoldStatus.CONFIRMED
                for sid in hold.seat_ids:
                    seat = self._seats[sid]
                    seat.status = SeatStatus.SOLD
                    seat.hold_id = hold_id
                    audit_log.record(
                        reason="payment_approved",
                        hold_id=hold_id,
                        user_id=hold.user_id,
                        seat_id=sid,
                        from_state=SeatStatus.HELD.value,
                        to_state=SeatStatus.SOLD.value,
                    )
                return {
                    "success": True,
                    "hold_id": hold_id,
                    "status": "SOLD",
                    "payment_result": payment_result.value,
                    "seats": hold.seat_ids,
                    "total": hold.total,
                    "currency": hold.currency,
                    "message": "Compra confirmada exitosamente",
                }

            elif payment_result == PaymentResult.DECLINED:
                # Liberar asientos
                hold.status = HoldStatus.RELEASED
                for sid in hold.seat_ids:
                    seat = self._seats[sid]
                    seat.status = SeatStatus.AVAILABLE
                    seat.hold_id = None
                    audit_log.record(
                        reason="payment_declined",
                        hold_id=hold_id,
                        user_id=hold.user_id,
                        seat_id=sid,
                        from_state=SeatStatus.HELD.value,
                        to_state=SeatStatus.AVAILABLE.value,
                    )
                return {
                    "success": False,
                    "hold_id": hold_id,
                    "status": "RELEASED",
                    "payment_result": payment_result.value,
                    "message": "Pago rechazado, asientos liberados",
                }

            else:
                # ERROR o TIMEOUT: mantener HOLD, no liberar
                audit_log.record(
                    reason=f"payment_{payment_result.value.lower()}",
                    hold_id=hold_id,
                    user_id=hold.user_id,
                    extra={"payment_result": payment_result.value},
                )
                return {
                    "success": False,
                    "hold_id": hold_id,
                    "status": "HELD",
                    "payment_result": payment_result.value,
                    "message": f"Pago {payment_result.value}, HOLD mantiene asientos. Reintentar.",
                }

    # ─── Simulación de carrera ────────────────────────────────

    async def simulate_race(self, seat_id: str, num_users: int = 20) -> dict:
        """
        Simula N usuarios compitiendo por 1 asiento simultáneamente.
        Garantiza exactamente 1 ganador.
        """
        self.expire_holds()

        if seat_id not in self._seats:
            return {"success": False, "error": "SEAT_NOT_FOUND", "reason": f"seat {seat_id} not found"}

        # Resetear el asiento a AVAILABLE para la simulación
        async with self._global_lock:
            seat = self._seats[seat_id]
            if seat.status != SeatStatus.AVAILABLE:
                seat.status = SeatStatus.AVAILABLE
                seat.hold_id = None

        results = []
        tasks = []
        for i in range(num_users):
            req = ReserveRequest(
                user_id=f"usr_race_{i:04d}",
                event_id=config.default_event_id,
                seat_ids=[seat_id],
            )
            tasks.append(self.reserve(req, idempotency_key=f"race-{seat_id}-{i}"))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        winners = 0
        rejected = 0
        winner_hold_id = None
        details = []

        for i, resp in enumerate(responses):
            if isinstance(resp, Exception):
                rejected += 1
                details.append(f"usr_race_{i:04d}: ERROR - {resp}")
            elif resp.get("success"):
                winners += 1
                winner_hold_id = resp["hold_id"]
                details.append(f"usr_race_{i:04d}: WINNER - hold={resp['hold_id']}")
            else:
                rejected += 1
                details.append(f"usr_race_{i:04d}: REJECTED - {resp.get('error')}")

        return {
            "success": True,
            "seat_id": seat_id,
            "total_requests": num_users,
            "winners": winners,
            "rejected": rejected,
            "hold_id": winner_hold_id,
            "details": details,
        }


# Instancia global del motor
engine = SeatLockEngine()
