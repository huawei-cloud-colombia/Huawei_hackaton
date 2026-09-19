"""Fixtures compartidas para el test suite del FlowMatch Assignment Engine."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config import load_config, merge_config
from app.engine import FlowMatchEngine

APP_DIR = Path(__file__).resolve().parent.parent / "app"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Epoch de referencia para el timestamp *por defecto* de los pedidos de
# prueba. Se deja deliberadamente en el epoch (0.0) en vez de una fecha real:
# las pruebas de Fase 2/3 simulan el paso del tiempo con valores de `now`
# arbitrarios (1000.0, 2_000_000.0, etc.) que representan "segundos desde que
# arranco la prueba", no una fecha de calendario. Con el timestamp del
# pedido fijo en el epoch, siempre queda en el pasado respecto a cualquier
# `now` positivo usado en las pruebas, sin disparar la validacion de
# "timestamp en el futuro" (que si se prueba explicitamente, con su propio
# timestamp, en test_bono_d_edge_cases.py).
BASE_NOW = 0.0

BASE_CONFIG = load_config(APP_DIR / "config.json")

# Config "rapida" para pruebas: latencia de pricing casi nula y sin fallos
# aleatorios por defecto, para que las pruebas sean deterministas y veloces.
# Los tests de Fase 3 sobreescriben failure_probability puntualmente.
FAST_PRICING_OVERRIDES = {
    "pricing": {
        "call_latency_ms_min": 0,
        "call_latency_ms_max": 1,
        "timeout_seconds": 5.0,
        "slow_call_probability": 0.0,
        "failure_probability": 0.0,
    }
}


def fast_config(overrides: dict | None = None) -> dict:
    cfg = merge_config(BASE_CONFIG, FAST_PRICING_OVERRIDES)
    if overrides:
        cfg = merge_config(cfg, overrides)
    return cfg


def load_sample_couriers() -> list[dict]:
    return json.loads((DATA_DIR / "couriers_sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_couriers() -> list[dict]:
    return load_sample_couriers()


@pytest.fixture
def engine_factory():
    """Devuelve una fabrica de motores con config configurable, ya sembrados
    con un estado de repartidores dado (o el sample por defecto)."""

    def _make(config_overrides: dict | None = None, couriers: list[dict] | None = None) -> FlowMatchEngine:
        cfg = fast_config(config_overrides)
        eng = FlowMatchEngine(cfg)
        eng.reset_couriers(couriers if couriers is not None else load_sample_couriers())
        return eng

    return _make


def make_order(
    order_id: str,
    pickup_zone: str = "centro",
    distance_km: float = 3.2,
    priority: str = "normal",
    timestamp: str | None = None,
    couriers: list[dict] | None = None,
) -> dict:
    if timestamp is None:
        timestamp = datetime.fromtimestamp(BASE_NOW, tz=timezone.utc).isoformat()
    order = {
        "order_id": order_id,
        "timestamp": timestamp,
        "pickup_zone": pickup_zone,
        "distance_km": distance_km,
        "priority": priority,
    }
    if couriers is not None:
        order["couriers"] = couriers
    return order
