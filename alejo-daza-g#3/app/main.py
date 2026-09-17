from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .models import (
    ConfirmRequest,
    ConfirmResponse,
    HealthResponse,
    Hold,
    HoldRequest,
    RejectedResponse,
    Reason,
    Seat,
)
from .service import (
    SeatLockError,
    confirm_hold,
    create_hold,
    expire_holds,
    get_hold,
    get_seat,
    list_seats,
    release_hold,
)

logger = logging.getLogger("seatlock")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop = asyncio.Event()

    async def sweeper():
        while not stop.is_set():
            try:
                n = await asyncio.to_thread(expire_holds)
                if n:
                    logger.info("expired %d holds", n)
            except Exception:
                logger.exception("sweeper error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.sweeper_interval_seconds)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(sweeper())
    logger.info("SeatLock started (ttl=%ss, max_seats=%s)", settings.hold_ttl_seconds, settings.max_seats_per_user)
    yield
    stop.set()
    await task


app = FastAPI(title="SeatLock", version="1.0.0", lifespan=lifespan)


@app.exception_handler(SeatLockError)
async def seatlock_error_handler(request: Request, exc: SeatLockError):
    body = RejectedResponse(reason=exc.reason, detail=exc.detail, conflicting_seats=exc.conflicting_seats)
    status = 404 if exc.reason in (Reason.HOLD_NOT_FOUND,) else 409
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", hold_ttl_seconds=settings.hold_ttl_seconds, max_seats_per_user=settings.max_seats_per_user)


@app.get("/events/{event_id}/seats", response_model=list[Seat])
def get_event_seats(event_id: str):
    return list_seats(event_id)


@app.get("/seats/{seat_id}", response_model=Seat)
def get_one_seat(seat_id: str):
    seat = get_seat(seat_id)
    if seat is None:
        return JSONResponse(status_code=404, content={"detail": "seat not found"})
    return seat


@app.post("/holds", response_model=Hold, status_code=201)
def post_hold(req: HoldRequest):
    return create_hold(req.user_id, req.event_id, req.seat_ids)


@app.get("/holds/{hold_id}", response_model=Hold)
def get_one_hold(hold_id: str):
    hold = get_hold(hold_id)
    if hold is None:
        return JSONResponse(status_code=404, content={"detail": "hold not found"})
    return hold


@app.delete("/holds/{hold_id}", response_model=Hold)
def delete_hold(hold_id: str, user_id: str = Query(...)):
    return release_hold(hold_id, user_id)


@app.post("/holds/{hold_id}/confirm", response_model=ConfirmResponse)
def post_confirm(hold_id: str, req: ConfirmRequest):
    return confirm_hold(hold_id, req.user_id)


@app.post("/admin/expire")
def admin_expire():
    return {"expired": expire_holds()}


@app.get("/config")
def get_config():
    return {
        "hold_ttl_seconds": settings.hold_ttl_seconds,
        "max_seats_per_user": settings.max_seats_per_user,
        "sweeper_interval_seconds": settings.sweeper_interval_seconds,
    }


@app.get("/ui")
def ui_redirect():
    return RedirectResponse(url="/static/index.html")


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
