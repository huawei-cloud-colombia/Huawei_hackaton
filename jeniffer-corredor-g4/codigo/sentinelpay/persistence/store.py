"""
Persistencia en memoria para SentinelPay Risk Engine.

Mantiene:
    - Promedio historico de montos por tarjeta.
    - Transacciones procesadas.
    - Resultados de evaluacion.
    - Velocity tracker (sliding window) para Fase 2.
    - Blocklist temporal para Fase 2.

Esta estructura esta disenada para ser reutilizada en la Fase 2
con ventanas deslizantes (sliding windows).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.persistence.blocklist import TemporalBlocklist
from sentinelpay.persistence.velocity_tracker import VelocityTracker


class InMemoryStore:
    """
    Almacen en memoria seguro para estado del motor de riesgo.

    Atributos:
        _card_amounts: mapeo card_id -> lista de montos historicos.
        _transactions: lista de transacciones procesadas.
        _results: lista de resultados de evaluacion.
        velocity_tracker: tracker de ventanas deslizantes (Fase 2).
        blocklist: blocklist temporal con expiracion (Fase 2).
    """

    def __init__(self) -> None:
        self._card_amounts: dict[str, list[float]] = defaultdict(list)
        self._transactions: list[Transaction] = []
        self._results: list[dict[str, Any]] = []
        self.velocity_tracker = VelocityTracker()
        self.blocklist = TemporalBlocklist()

    def get_card_average(self, card_id: str) -> float | None:
        """
        Retorna el promedio historico de montos para una tarjeta.

        Si no hay historial, retorna None.
        """
        amounts = self._card_amounts.get(card_id)
        if not amounts:
            return None
        return sum(amounts) / len(amounts)

    def get_card_count(self, card_id: str) -> int:
        """Retorna el numero de transacciones historicas de una tarjeta."""
        return len(self._card_amounts.get(card_id, []))

    def record_transaction(self, transaction: Transaction) -> None:
        """Registra una transaccion procesada en el almacen."""
        self._card_amounts[transaction.card_id].append(transaction.amount)
        self._transactions.append(transaction)

    def record_result(self, result: dict[str, Any]) -> None:
        """Registra un resultado de evaluacion."""
        self._results.append(result)

    def get_transactions(self) -> list[Transaction]:
        """Retorna una copia de las transacciones procesadas."""
        return list(self._transactions)

    def get_results(self) -> list[dict[str, Any]]:
        """Retorna una copia de los resultados."""
        return list(self._results)

    def get_card_amounts(self, card_id: str) -> list[float]:
        """Retorna una copia de los montos historicos de una tarjeta."""
        return list(self._card_amounts.get(card_id, []))

    def clear(self) -> None:
        """Limpia todo el estado del almacen."""
        self._card_amounts.clear()
        self._transactions.clear()
        self._results.clear()
        self.velocity_tracker.clear()
        self.blocklist.clear()
