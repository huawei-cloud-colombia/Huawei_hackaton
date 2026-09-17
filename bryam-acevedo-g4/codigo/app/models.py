from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TransactionIn(BaseModel):
    id: str
    card_id: str
    merchant_id: str
    amount: float = Field(gt=0)
    currency: str
    country: str
    ip_country: str
    device_id: str
    ip: str
    timestamp: datetime


class Reason(BaseModel):
    rule: str
    weight: int
    detail: str


class EvaluationResult(BaseModel):
    transaction_id: str
    score: int
    decision: Literal["APPROVE", "REVIEW", "DECLINE"]
    reasons: list[Reason]
    bank_auth_status: str


class BurstRequest(BaseModel):
    """Utilidad para la Fase 4: dispara N transacciones seguidas con la misma tarjeta."""

    card_id: str
    merchant_id: str
    device_id: str
    ip: str
    country: str
    ip_country: str
    currency: str = "COP"
    amount: float = 10000
    count: int = 6
