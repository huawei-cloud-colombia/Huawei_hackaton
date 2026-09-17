"""
Tests del motor de scoring y servicio evaluador.

Incluye el caso obligatorio del reto: CO/RU/04:58.
"""

from sentinelpay.app.services.evaluator import Evaluator
from sentinelpay.app.models.transaction import Transaction
from sentinelpay.persistence.store import InMemoryStore


def _make_txn(
    id="t1", card_id="c1", amount=100, country="US", ip_country="US",
    timestamp="2024-01-01T12:00:00Z", merchant_id="m1",
):
    return Transaction(
        id=id, card_id=card_id, merchant_id=merchant_id, amount=amount,
        currency="USD", country=country, ip_country=ip_country,
        device_id="d1", ip="1.2.3.4", timestamp=timestamp,
    )


class TestScoringEngine:
    def test_no_rules_triggered_approve(self, evaluator):
        result = evaluator.evaluate(_make_txn())
        assert result["score"] == 0
        assert result["decision"] == "APPROVE"
        assert result["reasons"] == []

    def test_country_mismatch_only(self, evaluator):
        result = evaluator.evaluate(_make_txn(country="CO", ip_country="RU"))
        assert result["score"] == 30
        assert result["decision"] == "REVIEW"
        assert len(result["reasons"]) == 1
        assert result["reasons"][0]["rule"] == "country_mismatch"

    def test_unusual_hour_only(self, evaluator):
        result = evaluator.evaluate(_make_txn(timestamp="2024-01-01T03:00:00Z"))
        assert result["score"] == 10
        assert result["decision"] == "REVIEW"

    def test_country_and_hour(self, evaluator):
        result = evaluator.evaluate(
            _make_txn(country="CO", ip_country="RU", timestamp="2024-01-01T03:00:00Z")
        )
        assert result["score"] == 40
        assert result["decision"] == "REVIEW"
        rules = [r["rule"] for r in result["reasons"]]
        assert "country_mismatch" in rules
        assert "unusual_hour" in rules

    def test_all_three_rules(self, evaluator):
        evaluator.evaluate(_make_txn(card_id="c1", amount=100))
        evaluator.evaluate(_make_txn(card_id="c1", amount=100))
        evaluator.evaluate(_make_txn(card_id="c1", amount=100))
        result = evaluator.evaluate(
            _make_txn(
                card_id="c1", amount=500,
                country="CO", ip_country="RU",
                timestamp="2024-01-01T03:00:00Z",
            )
        )
        assert result["score"] == 65
        assert result["decision"] == "REJECT"

    def test_result_structure(self, evaluator):
        result = evaluator.evaluate(_make_txn(id="txn_xyz"))
        assert "transaction_id" in result
        assert "score" in result
        assert "decision" in result
        assert "reasons" in result
        assert result["transaction_id"] == "txn_xyz"

    def test_reasons_explainability(self, evaluator):
        result = evaluator.evaluate(
            _make_txn(country="CO", ip_country="RU", timestamp="2024-01-01T04:58:12Z")
        )
        for reason in result["reasons"]:
            assert "rule" in reason
            assert "weight" in reason
            assert "detail" in reason


class TestMandatoryRetoCase:
    """
    Caso obligatorio del reto:
        country = CO
        ip_country = RU
        hora = 04:58

    Resultado esperado:
        country_mismatch = +30
        unusual_hour = +10
        score = 40
    """

    def test_co_ru_0458(self, evaluator):
        txn = {
            "id": "txn_00234",
            "card_id": "card_9F21",
            "merchant_id": "merch_petshop_bog",
            "amount": 850000,
            "currency": "COP",
            "country": "CO",
            "ip_country": "RU",
            "device_id": "dev_a19x",
            "ip": "185.220.101.14",
            "timestamp": "2024-11-28T04:58:12Z",
        }
        result = evaluator.evaluate(txn)

        assert result["transaction_id"] == "txn_00234"
        assert result["score"] == 40
        assert result["decision"] == "REVIEW"

        rules = {r["rule"]: r for r in result["reasons"]}
        assert "country_mismatch" in rules
        assert rules["country_mismatch"]["weight"] == 30
        assert "unusual_hour" in rules
        assert rules["unusual_hour"]["weight"] == 10
        assert "04:58" in rules["unusual_hour"]["detail"]


class TestPersistence:
    def test_store_records_transaction(self, evaluator):
        txn = _make_txn(id="t1", card_id="c1", amount=100)
        evaluator.evaluate(txn)
        assert len(evaluator.store.get_transactions()) == 1
        assert len(evaluator.store.get_results()) == 1

    def test_store_card_average(self, evaluator):
        evaluator.evaluate(_make_txn(id="t1", card_id="c1", amount=100))
        evaluator.evaluate(_make_txn(id="t2", card_id="c1", amount=200))
        avg = evaluator.store.get_card_average("c1")
        assert avg == 150.0

    def test_store_clear(self, evaluator):
        evaluator.evaluate(_make_txn(id="t1", card_id="c1", amount=100))
        evaluator.reset()
        assert len(evaluator.store.get_transactions()) == 0
        assert evaluator.store.get_card_average("c1") is None
