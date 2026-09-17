"""Tests para NEXUS LIVE - Motor de reservas de alta concurrencia."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.circuit_breaker import CircuitBreaker
from app.checkout import CheckoutService
from app.payment_provider import MockPaymentProvider
from app.schemas import HoldStatus, PaymentResult, Seat, SeatStatus
from app.seatlock import SeatLockEngine


# ── Fixtures ────────────────────────────────────────────

@pytest.fixture
def engine():
    e = SeatLockEngine(hold_ttl_seconds=120, max_seats_per_user=6)
    e.add_seats([
        Seat(seat_id="VIP-A-001", section="VIP", price=500000),
        Seat(seat_id="VIP-A-002", section="VIP", price=500000),
        Seat(seat_id="VIP-A-003", section="VIP", price=500000),
        Seat(seat_id="PLAT-B-001", section="PLATEA", price=250000),
        Seat(seat_id="PLAT-B-002", section="PLATEA", price=250000),
    ])
    return e


@pytest.fixture
def short_ttl_engine():
    e = SeatLockEngine(hold_ttl_seconds=1, max_seats_per_user=6)
    e.add_seats([
        Seat(seat_id="VIP-A-001", section="VIP", price=500000),
        Seat(seat_id="VIP-A-002", section="VIP", price=500000),
    ])
    return e


# ── Fase 1: SeatLock ───────────────────────────────────

class TestSeatLock:
    def test_seat_starts_available(self, engine):
        seat = engine.get_seat("VIP-A-001")
        assert seat.status == SeatStatus.AVAILABLE

    def test_reserve_single_seat(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        assert r["ok"] is True
        assert r["hold_id"].startswith("hold_")
        assert r["total_price"] == 500000
        seat = engine.get_seat("VIP-A-001")
        assert seat.status == SeatStatus.HELD

    def test_reserve_multiple_seats(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001", "VIP-A-002"])
        assert r["ok"] is True
        assert r["total_price"] == 1000000
        assert engine.get_seat("VIP-A-001").status == SeatStatus.HELD
        assert engine.get_seat("VIP-A-002").status == SeatStatus.HELD

    def test_reserve_all_or_nothing(self, engine):
        # Primero reservar VIP-A-001
        engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        # Intentar reservar VIP-A-001 (ya HELD) + VIP-A-002 (AVAILABLE)
        r = engine.reserve("usr_2", "event_1", ["VIP-A-001", "VIP-A-002"])
        assert r["ok"] is False
        assert r["error"] == "SEATS_UNAVAILABLE"
        # VIP-A-002 debe seguir AVAILABLE (todo-o-nada)
        assert engine.get_seat("VIP-A-002").status == SeatStatus.AVAILABLE

    def test_reserve_empty_seats(self, engine):
        r = engine.reserve("usr_1", "event_1", [])
        assert r["ok"] is False
        assert r["error"] == "EMPTY_SEATS"

    def test_reserve_duplicate_seats(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001", "VIP-A-001"])
        assert r["ok"] is False
        assert r["error"] == "DUPLICATE_SEATS"

    def test_reserve_nonexistent_seat(self, engine):
        r = engine.reserve("usr_1", "event_1", ["NOPE-999"])
        assert r["ok"] is False
        assert r["error"] == "SEAT_NOT_FOUND"

    def test_reserve_empty_user(self, engine):
        r = engine.reserve("", "event_1", ["VIP-A-001"])
        assert r["ok"] is False
        assert r["error"] == "INVALID_USER"

    def test_max_seats_per_user(self, engine):
        # 6 asientos es el máximo
        seats_to_add = [Seat(seat_id=f"GEN-{i}", price=80000) for i in range(7)]
        engine.add_seats(seats_to_add)
        r = engine.reserve("usr_1", "event_1", [f"GEN-{i}" for i in range(7)])
        assert r["ok"] is False
        assert r["error"] == "MAX_SEATS_EXCEEDED"

    def test_reserve_exactly_max_seats(self, engine):
        seats_to_add = [Seat(seat_id=f"GEN-{i}", price=80000) for i in range(6)]
        engine.add_seats(seats_to_add)
        r = engine.reserve("usr_1", "event_1", [f"GEN-{i}" for i in range(6)])
        assert r["ok"] is True

    def test_server_controlled_pricing(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001", "PLAT-B-001"])
        assert r["ok"] is True
        assert r["total_price"] == 750000  # 500000 + 250000

    def test_hold_expiration(self, short_ttl_engine):
        r = short_ttl_engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        assert r["ok"] is True
        assert short_ttl_engine.get_seat("VIP-A-001").status == SeatStatus.HELD
        # Esperar expiración
        time.sleep(1.5)
        # Acceso al hold debe disparar expiración
        hold = short_ttl_engine.get_hold(r["hold_id"])
        assert hold.status == HoldStatus.EXPIRED
        assert short_ttl_engine.get_seat("VIP-A-001").status == SeatStatus.AVAILABLE

    def test_release_hold(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        assert r["ok"] is True
        rel = engine.release_hold(r["hold_id"])
        assert rel["ok"] is True
        assert engine.get_seat("VIP-A-001").status == SeatStatus.AVAILABLE

    def test_confirm_hold(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        c = engine.confirm_hold(r["hold_id"])
        assert c["ok"] is True
        assert c["status"] == HoldStatus.CONFIRMED.value
        assert engine.get_seat("VIP-A-001").status == SeatStatus.SOLD

    def test_confirm_twice(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        engine.confirm_hold(r["hold_id"])
        c2 = engine.confirm_hold(r["hold_id"])
        assert c2["ok"] is False
        assert c2["error"] == "ALREADY_CONFIRMED"

    def test_confirm_nonexistent_hold(self, engine):
        c = engine.confirm_hold("hold_NOPE")
        assert c["ok"] is False
        assert c["error"] == "HOLD_NOT_FOUND"

    def test_user_active_seats_limit(self, engine):
        # Usuario reserva 4 asientos en un hold
        seats_to_add = [Seat(seat_id=f"GEN-{i}", price=80000) for i in range(8)]
        engine.add_seats(seats_to_add)
        r1 = engine.reserve("usr_1", "event_1", [f"GEN-{i}" for i in range(4)])
        assert r1["ok"] is True
        # Intentar reservar 3 más (total 7 > 6)
        r2 = engine.reserve("usr_1", "event_1", [f"GEN-{i}" for i in range(4, 7)])
        assert r2["ok"] is False
        assert r2["error"] == "MAX_SEATS_EXCEEDED"


# ── Fase 2: Concurrency & Idempotency ──────────────────

class TestConcurrency:
    def test_100_concurrent_1_seat_1_winner(self, engine):
        """Prueba clave: 100 usuarios concurrentes por 1 asiento → 1 ganador."""
        results = []
        errors = []

        def attempt(user_num):
            try:
                return engine.reserve(
                    f"usr_{user_num:04d}", "event_1", ["VIP-A-001"],
                    idempotency_key=f"key-{user_num:04d}",
                )
            except Exception as e:
                errors.append(str(e))
                return None

        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = [executor.submit(attempt, i) for i in range(100)]
            for f in as_completed(futures):
                r = f.result()
                if r:
                    results.append(r)

        winners = [r for r in results if r.get("ok")]
        rejected = [r for r in results if not r.get("ok")]

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(winners) == 1, f"Expected 1 winner, got {len(winners)}"
        assert len(rejected) == 99, f"Expected 99 rejected, got {len(rejected)}"
        assert engine.get_seat("VIP-A-001").status == SeatStatus.HELD

    def test_concurrent_different_seats(self, engine):
        """Concurrencia sobre asientos diferentes → todos ganan."""
        def attempt(seat_id):
            return engine.reserve(f"usr_{seat_id}", "event_1", [seat_id])

        seat_ids = ["VIP-A-001", "VIP-A-002", "VIP-A-003"]
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(attempt, sid) for sid in seat_ids]
            results = [f.result() for f in as_completed(futures)]

        winners = [r for r in results if r.get("ok")]
        assert len(winners) == 3

    def test_no_overselling(self, engine):
        """Verificar que nunca hay overselling bajo concurrencia."""
        def attempt(user_num):
            return engine.reserve(f"usr_{user_num:04d}", "event_1", ["VIP-A-001"])

        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(attempt, i) for i in range(50)]
            results = [f.result() for f in as_completed(futures)]

        winners = [r for r in results if r.get("ok")]
        assert len(winners) == 1
        # El asiento debe estar HELD (no SOLD, no multiple HELD)
        seat = engine.get_seat("VIP-A-001")
        assert seat.status == SeatStatus.HELD
        assert seat.hold_id is not None


class TestIdempotency:
    def test_idempotent_replay(self, engine):
        """Misma Idempotency-Key + mismo payload → mismo resultado."""
        key = "reserve-usr1-001"
        r1 = engine.reserve("usr_1", "event_1", ["VIP-A-001"], idempotency_key=key)
        r2 = engine.reserve("usr_1", "event_1", ["VIP-A-001"], idempotency_key=key)
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r1["hold_id"] == r2["hold_id"]

    def test_idempotency_conflict(self, engine):
        """Misma Idempotency-Key + payload diferente → conflicto."""
        key = "reserve-usr1-002"
        r1 = engine.reserve("usr_1", "event_1", ["VIP-A-001"], idempotency_key=key)
        r2 = engine.reserve("usr_1", "event_1", ["VIP-A-002"], idempotency_key=key)
        assert r1["ok"] is True
        assert r2["ok"] is False
        assert r2["error"] == "IDEMPOTENCY_CONFLICT"

    def test_idempotency_different_keys(self, engine):
        """Diferentes keys → operaciones independientes."""
        r1 = engine.reserve("usr_1", "event_1", ["VIP-A-001"], idempotency_key="key-A")
        r2 = engine.reserve("usr_2", "event_1", ["VIP-A-002"], idempotency_key="key-B")
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r1["hold_id"] != r2["hold_id"]


# ── Fase 3: Checkout & Circuit Breaker ─────────────────

class TestCheckout:
    @pytest.fixture
    def checkout(self, engine):
        provider = MockPaymentProvider(seed=42)
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=15.0)
        return CheckoutService(engine, provider, cb)

    def test_confirm_approved(self, engine, checkout):
        checkout.payment_provider.force_result(PaymentResult.APPROVED)
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        c = checkout.confirm(r["hold_id"], "tok_test_001")
        assert c["ok"] is True
        assert c["payment_result"] == PaymentResult.APPROVED.value
        assert engine.get_seat("VIP-A-001").status == SeatStatus.SOLD

    def test_confirm_declined_releases_hold(self, engine, checkout):
        checkout.payment_provider.force_result(PaymentResult.DECLINED)
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        c = checkout.confirm(r["hold_id"], "tok_test_001")
        assert c["ok"] is False
        assert c["payment_result"] == PaymentResult.DECLINED.value
        assert engine.get_seat("VIP-A-001").status == SeatStatus.AVAILABLE

    def test_confirm_error_keeps_hold(self, engine, checkout):
        checkout.payment_provider.force_result(PaymentResult.ERROR)
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        c = checkout.confirm(r["hold_id"], "tok_test_001")
        assert c["ok"] is False
        assert c["payment_result"] == PaymentResult.ERROR.value
        assert engine.get_seat("VIP-A-001").status == SeatStatus.HELD

    def test_confirm_timeout_keeps_hold(self, engine, checkout):
        checkout.payment_provider.force_result(PaymentResult.TIMEOUT)
        checkout.payment_provider._timeout_delay = 0.1  # speed up test
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        c = checkout.confirm(r["hold_id"], "tok_test_001")
        assert c["ok"] is False
        assert c["payment_result"] == PaymentResult.TIMEOUT.value
        assert engine.get_seat("VIP-A-001").status == SeatStatus.HELD

    def test_confirm_empty_token(self, engine, checkout):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        c = checkout.confirm(r["hold_id"], "")
        assert c["ok"] is False

    def test_confirm_nonexistent_hold(self, engine, checkout):
        c = checkout.confirm("hold_NOPE", "tok_test_001")
        assert c["ok"] is False

    def test_confirm_already_confirmed(self, engine, checkout):
        checkout.payment_provider.force_result(PaymentResult.APPROVED)
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        checkout.confirm(r["hold_id"], "tok_test_001")
        c2 = checkout.confirm(r["hold_id"], "tok_test_002")
        assert c2["ok"] is True
        assert c2["status"] == HoldStatus.CONFIRMED.value


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state.value == "CLOSED"

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=15.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state.value == "CLOSED"
        cb.record_failure()
        assert cb.state.value == "OPEN"

    def test_open_blocks_calls(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=15.0)
        cb.record_failure()
        assert cb.can_call() is False

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        assert cb.state.value == "OPEN"
        time.sleep(0.15)
        assert cb.state.value == "HALF_OPEN"

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state.value == "HALF_OPEN"
        cb.record_success()
        assert cb.state.value == "CLOSED"

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state.value == "HALF_OPEN"
        cb.record_failure()
        assert cb.state.value == "OPEN"

    def test_circuit_breaker_blocks_confirm(self, engine):
        provider = MockPaymentProvider(seed=42)
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=15.0)
        co = CheckoutService(engine, provider, cb)
        # Forzar CB open
        cb.force_open()
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        c = co.confirm(r["hold_id"], "tok_test_001")
        assert c["ok"] is False
        assert c["payment_result"] == "PAYMENT_SERVICE_UNAVAILABLE"
        assert engine.get_seat("VIP-A-001").status == SeatStatus.HELD


# ── Trazabilidad ───────────────────────────────────────

class TestTraceability:
    def test_trace_events_created(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        trace = engine.get_trace_for_hold(r["hold_id"])
        assert len(trace) == 1
        assert trace[0].from_state == "AVAILABLE"
        assert trace[0].to_state == "HELD"
        assert trace[0].reason == "hold_created"

    def test_trace_confirm(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        engine.confirm_hold(r["hold_id"])
        trace = engine.get_trace_for_hold(r["hold_id"])
        assert len(trace) == 2
        assert trace[1].from_state == "HELD"
        assert trace[1].to_state == "SOLD"
        assert trace[1].reason == "payment_approved"

    def test_trace_release(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        engine.release_hold(r["hold_id"])
        trace = engine.get_trace_for_hold(r["hold_id"])
        assert len(trace) == 2
        assert trace[1].to_state == "AVAILABLE"

    def test_trace_has_timestamps(self, engine):
        r = engine.reserve("usr_1", "event_1", ["VIP-A-001"])
        trace = engine.get_trace_for_hold(r["hold_id"])
        assert trace[0].timestamp is not None
        assert trace[0].user_id == "usr_1"
