import secrets
from datetime import datetime, timezone

import config
import db
import payment_mock
import circuit_breaker
from services import audit_service


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat()


def gen_payment_id():
    return "pay_" + secrets.token_hex(5).upper()


def confirm_hold(hold_id, payment_token, scenario="AUTO"):
    if not payment_token:
        return {"error": "empty_payment_token", "status": 400}

    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT hold_id, user_id, event_id, status, total, currency, expires_at "
            "FROM holds WHERE hold_id = ?",
            (hold_id,),
        ).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return {"error": "hold_not_found", "status": 404}

        if row["status"] == "SOLD":
            conn.execute("ROLLBACK")
            return {"error": "hold_already_sold", "status": 409}
        if row["status"] in ("EXPIRED", "RELEASED"):
            conn.execute("ROLLBACK")
            return {"error": "hold_expired", "current_status": row["status"], "status": 409}
        if row["status"] != "HELD":
            conn.execute("ROLLBACK")
            return {"error": "hold_not_active", "current_status": row["status"], "status": 409}

        expires_at = datetime.fromisoformat(row["expires_at"])
        if now_utc() > expires_at:
            conn.execute("ROLLBACK")
            return {"error": "hold_expired", "status": 409}

        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return {"error": "internal_error", "detail": str(exc), "status": 500}
    finally:
        conn.close()

    if not circuit_breaker.breaker.allow_request():
        audit_service.log_transition(hold_id, None, row["user_id"], "HELD", "HELD", "circuit_breaker_open")
        return {"error": "PAYMENT_SERVICE_UNAVAILABLE", "circuit_breaker": circuit_breaker.breaker.state, "status": 503}

    amount = row["total"]
    currency = row["currency"]
    pay_result = payment_mock.mock_payment_authorize(amount, currency, payment_token, scenario)
    result_status = pay_result.get("result")

    payment_id = gen_payment_id()
    conn = db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        conn.execute(
            "INSERT INTO payments (payment_id, hold_id, token, scenario, result, amount, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (payment_id, hold_id, payment_token, scenario, result_status, amount, now_iso()),
        )

        seat_rows = conn.execute(
            "SELECT seat_id FROM hold_seats WHERE hold_id = ?", (hold_id,)
        ).fetchall()
        seat_ids = [r["seat_id"] for r in seat_rows]

        if result_status == "APPROVED":
            for sid in seat_ids:
                conn.execute(
                    "UPDATE seats SET status = 'SOLD', version = version + 1 WHERE seat_id = ?",
                    (sid,),
                )
                audit_service.log_transition_conn(
                    conn, hold_id, sid, row["user_id"], "HELD", "SOLD", "payment_approved"
                )
            conn.execute("UPDATE holds SET status = 'SOLD' WHERE hold_id = ?", (hold_id,))
            circuit_breaker.breaker.record_success()
            conn.execute("COMMIT")

            response = {
                "payment_id": payment_id,
                "hold_id": hold_id,
                "result": "APPROVED",
                "status": "SOLD",
                "amount": amount,
                "currency": currency,
                "auth_code": pay_result.get("auth_code"),
            }

            if scenario == "RECURRENCE" or pay_result.get("recurring"):
                from services import recurrence_service
                rec = recurrence_service.create_recurrence(
                    hold_id, amount, installments_total=3, interval_days=30
                )
                response["recurrence"] = rec

            return response

        elif result_status == "DECLINED":
            for sid in seat_ids:
                conn.execute(
                    "UPDATE seats SET status = 'AVAILABLE', version = version + 1 WHERE seat_id = ?",
                    (sid,),
                )
                audit_service.log_transition_conn(
                    conn, hold_id, sid, row["user_id"], "HELD", "AVAILABLE", "payment_declined"
                )
            conn.execute("UPDATE holds SET status = 'RELEASED' WHERE hold_id = ?", (hold_id,))
            circuit_breaker.breaker.record_success()
            conn.execute("COMMIT")
            return {
                "payment_id": payment_id,
                "hold_id": hold_id,
                "result": "DECLINED",
                "status": "RELEASED",
                "reason": pay_result.get("reason"),
            }

        else:
            for sid in seat_ids:
                audit_service.log_transition_conn(
                    conn, hold_id, sid, row["user_id"], "HELD", "HELD",
                    f"payment_{result_status.lower()}"
                )
            circuit_breaker.breaker.record_failure()
            conn.execute("COMMIT")
            return {
                "payment_id": payment_id,
                "hold_id": hold_id,
                "result": result_status,
                "status": "HELD",
                "reason": pay_result.get("reason"),
                "pending_retry": True,
                "circuit_breaker": circuit_breaker.breaker.state,
            }
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return {"error": "internal_error", "detail": str(exc), "status": 500}
    finally:
        conn.close()


def get_circuit_breaker_state():
    return circuit_breaker.breaker.snapshot()


def reset_circuit_breaker():
    circuit_breaker.breaker.reset()
    return circuit_breaker.breaker.snapshot()
