from __future__ import annotations

import asyncio
import random
import secrets
import time
from dataclasses import dataclass, field

from .config import Settings, settings
from .models import PaymentResult, PaymentStatus


class CircuitBreaker:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self, failure_threshold: int = 3, recovery_seconds: float = 15.0):
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False

    def tick(self) -> None:
        if self.state == self.OPEN and time.monotonic() - self._opened_at >= self.recovery_seconds:
            self.state = self.HALF_OPEN
            self._trial_in_flight = False

    def allow_request(self) -> bool:
        if self.state == self.CLOSED:
            return True
        if self.state == self.HALF_OPEN:
            if not self._trial_in_flight:
                self._trial_in_flight = True
                return True
            return False
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._trial_in_flight = False
        self.state = self.CLOSED

    def record_failure(self) -> None:
        if self.state == self.HALF_OPEN:
            self.state = self.OPEN
            self._opened_at = time.monotonic()
            self._trial_in_flight = False
            return
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self.state = self.OPEN
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        self.state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False


@dataclass
class PaymentStats:
    authorized: int = 0
    declined: int = 0
    error: int = 0
    timeout: int = 0
    calls: int = 0


class PaymentProvider:
    MODES = {"random", "always_approved", "always_declined", "always_error", "always_timeout"}

    def __init__(self, cfg: Settings = settings):
        self.cfg = cfg
        self.mode = "random"
        self._outcomes: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self.stats = PaymentStats()

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(f"invalid mode {mode}; valid: {self.MODES}")
        self.mode = mode

    async def authorize(self, charge_key: str, payment_token: str) -> PaymentResult:
        self.stats.calls += 1
        if self.mode == "always_approved":
            self.stats.authorized += 1
            return PaymentResult(PaymentStatus.APPROVED, self._txn())
        if self.mode == "always_declined":
            self.stats.declined += 1
            return PaymentResult(PaymentStatus.DECLINED, None)
        if self.mode == "always_error":
            self.stats.error += 1
            return PaymentResult(PaymentStatus.ERROR, None)
        if self.mode == "always_timeout":
            self.stats.timeout += 1
            await asyncio.sleep(self.cfg.pay_timeout_seconds + 0.2)
            return PaymentResult(PaymentStatus.TIMEOUT, None)

        async with self._lock:
            true = self._outcomes.get(charge_key)
            if true is None:
                true = PaymentStatus.APPROVED.value if random.random() < 0.875 else PaymentStatus.DECLINED.value
                self._outcomes[charge_key] = true

        r = random.random()
        if r < self.cfg.pay_prob_error:
            self.stats.error += 1
            return PaymentResult(PaymentStatus.ERROR, None)
        if r < self.cfg.pay_prob_error + self.cfg.pay_prob_timeout:
            self.stats.timeout += 1
            await asyncio.sleep(self.cfg.pay_timeout_seconds + 0.2)
            return PaymentResult(PaymentStatus.TIMEOUT, None)

        if true == PaymentStatus.APPROVED.value:
            self.stats.authorized += 1
            return PaymentResult(PaymentStatus.APPROVED, self._txn())
        self.stats.declined += 1
        return PaymentResult(PaymentStatus.DECLINED, None)

    def _txn(self) -> str:
        return "txn_" + secrets.token_hex(6).upper()

    def reset(self) -> None:
        self._outcomes.clear()
        self.stats = PaymentStats()
