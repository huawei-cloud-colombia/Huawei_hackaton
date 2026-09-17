"""
Regla 2 - Pais diferente.

Si country != ip_country, sumar +weight al score.
Compara el pais de la tarjeta con el pais detectado por IP.
"""

from __future__ import annotations

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.base import BaseRule, RuleResult
from sentinelpay.persistence.store import InMemoryStore


class CountryMismatchRule(BaseRule):
    """
    Regla de discrepancia de pais.

    Args:
        enabled: si la regla esta activa.
        weight: puntaje aportado al dispararse (default: 30).
    """

    def __init__(self, enabled: bool = True, weight: int = 30) -> None:
        super().__init__(name="country_mismatch", enabled=enabled, weight=weight)

    def _evaluate(self, transaction: Transaction, store: InMemoryStore) -> RuleResult | None:
        if transaction.country != transaction.ip_country:
            return RuleResult(
                rule=self.name,
                weight=self.weight,
                detail=f"card_country={transaction.country}, ip_country={transaction.ip_country}",
            )
        return None
