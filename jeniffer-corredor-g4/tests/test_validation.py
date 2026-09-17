"""
Tests de validacion de errores.

Una transaccion invalida no debe tumbar el proceso.
"""

import pytest
from pydantic import ValidationError

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.services.evaluator import Evaluator


def _base_dict():
    return {
        "id": "txn_001",
        "card_id": "card_001",
        "merchant_id": "merch_001",
        "amount": 100,
        "currency": "USD",
        "country": "US",
        "ip_country": "US",
        "device_id": "dev_001",
        "ip": "1.2.3.4",
        "timestamp": "2024-01-01T12:00:00Z",
    }


class TestValidation:
    def test_negative_amount(self):
        d = _base_dict()
        d["amount"] = -50
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_zero_amount(self):
        d = _base_dict()
        d["amount"] = 0
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_missing_field(self):
        d = _base_dict()
        del d["amount"]
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_empty_card_id(self):
        d = _base_dict()
        d["card_id"] = ""
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_empty_device_id(self):
        d = _base_dict()
        d["device_id"] = ""
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_invalid_ip(self):
        d = _base_dict()
        d["ip"] = "999.999.999.999"
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_invalid_timestamp(self):
        d = _base_dict()
        d["timestamp"] = "not-a-timestamp"
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_empty_id(self):
        d = _base_dict()
        d["id"] = ""
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_empty_merchant_id(self):
        d = _base_dict()
        d["merchant_id"] = "   "
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_invalid_currency_length(self):
        d = _base_dict()
        d["currency"] = "DOLLAR"
        with pytest.raises(ValidationError):
            Transaction(**d)

    def test_invalid_country_length(self):
        d = _base_dict()
        d["country"] = "USA"
        with pytest.raises(ValidationError):
            Transaction(**d)


class TestEvaluatorErrorHandling:
    def test_negative_amount_returns_error_not_crash(self):
        ev = Evaluator()
        d = _base_dict()
        d["amount"] = -50
        result = ev.evaluate(d)
        assert result["decision"] == "ERROR"
        assert result["score"] == 0
        assert "errors" in result

    def test_missing_field_returns_error_not_crash(self):
        ev = Evaluator()
        d = _base_dict()
        del d["timestamp"]
        result = ev.evaluate(d)
        assert result["decision"] == "ERROR"
        assert "errors" in result

    def test_invalid_ip_returns_error_not_crash(self):
        ev = Evaluator()
        d = _base_dict()
        d["ip"] = "not-an-ip"
        result = ev.evaluate(d)
        assert result["decision"] == "ERROR"

    def test_batch_with_invalid_does_not_crash(self):
        ev = Evaluator()
        valid = _base_dict()
        invalid = _base_dict()
        invalid["amount"] = -1
        results = ev.evaluate_batch([valid, invalid, valid])
        assert len(results) == 3
        assert results[0]["decision"] != "ERROR"
        assert results[1]["decision"] == "ERROR"
        assert results[2]["decision"] != "ERROR"
