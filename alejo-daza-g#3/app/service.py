from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import settings
from .db import get_conn
from .models import (
    ConfirmResponse,
    Hold,
    HoldStatus,
    Reason,
    Seat,
    SeatStatus,
)

UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


@dataclass
class SeatLockError(Exception):
    reason: Reason
    detail: str
    conflicting_seats: list[str] | None = None


def _new_hold_id() -> str:
    return "hold_" + secrets.token_hex(4).upper()


def _reclaim_expired(conn: sqlite3.Connection) -> int:
    now = _iso(_now())
    rows = conn.execute(
        "SELECT hold_id FROM holds WHERE status='HELD' AND expires_at <= ?",
        (now,),
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE seats SET status='AVAILABLE', held_by_hold_id=NULL "
            "WHERE held_by_hold_id=? AND status='HELD'",
            (r["hold_id"],),
        )
        conn.execute("UPDATE holds SET status='EXPIRED' WHERE hold_id=?", (r["hold_id"],))
    return len(rows)


def _row_to_seat(row: sqlite3.Row) -> Seat:
    status = row["status"]
    held_by = row["held_by_hold_id"]
    if status == SeatStatus.HELD.value and row["hold_expires_at"] is not None:
        if row["hold_status"] != HoldStatus.HELD.value or row["hold_expires_at"] <= _iso(_now()):
            status = SeatStatus.AVAILABLE.value
            held_by = None
    return Seat(
        seat_id=row["seat_id"],
        event_id=row["event_id"],
        section=row["section"],
        price=row["price"],
        currency=row["currency"],
        status=SeatStatus(status),
        held_by_hold_id=held_by,
    )


_SEAT_SELECT = """
    SELECT s.seat_id, s.event_id, s.section, s.price, s.currency,
           s.status, s.held_by_hold_id,
           h.status AS hold_status, h.expires_at AS hold_expires_at
    FROM seats s
    LEFT JOIN holds h ON h.hold_id = s.held_by_hold_id
"""


def list_seats(event_id: str) -> list[Seat]:
    with get_conn() as conn:
        rows = conn.execute(_SEAT_SELECT + " WHERE s.event_id=? ORDER BY s.seat_id", (event_id,)).fetchall()
        return [_row_to_seat(r) for r in rows]


def get_seat(seat_id: str) -> Seat | None:
    with get_conn() as conn:
        row = conn.execute(_SEAT_SELECT + " WHERE s.seat_id=?", (seat_id,)).fetchone()
        return _row_to_seat(row) if row else None


def _build_hold(conn: sqlite3.Connection, hold_id: str) -> Hold | None:
    h = conn.execute("SELECT * FROM holds WHERE hold_id=?", (hold_id,)).fetchone()
    if not h:
        return None
    seats = [r["seat_id"] for r in conn.execute(
        "SELECT seat_id FROM hold_seats WHERE hold_id=? ORDER BY seat_id", (hold_id,)
    ).fetchall()]
    status = HoldStatus(h["status"])
    if status == HoldStatus.HELD and h["expires_at"] <= _iso(_now()):
        status = HoldStatus.EXPIRED
    return Hold(
        hold_id=h["hold_id"],
        user_id=h["user_id"],
        event_id=h["event_id"],
        seat_ids=seats,
        status=status,
        total=h["total"],
        currency=h["currency"],
        created_at=_parse(h["created_at"]),
        expires_at=_parse(h["expires_at"]),
    )


def get_hold(hold_id: str) -> Hold | None:
    with get_conn() as conn:
        return _build_hold(conn, hold_id)


def create_hold(user_id: str, event_id: str, seat_ids: list[str]) -> Hold:
    seen: list[str] = []
    for sid in seat_ids:
        if sid not in seen:
            seen.append(sid)
    seat_ids = seen
    if not seat_ids:
        raise SeatLockError(Reason.EMPTY_REQUEST, "seat_ids is empty")

    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            _reclaim_expired(conn)

            placeholders = ",".join("?" for _ in seat_ids)
            rows = conn.execute(
                _SEAT_SELECT + f" WHERE s.seat_id IN ({placeholders})",
                seat_ids,
            ).fetchall()
            by_id = {r["seat_id"]: r for r in rows}

            missing = [sid for sid in seat_ids if sid not in by_id]
            if missing:
                raise SeatLockError(Reason.SEAT_NOT_AVAILABLE, f"unknown seats: {missing}", missing)

            conflicts: list[str] = []
            for sid in seat_ids:
                seat = _row_to_seat(by_id[sid])
                if seat.status != SeatStatus.AVAILABLE:
                    conflicts.append(sid)
            if conflicts:
                raise SeatLockError(
                    Reason.SEAT_NOT_AVAILABLE,
                    f"seats not available: {conflicts}",
                    conflicts,
                )

            active = conn.execute(
                """SELECT COUNT(*) AS c FROM hold_seats hs
                   JOIN holds h ON h.hold_id = hs.hold_id
                   WHERE h.user_id=? AND h.status='HELD' AND h.expires_at > ?""",
                (user_id, _iso(_now())),
            ).fetchone()["c"]
            if active + len(seat_ids) > settings.max_seats_per_user:
                raise SeatLockError(
                    Reason.MAX_SEATS_EXCEEDED,
                    f"user holds {active} active seats; requesting {len(seat_ids)}; "
                    f"limit is {settings.max_seats_per_user}",
                )

            total = sum(by_id[sid]["price"] for sid in seat_ids)
            currency = by_id[seat_ids[0]]["currency"]
            now = _now()
            expires = now + timedelta(seconds=settings.hold_ttl_seconds)
            hold_id = _new_hold_id()

            conn.execute(
                "INSERT INTO holds (hold_id,user_id,event_id,status,total,currency,created_at,expires_at) "
                "VALUES (?,?,?,'HELD',?,?,?,?)",
                (hold_id, user_id, event_id, total, currency, _iso(now), _iso(expires)),
            )
            for sid in seat_ids:
                conn.execute(
                    "INSERT INTO hold_seats (hold_id,seat_id) VALUES (?,?)",
                    (hold_id, sid),
                )
                conn.execute(
                    "UPDATE seats SET status='HELD', held_by_hold_id=? WHERE seat_id=?",
                    (hold_id, sid),
                )
            conn.execute("COMMIT;")
        except SeatLockError:
            conn.execute("ROLLBACK;")
            raise
        except Exception:
            conn.execute("ROLLBACK;")
            raise

        return Hold(
            hold_id=hold_id,
            user_id=user_id,
            event_id=event_id,
            seat_ids=seat_ids,
            status=HoldStatus.HELD,
            total=total,
            currency=currency,
            created_at=now,
            expires_at=expires,
        )


def release_hold(hold_id: str, user_id: str) -> Hold:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            _reclaim_expired(conn)
            h = conn.execute("SELECT * FROM holds WHERE hold_id=?", (hold_id,)).fetchone()
            if not h or h["user_id"] != user_id:
                raise SeatLockError(Reason.HOLD_NOT_FOUND, f"hold {hold_id} not found for user {user_id}")
            if h["status"] != HoldStatus.HELD.value:
                raise SeatLockError(Reason.HOLD_NOT_ACTIVE, f"hold {hold_id} status is {h['status']}")
            conn.execute(
                "UPDATE seats SET status='AVAILABLE', held_by_hold_id=NULL WHERE held_by_hold_id=? AND status='HELD'",
                (hold_id,),
            )
            conn.execute("UPDATE holds SET status='RELEASED' WHERE hold_id=?", (hold_id,))
            conn.execute("COMMIT;")
        except SeatLockError:
            conn.execute("ROLLBACK;")
            raise
        except Exception:
            conn.execute("ROLLBACK;")
            raise

        return _build_hold(conn, hold_id)  # type: ignore[return-value]


def confirm_hold(hold_id: str, user_id: str) -> ConfirmResponse:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            _reclaim_expired(conn)
            h = conn.execute("SELECT * FROM holds WHERE hold_id=?", (hold_id,)).fetchone()
            if not h or h["user_id"] != user_id:
                raise SeatLockError(Reason.HOLD_NOT_FOUND, f"hold {hold_id} not found for user {user_id}")
            if h["status"] == HoldStatus.EXPIRED.value:
                raise SeatLockError(Reason.HOLD_EXPIRED, f"hold {hold_id} expired")
            if h["status"] != HoldStatus.HELD.value:
                raise SeatLockError(Reason.HOLD_NOT_ACTIVE, f"hold {hold_id} status is {h['status']}")

            seats = [r["seat_id"] for r in conn.execute(
                "SELECT seat_id FROM hold_seats WHERE hold_id=? ORDER BY seat_id", (hold_id,)
            ).fetchall()]
            cur = conn.execute(
                "UPDATE seats SET status='SOLD' WHERE held_by_hold_id=? AND status='HELD'",
                (hold_id,),
            )
            if cur.rowcount != len(seats):
                raise SeatLockError(Reason.SEAT_NOT_HELD, f"hold {hold_id} seats are not all HELD")
            conn.execute("UPDATE holds SET status='SOLD' WHERE hold_id=?", (hold_id,))
            conn.execute("COMMIT;")
        except SeatLockError:
            conn.execute("ROLLBACK;")
            raise
        except Exception:
            conn.execute("ROLLBACK;")
            raise

        return ConfirmResponse(
            hold_id=hold_id,
            user_id=user_id,
            event_id=h["event_id"],
            seat_ids=seats,
            total=h["total"],
            currency=h["currency"],
        )


def expire_holds() -> int:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE;")
        try:
            n = _reclaim_expired(conn)
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
        return n
