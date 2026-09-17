import threading
import time

import config


class CircuitBreaker:
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self, failure_threshold=None, recovery_seconds=None, half_open_trials=None):
        self.failure_threshold = failure_threshold or config.CB_FAILURE_THRESHOLD
        self.recovery_seconds = recovery_seconds or config.CB_RECOVERY_SECONDS
        self.half_open_trials = half_open_trials or config.CB_HALF_OPEN_TRIALS
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = None
        self._half_open_used = 0
        self._lock = threading.RLock()

    @property
    def state(self):
        with self._lock:
            if self._state == self.OPEN and self._opened_at is not None:
                if time.time() - self._opened_at >= self.recovery_seconds:
                    self._state = self.HALF_OPEN
                    self._half_open_used = 0
            return self._state

    def allow_request(self):
        with self._lock:
            current = self.state
            if current == self.CLOSED:
                return True
            if current == self.OPEN:
                return False
            if current == self.HALF_OPEN:
                if self._half_open_used < self.half_open_trials:
                    self._half_open_used += 1
                    return True
                return False
            return False

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._state = self.CLOSED
            self._opened_at = None
            self._half_open_used = 0

    def record_failure(self):
        with self._lock:
            self._failures += 1
            if self._state == self.HALF_OPEN:
                self._state = self.OPEN
                self._opened_at = time.time()
                self._half_open_used = 0
            elif self._failures >= self.failure_threshold:
                self._state = self.OPEN
                self._opened_at = time.time()

    def reset(self):
        with self._lock:
            self._state = self.CLOSED
            self._failures = 0
            self._opened_at = None
            self._half_open_used = 0

    def snapshot(self):
        with self._lock:
            return {
                "state": self.state,
                "failures": self._failures,
                "threshold": self.failure_threshold,
                "recovery_seconds": self.recovery_seconds,
            }


breaker = CircuitBreaker()
