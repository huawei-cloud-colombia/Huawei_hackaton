"""
models.py — Modelos de dominio del motor de reservas NEXUS LIVE.
Define los estados, asientos, reservas y eventos de auditoría.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ─── Enums de estado ───────────────────────────────────────────

class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    SOLD = "SOLD"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class PaymentResult(str, Enum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


class CircuitBreakerState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# ─── Modelos de solicitud ─────────────────────────────────────

class ReserveRequest(BaseModel):
    user_id: str = Field(..., min_length=1, description="ID del usuario")
    event_id: str = Field(..., min_length=1, description="ID del evento")
    seat_ids: List[str] = Field(..., min_length=1, description="Lista de asientos a reservar")


class ConfirmRequest(BaseModel):
    hold_id: str = Field(..., min_length=1, description="ID de la reserva")
    payment_token: str = Field(..., min_length=1, description="Token de pago")


# ─── Modelos de respuesta ─────────────────────────────────────

class SeatInfo(BaseModel):
    seat_id: str
    section: str
    price: int
    currency: str
    status: SeatStatus


class HoldInfo(BaseModel):
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: List[str]
    status: HoldStatus
    total: int
    currency: str
    created_at: datetime
    expires_at: datetime


class ReserveResponse(BaseModel):
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: List[str]
    status: str
    total: int
    currency: str
    expires_at: datetime


class ConfirmResponse(BaseModel):
    hold_id: str
    status: str
    payment_result: Optional[str] = None
    seats: List[str] = []
    total: Optional[int] = None
    currency: Optional[str] = None
    message: str = ""


class ErrorResponse(BaseModel):
    error: str
    reason: str
    detail: Optional[str] = None


# ─── Evento de auditoría / trazabilidad ───────────────────────

class AuditEvent(BaseModel):
    hold_id: Optional[str] = None
    user_id: Optional[str] = None
    seat_id: Optional[str] = None
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    extra: Optional[dict] = None


# ─── Resultado de carrera (simulación) ────────────────────────

class RaceResult(BaseModel):
    seat_id: str
    total_requests: int
    winners: int
    rejected: int
    hold_id: Optional[str] = None
    details: List[str] = []
