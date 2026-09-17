from datetime import datetime, timezone
import db


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def log_transition(hold_id, seat_id, user_id, from_state, to_state, reason):
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO audit_log (hold_id, seat_id, user_id, from_state, to_state, reason, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (hold_id, seat_id, user_id, from_state, to_state, reason, now_iso()),
        )
    finally:
        conn.close()


def log_transition_conn(conn, hold_id, seat_id, user_id, from_state, to_state, reason):
    conn.execute(
        "INSERT INTO audit_log (hold_id, seat_id, user_id, from_state, to_state, reason, timestamp) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (hold_id, seat_id, user_id, from_state, to_state, reason, now_iso()),
    )


def get_audit(hold_id):
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, hold_id, seat_id, user_id, from_state, to_state, reason, timestamp "
            "FROM audit_log WHERE hold_id = ? ORDER BY id",
            (hold_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_audit_all(limit=100, offset=0):
    conn = db.get_connection()
    try:
        rows = conn.execute(
            "SELECT id, hold_id, seat_id, user_id, from_state, to_state, reason, timestamp "
            "FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
