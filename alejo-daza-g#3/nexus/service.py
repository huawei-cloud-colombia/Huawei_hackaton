from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time

from .idempotency import IdempotencyStore
from .models import (
    CheckoutResponse,
    Confirmation,
    Event,
    Hold,
    HoldStatus,
    PaymentStatus,
    Reason,
    RejectedResponse,
    ReleaseResponse,
    iso,
)
from .payment import CircuitBreaker, PaymentProvider
from .state import HoldRuntime, SeatLockError, StateMachine


def fingerprint(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _hold_to_dict(h: HoldRuntime) -> dict:
    return Hold(
        hold_id=h.hold_id,
        user_id=h.user_id,
        event_id=h.event_id,
        seat_ids=list(h.seat_ids),
        status=h.status,
        total=h.total,
        currency=h.currency,
        created_at=iso(h.created_at),
        expires_at=iso(h.expires_at),
    ).model_dump(mode="json")


def _rejected(reason: Reason, detail: str, conflicting: list[str] | None = None) -> dict:
    return RejectedResponse(reason=reason, detail=detail, conflicting_seats=conflicting).model_dump(mode="json")


class BookingService:
    def __init__(
        self,
        state: StateMachine,
        idem: IdempotencyStore,
        queue: asyncio.Queue,
        provider: PaymentProvider,
        cb: CircuitBreaker,
    ):
        self.state = state
        self.idem = idem
        self.queue = queue
        self.provider = provider
        self.cb = cb
        self.confirmations: dict[str, Confirmation] = {}

    async def _enqueue(self, events: list[Event]) -> None:
        for ev in events:
            await self.queue.put(ev)

    async def create_hold(self, key: str, user_id: str, event_id: str, seat_ids: list[str]) -> tuple[int, dict]:
        fp = fingerprint("hold", user_id, event_id, seat_ids)
        return await self.idem.run(key, fp, lambda: self._create_hold(user_id, event_id, seat_ids))

    async def _create_hold(self, user_id: str, event_id: str, seat_ids: list[str]) -> tuple[int, dict, bool]:
        try:
            hold, events = await self.state.create_hold(user_id, event_id, seat_ids, time.time())
            await self._enqueue(events)
            return 201, _hold_to_dict(hold), True
        except SeatLockError as e:
            return 409, _rejected(e.reason, e.detail, e.conflicting_seats), True

    async def release(self, key: str, hold_id: str, user_id: str) -> tuple[int, dict]:
        fp = fingerprint("release", hold_id, user_id)
        return await self.idem.run(key, fp, lambda: self._release(hold_id, user_id))

    async def _release(self, hold_id: str, user_id: str) -> tuple[int, dict, bool]:
        try:
            hold, events = await self.state.release(hold_id, user_id, time.time())
            await self._enqueue(events)
            return 200, ReleaseResponse(hold_id=hold.hold_id, seat_ids=list(hold.seat_ids)).model_dump(mode="json"), True
        except SeatLockError as e:
            status = 404 if e.reason == Reason.HOLD_NOT_FOUND else 409
            return status, _rejected(e.reason, e.detail), True

    async def checkout(self, key: str, hold_id: str, user_id: str, payment_token: str) -> tuple[int, dict]:
        fp = fingerprint("checkout", hold_id, user_id, payment_token)
        return await self.idem.run(key, fp, lambda: self._checkout(hold_id, user_id, payment_token))

    async def _checkout(self, hold_id: str, user_id: str, payment_token: str) -> tuple[int, dict, bool]:
        now = time.time()
        hold = self.state.holds.get(hold_id)
        if hold is None or hold.user_id != user_id:
            return 404, _rejected(Reason.HOLD_NOT_FOUND, f"hold {hold_id} not found for user {user_id}"), True
        if hold.status == HoldStatus.EXPIRED or (hold.status == HoldStatus.HELD and hold.expires_at <= now):
            return 409, _rejected(Reason.HOLD_EXPIRED, f"hold {hold_id} expired"), True
        if hold.status != HoldStatus.HELD:
            return 409, _rejected(Reason.HOLD_NOT_ACTIVE, f"hold {hold_id} status is {hold.status.value}"), True

        if not self.cb.allow_request():
            return 503, _rejected(Reason.PAYMENT_SERVICE_UNAVAILABLE, "circuit breaker is OPEN"), False

        hold.checking = True
        try:
            charge_key = f"{hold_id}:{payment_token}"
            result = await self.provider.authorize(charge_key, payment_token)
        finally:
            hold.checking = False

        if result.status in (PaymentStatus.APPROVED, PaymentStatus.DECLINED):
            self.cb.record_success()
        else:
            self.cb.record_failure()

        if result.status == PaymentStatus.APPROVED:
            try:
                hold2, events = await self.state.checkout(hold_id, user_id, time.time(), reason="payment_approved")
            except SeatLockError as e:
                return 409, _rejected(e.reason, e.detail), True
            await self._enqueue(events)
            conf = Confirmation(
                confirmation_id="conf_" + secrets.token_hex(5).upper(),
                hold_id=hold2.hold_id,
                user_id=hold2.user_id,
                event_id=hold2.event_id,
                seat_ids=list(hold2.seat_ids),
                total=hold2.total,
                currency=hold2.currency,
                transaction_id=result.transaction_id or "",
                confirmed_at=iso(now),
            )
            self.confirmations[hold2.hold_id] = conf
            return 200, CheckoutResponse(
                hold_id=hold2.hold_id, user_id=hold2.user_id, event_id=hold2.event_id,
                seat_ids=list(hold2.seat_ids), total=hold2.total, currency=hold2.currency,
                transaction_id=result.transaction_id,
            ).model_dump(mode="json"), True

        if result.status == PaymentStatus.DECLINED:
            try:
                hold2, events = await self.state.release(hold_id, user_id, time.time(), reason="payment_declined")
            except SeatLockError:
                pass
            else:
                await self._enqueue(events)
            return 402, _rejected(Reason.PAYMENT_DECLINED, "payment declined; hold released"), True

        return 409, _rejected(Reason.PAYMENT_PENDING, f"payment {result.status.value}; retry the same request"), False

    def get_confirmation(self, hold_id: str) -> Confirmation | None:
        return self.confirmations.get(hold_id)
