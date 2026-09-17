from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS seats (
    seat_id          TEXT PRIMARY KEY,
    event_id         TEXT NOT NULL,
    section          TEXT NOT NULL,
    price            INTEGER NOT NULL,
    currency         TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('AVAILABLE','HELD','SOLD')),
    held_by_hold_id  TEXT
);

CREATE TABLE IF NOT EXISTS holds (
    hold_id    TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('HELD','EXPIRED','RELEASED','SOLD')),
    total      INTEGER NOT NULL,
    currency   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hold_seats (
    hold_id  TEXT NOT NULL,
    seat_id  TEXT NOT NULL,
    PRIMARY KEY (hold_id, seat_id),
    FOREIGN KEY (hold_id) REFERENCES holds(hold_id),
    FOREIGN KEY (seat_id) REFERENCES seats(seat_id)
);

CREATE INDEX IF NOT EXISTS idx_seats_event ON seats(event_id);
CREATE INDEX IF NOT EXISTS idx_holds_user  ON holds(user_id, status);
CREATE INDEX IF NOT EXISTS idx_holds_exp   ON holds(status, expires_at);
"""

SEED_EVENTS = {
    "aurora-bogota-2026": [
        ("VIP", "A", 10, 210000),
        ("PLATEA", "B", 20, 120000),
        ("GENERAL", "C", 30, 80000),
    ],
}
CURRENCY = "COP"


def _seed(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for event_id, sections in SEED_EVENTS.items():
        for section, prefix, count, price in sections:
            for i in range(1, count + 1):
                seat_id = f"{prefix}-{100 + i}"
                cur.execute(
                    """INSERT OR IGNORE INTO seats
                       (seat_id, event_id, section, price, currency, status, held_by_hold_id)
                       VALUES (?, ?, ?, ?, ?, 'AVAILABLE', NULL)""",
                    (seat_id, event_id, section, price, CURRENCY),
                )


def init_db(db_path: str | None = None) -> None:
    path = db_path or settings.db_path
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.executescript(SCHEMA)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or settings.db_path
    conn = sqlite3.connect(path, timeout=10.0, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
    finally:
        conn.close()
