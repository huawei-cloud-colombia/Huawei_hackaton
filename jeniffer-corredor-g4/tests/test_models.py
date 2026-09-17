"""
Tests del modelo de transaccion.
"""

import pytest
from pydantic import ValidationError

from sentinelpay.app.models.transaction import Transaction


class TestTransactionModel:
    def test_valid_transaction(self, sample_txn_dict):
        txn = Transaction(**sample_txn_dict)
        assert txn.id == "txn_00234"
        assert txn.card_id == "card_9F21"
        assert txn.amount == 850000
        assert txn.currency == "COP"
        assert txn.country == "CO"
        assert txn.ip_country == "RU"

    def test_currency_uppercase(self):
        txn = Transaction(
            id="t1", card_id="c1", merchant_id="m1", amount=100,
            currency="cop", country="co", ip_country="ru",
            device_id="d1", ip="1.2.3.4", timestamp="2024-01-01T12:00:00Z",
        )
        assert txn.currency == "COP"
        assert txn.country == "CO"
        assert txn.ip_country == "RU"

    def test_timestamp_parsed(self, sample_txn_dict):
        txn = Transaction(**sample_txn_dict)
        assert txn.timestamp.year == 2024
        assert txn.timestamp.month == 11
        assert txn.timestamp.day == 28
        assert txn.timestamp.hour == 4

    def test_extra_field_forbidden(self, sample_txn_dict):
        sample_txn_dict["extra_field"] = "nope"
        with pytest.raises(ValidationError):
            Transaction(**sample_txn_dict)

    def test_missing_field(self):
        with pytest.raises(ValidationError):
            Transaction(
                id="t1", card_id="c1", merchant_id="m1", amount=100,
                currency="USD", country="US",
                device_id="d1", ip="1.2.3.4", timestamp="2024-01-01T12:00:00Z",
            )
