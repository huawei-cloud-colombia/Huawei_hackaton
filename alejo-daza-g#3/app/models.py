from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


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
    INVALID_TRANSITION = "invalid_transition"
    EMPTY_REQUEST = "empty_request"


class Section(str, Enum):
    VIP = "VIP"
    PLATEA = "PLATEA"
    GENERAL = "GENERAL"


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
    created_at: datetime
    expires_at: datetime


class RejectedResponse(BaseModel):
    status: str = "REJECTED"
    reason: Reason
    detail: str
    conflicting_seats: list[str] | None = None


class ConfirmRequest(BaseModel):
    user_id: str


class ConfirmResponse(BaseModel):
    status: str = "SOLD"
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: list[str]
    total: int
    currency: str


class HealthResponse(BaseModel):
    status: str
    hold_ttl_seconds: int
    max_seats_per_user: int


def utc_now() -> datetime:
    return datetime.now(tz=None).astimezone()
