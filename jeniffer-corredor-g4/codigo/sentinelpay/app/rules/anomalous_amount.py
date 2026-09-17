"""
Regla 1 - Monto anomalo.

Si amount > multiplier x promedio historico de la tarjeta,
sumar +weight al score.

El promedio historico se mantiene en el InMemoryStore.
Si no hay historial para la tarjeta, la regla no se dispara.
"""

from __future__ import annotations

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.base import BaseRule, RuleResult
from sentinelpay.persistence.store import InMemoryStore


class AnomalousAmountRule(BaseRule):
    """
    Regla de monto anomalo.

    Args:
        enabled: si la regla esta activa.
        weight: puntaje aportado al dispararse (default: 25).
        multiplier: factor multiplicador del promedio historico (default: 3.0).
    """

    def __init__(
        self,
        enabled: bool = True,
        weight: int = 25,
        multiplier: float = 3.0,
    ) -> None:
        super().__init__(name="anomalous_amount", enabled=enabled, weight=weight)
        self.multiplier = multiplier

    def _evaluate(self, transaction: Transaction, store: InMemoryStore) -> RuleResult | None:
        avg = store.get_card_average(transaction.card_id)
        if avg is None or avg == 0:
            return None

        threshold = self.multiplier * avg
        if transaction.amount > threshold:
            return RuleResult(
                rule=self.name,
                weight=self.weight,
                detail=(
                    f"amount={transaction.amount}, "
                    f"threshold={self.multiplier}x avg={avg:.2f} ({threshold:.2f})"
                ),
            )
        return None
