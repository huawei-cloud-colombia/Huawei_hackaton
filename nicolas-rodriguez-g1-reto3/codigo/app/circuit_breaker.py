"""
Circuit Breaker para el proveedor de pagos.

Estados: CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN

- CLOSED: las llamadas pasan normalmente.
- OPEN: no se golpea el servicio degradado. Se retorna PAYMENT_SERVICE_UNAVAILABLE.
- HALF_OPEN: se permite una llamada de prueba. Si funciona → CLOSED, si falla → OPEN.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from .schemas import CircuitBreakerState, PaymentResult


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 15.0,
    ):
        self._lock = threading.Lock()
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

    @property
    def state(self) -> CircuitBreakerState:
        with self._lock:
            self._update_state()
            return self._state

    def _update_state(self) -> None:
        """Transición automática OPEN → HALF_OPEN. Debe llamarse dentro del lock."""
        if self._state == CircuitBreakerState.OPEN:
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = CircuitBreakerState.HALF_OPEN

    def can_call(self) -> bool:
        """Verificar si se puede hacer una llamada al servicio."""
        with self._lock:
            self._update_state()
            if self._state == CircuitBreakerState.OPEN:
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._state = CircuitBreakerState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.OPEN
            elif self._failure_count >= self._failure_threshold:
                self._state = CircuitBreakerState.OPEN

    def force_open(self) -> None:
        with self._lock:
            self._state = CircuitBreakerState.OPEN
            self._last_failure_time = time.monotonic()

    def force_closed(self) -> None:
        with self._lock:
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0

    def get_info(self) -> dict[str, Any]:
        with self._lock:
            self._update_state()
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self._failure_threshold,
                "recovery_timeout": self._recovery_timeout,
            }
