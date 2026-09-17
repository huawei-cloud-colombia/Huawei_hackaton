import copy

from app.bank import CircuitState
from app.engine import RiskEngine
from tests.helpers import make_txn
from tests.test_phase1 import no_flake_config


def test_decision_thresholds_boundaries():
    engine = RiskEngine(no_flake_config())
    assert engine._decide(score=39, hard_decline=False) == "APPROVE"
    assert engine._decide(score=40, hard_decline=False) == "REVIEW"
    assert engine._decide(score=74, hard_decline=False) == "REVIEW"
    assert engine._decide(score=75, hard_decline=False) == "DECLINE"
    assert engine._decide(score=0, hard_decline=True) == "DECLINE"


def test_score_never_exceeds_100():
    engine = RiskEngine(no_flake_config())
    card = "card_overload"
    # Fuerza country_mismatch + unusual_hour + monto anómalo + velocidad en la misma tarjeta.
    from datetime import datetime, timezone

    for i in range(6):
        engine.evaluate(
            make_txn(
                id=f"txn_{i}",
                card_id=card,
                amount=5000 + i,
                country="CO",
                ip_country="RU",
                timestamp=datetime(2024, 11, 28, 3, 0, 0, tzinfo=timezone.utc),
            )
        )

    result = engine.evaluate(
        make_txn(
            id="txn_final",
            card_id=card,
            amount=999999,
            country="CO",
            ip_country="RU",
            timestamp=datetime(2024, 11, 28, 3, 0, 0, tzinfo=timezone.utc),
        )
    )
    assert result["score"] <= 100


def test_circuit_breaker_opens_after_repeated_failures():
    cfg = copy.deepcopy(no_flake_config())
    cfg["bank_auth"]["failure_probability"] = 1.0
    cfg["bank_auth"]["simulated_latency_seconds"] = 0.0
    cfg["circuit_breaker"]["failure_threshold"] = 3
    engine = RiskEngine(cfg)

    statuses = []
    for i in range(3):
        result = engine.evaluate(
            make_txn(
                id=f"txn_{i}",
                card_id=f"card_iso_{i}",
                device_id=f"dev_iso_{i}",
                ip=f"10.1.0.{i}",
                country="CO",
                ip_country="CO",
            )
        )
        statuses.append(result["bank_auth_status"])

    assert engine.circuit_breaker.state == CircuitState.OPEN

    degraded = engine.evaluate(
        make_txn(
            id="txn_after_open",
            card_id="card_iso_after",
            device_id="dev_iso_after",
            ip="10.1.0.99",
            country="CO",
            ip_country="CO",
        )
    )
    assert degraded["bank_auth_status"] == "circuit_open_degraded"
    assert degraded["decision"] == "REVIEW"
