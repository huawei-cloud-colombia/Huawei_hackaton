"""
NEXUS LIVE - API FastAPI + NEXUS Control Room.

Endpoints:
  GET  /                    → Interfaz web (NEXUS Control Room)
  GET  /api/seats           → Mapa de asientos
  POST /api/reserve         → Crear HOLD
  GET  /api/holds/{id}      → Consultar HOLD
  POST /api/confirm         → Confirmar compra
  POST /api/release/{id}    → Liberar HOLD
  POST /api/race            → Simular carrera concurrente
  GET  /api/trace/{id}      → Trazabilidad de un HOLD
  GET  /api/trace           → Trazabilidad completa
  GET  /api/circuit-breaker → Estado del circuit breaker
  POST /api/circuit-breaker/reset → Resetear circuit breaker
  GET  /api/waitlist        → Estado de la sala de espera
  POST /api/waitlist/join   → Unirse a la sala de espera
  POST /api/waitlist/leave  → Abandonar la sala de espera
  POST /api/explain/{id}    → Explicación operacional con GLM 5.2 (Bono D)
  POST /api/expire          → Forzar expiración de HOLDs
  POST /api/reset           → Resetear todo el sistema
"""
from __future__ import annotations

import concurrent.futures
import json
import os
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .circuit_breaker import CircuitBreaker
from .checkout import CheckoutService
from .glm_explainer import OperationsExplainer
from .payment_provider import MockPaymentProvider
from .schemas import Seat, SeatStatus
from .seatlock import SeatLockEngine
from .waitlist import FairWaitlist

# ── Init ────────────────────────────────────────────────

app = FastAPI(title="NEXUS LIVE", version="1.0.0")

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

engine = SeatLockEngine(hold_ttl_seconds=120, max_seats_per_user=6)
payment_provider = MockPaymentProvider(seed=42)
circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=15.0)
checkout = CheckoutService(engine, payment_provider, circuit_breaker)
waitlist = FairWaitlist(entry_timeout_seconds=60)
explainer = OperationsExplainer()


def _init_seats() -> None:
    """Inicializar asientos del evento aurora-bogota-2026."""
    seats = []
    # VIP
    for i in range(1, 11):
        seats.append(Seat(seat_id=f"VIP-A-{i:03d}", section="VIP", price=500000, currency="COP"))
    # PLATEA
    for i in range(1, 21):
        seats.append(Seat(seat_id=f"PLAT-B-{i:03d}", section="PLATEA", price=250000, currency="COP"))
    # GENERAL
    for i in range(1, 31):
        seats.append(Seat(seat_id=f"GEN-C-{i:03d}", section="GENERAL", price=80000, currency="COP"))
    engine.add_seats(seats)


_init_seats()


# ── Web UI ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Seats ──────────────────────────────────────────────

@app.get("/api/seats")
async def get_seats():
    return {"seats": engine.get_seat_map()}


@app.get("/api/seats/available")
async def get_available_seats():
    return {"seats": [s.model_dump() for s in engine.get_available_seats()]}


# ── Reserve ────────────────────────────────────────────

@app.post("/api/reserve")
async def reserve(
    body: dict,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    result = engine.reserve(
        user_id=body.get("user_id", ""),
        event_id=body.get("event_id", "aurora-bogota-2026"),
        seat_ids=body.get("seat_ids", []),
        idempotency_key=idempotency_key,
    )
    return result


# ── Holds ──────────────────────────────────────────────

@app.get("/api/holds/{hold_id}")
async def get_hold(hold_id: str):
    hold = engine.get_hold(hold_id)
    if not hold:
        return JSONResponse(status_code=404, content={"ok": False, "error": "HOLD_NOT_FOUND"})
    return {
        "ok": True,
        "hold_id": hold.hold_id,
        "user_id": hold.user_id,
        "event_id": hold.event_id,
        "seat_ids": hold.seat_ids,
        "total_price": hold.total_price,
        "currency": hold.currency,
        "status": hold.status.value,
        "remaining_seconds": hold.remaining_seconds(),
        "created_at": hold.created_at,
        "expires_at": hold.expires_at,
        "confirmed_at": hold.confirmed_at,
    }


@app.get("/api/holds")
async def get_all_holds():
    holds = engine.get_all_holds()
    return {
        "holds": [
            {
                "hold_id": h.hold_id,
                "user_id": h.user_id,
                "seat_ids": h.seat_ids,
                "total_price": h.total_price,
                "status": h.status.value,
                "remaining_seconds": h.remaining_seconds(),
            }
            for h in holds
        ]
    }


# ── Confirm ────────────────────────────────────────────

@app.post("/api/confirm")
async def confirm(body: dict):
    result = checkout.confirm(
        hold_id=body.get("hold_id", ""),
        payment_token=body.get("payment_token", ""),
        payment_idempotency_key=body.get("payment_idempotency_key"),
    )
    return result


# ── Release ────────────────────────────────────────────

@app.post("/api/release/{hold_id}")
async def release(hold_id: str):
    return engine.release_hold(hold_id)


# ── Race Simulation ────────────────────────────────────

@app.post("/api/race")
async def simulate_race(body: dict):
    """
    Simular una carrera: N usuarios intentan reservar el mismo asiento.
    """
    n = body.get("concurrent_users", 20)
    seat_id = body.get("seat_id", "VIP-A-001")
    event_id = body.get("event_id", "aurora-bogota-2026")

    # Asegurar que el asiento esté disponible
    seat = engine.get_seat(seat_id)
    if not seat:
        return {"ok": False, "error": "SEAT_NOT_FOUND"}
    if seat.status != SeatStatus.AVAILABLE:
        return {
            "ok": False,
            "error": "SEAT_NOT_AVAILABLE",
            "message": f"Asiento {seat_id} no está disponible (estado: {seat.status.value})",
        }

    results = []
    winners = 0
    rejected = 0

    def attempt(user_num: int) -> dict:
        uid = f"race_user_{user_num:04d}"
        r = engine.reserve(
            user_id=uid,
            event_id=event_id,
            seat_ids=[seat_id],
            idempotency_key=f"race-{seat_id}-{user_num:04d}",
        )
        return r

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(n, 100)) as executor:
        futures = {executor.submit(attempt, i): i for i in range(1, n + 1)}
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            if r.get("ok"):
                winners += 1
            else:
                rejected += 1
            results.append(r)

    # Contar overselling: asientos SOLD o HELD por más de un hold
    overselling = max(0, winners - 1)

    return {
        "ok": True,
        "total_requests": n,
        "winners": winners,
        "rejected": rejected,
        "overselling": overselling,
        "seat_id": seat_id,
        "results": results,
    }


# ── Trace ──────────────────────────────────────────────

@app.get("/api/trace")
async def get_trace():
    events = engine.get_trace()
    return {"events": [e.model_dump() for e in events]}


@app.get("/api/trace/{hold_id}")
async def get_trace_for_hold(hold_id: str):
    events = engine.get_trace_for_hold(hold_id)
    return {"hold_id": hold_id, "events": [e.model_dump() for e in events]}


# ── Circuit Breaker ────────────────────────────────────

@app.get("/api/circuit-breaker")
async def get_cb():
    return checkout.get_circuit_breaker_info()


@app.post("/api/circuit-breaker/reset")
async def reset_cb():
    circuit_breaker.force_closed()
    return {"ok": True, "message": "Circuit breaker reseteado a CLOSED"}


@app.post("/api/circuit-breaker/force-open")
async def force_open_cb():
    circuit_breaker.force_open()
    return {"ok": True, "message": "Circuit breaker forzado a OPEN"}


# ── Waitlist (Bono A) ──────────────────────────────────

@app.get("/api/waitlist")
async def get_waitlist():
    return {"queue": waitlist.get_queue(), "size": waitlist.size()}


@app.post("/api/waitlist/join")
async def join_waitlist(body: dict):
    return waitlist.join(
        user_id=body.get("user_id", ""),
        event_id=body.get("event_id", "aurora-bogota-2026"),
        seat_ids=body.get("seat_ids", []),
    )


@app.post("/api/waitlist/leave")
async def leave_waitlist(body: dict):
    return waitlist.leave(
        user_id=body.get("user_id", ""),
        event_id=body.get("event_id", "aurora-bogota-2026"),
    )


# ── Operations Explainer (Bono D) ──────────────────────

@app.post("/api/explain/{hold_id}")
async def explain_hold(hold_id: str):
    hold = engine.get_hold(hold_id)
    hold_info = None
    if hold:
        hold_info = {
            "status": hold.status.value,
            "user_id": hold.user_id,
            "seat_ids": hold.seat_ids,
            "total_price": hold.total_price,
            "currency": hold.currency,
        }
    trace_events = engine.get_trace_for_hold(hold_id)
    result = explainer.explain_hold_history(hold_id, trace_events, hold_info)
    return result


# ── Expiration ────────────────────────────────────────

@app.post("/api/expire")
async def expire_holds():
    count = engine.expire_now()
    return {"ok": True, "expired": count}


# ── Reset ──────────────────────────────────────────────

@app.post("/api/reset")
async def reset_system():
    engine.reset()
    checkout.reset()
    waitlist.reset()
    circuit_breaker.force_closed()
    payment_provider.reset()
    _init_seats()
    return {"ok": True, "message": "Sistema reseteado"}


# ── Payment Provider Control ───────────────────────────

@app.post("/api/payment/force")
async def force_payment(body: dict):
    result = body.get("result", "").upper()
    from .schemas import PaymentResult
    try:
        pr = PaymentResult(result)
    except ValueError:
        return {"ok": False, "error": "Invalid result"}
    payment_provider.force_result(pr)
    return {"ok": True, "forced_result": result}


@app.get("/api/payment/info")
async def payment_info():
    return {
        "call_count": payment_provider.get_call_count(),
        "circuit_breaker": checkout.get_circuit_breaker_info(),
    }
