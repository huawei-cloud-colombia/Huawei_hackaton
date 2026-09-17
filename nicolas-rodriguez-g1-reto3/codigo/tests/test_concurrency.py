"""
Bono B - Prueba de concurrencia real.

Demuestra que N solicitudes simultáneas sobre 1 asiento producen
exactamente 1 ganador y 0 overselling.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.schemas import Seat, SeatStatus
from app.seatlock import SeatLockEngine


def run_race(engine: SeatLockEngine, seat_id: str, n: int) -> dict:
    """Ejecutar una carrera de N usuarios por 1 asiento."""
    results = []
    errors = []

    def attempt(user_num: int):
        try:
            return engine.reserve(
                user_id=f"race_usr_{user_num:05d}",
                event_id="aurora-bogota-2026",
                seat_ids=[seat_id],
                idempotency_key=f"race-{seat_id}-{user_num:05d}",
            )
        except Exception as e:
            errors.append(str(e))
            return None

    with ThreadPoolExecutor(max_workers=min(n, 200)) as executor:
        futures = {executor.submit(attempt, i): i for i in range(n)}
        for f in as_completed(futures):
            r = f.result()
            if r is not None:
                results.append(r)

    winners = [r for r in results if r.get("ok")]
    rejected = [r for r in results if not r.get("ok")]

    return {
        "total": n,
        "winners": len(winners),
        "rejected": len(rejected),
        "errors": errors,
        "overselling": max(0, len(winners) - 1),
    }


class TestRealConcurrency:
    @pytest.fixture
    def engine(self):
        e = SeatLockEngine(hold_ttl_seconds=120, max_seats_per_user=6)
        e.add_seats([Seat(seat_id=f"VIP-A-{i:03d}", price=500000) for i in range(1, 11)])
        return e

    def test_20_users_1_seat(self, engine):
        result = run_race(engine, "VIP-A-001", 20)
        assert result["errors"] == []
        assert result["winners"] == 1
        assert result["rejected"] == 19
        assert result["overselling"] == 0

    def test_50_users_1_seat(self, engine):
        result = run_race(engine, "VIP-A-001", 50)
        assert result["errors"] == []
        assert result["winners"] == 1
        assert result["rejected"] == 49
        assert result["overselling"] == 0

    def test_100_users_1_seat(self, engine):
        result = run_race(engine, "VIP-A-001", 100)
        assert result["errors"] == []
        assert result["winners"] == 1
        assert result["rejected"] == 99
        assert result["overselling"] == 0

    def test_200_users_1_seat(self, engine):
        result = run_race(engine, "VIP-A-001", 200)
        assert result["errors"] == []
        assert result["winners"] == 1
        assert result["rejected"] == 199
        assert result["overselling"] == 0

    def test_multiple_races_different_seats(self, engine):
        """Carreras simultáneas sobre asientos diferentes."""
        def race_for_seat(seat_id):
            return run_race(engine, seat_id, 20)

        seat_ids = ["VIP-A-001", "VIP-A-002", "VIP-A-003", "VIP-A-004"]
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(race_for_seat, sid) for sid in seat_ids]
            results = [f.result() for f in as_completed(futures)]

        for r in results:
            assert r["winners"] == 1
            assert r["overselling"] == 0

    def test_seat_state_after_race(self, engine):
        """Después de la carrera, el asiento debe estar HELD (no SOLD)."""
        run_race(engine, "VIP-A-001", 50)
        seat = engine.get_seat("VIP-A-001")
        assert seat.status == SeatStatus.HELD
        assert seat.hold_id is not None
        assert seat.held_by is not None
