"""Carga y utilidades de configuracion.

Todas las reglas y umbrales del motor (activar/desactivar reglas, ventanas de
tiempo, umbrales de contencion, parametros del circuit breaker, etc.) viven en
``config.json`` para poder ajustarse sin tocar codigo, tal como pide la Fase 1
del reto ("cada regla/parametro debe poder activarse/desactivarse y ajustarse").
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def load_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_config(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Combina ``overrides`` sobre ``base`` recursivamente (sin mutar ninguno).

    Se usa principalmente en pruebas, para partir de la configuracion real del
    proyecto y sobreescribir solo un par de campos (p. ej. ventanas de tiempo
    mas cortas para que las pruebas corran rapido).
    """
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
