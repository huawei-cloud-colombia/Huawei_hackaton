"""
Tests de la regla de pais diferente.
"""

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.country_mismatch import CountryMismatchRule
from sentinelpay.persistence.store import InMemoryStore


def _make_txn(country="CO", ip_country="CO"):
    return Transaction(
        id="t1", card_id="c1", merchant_id="m1", amount=100,
        currency="USD", country=country, ip_country=ip_country,
        device_id="d1", ip="1.2.3.4", timestamp="2024-01-01T12:00:00Z",
    )


class TestCountryMismatchRule:
    def test_same_country_no_trigger(self, store):
        rule = CountryMismatchRule()
        result = rule.evaluate(_make_txn(country="CO", ip_country="CO"), store)
        assert result is None

    def test_different_country_triggers(self, store):
        rule = CountryMismatchRule()
        result = rule.evaluate(_make_txn(country="CO", ip_country="RU"), store)
        assert result is not None
        assert result.rule == "country_mismatch"
        assert result.weight == 30
        assert "CO" in result.detail
        assert "RU" in result.detail

    def test_disabled_rule(self, store):
        rule = CountryMismatchRule(enabled=False)
        result = rule.evaluate(_make_txn(country="CO", ip_country="RU"), store)
        assert result is None

    def test_custom_weight(self, store):
        rule = CountryMismatchRule(weight=50)
        result = rule.evaluate(_make_txn(country="US", ip_country="CN"), store)
        assert result is not None
        assert result.weight == 50
