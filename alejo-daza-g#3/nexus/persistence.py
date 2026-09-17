from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass

from .config import Settings, settings
from .models import Event, EventType, SeatStatus
from .state import SeatRuntime, build_catalog

SCHEMA = """
CREATE TABLE IF NOT EXISTS seats (
    seat_id          TEXT PRIMARY KEY,
    section          TEXT NOT NULL,
    price            INTEGER NOT NULL,
    currency         TEXT NOT NULL,
    status           TEXT NOT NULL,
    held_by_hold_id  TEXT
);
CREATE TABLE IF NOT EXISTS holds (
    hold_id    TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    status     TEXT NOT NULL,
    total      INTEGER NOT NULL,
    currency   TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS hold_seats (
    hold_id  TEXT NOT NULL,
    seat_id  TEXT NOT NULL,
    PRIMARY KEY (hold_id, seat_id)
);
CREATE INDEX IF NOT EXISTS idx_seats_status ON seats(status);
CREATE TABLE IF NOT EXISTS transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hold_id     TEXT,
    user_id     TEXT,
    seat_ids    TEXT,
    prev_status TEXT,
    new_status  TEXT,
    reason      TEXT,
    timestamp   REAL
);
CREATE INDEX IF NOT EXISTS idx_trans_hold ON transitions(hold_id);
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str = settings.db_path) -> None:
    conn = _connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def load_catalog(cfg: Settings = settings, db_path: str = settings.db_path) -> dict[str, SeatRuntime]:
    seats = build_catalog(cfg)
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "SELECT seat_id, status FROM seats WHERE status='SOLD'"
        )
        sold = {row["seat_id"] for row in cur.fetchall()}
    finally:
        conn.close()
    for sid in sold:
        if sid in seats:
            seats[sid].status = SeatStatus.SOLD
    return seats


def seed_db(seats: dict[str, SeatRuntime], db_path: str = settings.db_path) -> None:
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        conn.executemany(
            "INSERT OR IGNORE INTO seats (seat_id, section, price, currency, status, held_by_hold_id) "
            "VALUES (?, ?, ?, ?, 'AVAILABLE', NULL)",
            [(s.seat_id, s.section, s.price, s.currency) for s in seats.values()],
        )
        conn.execute("COMMIT;")
    finally:
        conn.close()


def seat_count(db_path: str = settings.db_path) -> int:
    conn = _connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM seats").fetchone()["c"]
    finally:
        conn.close()


def query_transitions(db_path: str = settings.db_path, hold_id: str | None = None, limit: int = 200) -> list[dict]:
    conn = _connect(db_path)
    try:
        if hold_id:
            rows = conn.execute(
                "SELECT id, hold_id, user_id, seat_ids, prev_status, new_status, reason, timestamp "
                "FROM transitions WHERE hold_id=? ORDER BY id DESC LIMIT ?",
                (hold_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, hold_id, user_id, seat_ids, prev_status, new_status, reason, timestamp "
                "FROM transitions ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "transition_id": r["id"],
                "hold_id": r["hold_id"],
                "user_id": r["user_id"],
                "seat_ids": [s for s in r["seat_ids"].split(",") if s],
                "prev_status": r["prev_status"],
                "new_status": r["new_status"],
                "reason": r["reason"],
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _write_batch(path: str, batch: list[Event]) -> None:
    conn = _connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        for ev in batch:
            conn.execute(
                "INSERT INTO transitions (hold_id,user_id,seat_ids,prev_status,new_status,reason,timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (ev.hold_id, ev.user_id, ",".join(ev.seat_ids), ev.prev_status, ev.new_status, ev.reason, ev.timestamp),
            )
            if ev.type == EventType.HOLD_CREATED:
                conn.execute(
                    "INSERT OR REPLACE INTO holds (hold_id,user_id,event_id,status,total,currency,created_at,expires_at) "
                    "VALUES (?,?,?,'HELD',?,?,?,?)",
                    (ev.hold_id, ev.user_id, ev.event_id, ev.total, ev.currency, ev.created_at, ev.expires_at),
                )
                conn.executemany(
                    "INSERT OR REPLACE INTO hold_seats (hold_id,seat_id) VALUES (?,?)",
                    [(ev.hold_id, sid) for sid in ev.seat_ids],
                )
                conn.executemany(
                    "UPDATE seats SET status='HELD', held_by_hold_id=? WHERE seat_id=?",
                    [(ev.hold_id, sid) for sid in ev.seat_ids],
                )
            elif ev.type == EventType.HOLD_CONFIRMED:
                conn.executemany(
                    "UPDATE seats SET status='SOLD', held_by_hold_id=NULL WHERE seat_id=?",
                    [(sid,) for sid in ev.seat_ids],
                )
                conn.execute("UPDATE holds SET status='SOLD' WHERE hold_id=?", (ev.hold_id,))
            elif ev.type == EventType.HOLD_RELEASED:
                conn.executemany(
                    "UPDATE seats SET status='AVAILABLE', held_by_hold_id=NULL WHERE seat_id=?",
                    [(sid,) for sid in ev.seat_ids],
                )
                conn.execute("UPDATE holds SET status='RELEASED' WHERE hold_id=?", (ev.hold_id,))
            elif ev.type == EventType.HOLD_EXPIRED:
                conn.executemany(
                    "UPDATE seats SET status='AVAILABLE', held_by_hold_id=NULL WHERE seat_id=?",
                    [(sid,) for sid in ev.seat_ids],
                )
                conn.execute("UPDATE holds SET status='EXPIRED' WHERE hold_id=?", (ev.hold_id,))
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()


@dataclass
class WriterStats:
    events_processed: int = 0
    errors: int = 0
    last_error: str = ""


class WriterWorker:
    def __init__(self, queue: asyncio.Queue, db_path: str = settings.db_path, cfg: Settings = settings):
        self.queue = queue
        self.db_path = db_path
        self.cfg = cfg
        self.stats = WriterStats()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                first = await self.queue.get()
            except asyncio.CancelledError:
                break
            if first is None:
                break
            batch: list[Event] = [first]
            deadline = time.monotonic() + self.cfg.writer_flush_ms / 1000.0
            while len(batch) < self.cfg.writer_batch_size:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    break
                try:
                    ev = await asyncio.wait_for(self.queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    break
                except asyncio.CancelledError:
                    break
                if ev is None:
                    break
                batch.append(ev)
            try:
                await asyncio.to_thread(_write_batch, self.db_path, batch)
                self.stats.events_processed += len(batch)
            except Exception as e:
                self.stats.errors += 1
                self.stats.last_error = repr(e)

    async def stop(self) -> None:
        self._stop.set()
        await self.queue.put(None)
