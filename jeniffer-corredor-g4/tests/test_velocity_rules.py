"""
Tests de las reglas de velocity (card y device) y su integracion
con el ScoringEngine.

Cubre:
    - 1 transaccion (sin trigger)
    - 5 transacciones (sin trigger, limite exacto)
    - sexta transaccion (trigger velocity, DECLINE, block)
    - expiracion del bloqueo
    - transaccion durante bloqueo
    - bloqueo por device
    - 3 tarjetas distintas
    - misma tarjeta repetida (no trigger device)
    - timestamps fuera de ventana
    - limpieza de estado
    - casos en los limites temporales
"""

from __future__ import annotations

from typing import Any

import pytest

from sentinelpay.app.services.evaluator import Evaluator


def _txn(
    id: str = "t1",
    card_id: str = "card_1",
    device_id: str = "dev_1",
    amount: float = 100,
    seconds: float = 0,
    country: str = "CO",
    ip_country: str = "CO",
) -> dict[str, Any]:
    """Genera un dict de transaccion con timestamp base + seconds."""
    base = "2024-11-28T12:00:00Z"
    from datetime import datetime, timedelta, timezone

    dt = datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": id,
        "card_id": card_id,
        "merchant_id": "merch_1",
        "amount": amount,
        "currency": "COP",
        "country": country,
        "ip_country": ip_country,
        "device_id": device_id,
        "ip": "190.24.6.10",
        "timestamp": ts,
    }


class TestVelocityCardRule:
    def test_one_transaction_no_trigger(self, evaluator):
        result = evaluator.evaluate(_txn(id="t1", amount=5000))
        assert result["decision"] != "DECLINE"
        assert result["score"] == 0

    def test_five_transactions_no_trigger(self, evaluator):
        for i in range(5):
            result = evaluator.evaluate(_txn(id=f"t{i+1}", amount=5000 + i * 1000, seconds=i))
            assert result["decision"] != "DECLINE", f"txn {i+1} should not decline"

    def test_sixth_transaction_triggers_velocity(self, evaluator):
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(5):
            evaluator.evaluate(_txn(id=f"t{i+1}", amount=amounts[i], seconds=i))

        result = evaluator.evaluate(_txn(id="t6", amount=amounts[5], seconds=7))
        assert result["decision"] == "DECLINE"
        assert result["score"] == 40
        rules = [r["rule"] for r in result["reasons"]]
        assert "velocity_limit_exceeded" in rules
        detail = next(r["detail"] for r in result["reasons"] if r["rule"] == "velocity_limit_exceeded")
        assert "6 txns" in detail
        assert "7s" in detail
        assert "limit: 5 in 10s" in detail

    def test_card_blocked_after_velocity(self, evaluator):
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(6):
            evaluator.evaluate(_txn(id=f"t{i+1}", amount=amounts[i], seconds=i))

        result = evaluator.evaluate(_txn(id="t7", amount=5000, seconds=10))
        assert result["decision"] == "DECLINE"
        assert result["score"] == 0
        rules = [r["rule"] for r in result["reasons"]]
        assert "card_temporarily_blocked" in rules

    def test_block_expiry(self, evaluator):
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(6):
            evaluator.evaluate(_txn(id=f"t{i+1}", amount=amounts[i], seconds=i))

        result = evaluator.evaluate(_txn(id="t_after", amount=5000, seconds=130))
        assert result["decision"] != "DECLINE"
        rules = [r["rule"] for r in result["reasons"]]
        assert "card_temporarily_blocked" not in rules

    def test_block_boundary_just_before_expiry(self, evaluator):
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(6):
            evaluator.evaluate(_txn(id=f"t{i+1}", amount=amounts[i], seconds=i))

        result = evaluator.evaluate(_txn(id="t_boundary", amount=5000, seconds=119))
        assert result["decision"] == "DECLINE"
        rules = [r["rule"] for r in result["reasons"]]
        assert "card_temporarily_blocked" in rules

    def test_timestamps_outside_window(self, evaluator):
        evaluator.evaluate(_txn(id="t1", amount=5000, seconds=0))
        evaluator.evaluate(_txn(id="t2", amount=5000, seconds=5))
        evaluator.evaluate(_txn(id="t3", amount=5000, seconds=10))
        evaluator.evaluate(_txn(id="t4", amount=5000, seconds=15))
        evaluator.evaluate(_txn(id="t5", amount=5000, seconds=20))

        result = evaluator.evaluate(_txn(id="t6", amount=5000, seconds=25))
        rules = [r["rule"] for r in result["reasons"]]
        assert "velocity_limit_exceeded" not in rules

    def test_velocity_disabled(self, tmp_path):
        config = tmp_path / "rules.yaml"
        config.write_text(
            """
rules:
  anomalous_amount: {enabled: true, weight: 25, multiplier: 3.0}
  country_mismatch: {enabled: true, weight: 30}
  unusual_hour: {enabled: true, weight: 10, default_timezone: UTC}
  velocity_card: {enabled: false, threshold: 5, window_seconds: 10, weight: 40, block_duration: 120}
  velocity_device: {enabled: true, threshold: 3, window_seconds: 30, weight: 50, block_duration: 120}
scoring: {reject_threshold: 50, review_threshold: 0}
""",
            encoding="utf-8",
        )
        ev = Evaluator(config_path=str(config))
        for i in range(5):
            ev.evaluate(_txn(id=f"t{i+1}", amount=5000 + i * 1000, seconds=i))
        result = ev.evaluate(_txn(id="t6", amount=10000, seconds=7))
        assert result["decision"] != "DECLINE"

    def test_custom_threshold(self, tmp_path):
        config = tmp_path / "rules.yaml"
        config.write_text(
            """
rules:
  anomalous_amount: {enabled: false, weight: 25, multiplier: 3.0}
  country_mismatch: {enabled: false, weight: 30}
  unusual_hour: {enabled: false, weight: 10, default_timezone: UTC}
  velocity_card: {enabled: true, threshold: 2, window_seconds: 10, weight: 40, block_duration: 120}
  velocity_device: {enabled: false, threshold: 3, window_seconds: 30, weight: 50, block_duration: 120}
scoring: {reject_threshold: 50, review_threshold: 0}
""",
            encoding="utf-8",
        )
        ev = Evaluator(config_path=str(config))
        ev.evaluate(_txn(id="t1", amount=5000, seconds=0))
        ev.evaluate(_txn(id="t2", amount=5000, seconds=1))
        result = ev.evaluate(_txn(id="t3", amount=5000, seconds=2))
        assert result["decision"] == "DECLINE"
        assert result["score"] == 40


class TestVelocityDeviceRule:
    def test_three_distinct_cards_triggers(self, evaluator):
        evaluator.evaluate(_txn(id="t1", card_id="c1", device_id="devA", amount=5000, seconds=0))
        evaluator.evaluate(_txn(id="t2", card_id="c2", device_id="devA", amount=5000, seconds=1))
        result = evaluator.evaluate(_txn(id="t3", card_id="c3", device_id="devA", amount=5000, seconds=2))
        assert result["decision"] == "DECLINE"
        assert result["score"] == 50
        rules = [r["rule"] for r in result["reasons"]]
        assert "device_velocity_exceeded" in rules

    def test_same_card_repeated_no_trigger(self, evaluator):
        evaluator.evaluate(_txn(id="t1", card_id="c1", device_id="devA", amount=5000, seconds=0))
        evaluator.evaluate(_txn(id="t2", card_id="c1", device_id="devA", amount=5000, seconds=1))
        result = evaluator.evaluate(_txn(id="t3", card_id="c1", device_id="devA", amount=5000, seconds=2))
        rules = [r["rule"] for r in result["reasons"]]
        assert "device_velocity_exceeded" not in rules

    def test_device_blocked_after_trigger(self, evaluator):
        evaluator.evaluate(_txn(id="t1", card_id="c1", device_id="devA", amount=5000, seconds=0))
        evaluator.evaluate(_txn(id="t2", card_id="c2", device_id="devA", amount=5000, seconds=1))
        evaluator.evaluate(_txn(id="t3", card_id="c3", device_id="devA", amount=5000, seconds=2))

        result = evaluator.evaluate(_txn(id="t4", card_id="c4", device_id="devA", amount=5000, seconds=3))
        assert result["decision"] == "DECLINE"
        rules = [r["rule"] for r in result["reasons"]]
        assert "device_temporarily_blocked" in rules

    def test_device_block_expiry(self, evaluator):
        evaluator.evaluate(_txn(id="t1", card_id="c1", device_id="devA", amount=5000, seconds=0))
        evaluator.evaluate(_txn(id="t2", card_id="c2", device_id="devA", amount=5000, seconds=1))
        evaluator.evaluate(_txn(id="t3", card_id="c3", device_id="devA", amount=5000, seconds=2))

        result = evaluator.evaluate(_txn(id="t_after", card_id="c4", device_id="devA", amount=5000, seconds=130))
        rules = [r["rule"] for r in result["reasons"]]
        assert "device_temporarily_blocked" not in rules

    def test_device_window_excludes_old(self, evaluator):
        evaluator.evaluate(_txn(id="t1", card_id="c1", device_id="devA", amount=5000, seconds=0))
        evaluator.evaluate(_txn(id="t2", card_id="c2", device_id="devA", amount=5000, seconds=1))
        evaluator.evaluate(_txn(id="t3", card_id="c3", device_id="devA", amount=5000, seconds=35))

        result = evaluator.evaluate(_txn(id="t4", card_id="c4", device_id="devA", amount=5000, seconds=36))
        rules = [r["rule"] for r in result["reasons"]]
        assert "device_velocity_exceeded" not in rules

    def test_two_distinct_cards_no_trigger(self, evaluator):
        evaluator.evaluate(_txn(id="t1", card_id="c1", device_id="devA", amount=5000, seconds=0))
        result = evaluator.evaluate(_txn(id="t2", card_id="c2", device_id="devA", amount=5000, seconds=1))
        rules = [r["rule"] for r in result["reasons"]]
        assert "device_velocity_exceeded" not in rules


class TestStateCleanup:
    def test_velocity_tracker_cleanup(self, evaluator):
        for i in range(6):
            evaluator.evaluate(_txn(id=f"t{i+1}", amount=5000, seconds=i))

        assert len(evaluator.store.velocity_tracker._card_timestamps) > 0

        evaluator.evaluate(_txn(id="t_late", amount=5000, seconds=400))
        for card_id in evaluator.store.velocity_tracker._card_timestamps:
            timestamps = evaluator.store.velocity_tracker._card_timestamps[card_id]
            for t in timestamps:
                from datetime import datetime, timedelta, timezone
                cutoff = datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=100)
                assert t >= cutoff

    def test_blocklist_cleanup(self, evaluator):
        for i in range(6):
            evaluator.evaluate(_txn(id=f"t{i+1}", amount=5000, seconds=i))

        assert len(evaluator.store.blocklist.get_blocked_cards()) > 0

        evaluator.evaluate(_txn(id="t_late", amount=5000, seconds=200))
        assert len(evaluator.store.blocklist.get_blocked_cards()) == 0
