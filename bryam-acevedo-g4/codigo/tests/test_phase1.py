import copy
from datetime import datetime, timezone

from app.config import DEFAULT_CONFIG
from app.engine import RiskEngine
from tests.helpers import make_txn


def no_flake_config():
    """Config con bank auth siempre exitoso, para no depender del azar en asserts de score/decision."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["bank_auth"]["failure_probability"] = 0.0
    cfg["bank_auth"]["simulated_latency_seconds"] = 0.0
    return cfg


def test_example_from_spec_country_and_hour():
    engine = RiskEngine(no_flake_config())
    txn = make_txn(
        id="txn_00234",
        card_id="card_9F21",
        merchant_id="merch_petshop_bog",
        amount=850000,
        country="CO",
        ip_country="RU",
        device_id="dev_a19x",
        ip="185.220.101.14",
        timestamp=datetime(2024, 11, 28, 4, 58, 12, tzinfo=timezone.utc),
    )
    result = engine.evaluate(txn)
    assert result["score"] == 40
    assert result["decision"] == "REVIEW"
    rules = {r["rule"] for r in result["reasons"]}
    assert "country_mismatch" in rules
    assert "unusual_hour" in rules


def test_amount_anomaly_triggers_after_history():
    engine = RiskEngine(no_flake_config())
    card = "card_hist"
    for _ in range(5):
        engine.evaluate(make_txn(id="warmup", card_id=card, amount=10000, country="CO", ip_country="CO"))

    result = engine.evaluate(make_txn(id="spike", card_id=card, amount=100000, country="CO", ip_country="CO"))
    rules = {r["rule"] for r in result["reasons"]}
    assert "amount_anomaly" in rules


def test_no_rules_triggered_is_approve():
    engine = RiskEngine(no_flake_config())
    result = engine.evaluate(make_txn(country="CO", ip_country="CO", timestamp=datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc)))
    assert result["score"] == 0
    assert result["decision"] == "APPROVE"
    assert result["reasons"] == []


def test_rule_can_be_disabled_via_config():
    cfg = no_flake_config()
    cfg["rules"]["country_mismatch"]["enabled"] = False
    engine = RiskEngine(cfg)
    result = engine.evaluate(make_txn(country="CO", ip_country="RU", timestamp=datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc)))
    rules = {r["rule"] for r in result["reasons"]}
    assert "country_mismatch" not in rules
