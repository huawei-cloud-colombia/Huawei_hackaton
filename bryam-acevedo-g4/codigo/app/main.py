from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.engine import RiskEngine
from app.models import EvaluationResult, TransactionIn

app = FastAPI(title="SentinelPay Risk Engine")
engine = RiskEngine()

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/evaluate", response_model=EvaluationResult)
def evaluate(transaction: TransactionIn) -> dict[str, Any]:
    txn = transaction.model_dump()
    return engine.evaluate(txn)


@app.post("/evaluate/auto")
def evaluate_auto(transaction: dict[str, Any]) -> dict[str, Any]:
    """Igual que /evaluate pero autogenera `id` y `timestamp` si no vienen
    (usado por el formulario de la Fase 4 y por la simulación de ráfaga)."""
    transaction.setdefault("id", f"txn_{uuid.uuid4().hex[:8]}")
    transaction.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    txn_in = TransactionIn(**transaction)
    return engine.evaluate(txn_in.model_dump())


@app.get("/reports")
def list_reports() -> list[dict[str, Any]]:
    return engine.list_audit_reports()


@app.get("/reports/{transaction_id}")
def get_report(transaction_id: str) -> dict[str, Any]:
    report = engine.get_audit_report(transaction_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No hay reporte para esa transacción (no fue DECLINE).")
    return report


@app.post("/reset")
def reset() -> dict[str, str]:
    engine.reset()
    return {"status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
