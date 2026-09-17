"""Configuración de reglas del motor de riesgo.

Todas las reglas se pueden activar/desactivar y su peso es configurable,
ya sea editando este archivo, pasando un dict al construir RiskEngine,
o cargando un JSON externo con `load_config_from_file`.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "rules": {
        "amount_anomaly": {
            "enabled": True,
            "weight": 25,
            "multiplier": 3,  # dispara si amount > multiplier * promedio histórico
        },
        "country_mismatch": {
            "enabled": True,
            "weight": 30,
        },
        "unusual_hour": {
            "enabled": True,
            "weight": 10,
            "start_hour": 1,
            "end_hour": 5,  # [start_hour, end_hour) en hora local del comercio
        },
        "velocity_card": {
            "enabled": True,
            "weight": 40,
            "max_count": 5,
            "window_seconds": 10,
            "hard_decline": True,
        },
        "velocity_device": {
            "enabled": True,
            "weight": 50,
            "max_distinct_cards": 3,
            "window_seconds": 30,
            "hard_decline": True,
        },
        "collusion_graph": {
            "enabled": True,
            "weight": 20,
            "max_distinct_cards": 4,
            "window_seconds": 120,
            "hard_decline": False,
        },
    },
    "blocklist": {
        "block_duration_seconds": 120,
    },
    "thresholds": {
        "approve_below": 40,
        "decline_at_or_above": 75,
    },
    "bank_auth": {
        "failure_probability": 0.3,
        "simulated_latency_seconds": 0.15,
        "timeout_threshold_seconds": 2.0,
    },
    "circuit_breaker": {
        "failure_threshold": 3,
        "open_duration_seconds": 15,
    },
}


def load_config_from_file(path: str | Path) -> dict[str, Any]:
    """Carga un JSON de configuración y lo mezcla (merge superficial por sección) sobre DEFAULT_CONFIG."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    merged = copy.deepcopy(DEFAULT_CONFIG)
    for section, values in data.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            for key, val in values.items():
                if isinstance(val, dict) and isinstance(merged[section].get(key), dict):
                    merged[section][key].update(val)
                else:
                    merged[section][key] = val
        else:
            merged[section] = values
    return merged
