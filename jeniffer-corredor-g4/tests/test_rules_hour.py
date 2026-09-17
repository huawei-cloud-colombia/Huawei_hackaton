"""
Tests de la regla de hora inusual.

El rango [01:00, 05:00) es inclusivo en inicio, exclusivo en fin.
Con default_timezone=UTC, el timestamp UTC se usa directamente.
"""

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.unusual_hour import UnusualHourRule
from sentinelpay.persistence.store import InMemoryStore


def _make_txn(timestamp="2024-01-01T12:00:00Z"):
    return Transaction(
        id="t1", card_id="c1", merchant_id="m1", amount=100,
        currency="USD", country="US", ip_country="US",
        device_id="d1", ip="1.2.3.4", timestamp=timestamp,
    )


class TestUnusualHourRule:
    def test_00_59_not_unusual(self, store):
        rule = UnusualHourRule()
        result = rule.evaluate(_make_txn("2024-01-01T00:59:00Z"), store)
        assert result is None

    def test_01_00_is_unusual(self, store):
        rule = UnusualHourRule()
        result = rule.evaluate(_make_txn("2024-01-01T01:00:00Z"), store)
        assert result is not None
        assert result.rule == "unusual_hour"
        assert result.weight == 10

    def test_04_59_is_unusual(self, store):
        rule = UnusualHourRule()
        result = rule.evaluate(_make_txn("2024-01-01T04:59:00Z"), store)
        assert result is not None

    def test_05_00_not_unusual(self, store):
        rule = UnusualHourRule()
        result = rule.evaluate(_make_txn("2024-01-01T05:00:00Z"), store)
        assert result is None

    def test_normal_hour_not_unusual(self, store):
        rule = UnusualHourRule()
        result = rule.evaluate(_make_txn("2024-01-01T14:30:00Z"), store)
        assert result is None

    def test_disabled_rule(self, store):
        rule = UnusualHourRule(enabled=False)
        result = rule.evaluate(_make_txn("2024-01-01T03:00:00Z"), store)
        assert result is None

    def test_custom_weight(self, store):
        rule = UnusualHourRule(weight=20)
        result = rule.evaluate(_make_txn("2024-01-01T03:00:00Z"), store)
        assert result is not None
        assert result.weight == 20

    def test_custom_timezone(self, store):
        rule = UnusualHourRule(default_timezone="America/Bogota")
        # 09:00 UTC = 04:00 Bogota (UTC-5) -> unusual
        result = rule.evaluate(_make_txn("2024-01-01T09:00:00Z"), store)
        assert result is not None
        assert "04:00" in result.detail

    def test_merchant_timezone_override(self, store):
        rule = UnusualHourRule(
            default_timezone="UTC",
            merchant_timezones={"m1": "America/Bogota"},
        )
        # 09:00 UTC = 04:00 Bogota -> unusual
        result = rule.evaluate(_make_txn("2024-01-01T09:00:00Z"), store)
        assert result is not None

    def test_detail_format(self, store):
        rule = UnusualHourRule()
        result = rule.evaluate(_make_txn("2024-01-01T04:58:12Z"), store)
        assert result is not None
        assert "04:58" in result.detail
        assert "local time" in result.detail
