"""
Tests de configuracion de reglas.
"""

from sentinelpay.app.config.settings import Settings
from sentinelpay.app.rules.anomalous_amount import AnomalousAmountRule
from sentinelpay.app.rules.country_mismatch import CountryMismatchRule
from sentinelpay.app.rules.unusual_hour import UnusualHourRule
from sentinelpay.app.services.evaluator import Evaluator
from sentinelpay.app.models.transaction import Transaction
from sentinelpay.persistence.store import InMemoryStore


def _make_txn(amount=100, country="US", ip_country="US", timestamp="2024-01-01T12:00:00Z"):
    return Transaction(
        id="t1", card_id="c1", merchant_id="m1", amount=amount,
        currency="USD", country=country, ip_country=ip_country,
        device_id="d1", ip="1.2.3.4", timestamp=timestamp,
    )


class TestRuleConfig:
    def test_default_config_loads(self):
        settings = Settings()
        rc = settings.rules_config
        assert "anomalous_amount" in rc
        assert "country_mismatch" in rc
        assert "unusual_hour" in rc

    def test_rule_enabled_by_default(self):
        ev = Evaluator()
        for rule in ev.rules:
            assert rule.enabled is True

    def test_rule_disabled(self, tmp_path):
        config = tmp_path / "rules.yaml"
        config.write_text(
            """
rules:
  anomalous_amount:
    enabled: false
    weight: 25
  country_mismatch:
    enabled: true
    weight: 30
  unusual_hour:
    enabled: true
    weight: 10
    default_timezone: UTC
scoring:
  reject_threshold: 50
  review_threshold: 0
""",
            encoding="utf-8",
        )
        ev = Evaluator(config_path=str(config))
        assert ev.rules[0].enabled is False
        assert ev.rules[1].enabled is True
        assert ev.rules[2].enabled is True

    def test_custom_weight(self, tmp_path):
        config = tmp_path / "rules.yaml"
        config.write_text(
            """
rules:
  anomalous_amount:
    enabled: true
    weight: 99
  country_mismatch:
    enabled: true
    weight: 88
  unusual_hour:
    enabled: true
    weight: 77
    default_timezone: UTC
scoring:
  reject_threshold: 50
  review_threshold: 0
""",
            encoding="utf-8",
        )
        ev = Evaluator(config_path=str(config))
        assert ev.rules[0].weight == 99
        assert ev.rules[1].weight == 88
        assert ev.rules[2].weight == 77

    def test_all_rules_disabled(self, tmp_path):
        config = tmp_path / "rules.yaml"
        config.write_text(
            """
rules:
  anomalous_amount:
    enabled: false
    weight: 25
  country_mismatch:
    enabled: false
    weight: 30
  unusual_hour:
    enabled: false
    weight: 10
    default_timezone: UTC
scoring:
  reject_threshold: 50
  review_threshold: 0
""",
            encoding="utf-8",
        )
        ev = Evaluator(config_path=str(config))
        result = ev.evaluate(_make_txn(country="CO", ip_country="RU", timestamp="2024-01-01T03:00:00Z"))
        assert result["score"] == 0
        assert result["decision"] == "APPROVE"
        assert result["reasons"] == []

    def test_custom_thresholds(self, tmp_path):
        config = tmp_path / "rules.yaml"
        config.write_text(
            """
rules:
  anomalous_amount:
    enabled: true
    weight: 25
  country_mismatch:
    enabled: true
    weight: 30
  unusual_hour:
    enabled: true
    weight: 10
    default_timezone: UTC
scoring:
  reject_threshold: 100
  review_threshold: 0
""",
            encoding="utf-8",
        )
        ev = Evaluator(config_path=str(config))
        result = ev.evaluate(_make_txn(country="CO", ip_country="RU"))
        assert result["score"] == 30
        assert result["decision"] == "REVIEW"
