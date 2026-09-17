"""
Clase base para las reglas de scoring de SentinelPay.

Cada regla hereda de BaseRule e implementa _evaluate().
Si la regla esta deshabilitada, no se ejecuta.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.persistence.store import InMemoryStore


class RuleResult:
    """Resultado de una regla disparada."""

    def __init__(
        self,
        rule: str,
        weight: int,
        detail: str,
        decline: bool = False,
        block_card: bool = False,
        block_device: bool = False,
        block_duration: int = 120,
    ) -> None:
        self.rule = rule
        self.weight = weight
        self.detail = detail
        self.decline = decline
        self.block_card = block_card
        self.block_device = block_device
        self.block_duration = block_duration

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "weight": self.weight,
            "detail": self.detail,
        }

    def __repr__(self) -> str:
        return f"RuleResult(rule={self.rule!r}, weight={self.weight}, detail={self.detail!r})"


class BaseRule(ABC):
    """
    Clase base abstracta para todas las reglas.

    Args:
        name: nombre identificador de la regla.
        enabled: si la regla esta activa.
        weight: peso/puntaje que aporta la regla al score.
    """

    def __init__(self, name: str, enabled: bool = True, weight: int = 0) -> None:
        self.name = name
        self.enabled = enabled
        self.weight = weight

    @abstractmethod
    def _evaluate(self, transaction: Transaction, store: InMemoryStore) -> RuleResult | None:
        """
        Logica interna de la regla.

        Retorna RuleResult si la regla se dispara, None en caso contrario.
        """
        ...

    def evaluate(self, transaction: Transaction, store: InMemoryStore) -> RuleResult | None:
        """
        Evalua la regla contra una transaccion.

        Si la regla esta deshabilitada, retorna None.
        """
        if not self.enabled:
            return None
        return self._evaluate(transaction, store)
