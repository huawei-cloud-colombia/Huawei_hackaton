from __future__ import annotations

import asyncio
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "nexus_fase3.db")
for ext in ("", "-wal", "-shm"):
    p = DB + ext
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass
os.environ["NEXUS_DB_PATH"] = DB
os.environ.setdefault("NEXUS_HOLD_TTL", "600")
os.environ["NEXUS_CB_RECOVERY"] = "2"
os.environ["NEXUS_PAY_TIMEOUT"] = "0.5"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

from nexus.main import app  # noqa: E402
from stress_lib import free_port, start_server, stop_server, post, get, wait_ready  # noqa: E402

EVENT = "aurora-bogota-2026"


async def hold(client, seat, user, key):
    st, _, b = await post(client, "/holds", {"user_id": user, "event_id": EVENT, "seat_ids": [seat]}, {"Idempotency-Key": key})
    return st, b


async def seat_status(client, seat):
    st, b = await get(client, f"/seats/{seat}")
    return b.get("status")


async def set_mode(client, mode):
    await post(client, "/admin/payment/mode", {"mode": mode})


async def cb(client):
    _, b = await get(client, "/admin/circuit-breaker")
    return b.get("state")


async def run_fase3() -> dict:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server, thread = start_server(app, port)
    rep: dict = {}
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15.0, limits=httpx.Limits(max_connections=200)) as client:
            await wait_ready(client)
            await post(client, "/admin/circuit-breaker/reset", {})

            # --- A. APPROVED -> SOLD ---
            await set_mode(client, "always_approved")
            st, hb = await hold(client, "VIP-A-002", "uA", "kA-hold")
            stc, _, bc = await post(client, "/checkout", {"hold_id": hb["hold_id"], "user_id": "uA", "payment_token": "tok_A"}, {"Idempotency-Key": "kA-co"})
            rep["A_checkout"] = stc
            rep["A_seat"] = await seat_status(client, "VIP-A-002")
            _, conf = await get(client, f"/confirmations/{hb['hold_id']}")
            rep["A_confirmation"] = conf.get("confirmation_id") is not None

            # --- B. DECLINED -> release ---
            await set_mode(client, "always_declined")
            st, hb = await hold(client, "VIP-A-003", "uB", "kB-hold")
            stc, _, bc = await post(client, "/checkout", {"hold_id": hb["hold_id"], "user_id": "uB", "payment_token": "tok_B"}, {"Idempotency-Key": "kB-co"})
            rep["B_checkout"] = stc
            rep["B_reason"] = bc.get("reason")
            rep["B_seat"] = await seat_status(client, "VIP-A-003")

            # --- C. TIMEOUT ambiguous -> retry -> SOLD (no double charge) ---
            await set_mode(client, "always_timeout")
            st, hb = await hold(client, "VIP-A-004", "uC", "kC-hold")
            stc1, _, bc1 = await post(client, "/checkout", {"hold_id": hb["hold_id"], "user_id": "uC", "payment_token": "tok_C"}, {"Idempotency-Key": "kC-co"})
            rep["C_timeout_status"] = stc1
            rep["C_reason"] = bc1.get("reason")
            rep["C_seat_after_timeout"] = await seat_status(client, "VIP-A-004")
            await set_mode(client, "always_approved")
            stc2, _, bc2 = await post(client, "/checkout", {"hold_id": hb["hold_id"], "user_id": "uC", "payment_token": "tok_C"}, {"Idempotency-Key": "kC-co"})
            rep["C_retry_status"] = stc2
            rep["C_seat_after_retry"] = await seat_status(client, "VIP-A-004")

            # --- D. Circuit breaker CLOSED -> OPEN -> 503 -> HALF_OPEN -> CLOSED ---
            await post(client, "/admin/circuit-breaker/reset", {})
            await set_mode(client, "always_error")
            d_holds = []
            for i in range(3):
                st, hb = await hold(client, f"VIP-A-00{5+i}", f"uD{i}", f"kD-hold{i}")
                d_holds.append(hb)
                await post(client, "/checkout", {"hold_id": hb["hold_id"], "user_id": f"uD{i}", "payment_token": "tok_D"}, {"Idempotency-Key": f"kD-co{i}"})
            rep["D_cb_after_3_errors"] = await cb(client)
            st, hb4 = await hold(client, "VIP-A-008", "uD3", "kD-hold3")
            stc, _, bc4 = await post(client, "/checkout", {"hold_id": hb4["hold_id"], "user_id": "uD3", "payment_token": "tok_D"}, {"Idempotency-Key": "kD-co3"})
            rep["D_4th_checkout"] = stc
            rep["D_4th_reason"] = bc4.get("reason")
            rep["D_seat_4th"] = await seat_status(client, "VIP-A-008")
            await asyncio.sleep(2.4)
            rep["D_cb_after_recovery"] = await cb(client)
            await set_mode(client, "always_approved")
            stc, _, _ = await post(client, "/checkout", {"hold_id": hb4["hold_id"], "user_id": "uD3", "payment_token": "tok_D"}, {"Idempotency-Key": "kD-co3b"})
            rep["D_halfopen_trial_status"] = stc
            rep["D_cb_after_trial"] = await cb(client)

            # --- E. HALF_OPEN failure -> OPEN ---
            await post(client, "/admin/circuit-breaker/reset", {})
            await set_mode(client, "always_error")
            for i in range(3):
                st, hb = await hold(client, f"GEN-000{i+1}", f"uE{i}", f"kE-hold{i}")
                await post(client, "/checkout", {"hold_id": hb["hold_id"], "user_id": f"uE{i}", "payment_token": "tok_E"}, {"Idempotency-Key": f"kE-co{i}"})
            await asyncio.sleep(2.4)
            rep["E_cb_halfopen"] = await cb(client)
            st, hb = await hold(client, "GEN-0004", "uE3", "kE-hold3")
            stc, _, _ = await post(client, "/checkout", {"hold_id": hb["hold_id"], "user_id": "uE3", "payment_token": "tok_E"}, {"Idempotency-Key": "kE-co3"})
            rep["E_cb_after_halfopen_failure"] = await cb(client)

            await asyncio.sleep(0.3)
            _, rep["stats"] = await get(client, "/admin/stats")
    finally:
        stop_server(server, thread)
    return rep


def _print(r: dict) -> None:
    print("\n" + "=" * 64)
    print(" FASE 3 — Confirmacion y proveedor de pagos inestable")
    print("=" * 64)
    print(f" A. APPROVED -> SOLD        : checkout={r['A_checkout']} seat={r['A_seat']} conf={r['A_confirmation']}")
    print(f" B. DECLINED -> release     : checkout={r['B_checkout']} reason={r['B_reason']} seat={r['B_seat']}")
    print(f" C. TIMEOUT -> retry -> SOLD: timeout={r['C_timeout_status']}({r['C_reason']}) seat_after_to={r['C_seat_after_timeout']} | retry={r['C_retry_status']} seat={r['C_seat_after_retry']}")
    print(f" D. CB CLOSED->OPEN->503->HO->CLOSED:")
    print(f"      3 errors -> {r['D_cb_after_3_errors']} | 4th checkout={r['D_4th_checkout']}({r['D_4th_reason']}) seat={r['D_seat_4th']}")
    print(f"      after recovery -> {r['D_cb_after_recovery']} | trial={r['D_halfopen_trial_status']} -> {r['D_cb_after_trial']}")
    print(f" E. CB HALF_OPEN failure -> OPEN: halfopen={r['E_cb_halfopen']} -> after failure={r['E_cb_after_halfopen_failure']}")
    print("-" * 64)
    s = r["stats"]
    print(f" Stats: pay authorized={s['pay_authorized']} declined={s['pay_declined']} error={s['pay_error']} timeout={s['pay_timeout']} sold={s['sold']} writer_errors={s['writer_errors']}")
    ok = (
        r["A_checkout"] == 200 and r["A_seat"] == "SOLD" and r["A_confirmation"] is True
        and r["B_checkout"] == 402 and r["B_reason"] == "PAYMENT_DECLINED" and r["B_seat"] == "AVAILABLE"
        and r["C_timeout_status"] == 409 and r["C_reason"] == "PAYMENT_PENDING" and r["C_seat_after_timeout"] == "HELD"
        and r["C_retry_status"] == 200 and r["C_seat_after_retry"] == "SOLD"
        and r["D_cb_after_3_errors"] == "OPEN" and r["D_4th_checkout"] == 503 and r["D_4th_reason"] == "PAYMENT_SERVICE_UNAVAILABLE" and r["D_seat_4th"] == "HELD"
        and r["D_cb_after_recovery"] == "HALF_OPEN" and r["D_halfopen_trial_status"] == 200 and r["D_cb_after_trial"] == "CLOSED"
        and r["E_cb_halfopen"] == "HALF_OPEN" and r["E_cb_after_halfopen_failure"] == "OPEN"
        and s["writer_errors"] == 0
    )
    print("=" * 64)
    print(" RESULTADO: " + ("PASS" if ok else "FAIL"))
    print("=" * 64)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    _print(asyncio.run(run_fase3()))
