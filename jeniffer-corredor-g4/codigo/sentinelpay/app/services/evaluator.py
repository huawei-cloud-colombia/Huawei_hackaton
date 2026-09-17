"""
Servicio evaluador de SentinelPay Risk Engine.

Punto de entrada principal para evaluar transacciones.

Uso:
    from sentinelpay import evaluate

    result = evaluate({
        "id": "txn_00234",
        "card_id": "card_9F21",
        ...
    })

Para control manual (tests, etc.):
    from sentinelpay import Evaluator

    ev = Evaluator()
    result = ev.evaluate(txn_dict)
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from sentinelpay.app.config.settings import Settings
from sentinelpay.app.models.transaction import Transaction
from sentinelpay.app.rules.anomalous_amount import AnomalousAmountRule
from sentinelpay.app.rules.base import BaseRule
from sentinelpay.app.rules.country_mismatch import CountryMismatchRule
from sentinelpay.app.rules.unusual_hour import UnusualHourRule
from sentinelpay.app.rules.velocity_card import VelocityCardRule
from sentinelpay.app.rules.velocity_device import VelocityDeviceRule
from sentinelpay.app.scoring.engine import ScoringEngine
from sentinelpay.persistence.store import InMemoryStore


class Evaluator:
    """
    Orquestador del motor de riesgo.

    Construye las reglas, el motor de scoring y el almacen
    a partir de la configuracion.

    Args:
        config_path: ruta al archivo YAML de configuracion.
            Si es None, usa la default.
    """

    def __init__(self, config_path: str | None = None) -> None:
        self.settings = Settings(config_path)
        self.store = InMemoryStore()
        self.rules: list[BaseRule] = []
        self._build_rules()
        self._build_engine()

    def _build_rules(self) -> None:
        """Construye las reglas a partir de la configuracion."""
        rc = self.settings.rules_config

        am_cfg = rc.get("anomalous_amount", {})
        self.rules.append(
            AnomalousAmountRule(
                enabled=am_cfg.get("enabled", True),
                weight=am_cfg.get("weight", 25),
                multiplier=am_cfg.get("multiplier", 3.0),
            )
        )

        cm_cfg = rc.get("country_mismatch", {})
        self.rules.append(
            CountryMismatchRule(
                enabled=cm_cfg.get("enabled", True),
                weight=cm_cfg.get("weight", 30),
            )
        )

        uh_cfg = rc.get("unusual_hour", {})
        merchant_tz = uh_cfg.get("merchant_timezones")
        self.rules.append(
            UnusualHourRule(
                enabled=uh_cfg.get("enabled", True),
                weight=uh_cfg.get("weight", 10),
                start_hour=uh_cfg.get("start_hour", 1),
                end_hour=uh_cfg.get("end_hour", 5),
                default_timezone=uh_cfg.get("default_timezone", "UTC"),
                merchant_timezones=merchant_tz,
            )
        )

        vc_cfg = rc.get("velocity_card", {})
        self.rules.append(
            VelocityCardRule(
                enabled=vc_cfg.get("enabled", True),
                weight=vc_cfg.get("weight", 40),
                threshold=vc_cfg.get("threshold", 5),
                window_seconds=vc_cfg.get("window_seconds", 10),
                block_duration=vc_cfg.get("block_duration", 120),
            )
        )

        vd_cfg = rc.get("velocity_device", {})
        self.rules.append(
            VelocityDeviceRule(
                enabled=vd_cfg.get("enabled", True),
                weight=vd_cfg.get("weight", 50),
                threshold=vd_cfg.get("threshold", 3),
                window_seconds=vd_cfg.get("window_seconds", 30),
                block_duration=vd_cfg.get("block_duration", 120),
            )
        )

    def _build_engine(self) -> None:
        """Construye el motor de scoring."""
        self.engine = ScoringEngine(
            rules=self.rules,
            store=self.store,
            reject_threshold=self.settings.reject_threshold,
            review_threshold=self.settings.review_threshold,
        )

    def evaluate(self, transaction: Transaction | dict[str, Any]) -> dict[str, Any]:
        """
        Evalua una transaccion y retorna el resultado.

        Acepta un dict o un Transaction. Si la validacion falla,
        retorna un resultado con decision=ERROR sin tumbar el proceso.

        Returns:
            dict con transaction_id, score, decision, reasons.
            Si hay error de validacion, incluye 'errors'.
        """
        txn_id = "unknown"
        try:
            if isinstance(transaction, dict):
                txn_id = transaction.get("id", "unknown")
                transaction = Transaction(**transaction)
            else:
                txn_id = transaction.id
        except ValidationError as e:
            return {
                "transaction_id": txn_id,
                "score": 0,
                "decision": "ERROR",
                "reasons": [],
                "errors": e.errors(),
            }

        return self.engine.evaluate(transaction)

    def evaluate_batch(self, transactions: list[Transaction | dict[str, Any]]) -> list[dict[str, Any]]:
        """Evalua una lista de transacciones."""
        return [self.evaluate(t) for t in transactions]

    def reset(self) -> None:
        """Reinicia el estado del almacen."""
        self.store.clear()


_default_evaluator: Evaluator | None = None


def _get_default_evaluator() -> Evaluator:
    global _default_evaluator
    if _default_evaluator is None:
        _default_evaluator = Evaluator()
    return _default_evaluator


def evaluate(transaction: Transaction | dict[str, Any]) -> dict[str, Any]:
    """
    Evalua una transaccion usando el evaluador por defecto (singleton).

    Funcion de conveniencia para uso rapido.

    Args:
        transaction: dict o Transaction con los datos de la transaccion.

    Returns:
        dict con transaction_id, score, decision, reasons.
    """
    return _get_default_evaluator().evaluate(transaction)


def reset() -> None:
    """Reinicia el evaluador por defecto (limpia estado en memoria)."""
    global _default_evaluator
    if _default_evaluator is not None:
        _default_evaluator.reset()
