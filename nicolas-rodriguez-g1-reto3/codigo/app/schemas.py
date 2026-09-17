"""Modelos y esquemas de datos para NEXUS LIVE."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


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


class Seat(BaseModel):
    seat_id: str
    section: str = "GENERAL"
    price: float = 50.0
    currency: str = "COP"
    status: SeatStatus = SeatStatus.AVAILABLE
    held_by: Optional[str] = None
    hold_id: Optional[str] = None

    def is_available(self) -> bool:
        return self.status == SeatStatus.AVAILABLE


class Hold(BaseModel):
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: list[str]
    total_price: float
    currency: str = "COP"
    status: HoldStatus = HoldStatus.ACTIVE
    created_at: str = Field(default_factory=utc_now_iso)
    expires_at: str = ""
    confirmed_at: Optional[str] = None

    def is_active(self) -> bool:
        return self.status == HoldStatus.ACTIVE

    def is_expired(self) -> bool:
        if self.status != HoldStatus.ACTIVE:
            return False
        return utc_now() > datetime.fromisoformat(self.expires_at)

    def remaining_seconds(self) -> float:
        if not self.is_active():
            return 0.0
        delta = datetime.fromisoformat(self.expires_at) - utc_now()
        return max(0.0, delta.total_seconds())


class TraceEvent(BaseModel):
    timestamp: str = Field(default_factory=utc_now_iso)
    hold_id: Optional[str] = None
    seat_id: Optional[str] = None
    user_id: Optional[str] = None
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReserveRequest(BaseModel):
    user_id: str
    event_id: str
    seat_ids: list[str]


class ConfirmRequest(BaseModel):
    hold_id: str
    payment_token: str


class RaceResult(BaseModel):
    total_requests: int
    winners: int
    rejected: int
    overselling: int
    results: list[dict[str, Any]] = Field(default_factory=list)


class HoldResponse(BaseModel):
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: list[str]
    total_price: float
    currency: str
    status: str
    remaining_seconds: float
    created_at: str
    expires_at: str


class ConfirmResponse(BaseModel):
    hold_id: str
    status: str
    payment_result: str
    seats: list[str]
    total_price: float
    message: str


class WaitlistEntry(BaseModel):
    position: int
    user_id: str
    event_id: str
    seat_ids: list[str]
    joined_at: str = Field(default_factory=utc_now_iso)
