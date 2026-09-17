from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from .config import Settings, settings
from .models import Event, EventType, HoldStatus, Reason, SeatStatus, iso


class SeatLockError(Exception):
    def __init__(self, reason: Reason, detail: str, conflicting_seats: list[str] | None = None):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
        self.conflicting_seats = conflicting_seats


@dataclass
class SeatRuntime:
    seat_id: str
    section: str
    price: int
    currency: str
    status: SeatStatus = SeatStatus.AVAILABLE
    held_by: str | None = None


@dataclass
class HoldRuntime:
    hold_id: str
    user_id: str
    event_id: str
    seat_ids: list[str]
    status: HoldStatus = HoldStatus.HELD
    total: int = 0
    currency: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0
    checking: bool = False


def new_hold_id() -> str:
    return "hold_" + secrets.token_hex(5).upper()


def build_catalog(cfg: Settings = settings) -> dict[str, SeatRuntime]:
    seats: dict[str, SeatRuntime] = {}
    for section, prefix, count, price, width in cfg.seat_sections:
        for i in range(1, count + 1):
            sid = f"{prefix}-{i:0{width}d}"
            seats[sid] = SeatRuntime(sid, section, price, cfg.currency)
    return seats


class StateMachine:
    def __init__(self, seats: dict[str, SeatRuntime], cfg: Settings = settings):
        self.cfg = cfg
        self.seats = seats
        self.holds: dict[str, HoldRuntime] = {}
        self.user_active: dict[str, int] = {}
        self._locks: list[asyncio.Lock] = [asyncio.Lock() for _ in range(cfg.num_shards)]
        self.trace: list[dict] = []
        self._trace_seq = 0

    def _record_trace(self, hold_id: str, user_id: str, seat_ids: list[str], prev: str, new: str, reason: str, ts: float) -> None:
        self._trace_seq += 1
        self.trace.append({
            "transition_id": self._trace_seq,
            "hold_id": hold_id,
            "user_id": user_id,
            "seat_ids": list(seat_ids),
            "prev_status": prev,
            "new_status": new,
            "reason": reason,
            "timestamp": ts,
        })
        if len(self.trace) > 50000:
            self.trace = self.trace[-40000:]

    def _shard(self, seat_id: str) -> int:
        return hash(seat_id) % self.cfg.num_shards

    @asynccontextmanager
    async def _acquire(self, seat_ids: list[str]) -> AsyncIterator[None]:
        idxs = sorted({self._shard(sid) for sid in seat_ids})
        locks = [self._locks[i] for i in idxs]
        for lk in locks:
            await lk.acquire()
        try:
            yield
        finally:
            for lk in reversed(locks):
                lk.release()

    def get_seat(self, seat_id: str) -> SeatRuntime | None:
        return self.seats.get(seat_id)

    def list_seats(self, event_id: str, section: str | None = None) -> list[SeatRuntime]:
        out = []
        for s in self.seats.values():
            if section and s.section != section:
                continue
            out.append(s)
        return out

    def counts(self) -> dict[str, int]:
        av = hd = sd = 0
        for s in self.seats.values():
            if s.status == SeatStatus.AVAILABLE:
                av += 1
            elif s.status == SeatStatus.HELD:
                hd += 1
            elif s.status == SeatStatus.SOLD:
                sd += 1
        return {"available": av, "held": hd, "sold": sd}

    async def create_hold(self, user_id: str, event_id: str, seat_ids: list[str], now: float):
        seen: list[str] = []
        for sid in seat_ids:
            if sid not in seen:
                seen.append(sid)
        seat_ids = seen
        if not seat_ids:
            raise SeatLockError(Reason.EMPTY_REQUEST, "seat_ids is empty")

        async with self._acquire(seat_ids):
            conflicts: list[str] = []
            for sid in seat_ids:
                seat = self.seats.get(sid)
                if seat is None or seat.status != SeatStatus.AVAILABLE:
                    conflicts.append(sid)
            if conflicts:
                raise SeatLockError(Reason.SEAT_NOT_AVAILABLE, f"seats not available: {conflicts}", conflicts)

            active = self.user_active.get(user_id, 0)
            if active + len(seat_ids) > self.cfg.max_seats_per_user:
                raise SeatLockError(
                    Reason.MAX_SEATS_EXCEEDED,
                    f"user holds {active} active seats; requesting {len(seat_ids)}; "
                    f"limit is {self.cfg.max_seats_per_user}",
                )

            total = sum(self.seats[sid].price for sid in seat_ids)
            currency = self.seats[seat_ids[0]].currency
            hold_id = new_hold_id()
            expires = now + self.cfg.hold_ttl_seconds
            hold = HoldRuntime(
                hold_id=hold_id, user_id=user_id, event_id=event_id, seat_ids=list(seat_ids),
                status=HoldStatus.HELD, total=total, currency=currency,
                created_at=now, expires_at=expires,
            )
            self.holds[hold_id] = hold
            for sid in seat_ids:
                seat = self.seats[sid]
                seat.status = SeatStatus.HELD
                seat.held_by = hold_id
            self.user_active[user_id] = active + len(seat_ids)

            event = Event(
                type=EventType.HOLD_CREATED, hold_id=hold_id, seat_ids=list(seat_ids),
                user_id=user_id, event_id=event_id, total=total, currency=currency,
                created_at=now, expires_at=expires,
                prev_status=SeatStatus.AVAILABLE.value, new_status=SeatStatus.HELD.value,
                reason="hold_created", timestamp=now,
            )
            self._record_trace(hold_id, user_id, seat_ids, SeatStatus.AVAILABLE.value, SeatStatus.HELD.value, "hold_created", now)
            return hold, [event]

    async def checkout(self, hold_id: str, user_id: str, now: float, reason: str = "checkout"):
        hold = self.holds.get(hold_id)
        if hold is None or hold.user_id != user_id:
            raise SeatLockError(Reason.HOLD_NOT_FOUND, f"hold {hold_id} not found for user {user_id}")

        async with self._acquire(hold.seat_ids):
            hold = self.holds.get(hold_id)
            if hold is None or hold.user_id != user_id:
                raise SeatLockError(Reason.HOLD_NOT_FOUND, f"hold {hold_id} not found for user {user_id}")
            if hold.status == HoldStatus.EXPIRED or (hold.status == HoldStatus.HELD and hold.expires_at <= now):
                raise SeatLockError(Reason.HOLD_EXPIRED, f"hold {hold_id} expired")
            if hold.status != HoldStatus.HELD:
                raise SeatLockError(Reason.HOLD_NOT_ACTIVE, f"hold {hold_id} status is {hold.status.value}")

            for sid in hold.seat_ids:
                seat = self.seats[sid]
                if seat.status != SeatStatus.HELD or seat.held_by != hold_id:
                    raise SeatLockError(Reason.SEAT_NOT_HELD, f"seat {sid} is not held by {hold_id}")
                seat.status = SeatStatus.SOLD
            hold.status = HoldStatus.SOLD
            self.user_active[user_id] = max(0, self.user_active.get(user_id, 0) - len(hold.seat_ids))

            event = Event(
                type=EventType.HOLD_CONFIRMED, hold_id=hold_id, seat_ids=list(hold.seat_ids),
                user_id=user_id, prev_status=SeatStatus.HELD.value, new_status=SeatStatus.SOLD.value,
                reason=reason, timestamp=now,
            )
            self._record_trace(hold_id, user_id, hold.seat_ids, SeatStatus.HELD.value, SeatStatus.SOLD.value, reason, now)
            return hold, [event]

    async def release(self, hold_id: str, user_id: str, now: float, reason: str = "released"):
        hold = self.holds.get(hold_id)
        if hold is None or hold.user_id != user_id:
            raise SeatLockError(Reason.HOLD_NOT_FOUND, f"hold {hold_id} not found for user {user_id}")

        async with self._acquire(hold.seat_ids):
            hold = self.holds.get(hold_id)
            if hold is None or hold.user_id != user_id:
                raise SeatLockError(Reason.HOLD_NOT_FOUND, f"hold {hold_id} not found for user {user_id}")
            if hold.status == HoldStatus.EXPIRED or (hold.status == HoldStatus.HELD and hold.expires_at <= now):
                raise SeatLockError(Reason.HOLD_EXPIRED, f"hold {hold_id} expired")
            if hold.status != HoldStatus.HELD:
                raise SeatLockError(Reason.HOLD_NOT_ACTIVE, f"hold {hold_id} status is {hold.status.value}")

            for sid in hold.seat_ids:
                seat = self.seats[sid]
                if seat.status == SeatStatus.HELD and seat.held_by == hold_id:
                    seat.status = SeatStatus.AVAILABLE
                    seat.held_by = None
            hold.status = HoldStatus.RELEASED
            self.user_active[user_id] = max(0, self.user_active.get(user_id, 0) - len(hold.seat_ids))

            event = Event(
                type=EventType.HOLD_RELEASED, hold_id=hold_id, seat_ids=list(hold.seat_ids),
                user_id=user_id, prev_status=SeatStatus.HELD.value, new_status=SeatStatus.AVAILABLE.value,
                reason=reason, timestamp=now,
            )
            self._record_trace(hold_id, user_id, hold.seat_ids, SeatStatus.HELD.value, SeatStatus.AVAILABLE.value, reason, now)
            return hold, [event]

    async def reap(self, now: float, chunk: int = 1000) -> list[Event]:
        expired = [h for h in self.holds.values() if h.status == HoldStatus.HELD and not h.checking and h.expires_at <= now]
        events: list[Event] = []
        for i in range(0, len(expired), chunk):
            batch = expired[i : i + chunk]
            for hold in batch:
                if hold.status != HoldStatus.HELD:
                    continue
                for sid in hold.seat_ids:
                    seat = self.seats[sid]
                    if seat.status == SeatStatus.HELD and seat.held_by == hold.hold_id:
                        seat.status = SeatStatus.AVAILABLE
                        seat.held_by = None
                hold.status = HoldStatus.EXPIRED
                self.user_active[hold.user_id] = max(0, self.user_active.get(hold.user_id, 0) - len(hold.seat_ids))
                events.append(Event(
                    type=EventType.HOLD_EXPIRED, hold_id=hold.hold_id, seat_ids=list(hold.seat_ids),
                    user_id=hold.user_id, prev_status=SeatStatus.HELD.value, new_status=SeatStatus.AVAILABLE.value,
                    reason="expired", timestamp=now,
                ))
                self._record_trace(hold.hold_id, hold.user_id, hold.seat_ids, SeatStatus.HELD.value, SeatStatus.AVAILABLE.value, "expired", now)
            if i + chunk < len(expired):
                await asyncio.sleep(0)
        return events
