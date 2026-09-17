"""
Tests de la regla de monto anomalo.
"""

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.anomalous_amount import AnomalousAmountRule
from sentinelpay.persistence.store import InMemoryStore


def _make_txn(amount=100, card_id="card_001"):
    return Transaction(
        id="t1", card_id=card_id, merchant_id="m1", amount=amount,
        currency="USD", country="US", ip_country="US",
        device_id="d1", ip="1.2.3.4", timestamp="2024-01-01T12:00:00Z",
    )


class TestAnomalousAmountRule:
    def test_normal_amount_no_trigger(self, store):
        store.record_transaction(_make_txn(amount=100))
        store.record_transaction(_make_txn(amount=110))
        rule = AnomalousAmountRule()
        result = rule.evaluate(_make_txn(amount=120), store)
        assert result is None

    def test_amount_exceeds_3x_average(self, store):
        store.record_transaction(_make_txn(amount=100))
        store.record_transaction(_make_txn(amount=100))
        store.record_transaction(_make_txn(amount=100))
        rule = AnomalousAmountRule()
        result = rule.evaluate(_make_txn(amount=400), store)
        assert result is not None
        assert result.rule == "anomalous_amount"
        assert result.weight == 25

    def test_no_history_no_trigger(self, store):
        rule = AnomalousAmountRule()
        result = rule.evaluate(_make_txn(amount=999999), store)
        assert result is None

    def test_custom_multiplier(self, store):
        store.record_transaction(_make_txn(amount=100))
        store.record_transaction(_make_txn(amount=100))
        rule = AnomalousAmountRule(multiplier=2.0)
        result = rule.evaluate(_make_txn(amount=250), store)
        assert result is not None
        assert result.weight == 25

    def test_disabled_rule(self, store):
        store.record_transaction(_make_txn(amount=100))
        store.record_transaction(_make_txn(amount=100))
        rule = AnomalousAmountRule(enabled=False)
        result = rule.evaluate(_make_txn(amount=999999), store)
        assert result is None

    def test_custom_weight(self, store):
        store.record_transaction(_make_txn(amount=100))
        store.record_transaction(_make_txn(amount=100))
        rule = AnomalousAmountRule(weight=50)
        result = rule.evaluate(_make_txn(amount=400), store)
        assert result is not None
        assert result.weight == 50

    def test_exact_3x_boundary_no_trigger(self, store):
        store.record_transaction(_make_txn(amount=100))
        store.record_transaction(_make_txn(amount=100))
        rule = AnomalousAmountRule()
        result = rule.evaluate(_make_txn(amount=300), store)
        assert result is None
