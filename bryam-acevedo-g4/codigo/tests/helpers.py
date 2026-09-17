from datetime import datetime, timezone


def make_txn(**overrides):
    base = {
        "id": "txn_test",
        "card_id": "card_test",
        "merchant_id": "merch_test",
        "amount": 10000.0,
        "currency": "COP",
        "country": "CO",
        "ip_country": "CO",
        "device_id": "dev_test",
        "ip": "10.0.0.1",
        "timestamp": datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base
