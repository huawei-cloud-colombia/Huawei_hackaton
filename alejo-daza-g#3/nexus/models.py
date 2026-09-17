from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


@dataclass
class Event:
    type: "EventType"
    hold_id: str
    seat_ids: list[str]
    user_id: str | None = None
    event_id: str | None = None
    total: int = 0
    currency: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0
    prev_status: str = ""
    new_status: str = ""
    reason: str = ""
    timestamp: float = 0.0


class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    SOLD = "SOLD"


class HoldStatus(str, Enum):
    HELD = "HELD"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    SOLD = "SOLD"


class Reason(str, Enum):
    SEAT_NOT_AVAILABLE = "seat_not_available"
    MAX_SEATS_EXCEEDED = "max_seats_exceeded"
    HOLD_NOT_FOUND = "hold_not_found"
    HOLD_EXPIRED = "hold_expired"
    HOLD_NOT_ACTIVE = "hold_not_active"
    SEAT_NOT_HELD = "seat_not_held"
    EMPTY_REQUEST = "empty_request"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    PAYMENT_DECLINED = "PAYMENT_DECLINED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_SERVICE_UNAVAILABLE = "PAYMENT_SERVICE_UNAVAILABLE"


class EventType(str, Enum):
    HOLD_CREATED = "HOLD_CREATED"
    HOLD_RELEASED = "HOLD_RELEASED"
    HOLD_CONFIRMED = "HOLD_CONFIRMED"
    HOLD_EXPIRED = "HOLD_EXPIRED"


class PaymentStatus(str, Enum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"


@dataclass
class PaymentResult:
    status: PaymentStatus
    transaction_id: str | None = None


UTC = timezone.utc


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Seat(BaseModel):
    seat_id: str
    event_id: str
    section: str
    price: int
    currency: str
    status: SeatStatus
    held_by_hold_id: str | None = None


class HoldRequest(BaseModel):
    user_id: str
    event_id: str
    seat_ids: list[str] = Field(min_length=1)


class Hold(BaseModel):
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: list[str]
    status: HoldStatus
    total: int
    currency: str
    created_at: str
    expires_at: str


class CheckoutRequest(BaseModel):
    hold_id: str
    user_id: str
    payment_token: str


class CheckoutResponse(BaseModel):
    status: str = "SOLD"
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: list[str]
    total: int
    currency: str
    transaction_id: str | None = None


class Confirmation(BaseModel):
    confirmation_id: str
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: list[str]
    total: int
    currency: str
    transaction_id: str
    confirmed_at: str


class Transition(BaseModel):
    transition_id: int
    hold_id: str
    user_id: str
    seat_ids: list[str]
    prev_status: str
    new_status: str
    reason: str
    timestamp: str


class ReleaseRequest(BaseModel):
    hold_id: str
    user_id: str


class ReleaseResponse(BaseModel):
    status: str = "RELEASED"
    hold_id: str
    seat_ids: list[str]


class RejectedResponse(BaseModel):
    status: str = "REJECTED"
    reason: Reason
    detail: str
    conflicting_seats: list[str] | None = None


class StatsResponse(BaseModel):
    total_seats: int
    available: int
    held: int
    sold: int
    active_holds: int
    writer_events_processed: int
    writer_errors: int
    writer_queue_depth: int
    idempotency_entries: int
    cb_state: str
    pay_authorized: int
    pay_declined: int
    pay_error: int
    pay_timeout: int
    pay_mode: str
