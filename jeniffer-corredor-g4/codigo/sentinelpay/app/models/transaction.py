"""
Modelo de transaccion financiera con validacion via Pydantic v2.

Campos obligatorios:
    - id: identificador unico de la transaccion
    - card_id: identificador de la tarjeta
    - merchant_id: identificador del comercio
    - amount: monto de la transaccion (debe ser > 0)
    - currency: codigo de moneda (ej. COP, USD)
    - country: pais de la tarjeta (ej. CO)
    - ip_country: pais desde donde se realiza la transaccion por IP
    - device_id: identificador del dispositivo
    - ip: direccion IP desde donde se realiza la transaccion
    - timestamp: fecha y hora de la transaccion (ISO 8601)
"""

from __future__ import annotations

import ipaddress
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class Transaction(BaseModel):
    """Representa una transaccion financiera validada."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    card_id: str
    merchant_id: str
    amount: float
    currency: str
    country: str
    ip_country: str
    device_id: str
    ip: str
    timestamp: datetime

    @field_validator("id", "card_id", "merchant_id", "device_id")
    @classmethod
    def identifier_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("el identificador no puede estar vacio")
        return v

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("el monto debe ser mayor a cero")
        return v

    @field_validator("currency", "country", "ip_country")
    @classmethod
    def string_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("el campo no puede estar vacio")
        return v

    @field_validator("ip")
    @classmethod
    def valid_ip_address(cls, v: str) -> str:
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"direccion IP invalida: {v}")
        return v

    @field_validator("currency")
    @classmethod
    def currency_format(cls, v: str) -> str:
        if len(v) != 3:
            raise ValueError(f"codigo de moneda debe tener 3 caracteres: {v}")
        return v.upper()

    @field_validator("country", "ip_country")
    @classmethod
    def country_code_format(cls, v: str) -> str:
        if len(v) != 2:
            raise ValueError(f"codigo de pais debe tener 2 caracteres: {v}")
        return v.upper()

    @property
    def hour_utc(self) -> int:
        """Hora UTC de la transaccion."""
        return self.timestamp.astimezone().hour

    @property
    def timestamp_utc(self) -> datetime:
        """Timestamp convertido a UTC."""
        return self.timestamp.astimezone()
