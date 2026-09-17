import secrets
import threading
from datetime import datetime, timedelta, timezone

import db
import payment_mock
from services import audit_service


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat()


def gen_recurrence_id():
    return "rec_" + secrets.token_hex(5).upper()


def create_recurrence(hold_id, amount, installments_total=3, interval_days=30):
    amount_per = amount // installments_total
    recurrence_id = gen_recurrence_id()
    next_charge = now_utc() + timedelta(days=interval_days)

    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT INTO recurrences "
            "(recurrence_id, hold_id, interval_days, next_charge_at, status, "
            "installments_total, installments_paid, amount_per_installment, currency) "
            "VALUES (?, ?, ?, ?, 'ACTIVE', ?, 1, ?, 'COP')",
            (recurrence_id, hold_id, interval_days, next_charge.isoformat(),
             installments_total, amount_per),
        )
    finally:
        conn.close()

    audit_service.log_transition(hold_id, None, None, "HELD", "SOLD", "recurrence_created")
    return get_recurrence(hold_id)


def get_recurrence(hold_id):
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT recurrence_id, hold_id, interval_days, next_charge_at, status, "
            "installments_total, installments_paid, amount_per_installment, currency "
            "FROM recurrences WHERE hold_id = ?",
            (hold_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def charge_next(hold_id, scenario="AUTO"):
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT recurrence_id, hold_id, interval_days, installments_total, installments_paid, "
            "amount_per_installment, currency, status "
            "FROM recurrences WHERE hold_id = ? AND status = 'ACTIVE'",
            (hold_id,),
        ).fetchone()
        if not row:
            return {"error": "no_active_recurrence", "status": 404}

        pay_result = payment_mock.mock_payment_authorize(
            row["amount_per_installment"], row["currency"], "tok_recur_" + row["recurrence_id"], scenario
        )
        result_status = pay_result.get("result")

        if result_status == "APPROVED":
            new_paid = row["installments_paid"] + 1
            new_status = "COMPLETED" if new_paid >= row["installments_total"] else "ACTIVE"
            next_charge = now_utc() + timedelta(days=row["interval_days"])
            conn.execute(
                "UPDATE recurrences SET installments_paid = ?, status = ?, next_charge_at = ? "
                "WHERE recurrence_id = ?",
                (new_paid, new_status, next_charge.isoformat(), row["recurrence_id"]),
            )
            audit_service.log_transition(hold_id, None, None, "SOLD", "SOLD", "recurrence_charged")
            result = get_recurrence(hold_id)
            result["charge_result"] = "APPROVED"
            return result
        else:
            conn.execute(
                "UPDATE recurrences SET status = 'FAILED' WHERE recurrence_id = ?",
                (row["recurrence_id"],),
            )
            audit_service.log_transition(hold_id, None, None, "SOLD", "SOLD", "recurrence_failed")
            return {"error": "recurrence_charge_failed", "result": result_status}
    finally:
        conn.close()


_recurrence_stop = threading.Event()


def recurrence_worker(interval=5):
    while not _recurrence_stop.is_set():
        try:
            conn = db.get_connection()
            try:
                now = now_iso()
                rows = conn.execute(
                    "SELECT hold_id FROM recurrences WHERE status = 'ACTIVE' AND next_charge_at < ?",
                    (now,),
                ).fetchall()
            finally:
                conn.close()
            for r in rows:
                try:
                    charge_next(r["hold_id"])
                except Exception:
                    pass
        except Exception:
            pass
        _recurrence_stop.wait(interval)


def start_recurrence_worker():
    _recurrence_stop.clear()
    t = threading.Thread(target=recurrence_worker, daemon=True, name="recurrence-worker")
    t.start()
    return t


def stop_recurrence_worker():
    _recurrence_stop.set()
