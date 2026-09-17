"""
SentinelPay Risk Engine
=======================

Motor de scoring de riesgo para transacciones financieras.

Uso basico:

    from sentinelpay import evaluate

    result = evaluate({
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
    })
    print(result)
"""

from sentinelpay.app.services.evaluator import evaluate, Evaluator, reset

__all__ = ["evaluate", "Evaluator", "reset"]
__version__ = "0.1.0"
