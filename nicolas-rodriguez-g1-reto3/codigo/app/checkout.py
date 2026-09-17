"""
Servicio de checkout que integra SeatLock + Payment Provider + Circuit Breaker.

Estrategia ante fallos del proveedor:
- APPROVED → HELD → SOLD, compra confirmada.
- DECLINED → HOLD liberado, asientos vuelven a AVAILABLE.
- ERROR → HOLD se mantiene activo (no hay certeza de rechazo). El cliente puede reintentar.
- TIMEOUT → HOLD se mantiene activo. No se vende sin certeza ni se libera inmediatamente.
  El cliente puede reintentar con el mismo payment_token (idempotencia del pago).
- Circuit Breaker OPEN → no se llama al proveedor, se retorna PAYMENT_SERVICE_UNAVAILABLE.
"""
from __future__ import annotations

import threading
from typing import Any

from .circuit_breaker import CircuitBreaker
from .payment_provider import MockPaymentProvider
from .schemas import (
    HoldStatus,
    PaymentResult,
    SeatStatus,
    TraceEvent,
    utc_now_iso,
)
from .seatlock import SeatLockEngine


class CheckoutService:
    def __init__(
        self,
        engine: SeatLockEngine,
        payment_provider: MockPaymentProvider | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        self._engine = engine
        self._payment = payment_provider or MockPaymentProvider()
        self._cb = circuit_breaker or CircuitBreaker()
        self._lock = threading.Lock()
        self._payment_idempotency: dict[str, dict[str, Any]] = {}

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._cb

    @property
    def payment_provider(self) -> MockPaymentProvider:
        return self._payment

    def confirm(
        self,
        hold_id: str,
        payment_token: str,
        payment_idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Confirmar un HOLD mediante pago.

        Estrategia de idempotencia de pago: si se usa payment_idempotency_key,
        un reintento con la misma clave retorna el mismo resultado sin volver
        a llamar al proveedor.
        """
        # Idempotencia de pago
        if payment_idempotency_key:
            cached = self._payment_idempotency.get(payment_idempotency_key)
            if cached:
                return cached

        # Validar payment_token
        if not payment_token or not payment_token.strip():
            return {
                "ok": False,
                "hold_id": hold_id,
                "status": "ERROR",
                "payment_result": PaymentResult.ERROR.value,
                "message": "payment_token vacío",
            }

        # Obtener hold
        hold = self._engine.get_hold(hold_id)
        if not hold:
            return {
                "ok": False,
                "hold_id": hold_id,
                "status": "ERROR",
                "payment_result": "NONE",
                "message": f"HOLD {hold_id} no existe",
            }

        if hold.status == HoldStatus.CONFIRMED:
            return {
                "ok": True,
                "hold_id": hold_id,
                "status": HoldStatus.CONFIRMED.value,
                "payment_result": PaymentResult.APPROVED.value,
                "seats": hold.seat_ids,
                "total_price": hold.total_price,
                "message": "HOLD ya estaba confirmado",
            }

        if hold.status in (HoldStatus.EXPIRED, HoldStatus.RELEASED):
            return {
                "ok": False,
                "hold_id": hold_id,
                "status": hold.status.value,
                "payment_result": "NONE",
                "message": f"HOLD {hold.status.value}, no se puede confirmar",
            }

        # Circuit breaker
        if not self._cb.can_call():
            result = {
                "ok": False,
                "hold_id": hold_id,
                "status": "HELD",
                "payment_result": "PAYMENT_SERVICE_UNAVAILABLE",
                "seats": hold.seat_ids,
                "total_price": hold.total_price,
                "message": "Circuit breaker OPEN - servicio de pagos no disponible",
            }
            if payment_idempotency_key:
                self._payment_idempotency[payment_idempotency_key] = result
            return result

        # Llamar al proveedor de pagos
        payment_response = self._payment.authorize(payment_token)
        payment_result = payment_response["result"]

        if payment_result == PaymentResult.APPROVED:
            self._cb.record_success()
            confirm_result = self._engine.confirm_hold(hold_id)
            result = {
                "ok": True,
                "hold_id": hold_id,
                "status": HoldStatus.CONFIRMED.value,
                "payment_result": PaymentResult.APPROVED.value,
                "seats": hold.seat_ids,
                "total_price": hold.total_price,
                "message": "Pago aprobado - compra confirmada",
            }
        elif payment_result == PaymentResult.DECLINED:
            self._cb.record_failure()
            self._engine.release_hold(hold_id, reason="payment_declined")
            result = {
                "ok": False,
                "hold_id": hold_id,
                "status": HoldStatus.RELEASED.value,
                "payment_result": PaymentResult.DECLINED.value,
                "seats": hold.seat_ids,
                "total_price": hold.total_price,
                "message": "Pago rechazado - HOLD liberado",
            }
        elif payment_result == PaymentResult.ERROR:
            self._cb.record_failure()
            result = {
                "ok": False,
                "hold_id": hold_id,
                "status": HoldStatus.ACTIVE.value,
                "payment_result": PaymentResult.ERROR.value,
                "seats": hold.seat_ids,
                "total_price": hold.total_price,
                "message": "Error del proveedor - HOLD se mantiene activo, puede reintentar",
            }
        elif payment_result == PaymentResult.TIMEOUT:
            self._cb.record_failure()
            result = {
                "ok": False,
                "hold_id": hold_id,
                "status": HoldStatus.ACTIVE.value,
                "payment_result": PaymentResult.TIMEOUT.value,
                "seats": hold.seat_ids,
                "total_price": hold.total_price,
                "message": "Timeout del proveedor - HOLD se mantiene activo, puede reintentar",
            }
        else:
            result = {
                "ok": False,
                "hold_id": hold_id,
                "status": "ERROR",
                "payment_result": "UNKNOWN",
                "message": "Resultado desconocido del proveedor",
            }

        if payment_idempotency_key:
            self._payment_idempotency[payment_idempotency_key] = result

        return result

    def get_circuit_breaker_info(self) -> dict[str, Any]:
        return self._cb.get_info()

    def reset(self) -> None:
        with self._lock:
            self._payment_idempotency.clear()
