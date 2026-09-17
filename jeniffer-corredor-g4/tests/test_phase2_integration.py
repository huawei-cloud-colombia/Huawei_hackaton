"""
Tests de integracion de la Fase 2 con la Fase 1.

Incluye:
    - Caso obligatorio: 6 transacciones, misma tarjeta, 7 segundos.
    - Verificacion de que las transacciones posteriores dentro de 120s
      devuelven DECLINE con card_temporarily_blocked.
    - Verificacion de que la Fase 1 sigue funcionando (regresion).
    - Combinacion de reglas base + velocity.
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
    merchant_id: str = "merch_1",
) -> dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    dt = datetime(2024, 11, 28, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    ts = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": id,
        "card_id": card_id,
        "merchant_id": merchant_id,
        "amount": amount,
        "currency": "COP",
        "country": country,
        "ip_country": ip_country,
        "device_id": device_id,
        "ip": "190.24.6.10",
        "timestamp": ts,
    }


class TestMandatoryPhase2:
    """
    Caso obligatorio de la Fase 2:

    Simula:
        6 transacciones
        misma tarjeta
        7 segundos
        montos entre 5.000 y 15.000 COP

    La transaccion 6 debe:
        - activar velocity
        - sumar +40
        - bloquear temporalmente
        - retornar DECLINE
        - explicar la razon

    Las transacciones posteriores dentro de 120 segundos deben devolver:
        DECLINE / card_temporarily_blocked
    """

    def test_six_transaction_burst(self):
        ev = Evaluator()
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        results = []

        for i in range(5):
            r = ev.evaluate(_txn(id=f"txn_{i+1:05d}", card_id="card_9F21", amount=amounts[i], seconds=i))
            results.append(r)
            assert r["decision"] != "DECLINE", f"txn {i+1} should not decline"

        r6 = ev.evaluate(_txn(id="txn_00006", card_id="card_9F21", amount=amounts[5], seconds=7))
        results.append(r6)

        assert r6["decision"] == "DECLINE"
        assert r6["score"] == 40

        rules = {r["rule"]: r for r in r6["reasons"]}
        assert "velocity_limit_exceeded" in rules
        assert rules["velocity_limit_exceeded"]["weight"] == 40
        detail = rules["velocity_limit_exceeded"]["detail"]
        assert "6 txns" in detail
        assert "7s" in detail
        assert "limit: 5 in 10s" in detail

    def test_post_block_decline(self):
        ev = Evaluator()
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(6):
            ev.evaluate(_txn(id=f"txn_{i+1:05d}", card_id="card_9F21", amount=amounts[i], seconds=i))

        r = ev.evaluate(_txn(id="txn_00007", card_id="card_9F21", amount=5000, seconds=10))
        assert r["decision"] == "DECLINE"
        assert r["score"] == 0
        rules = [r2["rule"] for r2 in r["reasons"]]
        assert "card_temporarily_blocked" in rules

    def test_post_block_at_119_seconds(self):
        ev = Evaluator()
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(6):
            ev.evaluate(_txn(id=f"txn_{i+1:05d}", card_id="card_9F21", amount=amounts[i], seconds=i))

        r = ev.evaluate(_txn(id="txn_119", card_id="card_9F21", amount=5000, seconds=119))
        assert r["decision"] == "DECLINE"
        rules = [r2["rule"] for r2 in r["reasons"]]
        assert "card_temporarily_blocked" in rules

    def test_unblock_after_120_seconds(self):
        ev = Evaluator()
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(6):
            ev.evaluate(_txn(id=f"txn_{i+1:05d}", card_id="card_9F21", amount=amounts[i], seconds=i))

        r = ev.evaluate(_txn(id="txn_120", card_id="card_9F21", amount=5000, seconds=130))
        assert r["decision"] != "DECLINE"
        rules = [r2["rule"] for r2 in r["reasons"]]
        assert "card_temporarily_blocked" not in rules

    def test_velocity_detail_dynamic(self):
        ev = Evaluator()
        amounts = [5000, 6000, 7000, 8000, 9000, 10000]
        for i in range(5):
            ev.evaluate(_txn(id=f"t{i+1}", card_id="c1", amount=amounts[i], seconds=i * 2))

        r = ev.evaluate(_txn(id="t6", card_id="c1", amount=10000, seconds=10))
        assert r["decision"] == "DECLINE"
        detail = next(r2["detail"] for r2 in r["reasons"] if r2["rule"] == "velocity_limit_exceeded")
        assert "6 txns" in detail


class TestPhase1Regression:
    """Verifica que la Fase 1 sigue funcionando despues de la Fase 2."""

    def test_co_ru_0458_still_works(self):
        ev = Evaluator()
        result = ev.evaluate({
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
        assert result["score"] == 40
        assert result["decision"] == "REVIEW"
        rules = {r["rule"]: r for r in result["reasons"]}
        assert "country_mismatch" in rules
        assert "unusual_hour" in rules

    def test_normal_transaction_still_approves(self):
        ev = Evaluator()
        result = ev.evaluate(_txn(id="t1", amount=100, country="CO", ip_country="CO"))
        assert result["decision"] == "APPROVE"
        assert result["score"] == 0

    def test_invalid_transaction_still_returns_error(self):
        ev = Evaluator()
        d = _txn(id="t1", amount=-100)
        result = ev.evaluate(d)
        assert result["decision"] == "ERROR"

    def test_batch_still_works(self):
        ev = Evaluator()
        txns = [_txn(id=f"t{i+1}", amount=100, seconds=i * 100) for i in range(3)]
        results = ev.evaluate_batch(txns)
        assert len(results) == 3


class TestCombinedRules:
    """Verifica que las reglas base y velocity pueden coexistir."""

    def test_velocity_plus_country_mismatch(self):
        ev = Evaluator()
        amounts = [5000, 6000, 7000, 8000, 9000]
        for i in range(5):
            ev.evaluate(_txn(id=f"t{i+1}", card_id="c1", amount=amounts[i], seconds=i, country="CO", ip_country="CO"))

        r = ev.evaluate(_txn(id="t6", card_id="c1", amount=10000, seconds=7, country="CO", ip_country="RU"))
        assert r["decision"] == "DECLINE"
        assert r["score"] == 70
        rules = {r2["rule"]: r2 for r2 in r["reasons"]}
        assert "velocity_limit_exceeded" in rules
        assert "country_mismatch" in rules

    def test_device_velocity_does_not_block_unrelated_device(self):
        ev = Evaluator()
        ev.evaluate(_txn(id="t1", card_id="c1", device_id="devA", amount=5000, seconds=0))
        ev.evaluate(_txn(id="t2", card_id="c2", device_id="devA", amount=5000, seconds=1))
        ev.evaluate(_txn(id="t3", card_id="c3", device_id="devA", amount=5000, seconds=2))

        r = ev.evaluate(_txn(id="t4", card_id="c1", device_id="devB", amount=5000, seconds=3))
        assert r["decision"] != "DECLINE"
