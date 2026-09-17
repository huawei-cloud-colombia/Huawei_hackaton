from app.engine import RiskEngine
from tests.helpers import make_txn
from tests.test_phase1 import no_flake_config


def test_velocity_card_blocks_on_sixth_transaction():
    engine = RiskEngine(no_flake_config())
    card = "card_9F21"
    results = []
    for i in range(6):
        results.append(
            engine.evaluate(
                make_txn(id=f"txn_{i}", card_id=card, amount=5000 + i * 1000, country="CO", ip_country="CO")
            )
        )

    for r in results[:5]:
        assert r["decision"] != "DECLINE" or "velocity_limit_exceeded" not in {x["rule"] for x in r["reasons"]}

    sixth = results[5]
    assert sixth["decision"] == "DECLINE"
    rules = {r["rule"] for r in sixth["reasons"]}
    assert "velocity_limit_exceeded" in rules


def test_card_stays_blocked_after_velocity_trigger():
    engine = RiskEngine(no_flake_config())
    card = "card_9F21"
    for i in range(6):
        engine.evaluate(make_txn(id=f"txn_{i}", card_id=card, amount=5000, country="CO", ip_country="CO"))

    seventh = engine.evaluate(make_txn(id="txn_7", card_id=card, amount=5000, country="CO", ip_country="CO"))
    assert seventh["decision"] == "DECLINE"
    rules = {r["rule"] for r in seventh["reasons"]}
    assert "card_temporarily_blocked" in rules
    assert seventh["bank_auth_status"] == "skipped_blocked"


def test_device_card_hopping_triggers_hard_decline():
    engine = RiskEngine(no_flake_config())
    device = "dev_shared"
    result = None
    for i in range(4):
        result = engine.evaluate(
            make_txn(id=f"txn_{i}", card_id=f"card_{i}", device_id=device, country="CO", ip_country="CO")
        )
    rules = {r["rule"] for r in result["reasons"]}
    assert "device_card_hopping" in rules
    assert result["decision"] == "DECLINE"
