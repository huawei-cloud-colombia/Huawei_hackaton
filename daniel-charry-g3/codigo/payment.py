"""
payment.py — Mock de proveedor de pagos + Circuit Breaker.

Mock produce: APPROVED (70%), DECLINED (10%), ERROR (10%), TIMEOUT (10%).
Circuit Breaker: 3 fallos → OPEN, 15s → HALF_OPEN, 1 prueba → CLOSED/OPEN.
"""

import asyncio
import random
import time
from typing import Optional

from config import config
from models import PaymentResult, CircuitBreakerState
from audit import audit_log


class CircuitBreaker:
    """Circuit breaker para proteger el proveedor de pagos."""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: int = 15,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None

    def can_call(self) -> bool:
        """Determina si se puede hacer una llamada al servicio."""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            # Verificar si ha pasado el tiempo de recuperación
            if self._last_failure_time and (
                time.time() - self._last_failure_time >= self.recovery_timeout
            ):
                self.state = CircuitBreakerState.HALF_OPEN
                return True
            return False

        if self.state == CircuitBreakerState.HALF_OPEN:
            return True

        return False

    def record_success(self):
        """Registra una llamada exitosa."""
        self._failure_count = 0
        self.state = CircuitBreakerState.CLOSED

    def record_failure(self):
        """Registra una llamada fallida."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.OPEN
        elif self._failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN

    def get_info(self) -> dict:
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


class PaymentService:
    """Mock de proveedor de pagos con circuit breaker."""

    def __init__(self):
        self.cb = CircuitBreaker(
            failure_threshold=config.cb_failure_threshold,
            recovery_timeout=config.cb_recovery_timeout,
        )
        self._force_result: Optional[PaymentResult] = None

    def force_result(self, result: Optional[PaymentResult]):
        """Fuerza un resultado específico (para tests/demo)."""
        self._force_result = result

    async def authorize(self, payment_token: str, hold_id: str = "") -> dict:
        """
        Autoriza un pago.
        Retorna dict con 'result' (PaymentResult) y 'message'.
        """
        if not self.cb.can_call():
            audit_log.record(
                reason="circuit_breaker_open",
                hold_id=hold_id,
                extra={"cb_state": self.cb.state.value},
            )
            return {
                "result": PaymentResult.ERROR,
                "message": "PAYMENT_SERVICE_UNAVAILABLE",
                "circuit_breaker": "OPEN",
            }

        try:
            result = await self._mock_call(payment_token)
            self.cb.record_success()
            return {
                "result": result,
                "message": result.value,
                "circuit_breaker": self.cb.state.value,
            }
        except asyncio.TimeoutError:
            self.cb.record_failure()
            return {
                "result": PaymentResult.TIMEOUT,
                "message": "Payment timed out",
                "circuit_breaker": self.cb.state.value,
            }
        except Exception as e:
            self.cb.record_failure()
            return {
                "result": PaymentResult.ERROR,
                "message": f"Payment error: {str(e)}",
                "circuit_breaker": self.cb.state.value,
            }

    async def _mock_call(self, payment_token: str) -> PaymentResult:
        """Simula la llamada al proveedor de pagos."""
        # Si hay un resultado forzado, usarlo
        if self._force_result:
            if self._force_result == PaymentResult.TIMEOUT:
                await asyncio.sleep(config.pay_timeout_seconds + 1)
            return self._force_result

        # Generar resultado aleatorio
        r = random.random()
        if r < config.pay_prob_approved:
            return PaymentResult.APPROVED
        elif r < config.pay_prob_approved + config.pay_prob_declined:
            return PaymentResult.DECLINED
        elif r < config.pay_prob_approved + config.pay_prob_declined + config.pay_prob_error:
            raise RuntimeError("Simulated payment provider error")
        else:
            # Timeout: dormir más del umbral
            await asyncio.sleep(config.pay_timeout_seconds + 1)
            return PaymentResult.APPROVED  # No se llega aquí por el timeout del caller

    def get_status(self) -> dict:
        """Retorna el estado del circuit breaker."""
        return self.cb.get_info()


# Instancia global
payment_service = PaymentService()
