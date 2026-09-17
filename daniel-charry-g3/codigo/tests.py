"""
tests.py — Pruebas del motor de reservas NEXUS LIVE.
Cubre los escenarios A-F del reto y casos límite.

Ejecutar: pytest tests.py -v
"""

import asyncio
import sys
import os
import pytest

# Asegurar que el directorio del código está en el path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from models import ReserveRequest, ConfirmRequest, SeatStatus, HoldStatus, PaymentResult
from seat_lock import SeatLockEngine
from payment import PaymentService, CircuitBreaker
from audit import audit_log


# ─── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def engine():
    return SeatLockEngine()


@pytest.fixture
def payment():
    return PaymentService()


# ─── FASE 1: Motor de reservas ───────────────────────────────

class TestSeatLock:
    """Escenario A — Reserva normal."""

    @pytest.mark.asyncio
    async def test_reserve_available_seats(self, engine):
        req = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001", "A-002"])
        result = await engine.reserve(req)
        assert result["success"] is True
        assert result["status"] == "HELD"
        assert result["total"] == 420000  # 210000 * 2

    @pytest.mark.asyncio
    async def test_seat_becomes_held(self, engine):
        req = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"])
        await engine.reserve(req)
        seat = engine.get_seat("A-001")
        assert seat.status == SeatStatus.HELD

    """Todo o nada."""

    @pytest.mark.asyncio
    async def test_all_or_nothing(self, engine):
        # Reservar A-001 primero
        await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        # Intentar reservar A-001 + A-002 (A-001 ya no disponible)
        result = await engine.reserve(ReserveRequest(user_id="usr_2", event_id="evt", seat_ids=["A-001", "A-002"]))
        assert result["success"] is False
        assert result["error"] == "SEAT_NOT_AVAILABLE"
        # A-002 debe seguir AVAILABLE
        assert engine.get_seat("A-002").status == SeatStatus.AVAILABLE

    """Asiento no disponible."""

    @pytest.mark.asyncio
    async def test_seat_not_available(self, engine):
        await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        result = await engine.reserve(ReserveRequest(user_id="usr_2", event_id="evt", seat_ids=["A-001"]))
        assert result["success"] is False
        assert result["error"] == "SEAT_NOT_AVAILABLE"

    """Límite de asientos por usuario."""

    @pytest.mark.asyncio
    async def test_seat_limit_per_user(self, engine):
        # Reservar 6 asientos (límite)
        req = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=[f"A-{i:03d}" for i in range(1, 7)])
        result = await engine.reserve(req)
        assert result["success"] is True
        # Intentar reservar 1 más
        req2 = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["B-001"])
        result2 = await engine.reserve(req2)
        assert result2["success"] is False
        assert result2["error"] == "SEAT_LIMIT_EXCEEDED"

    """Asiento inexistente."""

    @pytest.mark.asyncio
    async def test_seat_not_found(self, engine):
        result = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["ZZZ-999"]))
        assert result["success"] is False
        assert result["error"] == "SEAT_NOT_FOUND"

    """Duplicados en la solicitud."""

    @pytest.mark.asyncio
    async def test_duplicate_seats_in_request(self, engine):
        result = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001", "A-001"]))
        assert result["success"] is False
        assert result["error"] == "DUPLICATE_SEAT"

    """Precio controlado por servidor."""

    @pytest.mark.asyncio
    async def test_price_from_server(self, engine):
        result = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["VIP-A-001"]))
        assert result["success"] is True
        assert result["total"] == 500000  # precio VIP del catálogo
        assert result["currency"] == "COP"


# ─── FASE 2: Concurrencia e Idempotencia ─────────────────────

class TestConcurrency:
    """Escenario C — Concurrencia."""

    @pytest.mark.asyncio
    async def test_concurrent_race_one_winner(self, engine):
        """100 usuarios compitiendo por 1 asiento → exactamente 1 ganador."""
        result = await engine.simulate_race("VIP-A-001", num_users=100)
        assert result["winners"] == 1
        assert result["rejected"] == 99
        assert result["total_requests"] == 100

    @pytest.mark.asyncio
    async def test_concurrent_same_seat_two_users(self, engine):
        """Dos usuarios reservan el mismo asiento simultáneamente."""
        req1 = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"])
        req2 = ReserveRequest(user_id="usr_2", event_id="evt", seat_ids=["A-001"])
        r1, r2 = await asyncio.gather(engine.reserve(req1), engine.reserve(req2))
        winners = sum(1 for r in [r1, r2] if r["success"])
        assert winners == 1


class TestIdempotency:
    """Escenario D — Reintento."""

    @pytest.mark.asyncio
    async def test_idempotency_replay(self, engine):
        req = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"])
        r1 = await engine.reserve(req, idempotency_key="key-001")
        r2 = await engine.reserve(req, idempotency_key="key-001")
        assert r1["success"] is True
        assert r2["success"] is True
        assert r1["hold_id"] == r2["hold_id"]  # Mismo hold

    """Escenario E — Conflicto."""

    @pytest.mark.asyncio
    async def test_idempotency_conflict(self, engine):
        req1 = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"])
        req2 = ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-002"])
        r1 = await engine.reserve(req1, idempotency_key="key-002")
        r2 = await engine.reserve(req2, idempotency_key="key-002")
        assert r1["success"] is True
        assert r2["success"] is False
        assert r2["error"] == "IDEMPOTENCY_CONFLICT"


# ─── FASE 3: Pagos y Circuit Breaker ─────────────────────────

class TestPayment:
    """Confirmación con pago aprobado."""

    @pytest.mark.asyncio
    async def test_confirm_approved(self, engine, payment):
        payment.force_result(PaymentResult.APPROVED)
        r = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        pay = await payment.authorize("tok_test", r["hold_id"])
        confirm = await engine.confirm_hold(r["hold_id"], pay["result"])
        assert confirm["success"] is True
        assert confirm["status"] == "SOLD"
        assert engine.get_seat("A-001").status == SeatStatus.SOLD

    """Pago rechazado libera asientos."""

    @pytest.mark.asyncio
    async def test_confirm_declined_releases(self, engine, payment):
        payment.force_result(PaymentResult.DECLINED)
        r = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        pay = await payment.authorize("tok_test", r["hold_id"])
        confirm = await engine.confirm_hold(r["hold_id"], pay["result"])
        assert confirm["success"] is False
        assert engine.get_seat("A-001").status == SeatStatus.AVAILABLE

    """Timeout mantiene HOLD."""

    @pytest.mark.asyncio
    async def test_timeout_keeps_hold(self, engine, payment):
        payment.force_result(PaymentResult.TIMEOUT)
        r = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        pay = await payment.authorize("tok_test", r["hold_id"])
        confirm = await engine.confirm_hold(r["hold_id"], pay["result"])
        assert confirm["success"] is False
        assert engine.get_seat("A-001").status == SeatStatus.HELD  # Sigue HELD

    """Confirmar dos veces."""

    @pytest.mark.asyncio
    async def test_double_confirm(self, engine, payment):
        payment.force_result(PaymentResult.APPROVED)
        r = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        await engine.confirm_hold(r["hold_id"], PaymentResult.APPROVED)
        result = await engine.confirm_hold(r["hold_id"], PaymentResult.APPROVED)
        assert result["success"] is False
        assert result["error"] == "HOLD_ALREADY_CONFIRMED"


class TestCircuitBreaker:
    """Escenario F — Pago degradado."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens(self, payment):
        payment.force_result(PaymentResult.ERROR)
        cb = payment.cb
        assert cb.state.value == "CLOSED"
        # 3 fallos → OPEN
        for _ in range(3):
            await payment.authorize("tok", "hold_test")
        assert cb.state.value == "OPEN"

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_when_open(self, payment):
        payment.force_result(PaymentResult.ERROR)
        for _ in range(3):
            await payment.authorize("tok", "hold_test")
        # Ahora OPEN, debe bloquear
        result = await payment.authorize("tok", "hold_test")
        assert result["message"] == "PAYMENT_SERVICE_UNAVAILABLE"


# ─── Trazabilidad ────────────────────────────────────────────

class TestAudit:
    @pytest.mark.asyncio
    async def test_audit_records_hold(self, engine):
        audit_log.clear()
        await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        events = audit_log.get_all()
        assert len(events) > 0
        assert any(e.reason == "hold_created" for e in events)

    @pytest.mark.asyncio
    async def test_audit_records_confirm(self, engine):
        audit_log.clear()
        r = await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        await engine.confirm_hold(r["hold_id"], PaymentResult.APPROVED)
        events = audit_log.get_all()
        assert any(e.reason == "payment_approved" for e in events)


# ─── Expiración ──────────────────────────────────────────────

class TestExpiration:
    """Escenario B — Reserva expirada."""

    @pytest.mark.asyncio
    async def test_hold_expires(self, engine, monkeypatch):
        # Reducir TTL a 1 segundo
        monkeypatch.setattr(config, "hold_ttl_seconds", 1)
        await engine.reserve(ReserveRequest(user_id="usr_1", event_id="evt", seat_ids=["A-001"]))
        assert engine.get_seat("A-001").status == SeatStatus.HELD
        # Esperar expiración
        await asyncio.sleep(1.5)
        engine.expire_holds()
        assert engine.get_seat("A-001").status == SeatStatus.AVAILABLE
