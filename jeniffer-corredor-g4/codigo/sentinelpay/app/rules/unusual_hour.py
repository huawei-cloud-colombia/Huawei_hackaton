"""
Regla 3 - Hora inusual.

Si la transaccion ocurre entre 01:00 y 05:00 (hora local del comercio),
sumar +weight al score.

Determinacion de hora local:
    1. Si el merchant_id tiene una zona horaria configurada en
       merchant_timezones, se usa esa.
    2. Si no, se usa default_timezone (configurable, default: UTC).
    3. El timestamp de la transaccion (en UTC) se convierte a la zona
       horaria local del comercio.

El rango [01:00, 05:00) es inclusivo en el inicio y exclusivo en el fin.
Es decir: 01:00 dispara, 04:59 dispara, 05:00 NO dispara.
"""

from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.base import BaseRule, RuleResult
from sentinelpay.persistence.store import InMemoryStore


class UnusualHourRule(BaseRule):
    """
    Regla de hora inusual.

    Args:
        enabled: si la regla esta activa.
        weight: puntaje aportado al dispararse (default: 10).
        start_hour: hora de inicio del rango inusual (default: 1).
        end_hour: hora de fin del rango inusual (exclusive) (default: 5).
        default_timezone: zona horaria por defecto para comercios
            sin timezone explicito (default: UTC).
        merchant_timezones: mapeo merchant_id -> timezone string.
    """

    def __init__(
        self,
        enabled: bool = True,
        weight: int = 10,
        start_hour: int = 1,
        end_hour: int = 5,
        default_timezone: str = "UTC",
        merchant_timezones: dict[str, str] | None = None,
    ) -> None:
        super().__init__(name="unusual_hour", enabled=enabled, weight=weight)
        self.start_time = time(start_hour, 0)
        self.end_time = time(end_hour, 0)
        self.default_timezone = default_timezone
        self.merchant_timezones = merchant_timezones or {}

    def _get_timezone(self, merchant_id: str) -> ZoneInfo:
        """Obtiene la zona horaria del comercio o la default."""
        tz_name = self.merchant_timezones.get(merchant_id, self.default_timezone)
        return ZoneInfo(tz_name)

    def _evaluate(self, transaction: Transaction, store: InMemoryStore) -> RuleResult | None:
        tz = self._get_timezone(transaction.merchant_id)
        local_dt = transaction.timestamp_utc.astimezone(tz)
        local_time = local_dt.time()

        if self.start_time <= local_time < self.end_time:
            hh_mm = local_dt.strftime("%H:%M")
            return RuleResult(
                rule=self.name,
                weight=self.weight,
                detail=f"{hh_mm} local time",
            )
        return None
