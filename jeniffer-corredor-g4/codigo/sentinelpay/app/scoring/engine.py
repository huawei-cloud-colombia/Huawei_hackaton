"""
Motor de scoring de SentinelPay Risk Engine.

Evalua una transaccion contra todas las reglas configuradas,
acumula el score y genera la decision final.

Flujo de evaluacion (Fase 2):
    1. Validar transaccion (manejado por Evaluator).
    2. Verificar blocklist -> si bloqueada, DECLINE inmediato.
    3. Registrar en velocity tracker (antes de evaluar reglas).
    4. Evaluar todas las reglas (base + velocity).
    5. Si una regla senala DECLINE -> decision = DECLINE + blocklist.
    6. Sino -> decision normal (APPROVE / REVIEW / REJECT).
    7. Limpiar estado expirado.

Umbrales de decision (configurables):
    - DECLINE (velocity/blocklist) -> tiene prioridad
    - score >= reject_threshold -> REJECT
    - score > review_threshold  -> REVIEW
    - score == 0                -> APPROVE
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.base import BaseRule
from sentinelpay.persistence.store import InMemoryStore


class ScoringEngine:
    """
    Motor de scoring que aplica reglas a transacciones.

    Args:
        rules: lista de reglas a evaluar.
        store: almacen de estado en memoria.
        reject_threshold: score minimo para REJECT (default: 50).
        review_threshold: score minimo para REVIEW (default: 0).
    """

    def __init__(
        self,
        rules: list[BaseRule],
        store: InMemoryStore,
        reject_threshold: int = 50,
        review_threshold: int = 0,
    ) -> None:
        self.rules = rules
        self.store = store
        self.reject_threshold = reject_threshold
        self.review_threshold = review_threshold

    def evaluate(self, transaction: Transaction) -> dict[str, Any]:
        """
        Evalua una transaccion contra todas las reglas.

        Returns:
            dict con transaction_id, score, decision y reasons.
        """
        now = transaction.timestamp_utc

        # --- Paso 1: Verificar blocklist ---
        block_result = self._check_blocklist(transaction, now)
        if block_result is not None:
            self.store.record_result(block_result)
            return block_result

        # --- Paso 2: Registrar en velocity tracker ---
        self.store.velocity_tracker.record_card(transaction.card_id, now)
        self.store.velocity_tracker.record_device(
            transaction.device_id, transaction.card_id, now
        )

        # --- Paso 3: Evaluar reglas ---
        reasons: list[dict[str, Any]] = []
        score = 0
        decline = False
        block_card = False
        block_device = False
        block_duration = 120

        for rule in self.rules:
            result = rule.evaluate(transaction, self.store)
            if result is not None:
                reasons.append(result.to_dict())
                score += result.weight
                if result.decline:
                    decline = True
                if result.block_card:
                    block_card = True
                    block_duration = result.block_duration
                if result.block_device:
                    block_device = True
                    block_duration = result.block_duration

        # --- Paso 4: Registrar transaccion en store ---
        self.store.record_transaction(transaction)

        # --- Paso 5: Aplicar blocklist si corresponde ---
        if block_card:
            expiry = now + timedelta(seconds=block_duration)
            self.store.blocklist.block_card(transaction.card_id, expiry)
        if block_device:
            expiry = now + timedelta(seconds=block_duration)
            self.store.blocklist.block_device(transaction.device_id, expiry)

        # --- Paso 6: Determinar decision ---
        if decline:
            decision = "DECLINE"
        else:
            decision = self._make_decision(score)

        result = {
            "transaction_id": transaction.id,
            "score": score,
            "decision": decision,
            "reasons": reasons,
        }

        # --- Paso 7: Limpiar estado expirado ---
        self.store.velocity_tracker.cleanup(now)
        self.store.blocklist.cleanup(now)

        self.store.record_result(result)
        return result

    def _check_blocklist(
        self, transaction: Transaction, now: Any
    ) -> dict[str, Any] | None:
        """
        Verifica si la tarjeta o dispositivo estan bloqueados.

        Si estan bloqueados, retorna un resultado DECLINE inmediato.
        No ejecuta ninguna regla.
        """
        if self.store.blocklist.is_card_blocked(transaction.card_id, now):
            return {
                "transaction_id": transaction.id,
                "score": 0,
                "decision": "DECLINE",
                "reasons": [
                    {
                        "rule": "card_temporarily_blocked",
                        "weight": 0,
                        "detail": f"card_id={transaction.card_id}",
                    }
                ],
            }

        if self.store.blocklist.is_device_blocked(transaction.device_id, now):
            return {
                "transaction_id": transaction.id,
                "score": 0,
                "decision": "DECLINE",
                "reasons": [
                    {
                        "rule": "device_temporarily_blocked",
                        "weight": 0,
                        "detail": f"device_id={transaction.device_id}",
                    }
                ],
            }

        return None

    def _make_decision(self, score: int) -> str:
        if score >= self.reject_threshold:
            return "REJECT"
        if score > self.review_threshold:
            return "REVIEW"
        return "APPROVE"
