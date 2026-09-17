"""
Fixtures compartidas para los tests de SentinelPay.
"""

import pytest

from sentinelpay.app.services.evaluator import Evaluator
from sentinelpay.persistence.store import InMemoryStore


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def evaluator() -> Evaluator:
    return Evaluator()


@pytest.fixture
def sample_txn_dict() -> dict:
    return {
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


@pytest.fixture
def normal_txn_dict() -> dict:
    return {
        "id": "txn_normal_01",
        "card_id": "card_001",
        "merchant_id": "merch_amazon_us",
        "amount": 100.00,
        "currency": "USD",
        "country": "US",
        "ip_country": "US",
        "device_id": "dev_001",
        "ip": "192.168.1.1",
        "timestamp": "2024-11-28T14:30:00Z",
    }
