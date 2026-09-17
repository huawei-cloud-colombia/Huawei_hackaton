"""Simulación del servicio externo de autorización bancaria y circuit breaker (Fase 3)."""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class BankAuthError(Exception):
    """Se lanza cuando la llamada simulada al banco falla o excede el timeout."""


def mock_bank_auth(
    failure_probability: float = 0.3,
    simulated_latency_seconds: float = 0.15,
    timeout_threshold_seconds: float = 2.0,
) -> str:
    """Simula una llamada de autorización bancaria.

    Con probabilidad `failure_probability` la llamada falla (error de red)
    o se demora más que `timeout_threshold_seconds` (timeout). En un demo en
    vivo usamos una latencia simulada pequeña (`simulated_latency_seconds`)
    en vez de esperar los 2s reales, pero la lógica de decisión de éxito/
    fallo respeta el 30% configurado.
    """
    fails = random.random() < failure_probability
    time.sleep(simulated_latency_seconds)
    if fails:
        raise BankAuthError("bank_auth_timeout_or_error")
    return "approved"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    open_duration_seconds: float = 15.0

    state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    fail_count: int = field(default=0, init=False)
    opened_at: float | None = field(default=None, init=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)

    def call(self, fn, *args, **kwargs) -> tuple[str, str | None]:
        """Ejecuta `fn` protegida por el circuit breaker.

        Devuelve (status, result) donde status es uno de:
        "approved", "timeout_degraded", "circuit_open_degraded".
        """
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self.opened_at is not None and (time.monotonic() - self.opened_at) >= self.open_duration_seconds:
                    self.state = CircuitState.HALF_OPEN
                else:
                    return "circuit_open_degraded", None

        try:
            result = fn(*args, **kwargs)
        except Exception:
            with self._lock:
                self.fail_count += 1
                if self.state == CircuitState.HALF_OPEN or self.fail_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self.opened_at = time.monotonic()
            return "timeout_degraded", None

        with self._lock:
            self.state = CircuitState.CLOSED
            self.fail_count = 0
            self.opened_at = None
        return "approved", result
