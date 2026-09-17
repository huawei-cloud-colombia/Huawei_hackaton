from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, settings
from .idempotency import IdempotencyStore
from .models import Hold, HoldStatus, Seat, SeatStatus, StatsResponse, Transition, iso
from .payment import CircuitBreaker, PaymentProvider
from .persistence import WriterWorker, init_db, load_catalog, query_transitions, seat_count, seed_db
from .service import BookingService
from .state import StateMachine

logger = logging.getLogger("nexus")


@dataclass
class NexusRuntime:
    cfg: Settings
    db_path: str
    state: StateMachine
    idem: IdempotencyStore
    queue: asyncio.Queue
    writer: WriterWorker
    service: BookingService
    provider: PaymentProvider
    cb: CircuitBreaker
    tasks: list[asyncio.Task]


RUNTIME: NexusRuntime | None = None


async def build_runtime(cfg: Settings = settings, db_path: str | None = None) -> NexusRuntime:
    path = db_path or cfg.db_path
    init_db(path)
    seats = load_catalog(cfg, path)
    if seat_count(path) == 0:
        seed_db(seats, path)
        seats = load_catalog(cfg, path)

    state = StateMachine(seats, cfg)
    idem = IdempotencyStore(cfg.idempotency_ttl_seconds)
    queue: asyncio.Queue = asyncio.Queue()
    writer = WriterWorker(queue, path, cfg)
    provider = PaymentProvider(cfg)
    cb = CircuitBreaker(cfg.cb_failure_threshold, cfg.cb_recovery_seconds)
    service = BookingService(state, idem, queue, provider, cb)

    rt = NexusRuntime(cfg=cfg, db_path=path, state=state, idem=idem, queue=queue, writer=writer, service=service, provider=provider, cb=cb, tasks=[])

    async def reaper():
        while True:
            try:
                cb.tick()
                events = await state.reap(time.time())
                for ev in events:
                    await queue.put(ev)
            except Exception:
                logger.exception("reaper error")
            await asyncio.sleep(cfg.reaper_interval_seconds)

    async def idem_cleanup():
        while True:
            await asyncio.sleep(cfg.idempotency_cleanup_interval_seconds)
            try:
                await idem.cleanup()
            except Exception:
                logger.exception("idem cleanup error")

    rt.tasks = [
        asyncio.create_task(writer.run(), name="writer"),
        asyncio.create_task(reaper(), name="reaper"),
        asyncio.create_task(idem_cleanup(), name="idem-cleanup"),
    ]
    return rt


async def shutdown_runtime(rt: NexusRuntime) -> None:
    for t in rt.tasks:
        if t.get_name() != "writer":
            t.cancel()
    await rt.writer.stop()
    for t in rt.tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global RUNTIME
    RUNTIME = await build_runtime()
    logger.info("NEXUS started: %d seats, ttl=%ss, shards=%d", len(RUNTIME.state.seats), settings.hold_ttl_seconds, settings.num_shards)
    yield
    if RUNTIME is not None:
        await shutdown_runtime(RUNTIME)


app = FastAPI(title="NEXUS Live", version="2.0.0", lifespan=lifespan)


def _rt(request: Request) -> NexusRuntime:
    return RUNTIME  # type: ignore[return-value]


@app.post("/holds")
async def post_hold(req: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    rt = _rt(req)
    body = await req.json()
    key = idempotency_key or f"auto-{uuid.uuid4()}"
    status, resp = await rt.service.create_hold(key, body["user_id"], body["event_id"], body["seat_ids"])
    return JSONResponse(status_code=status, content=resp)


@app.post("/checkout")
async def post_checkout(req: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    rt = _rt(req)
    body = await req.json()
    key = idempotency_key or f"auto-{uuid.uuid4()}"
    status, resp = await rt.service.checkout(key, body["hold_id"], body["user_id"], body.get("payment_token", ""))
    return JSONResponse(status_code=status, content=resp)


@app.post("/release")
async def post_release(req: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    rt = _rt(req)
    body = await req.json()
    key = idempotency_key or f"auto-{uuid.uuid4()}"
    status, resp = await rt.service.release(key, body["hold_id"], body["user_id"])
    return JSONResponse(status_code=status, content=resp)


@app.get("/seats/{seat_id}")
async def get_seat(seat_id: str, request: Request):
    seat = _rt(request).state.get_seat(seat_id)
    if seat is None:
        return JSONResponse(status_code=404, content={"detail": "seat not found"})
    return Seat(
        seat_id=seat.seat_id, event_id=_rt(request).cfg.event_id, section=seat.section,
        price=seat.price, currency=seat.currency, status=seat.status, held_by_hold_id=seat.held_by,
    )


@app.get("/holds/{hold_id}")
async def get_one_hold(hold_id: str, request: Request):
    h = _rt(request).state.holds.get(hold_id)
    if h is None:
        return JSONResponse(status_code=404, content={"detail": "hold not found"})
    status = h.status
    if status == HoldStatus.HELD and h.expires_at <= time.time():
        status = HoldStatus.EXPIRED
    return Hold(
        hold_id=h.hold_id, user_id=h.user_id, event_id=h.event_id, seat_ids=list(h.seat_ids),
        status=status, total=h.total, currency=h.currency, created_at=iso(h.created_at), expires_at=iso(h.expires_at),
    )


@app.get("/events/{event_id}/seats")
async def get_event_seats(event_id: str, request: Request, section: str | None = Query(default=None), limit: int = Query(default=1000, le=50000)):
    seats = _rt(request).state.list_seats(event_id, section)
    seats = seats[:limit]
    eid = _rt(request).cfg.event_id
    return [
        Seat(seat_id=s.seat_id, event_id=eid, section=s.section, price=s.price, currency=s.currency, status=s.status, held_by_hold_id=s.held_by)
        for s in seats
    ]


@app.get("/admin/stats", response_model=StatsResponse)
async def get_stats(request: Request):
    rt = _rt(request)
    c = rt.state.counts()
    return StatsResponse(
        total_seats=len(rt.state.seats),
        available=c["available"], held=c["held"], sold=c["sold"],
        active_holds=sum(1 for h in rt.state.holds.values() if h.status.value == "HELD"),
        writer_events_processed=rt.writer.stats.events_processed,
        writer_errors=rt.writer.stats.errors,
        writer_queue_depth=rt.queue.qsize(),
        idempotency_entries=rt.idem.size(),
        cb_state=rt.cb.state,
        pay_authorized=rt.provider.stats.authorized,
        pay_declined=rt.provider.stats.declined,
        pay_error=rt.provider.stats.error,
        pay_timeout=rt.provider.stats.timeout,
        pay_mode=rt.provider.mode,
    )


@app.get("/confirmations/{hold_id}")
async def get_confirmation(hold_id: str, request: Request):
    conf = _rt(request).service.get_confirmation(hold_id)
    if conf is None:
        return JSONResponse(status_code=404, content={"detail": "confirmation not found"})
    return conf


def _trace_to_transition(t: dict) -> Transition:
    return Transition(
        transition_id=t["transition_id"],
        hold_id=t["hold_id"],
        user_id=t["user_id"],
        seat_ids=t["seat_ids"],
        prev_status=t["prev_status"],
        new_status=t["new_status"],
        reason=t["reason"],
        timestamp=iso(t["timestamp"]),
    )


@app.get("/admin/traceability")
async def get_traceability(request: Request, hold_id: str | None = Query(default=None), limit: int = Query(default=200, le=5000)):
    trace = _rt(request).state.trace
    items = [t for t in trace if hold_id is None or t["hold_id"] == hold_id]
    items = items[-limit:] if hold_id is None else items
    return [_trace_to_transition(t).model_dump(mode="json") for t in items]


@app.get("/admin/traceability/db")
async def get_traceability_db(request: Request, hold_id: str | None = Query(default=None), limit: int = Query(default=200, le=5000)):
    rows = await asyncio.to_thread(query_transitions, _rt(request).db_path, hold_id, limit)
    for r in rows:
        r["timestamp"] = iso(r["timestamp"])
    return rows


@app.get("/holds/{hold_id}/trace")
async def get_hold_trace(hold_id: str, request: Request):
    trace = [t for t in _rt(request).state.trace if t["hold_id"] == hold_id]
    return [_trace_to_transition(t).model_dump(mode="json") for t in trace]


@app.post("/admin/payment/mode")
async def set_payment_mode(req: Request):
    body = await req.json()
    _rt(req).provider.set_mode(body["mode"])
    return {"mode": _rt(req).provider.mode}


@app.get("/admin/payment/stats")
async def payment_stats(request: Request):
    p = _rt(request).provider
    return {
        "mode": p.mode,
        "calls": p.stats.calls,
        "authorized": p.stats.authorized,
        "declined": p.stats.declined,
        "error": p.stats.error,
        "timeout": p.stats.timeout,
    }


@app.post("/admin/payment/reset")
async def payment_reset(request: Request):
    _rt(request).provider.reset()
    return {"ok": True}


@app.get("/admin/circuit-breaker")
async def cb_state(request: Request):
    cb = _rt(request).cb
    return {"state": cb.state, "failures": cb._failures, "threshold": cb.failure_threshold, "recovery_seconds": cb.recovery_seconds}


@app.post("/admin/circuit-breaker/reset")
async def cb_reset(request: Request):
    _rt(request).cb.reset()
    return {"state": _rt(request).cb.state}


@app.get("/health")
async def health():
    return {"status": "ok", "seats": len(settings.seat_sections)}


@app.get("/config")
async def get_config():
    return {
        "hold_ttl_seconds": settings.hold_ttl_seconds,
        "max_seats_per_user": settings.max_seats_per_user,
        "num_shards": settings.num_shards,
        "reaper_interval_seconds": settings.reaper_interval_seconds,
        "total_seats": sum(c for _, _, c, _, _ in settings.seat_sections),
    }


@app.get("/admin/bench")
async def bench(request: Request, cycles: int = Query(default=300, le=5000)):
    rt = _rt(request)
    lats: list[float] = []
    for i in range(cycles):
        sid = f"GEN-{20000 + i:04d}"
        user = f"bench-{i}"
        t0 = time.perf_counter()
        try:
            hold, events = await rt.state.create_hold(user, rt.cfg.event_id, [sid], time.time())
            for ev in events:
                await rt.queue.put(ev)
        except Exception:
            continue
        lats.append((time.perf_counter() - t0) * 1_000_000)
        try:
            await rt.state.release(hold.hold_id, user, time.time())
        except Exception:
            pass
    lats.sort()
    if not lats:
        return {"cycles": cycles, "p50_us": 0, "p99_us": 0, "p99_ms": 0}
    return {
        "cycles": len(lats),
        "p50_us": round(lats[len(lats) // 2], 1),
        "p99_us": round(lats[int(len(lats) * 0.99)], 1),
        "p99_ms": round(lats[int(len(lats) * 0.99)] / 1000, 3),
    }


@app.get("/")
async def root():
    return FileResponse("static/nexus.html")


@app.get("/ui")
async def ui():
    return FileResponse("static/nexus.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
