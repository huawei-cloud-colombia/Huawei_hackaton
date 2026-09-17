"""
main.py — API FastAPI para NEXUS LIVE.

Endpoints:
  GET  /                    → Interfaz web
  GET  /api/seats           → Listar asientos
  GET  /api/seats/available → Asientos disponibles
  POST /api/reserve         → Crear HOLD (Idempotency-Key header)
  GET  /api/holds           → Listar reservas
  GET  /api/holds/{id}      → Consultar reserva
  POST /api/holds/{id}/release → Liberar reserva
  POST /api/confirm         → Confirmar compra
  POST /api/simulate/race  → Simular carrera
  GET  /api/audit           → Trazabilidad
  GET  /api/audit/export    → Exportar auditoría
  GET  /api/payment/status  → Estado circuit breaker
  POST /api/payment/force   → Forzar resultado de pago (demo)
  GET  /api/config          → Configuración actual
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Body
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import config
from models import ReserveRequest, ConfirmRequest, PaymentResult
from seat_lock import engine
from payment import payment_service
from audit import audit_log


# ─── Background task: expiración automática ──────────────────

async def expiration_loop():
    """Loop que expira HOLDs cada 1 segundo."""
    while True:
        try:
            engine.expire_holds()
        except Exception:
            pass
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(expiration_loop())
    yield
    task.cancel()


# ─── App ──────────────────────────────────────────────────────

app = FastAPI(
    title="NEXUS LIVE — Motor de Reservas",
    description="Reto 3: NEXUS LIVE // T-80",
    version="1.0.0",
    lifespan=lifespan,
)

# Servir archivos estáticos (interfaz)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# ─── CORS (para Angular frontend) ────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Endpoints de la interfaz ────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Sirve la interfaz web."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>NEXUS LIVE</h1><p>Interfaz no encontrada. Cree static/index.html</p>")


# ─── Endpoints de asientos ───────────────────────────────────

@app.get("/api/seats")
async def get_seats():
    return [s.model_dump(mode="json") for s in engine.get_all_seats()]


@app.get("/api/seats/available")
async def get_available_seats():
    return [s.model_dump(mode="json") for s in engine.get_available_seats()]


# ─── Endpoints de reservas ───────────────────────────────────

@app.post("/api/reserve")
async def reserve(
    request: ReserveRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    result = await engine.reserve(request, idempotency_key=idempotency_key)

    if result.get("success"):
        return result
    else:
        status_code = 409 if "CONFLICT" in result.get("error", "") else 400
        if result.get("error") == "SEAT_NOT_AVAILABLE":
            status_code = 409
        raise HTTPException(status_code=status_code, detail=result)


@app.get("/api/holds")
async def get_holds():
    return [h.to_info().model_dump(mode="json") for h in engine.get_all_holds()]


@app.get("/api/holds/{hold_id}")
async def get_hold(hold_id: str):
    hold = engine.get_hold(hold_id)
    if not hold:
        raise HTTPException(status_code=404, detail={"error": "HOLD_NOT_FOUND", "reason": f"hold {hold_id} not found"})
    info = hold.to_info()
    data = info.model_dump(mode="json")
    data["time_remaining"] = hold.time_remaining
    return data


@app.post("/api/holds/{hold_id}/release")
async def release_hold(hold_id: str):
    result = await engine.release_hold(hold_id)
    if result.get("success"):
        return result
    raise HTTPException(status_code=400, detail=result)


# ─── Endpoint de confirmación ────────────────────────────────

@app.post("/api/confirm")
async def confirm(request: ConfirmRequest):
    # 1. Verificar que el HOLD existe y está activo
    hold = engine.get_hold(request.hold_id)
    if not hold:
        raise HTTPException(status_code=404, detail={"error": "HOLD_NOT_FOUND", "reason": f"hold {request.hold_id} not found"})

    # 2. Llamar al proveedor de pagos (con circuit breaker)
    pay_result = await payment_service.authorize(request.payment_token, hold_id=request.hold_id)

    payment_result = PaymentResult(pay_result["result"])

    # 3. Confirmar o rechazar según resultado
    confirm_result = await engine.confirm_hold(request.hold_id, payment_result)

    # Agregar info del circuit breaker
    confirm_result["circuit_breaker"] = pay_result.get("circuit_breaker")

    if confirm_result.get("success"):
        return confirm_result
    else:
        # Si es error de negocio (no de pago), retornar 400
        if confirm_result.get("error") in ("HOLD_NOT_FOUND", "HOLD_ALREADY_CONFIRMED", "HOLD_NOT_ACTIVE", "HOLD_EXPIRED"):
            raise HTTPException(status_code=400, detail=confirm_result)
        return confirm_result


# ─── Simulación de carrera ───────────────────────────────────

@app.post("/api/simulate/race")
async def simulate_race(body: dict = Body(...)):
    seat_id = body.get("seat_id", "VIP-A-001")
    num_users = int(body.get("num_users", 20))
    result = await engine.simulate_race(seat_id, num_users)
    return result


# ─── Trazabilidad / Auditoría ────────────────────────────────

@app.get("/api/audit")
async def get_audit():
    events = audit_log.get_all()
    return [e.model_dump(mode="json") for e in events]


@app.get("/api/audit/{hold_id}")
async def get_audit_by_hold(hold_id: str):
    events = audit_log.get_by_hold(hold_id)
    return [e.model_dump(mode="json") for e in events]


@app.get("/api/audit/export")
async def export_audit():
    filepath = audit_log.export_json("audit_export.json")
    return {"message": "Audit exported", "filepath": filepath, "events": len(audit_log.get_all())}


# ─── Estado del circuit breaker ──────────────────────────────

@app.get("/api/payment/status")
async def payment_status():
    return payment_service.get_status()


@app.post("/api/payment/force")
async def payment_force(body: dict = Body(...)):
    result = body.get("result")
    if result:
        payment_service.force_result(PaymentResult(result))
        return {"message": f"Payment result forced to {result}"}
    else:
        payment_service.force_result(None)
        return {"message": "Forced result cleared"}


# ─── Configuración ───────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    return {
        "hold_ttl_seconds": config.hold_ttl_seconds,
        "max_seats_per_user": config.max_seats_per_user,
        "currency": config.currency,
        "default_event_id": config.default_event_id,
        "circuit_breaker": payment_service.get_status(),
        "payment_probs": {
            "approved": config.pay_prob_approved,
            "declined": config.pay_prob_declined,
            "error": config.pay_prob_error,
            "timeout": config.pay_prob_timeout,
        },
        "seat_sections": {
            k: {"prefix": v[0], "count": v[1], "price": v[2]}
            for k, v in config.seat_sections.items()
        },
    }


# ─── Reset (para demo) ───────────────────────────────────────

@app.post("/api/reset")
async def reset_system():
    """Reinicia el sistema completo (útil para demo)."""
    from seat_lock import SeatLockEngine
    global engine
    engine = SeatLockEngine()
    audit_log.clear()
    payment_service.cb = payment_service.cb.__class__(
        failure_threshold=config.cb_failure_threshold,
        recovery_timeout=config.cb_recovery_timeout,
    )
    return {"message": "System reset complete"}


# ─── Entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
