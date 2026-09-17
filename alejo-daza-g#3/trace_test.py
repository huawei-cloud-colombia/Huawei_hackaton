from __future__ import annotations

import asyncio
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "nexus_trace.db")
for ext in ("", "-wal", "-shm"):
    p = DB + ext
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass
os.environ["NEXUS_DB_PATH"] = DB
os.environ.setdefault("NEXUS_HOLD_TTL", "600")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402

from nexus.main import app  # noqa: E402
from stress_lib import free_port, start_server, stop_server, post, get, wait_ready  # noqa: E402

EVENT = "aurora-bogota-2026"
REQUIRED = {"user_id", "hold_id", "seat_ids", "prev_status", "new_status", "timestamp", "reason"}


async def run_trace() -> dict:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server, thread = start_server(app, port)
    rep: dict = {}
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15.0) as client:
            await wait_ready(client)
            await post(client, "/admin/payment/mode", {"mode": "always_approved"})

            # 1. hold -> AVAILABLE->HELD
            st, _, hb = await post(client, "/holds", {"user_id": "usr_tr", "event_id": EVENT, "seat_ids": ["VIP-A-001"]}, {"Idempotency-Key": "tr-hold"})
            hold_id = hb["hold_id"]
            await post(client, "/checkout", {"hold_id": hold_id, "user_id": "usr_tr", "payment_token": "tok_tr"}, {"Idempotency-Key": "tr-co"})
            rep["checkout_seat"] = (await get(client, "/seats/VIP-A-001"))[1].get("status")

            # 2. another hold -> release -> HELD->AVAILABLE
            st, _, hb2 = await post(client, "/holds", {"user_id": "usr_tr2", "event_id": EVENT, "seat_ids": ["VIP-A-002"]}, {"Idempotency-Key": "tr-hold2"})
            await post(client, "/release", {"hold_id": hb2["hold_id"], "user_id": "usr_tr2"}, {"Idempotency-Key": "tr-rel"})

            # 3. RAM traceability
            _, ram = await get(client, "/admin/traceability", {"limit": "50"})
            rep["ram_count"] = len(ram)
            rep["ram_has_all_fields"] = all(REQUIRED <= set(r.keys()) for r in ram)
            ram_hold = [r for r in ram if r["hold_id"] == hold_id]
            rep["ram_hold_transitions"] = [(r["prev_status"], r["new_status"], r["reason"]) for r in ram_hold]

            # 4. SQLite traceability (wait for writer flush)
            await asyncio.sleep(0.4)
            _, db = await get(client, "/admin/traceability/db", {"limit": "50"})
            rep["db_count"] = len(db)
            rep["db_has_all_fields"] = all(REQUIRED <= set(r.keys()) for r in db)
            db_hold = [r for r in db if r["hold_id"] == hold_id]
            rep["db_hold_transitions"] = [(r["prev_status"], r["new_status"], r["reason"]) for r in db_hold]

            # 5. per-hold trace endpoint
            _, ht = await get(client, f"/holds/{hold_id}/trace")
            rep["hold_trace_count"] = len(ht)
    finally:
        stop_server(server, thread)
    return rep


def _print(r: dict) -> None:
    print("\n" + "=" * 60)
    print(" TRAZABILIDAD — transitions en RAM + SQLite")
    print("=" * 60)
    print(f" Checkout seat            : {r['checkout_seat']}  (esperado: SOLD)")
    print(f" RAM trace registros      : {r['ram_count']} | todos campos: {r['ram_has_all_fields']}")
    print(f" RAM hold transitions     : {r['ram_hold_transitions']}")
    print(f" SQLite trace registros   : {r['db_count']} | todos campos: {r['db_has_all_fields']}")
    print(f" SQLite hold transitions  : {r['db_hold_transitions']}")
    print(f" /holds/{{id}}/trace       : {r['hold_trace_count']} registros")
    expected = {("AVAILABLE", "HELD", "hold_created"), ("HELD", "SOLD", "payment_approved")}
    ok = (
        r["checkout_seat"] == "SOLD"
        and r["ram_has_all_fields"] is True
        and r["db_has_all_fields"] is True
        and r["db_count"] >= 3
        and set(r["ram_hold_transitions"]) == expected
        and set(r["db_hold_transitions"]) == expected
        and r["hold_trace_count"] == 2
    )
    print("=" * 60)
    print(" RESULTADO: " + ("PASS" if ok else "FAIL"))
    print("=" * 60)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    _print(asyncio.run(run_trace()))
