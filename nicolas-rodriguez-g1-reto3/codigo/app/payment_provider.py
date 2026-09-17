"""
Proveedor de pagos mock con comportamiento configurable.

Produce: APPROVED, DECLINED, ERROR, TIMEOUT
Distribución por defecto: 70% approved, 10% declined, 10% error, 10% timeout
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any

from .schemas import PaymentResult


class MockPaymentProvider:
    def __init__(
        self,
        approve_rate: float = 0.70,
        decline_rate: float = 0.10,
        error_rate: float = 0.10,
        timeout_rate: float = 0.10,
        timeout_delay: float = 2.5,
        seed: int | None = None,
    ):
        self._lock = threading.Lock()
        self._approve_rate = approve_rate
        self._decline_rate = decline_rate
        self._error_rate = error_rate
        self._timeout_rate = timeout_rate
        self._timeout_delay = timeout_delay
        self._rng = random.Random(seed)
        self._call_count = 0
        self._forced_result: PaymentResult | None = None

    def authorize(self, payment_token: str) -> dict[str, Any]:
        """Autorizar un pago. Retorna dict con result y metadata."""
        with self._lock:
            self._call_count += 1

        if not payment_token or not payment_token.strip():
            return {
                "result": PaymentResult.ERROR,
                "message": "payment_token vacío",
                "latency_ms": 0,
            }

        with self._lock:
            if self._forced_result is not None:
                result = self._forced_result
            else:
                r = self._rng.random()
                if r < self._approve_rate:
                    result = PaymentResult.APPROVED
                elif r < self._approve_rate + self._decline_rate:
                    result = PaymentResult.DECLINED
                elif r < self._approve_rate + self._decline_rate + self._error_rate:
                    result = PaymentResult.ERROR
                else:
                    result = PaymentResult.TIMEOUT

        if result == PaymentResult.TIMEOUT:
            time.sleep(self._timeout_delay)
            return {
                "result": PaymentResult.TIMEOUT,
                "message": "Timeout del proveedor de pagos",
                "latency_ms": int(self._timeout_delay * 1000),
            }

        return {
            "result": result,
            "message": {
                PaymentResult.APPROVED: "Pago aprobado",
                PaymentResult.DECLINED: "Pago rechazado",
                PaymentResult.ERROR: "Error del proveedor",
            }.get(result, "Resultado desconocido"),
            "latency_ms": self._rng.randint(50, 500),
        }

    def force_result(self, result: PaymentResult | None) -> None:
        """Forzar un resultado específico para testing. None para aleatorio."""
        with self._lock:
            self._forced_result = result

    def get_call_count(self) -> int:
        with self._lock:
            return self._call_count

    def reset(self) -> None:
        with self._lock:
            self._call_count = 0
            self._forced_result = None
