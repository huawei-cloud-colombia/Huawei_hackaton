"""
Regla de velocity por dispositivo (Fase 2 - Card Testing).

Si `threshold` tarjetas diferentes usan el mismo device_id
en `window_seconds` segundos, sumar +weight al score
y marcar para DECLINE + blocklist.

Configuracion por defecto:
    threshold: 3 tarjetas distintas
    window_seconds: 30
    weight: 50
    block_duration: 120 segundos

Cuenta tarjetas distintas, no simplemente transacciones.
La regla se activa cuando distinct_cards >= threshold.
"""

from __future__ import annotations

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.base import BaseRule, RuleResult
from sentinelpay.persistence.store import InMemoryStore


class VelocityDeviceRule(BaseRule):
    """
    Regla de velocidad por dispositivo.

    Args:
        enabled: si la regla esta activa.
        weight: puntaje aportado al dispararse (default: 50).
        threshold: numero de tarjetas distintas que disparan la regla.
            Se dispara cuando distinct_cards >= threshold.
        window_seconds: tamano de la ventana en segundos.
        block_duration: duracion del bloqueo temporal en segundos.
    """

    def __init__(
        self,
        enabled: bool = True,
        weight: int = 50,
        threshold: int = 3,
        window_seconds: int = 30,
        block_duration: int = 120,
    ) -> None:
        super().__init__(name="device_velocity_exceeded", enabled=enabled, weight=weight)
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.block_duration = block_duration

    def _evaluate(self, transaction: Transaction, store: InMemoryStore) -> RuleResult | None:
        now = transaction.timestamp_utc

        window = store.velocity_tracker.get_device_window(
            transaction.device_id, now, self.window_seconds
        )
        distinct_cards = {card for _, card in window}

        if len(distinct_cards) >= self.threshold:
            timestamps = [t for t, _ in window]
            if len(timestamps) >= 2:
                time_span = (max(timestamps) - min(timestamps)).total_seconds()
            else:
                time_span = 0

            return RuleResult(
                rule=self.name,
                weight=self.weight,
                detail=(
                    f"{len(distinct_cards)} distinct cards in {int(time_span)}s "
                    f"(limit: {self.threshold} in {self.window_seconds}s)"
                ),
                decline=True,
                block_device=True,
                block_duration=self.block_duration,
            )
        return None
