import asyncio

from stress_test import run_stress


def test_nexus_stress_concurrent_safety():
    rep = asyncio.run(run_stress(n=40, seat="VIP-0003"))
    assert rep["winners_201"] == 1, f"expected 1 winner, got {rep['winners_201']}"
    assert rep["rejected_409"] == 39
    assert rep["other"] == []
    assert rep["writer_errors"] == 0, "SQLite reported 'database is locked'"
    assert rep["writer_events_processed"] >= 1
    assert rep["checkout_status"] == 200
    assert rep["sold_in_memory"] == 1


def test_nexus_idempotency_dedup():
    rep = asyncio.run(run_stress(n=10, seat="VIP-0004"))
    assert rep["idem_status_codes"] == [201, 201]
    assert rep["idem_same_hold"] is True
