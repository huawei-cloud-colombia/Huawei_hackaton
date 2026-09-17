"""
API FastAPI - ATLAS Control Room (Fase 4).
Expone endpoints para triage, correlacion y interfaz grafica.
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .triage_engine import TriageEngine
from .correlation_engine import CorrelationEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Cargar configuracion
BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

app = FastAPI(title="ATLAS CLOUD // SIGNAL-80", version="1.0.0")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Motores
triage_engine = TriageEngine(CONFIG)
correlation_engine = CorrelationEngine(CONFIG)

# Estado en memoria
processed_tickets: List[Dict[str, Any]] = []
incident_groups: List[Dict[str, Any]] = []


class TicketRequest(BaseModel):
    ticket_id: str
    customer_id: str = ""
    created_at: str = ""
    region: str = ""
    text: str


class BatchRequest(BaseModel):
    tickets: List[Dict[str, Any]]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """ATLAS Control Room - Interfaz grafica."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "ATLAS CLOUD // SIGNAL-80", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/triage")
async def triage_ticket(ticket: TicketRequest):
    """Procesa un ticket individual.

    process_ticket() hace llamadas HTTP sincronas (httpx.Client) y puede
    dormir varios segundos en los reintentos con backoff. Se ejecuta en un
    threadpool para no bloquear el event loop de asyncio: sin esto, mientras
    se clasifica UN ticket con GLM real, el servidor entero (incluido
    /api/health) queda congelado.
    """
    result = await run_in_threadpool(triage_engine.process_ticket, ticket.model_dump())
    return result


@app.post("/api/triage/batch")
async def triage_batch(batch: BatchRequest):
    """Procesa un lote de tickets."""
    global processed_tickets, incident_groups
    results = await run_in_threadpool(triage_engine.process_batch, batch.tickets)

    # Guardar resultados
    processed_tickets = results

    # Correlacionar
    valid_results = [r for r in results if "error" not in r]
    groups = await run_in_threadpool(correlation_engine.correlate, valid_results)
    processed_tickets = correlation_engine.assign_groups_to_tickets(processed_tickets, groups)
    incident_groups = groups

    return {
        "processed": len(results),
        "results": results,
        "incident_groups": groups,
        "audit_log": triage_engine.get_audit_log()
    }


@app.post("/api/load-sample")
async def load_sample():
    """Carga y procesa el dataset de ejemplo."""
    global processed_tickets, incident_groups

    data_path = BASE_DIR.parent / "data" / "tickets_sample.json"
    with open(data_path, "r", encoding="utf-8") as f:
        tickets = json.load(f)

    results = await run_in_threadpool(triage_engine.process_batch, tickets)
    processed_tickets = results

    valid_results = [r for r in results if "error" not in r]
    groups = await run_in_threadpool(correlation_engine.correlate, valid_results)
    processed_tickets = correlation_engine.assign_groups_to_tickets(processed_tickets, groups)
    incident_groups = groups

    return {
        "processed": len(results),
        "results": results,
        "incident_groups": groups,
        "audit_log": triage_engine.get_audit_log()
    }


@app.get("/api/tickets")
async def get_tickets(
    priority: Optional[str] = None,
    category: Optional[str] = None,
    module: Optional[str] = None,
    region: Optional[str] = None,
    group: Optional[str] = None
):
    """Devuelve tickets procesados con filtros opcionales."""
    tickets = processed_tickets

    if priority:
        tickets = [t for t in tickets if t.get("priority") == priority]
    if category:
        tickets = [t for t in tickets if t.get("category") == category]
    if module:
        tickets = [t for t in tickets if module.lower() in t.get("product_or_module", "").lower()]
    if region:
        tickets = [t for t in tickets if region.lower() in t.get("region", "").lower()]
    if group:
        tickets = [t for t in tickets if t.get("incident_group_id") == group]

    # Ordenar por prioridad
    priority_order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    tickets = sorted(tickets, key=lambda t: priority_order.get(t.get("priority", "P4"), 4))

    return {"tickets": tickets, "count": len(tickets)}


@app.get("/api/ticket/{ticket_id}")
async def get_ticket(ticket_id: str):
    """Devuelve el detalle de un ticket."""
    for t in processed_tickets:
        if t.get("ticket_id") == ticket_id:
            return t
    raise HTTPException(status_code=404, detail="Ticket no encontrado")


@app.get("/api/incidents")
async def get_incidents():
    """Devuelve los grupos de incidentes."""
    return {"incidents": incident_groups, "count": len(incident_groups)}


@app.get("/api/incident/{incident_id}/brief")
async def get_incident_brief(incident_id: str):
    """Genera brief ejecutivo para un incidente mayor (Bono D)."""
    for g in incident_groups:
        if g.get("incident_group_id") == incident_id:
            brief = await run_in_threadpool(triage_engine.glm.generate_executive_brief, g)
            if brief:
                return brief
            raise HTTPException(status_code=500, detail="No se pudo generar el brief")
    raise HTTPException(status_code=404, detail="Incidente no encontrado")


@app.get("/api/audit")
async def get_audit():
    """Devuelve el log de auditoria."""
    return {"audit_log": triage_engine.get_audit_log()}


@app.get("/api/config")
async def get_config():
    """Devuelve la configuracion (sin secretos)."""
    safe_config = {k: v for k, v in CONFIG.items() if "key" not in k.lower()}
    safe_config["demo_mode"] = triage_engine.glm.demo_mode
    return safe_config


@app.post("/api/clear")
async def clear_state():
    """Limpia el estado en memoria."""
    global processed_tickets, incident_groups
    processed_tickets = []
    incident_groups = []
    triage_engine.audit_log = []
    return {"status": "cleared"}
