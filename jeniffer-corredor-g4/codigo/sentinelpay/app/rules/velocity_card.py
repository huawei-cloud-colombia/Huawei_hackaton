"""
Regla de velocity por tarjeta (Fase 2 - Card Testing).

Si mas de `threshold` transacciones de la misma tarjeta ocurren
en `window_seconds` segundos, sumar +weight al score
y marcar para DECLINE + blocklist.

Configuracion por defecto:
    threshold: 5 transacciones
    window_seconds: 10
    weight: 40
    block_duration: 120 segundos

La regla se activa cuando la transaccion actual hace que se supere el limite.
El conteo incluye la transaccion actual.
"""

from __future__ import annotations

from datetime import timedelta

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.base import BaseRule, RuleResult
from sentinelpay.persistence.store import InMemoryStore


class VelocityCardRule(BaseRule):
    """
    Regla de velocidad por tarjeta.

    Args:
        enabled: si la regla esta activa.
        weight: puntaje aportado al dispararse (default: 40).
        threshold: numero maximo de transacciones permitidas en la ventana.
            Se dispara cuando count > threshold.
        window_seconds: tamano de la ventana en segundos.
        block_duration: duracion del bloqueo temporal en segundos.
    """

    def __init__(
        self,
        enabled: bool = True,
        weight: int = 40,
        threshold: int = 5,
        window_seconds: int = 10,
        block_duration: int = 120,
    ) -> None:
        super().__init__(name="velocity_limit_exceeded", enabled=enabled, weight=weight)
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.block_duration = block_duration

    def _evaluate(self, transaction: Transaction, store: InMemoryStore) -> RuleResult | None:
        now = transaction.timestamp_utc

        window = store.velocity_tracker.get_card_window(
            transaction.card_id, now, self.window_seconds
        )
        count = len(window)

        if count > self.threshold:
            if len(window) >= 2:
                time_span = (max(window) - min(window)).total_seconds()
            else:
                time_span = 0

            return RuleResult(
                rule=self.name,
                weight=self.weight,
                detail=(
                    f"{count} txns in {int(time_span)}s "
                    f"(limit: {self.threshold} in {self.window_seconds}s)"
                ),
                decline=True,
                block_card=True,
                block_duration=self.block_duration,
            )
        return None
