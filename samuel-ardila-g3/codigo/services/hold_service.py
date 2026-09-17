import secrets
import threading
import time
from datetime import datetime, timezone

import config
import db
from services import audit_service


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat()


def gen_hold_id():
    return "hold_" + secrets.token_hex(5).upper()


def create_hold(user_id, event_id, seat_ids):
    if not user_id or not isinstance(user_id, str):
        return {"error": "invalid_user", "status": 400}
    if not seat_ids or not isinstance(seat_ids, list):
        return {"error": "empty_seat_list", "status": 400}
    if len(seat_ids) != len(set(seat_ids)):
        return {"error": "duplicate_seat", "status": 400}

    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        placeholders = ",".join("?" * len(seat_ids))
        rows = conn.execute(
            f"SELECT seat_id, status, price FROM seats WHERE seat_id IN ({placeholders})",
            seat_ids,
        ).fetchall()

        found_ids = {r["seat_id"] for r in rows}
        missing = set(seat_ids) - found_ids
        if missing:
            conn.execute("ROLLBACK")
            return {"error": "seat_not_found", "missing": list(missing), "status": 404}

        unavailable = [r["seat_id"] for r in rows if r["status"] != "AVAILABLE"]
        if unavailable:
            conn.execute("ROLLBACK")
            return {"error": "seat_not_available", "seats": unavailable, "status": 409}

        active_count = conn.execute(
            "SELECT COUNT(*) FROM hold_seats hs JOIN holds h ON hs.hold_id = h.hold_id "
            "WHERE h.user_id = ? AND h.status = 'HELD'",
            (user_id,),
        ).fetchone()[0]
        if active_count + len(seat_ids) > config.MAX_SEATS_PER_USER:
            conn.execute("ROLLBACK")
            return {
                "error": "seat_limit_exceeded",
                "current": active_count,
                "limit": config.MAX_SEATS_PER_USER,
                "status": 409,
            }

        total = sum(r["price"] for r in rows)
        hold_id = gen_hold_id()
        created_at = now_utc()
        expires_at = created_at + timedelta_seconds(config.HOLD_TTL_SECONDS)

        conn.execute(
            "INSERT INTO holds (hold_id, user_id, event_id, status, total, currency, created_at, expires_at) "
            "VALUES (?, ?, ?, 'HELD', ?, ?, ?, ?)",
            (hold_id, user_id, event_id, total, config.CURRENCY, created_at.isoformat(), expires_at.isoformat()),
        )

        for seat_id in seat_ids:
            conn.execute(
                "INSERT INTO hold_seats (hold_id, seat_id) VALUES (?, ?)",
                (hold_id, seat_id),
            )
            conn.execute(
                "UPDATE seats SET status = 'HELD', version = version + 1 WHERE seat_id = ?",
                (seat_id,),
            )
            audit_service.log_transition_conn(
                conn, hold_id, seat_id, user_id, "AVAILABLE", "HELD", "hold_created"
            )

        conn.execute("COMMIT")

        return {
            "hold_id": hold_id,
            "user_id": user_id,
            "event_id": event_id,
            "seat_ids": seat_ids,
            "status": "HELD",
            "total": total,
            "currency": config.CURRENCY,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return {"error": "internal_error", "detail": str(exc), "status": 500}
    finally:
        conn.close()


def timedelta_seconds(seconds):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def get_hold(hold_id):
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT hold_id, user_id, event_id, status, total, currency, created_at, expires_at "
            "FROM holds WHERE hold_id = ?",
            (hold_id,),
        ).fetchone()
        if not row:
            return None
        hold = dict(row)
        seat_rows = conn.execute(
            "SELECT seat_id FROM hold_seats WHERE hold_id = ?", (hold_id,)
        ).fetchall()
        hold["seat_ids"] = [r["seat_id"] for r in seat_rows]

        expires_at = datetime.fromisoformat(hold["expires_at"])
        remaining = (expires_at - now_utc()).total_seconds()
        hold["remaining_seconds"] = max(0, remaining)
        return hold
    finally:
        conn.close()


def release_hold(hold_id):
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT hold_id, user_id, status FROM holds WHERE hold_id = ?", (hold_id,)
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return {"error": "hold_not_found", "status": 404}
        if row["status"] != "HELD":
            conn.execute("ROLLBACK")
            return {"error": "hold_not_active", "current_status": row["status"], "status": 409}

        seat_rows = conn.execute(
            "SELECT seat_id FROM hold_seats WHERE hold_id = ?", (hold_id,)
        ).fetchall()
        for sr in seat_rows:
            conn.execute(
                "UPDATE seats SET status = 'AVAILABLE', version = version + 1 WHERE seat_id = ?",
                (sr["seat_id"],),
            )
            audit_service.log_transition_conn(
                conn, hold_id, sr["seat_id"], row["user_id"], "HELD", "AVAILABLE", "hold_released"
            )

        conn.execute("UPDATE holds SET status = 'RELEASED' WHERE hold_id = ?", (hold_id,))
        conn.execute("COMMIT")
        return {"hold_id": hold_id, "status": "RELEASED"}
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return {"error": "internal_error", "detail": str(exc), "status": 500}
    finally:
        conn.close()


def expire_holds():
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        now = now_iso()
        expired = conn.execute(
            "SELECT hold_id, user_id FROM holds WHERE status = 'HELD' AND expires_at < ?",
            (now,),
        ).fetchall()
        for h in expired:
            seat_rows = conn.execute(
                "SELECT seat_id FROM hold_seats WHERE hold_id = ?", (h["hold_id"],)
            ).fetchall()
            for sr in seat_rows:
                conn.execute(
                    "UPDATE seats SET status = 'AVAILABLE', version = version + 1 WHERE seat_id = ?",
                    (sr["seat_id"],),
                )
                audit_service.log_transition_conn(
                    conn, h["hold_id"], sr["seat_id"], h["user_id"],
                    "HELD", "AVAILABLE", "hold_expired"
                )
            conn.execute(
                "UPDATE holds SET status = 'EXPIRED' WHERE hold_id = ?", (h["hold_id"],)
            )
        conn.execute("COMMIT")
        return len(expired)
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return 0
    finally:
        conn.close()


_expiry_stop = threading.Event()


def expiry_worker(interval=None):
    if interval is None:
        interval = max(1, config.HOLD_TTL_SECONDS // 4)
    while not _expiry_stop.is_set():
        try:
            expire_holds()
        except Exception:
            pass
        _expiry_stop.wait(interval)


def start_expiry_worker():
    _expiry_stop.clear()
    t = threading.Thread(target=expiry_worker, daemon=True, name="expiry-worker")
    t.start()
    return t


def stop_expiry_worker():
    _expiry_stop.set()
