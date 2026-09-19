"""FlowMatch Assignment Engine - API (FastAPI).

Expone el motor de asignacion como servicio HTTP y sirve la interfaz grafica
de verificacion de la Fase 4 (formulario + simulador de rafaga) en ``/``.

Para correrlo: ``uvicorn app.main:app --reload`` desde ``codigo/`` (ver
README.md en la raiz del proyecto para instrucciones completas).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .config import load_config
from .engine import FlowMatchEngine
from .schemas import AssignmentResult, BatchAssignIn, BurstSimulateIn, CourierIn, OrderIn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("flowmatch")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"

app = FastAPI(
    title="FlowMatch Assignment Engine",
    description="Motor de asignacion de pedidos a repartidores en tiempo real (Reto Hackathon Huawei).",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

config = load_config(BASE_DIR / "config.json")
engine = FlowMatchEngine(config)


def _seed_default_couriers() -> None:
    sample_path = DATA_DIR / "couriers_sample.json"
    if sample_path.exists():
        couriers = json.loads(sample_path.read_text(encoding="utf-8"))
        engine.reset_couriers(couriers)
        logger.info("Estado inicial de repartidores cargado desde %s (%d repartidores).", sample_path, len(couriers))
    else:
        logger.warning("No se encontro %s; el motor arranca sin repartidores.", sample_path)


_seed_default_couriers()


# ----------------------------------------------------------------------
# Interfaz grafica (Fase 4)
# ----------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "config": config})


# ----------------------------------------------------------------------
# Salud / estado
# ----------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "surge": engine.surge_status()}


@app.get("/state")
def get_state():
    now = time.time()
    return {
        "couriers": engine.store.snapshot(),
        "queue_length": len(engine.queue_snapshot()),
        "surge": engine.surge_status(now),
        "pricing_circuit_state": engine.pricing.breaker.state.value,
    }


@app.get("/couriers")
def get_couriers():
    return engine.store.snapshot()


@app.post("/couriers/reset")
def reset_couriers(couriers: List[CourierIn]):
    engine.reset_couriers([c.model_dump() for c in couriers])
    return {"status": "reset", "count": len(couriers)}


@app.get("/queue")
def get_queue():
    return engine.queue_snapshot()


@app.get("/reports/rejections")
def get_rejection_reports(limit: int = 20):
    return engine.recent_rejection_reports(limit)


# ----------------------------------------------------------------------
# Nucleo: asignacion
# ----------------------------------------------------------------------
@app.post("/assign", response_model=AssignmentResult)
def assign(order: OrderIn):
    result = engine.assign_single(order.model_dump())
    return result


@app.post("/assign/batch", response_model=List[AssignmentResult])
def assign_batch(payload: BatchAssignIn):
    results = engine.assign_batch([o.model_dump() for o in payload.orders])
    return results


@app.post("/simulate-burst", response_model=List[AssignmentResult])
def simulate_burst(payload: BurstSimulateIn):
    return engine.simulate_burst(payload.model_dump())
