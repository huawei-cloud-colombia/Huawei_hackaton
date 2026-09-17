"""
Ingesta de datos para SentinelPay Risk Engine.

Carga transacciones desde archivos JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sentinelpay.app.models.transaction import Transaction


def load_transactions_from_json(file_path: str | Path) -> list[Transaction]:
    """
    Carga transacciones validas desde un archivo JSON.

    El archivo debe contener una lista de objetos de transaccion.
    Las transacciones invalidas se omiten con un warning.

    Returns:
        Lista de objetos Transaction validos.
    """
    path = Path(file_path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Se esperaba una lista de transacciones, se obtuvo: {type(data)}")

    transactions: list[Transaction] = []
    for i, item in enumerate(data):
        try:
            txn = Transaction(**item)
            transactions.append(txn)
        except ValidationError as e:
            print(f"[WARNING] Transaccion #{i} invalida en {path.name}: {e}")

    return transactions


def load_transactions_from_dicts(dicts: list[dict[str, Any]]) -> list[Transaction]:
    """
    Carga transacciones desde una lista de diccionarios.

    Las transacciones invalidas se omiten.

    Returns:
        Lista de objetos Transaction validos.
    """
    transactions: list[Transaction] = []
    for i, item in enumerate(dicts):
        try:
            txn = Transaction(**item)
            transactions.append(txn)
        except ValidationError as e:
            print(f"[WARNING] Transaccion #{i} invalida: {e}")

    return transactions
