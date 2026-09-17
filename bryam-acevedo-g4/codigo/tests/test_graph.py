"""Bono A: detección de colusión por grafo (device/ip compartido entre tarjetas)."""
from app.engine import RiskEngine
from tests.helpers import make_txn
from tests.test_phase1 import no_flake_config


def test_shared_ip_across_distinct_cards_flags_ring():
    engine = RiskEngine(no_flake_config())
    shared_ip = "203.0.113.9"
    result = None
    for i in range(4):
        result = engine.evaluate(
            make_txn(
                id=f"txn_{i}",
                card_id=f"card_ring_{i}",
                device_id=f"dev_{i}",  # dispositivos distintos, solo la IP se comparte
                ip=shared_ip,
                country="CO",
                ip_country="CO",
            )
        )
    rules = {r["rule"] for r in result["reasons"]}
    assert "possible_fraud_ring" in rules


def test_ring_report_lists_connected_cards():
    engine = RiskEngine(no_flake_config())
    shared_ip = "203.0.113.9"
    for i in range(4):
        result = engine.evaluate(
            make_txn(
                id=f"txn_{i}",
                card_id=f"card_ring_{i}",
                device_id=f"dev_{i}",
                ip=shared_ip,
                country="CO",
                ip_country="CO",
            )
        )
    ring_reason = next(r for r in result["reasons"] if r["rule"] == "possible_fraud_ring")
    for i in range(4):
        assert f"card_ring_{i}" in ring_reason["detail"]
