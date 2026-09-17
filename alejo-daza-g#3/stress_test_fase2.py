from __future__ import annotations

import asyncio
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "nexus_fase2.db")
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
SEAT = "VIP-A-001"


async def run_fase2(n: int = 100) -> dict:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server, thread = start_server(app, port)
    limits = httpx.Limits(max_connections=max(1000, n + 10), max_keepalive_connections=100)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15.0, limits=limits) as client:
            await wait_ready(client)

            tasks = [
                post(client, "/holds", {"user_id": f"usr_{i}", "event_id": EVENT, "seat_ids": [SEAT]}, {"Idempotency-Key": f"reserve-usr{i}-001"})
                for i in range(n)
            ]
            results = await asyncio.gather(*tasks)
            statuses = [st for st, _, _ in results]
            win_idx = next((i for i, (st, _, _) in enumerate(results) if st == 201), None)
            wins = [b for st, _, b in results if st == 201]
            rejects = [b for st, _, b in results if st == 409]

            replay_same = None
            replay_conflict = None
            if win_idx is not None:
                wkey = f"reserve-usr{win_idx}-001"
                wuser = f"usr_{win_idx}"
                st1, _, b1 = await post(client, "/holds", {"user_id": wuser, "event_id": EVENT, "seat_ids": [SEAT]}, {"Idempotency-Key": wkey})
                replay_same = {"status": st1, "hold_id": b1.get("hold_id"), "same": b1.get("hold_id") == wins[0]["hold_id"]}

                st2, _, b2 = await post(client, "/holds", {"user_id": wuser, "event_id": EVENT, "seat_ids": ["VIP-A-002"]}, {"Idempotency-Key": wkey})
                replay_conflict = {"status": st2, "reason": b2.get("reason")}

            await asyncio.sleep(0.3)
            _, stats = await get(client, "/admin/stats")
    finally:
        stop_server(server, thread)

    return {
        "n": n,
        "seat": SEAT,
        "winners_201": statuses.count(201),
        "rejected_409": statuses.count(409),
        "other": [st for st in statuses if st not in (201, 409)],
        "sold_in_memory": stats.get("sold", 0),
        "held_in_memory": stats.get("held", 0),
        "writer_errors": stats.get("writer_errors", 0),
        "replay_same": replay_same,
        "replay_conflict": replay_conflict,
    }


def _print(r: dict) -> None:
    print("\n" + "=" * 60)
    print(" FASE 2 — La carrera por el ultimo asiento")
    print("=" * 60)
    print(f" Asiento disputado        : {r['seat']}")
    print(f" Solicitudes concurrentes : {r['n']}")
    print(f" Ganadores (201)          : {r['winners_201']}   (esperado: 1)")
    print(f" Rechazados (409)         : {r['rejected_409']}  (esperado: {r['n'] - 1})")
    print(f" Otros status             : {r['other']}")
    print(f" Overselling (SOLD)       : {r['sold_in_memory']}   (esperado: 0)")
    print("-" * 60)
    rs = r["replay_same"]
    rc = r["replay_conflict"]
    print(f" Idempotencia replay      : status={rs['status']} same_hold={rs['same']}  (esperado: 201, same=True)")
    print(f" Idempotencia conflicto   : status={rc['status']} reason={rc['reason']}  (esperado: 409, IDEMPOTENCY_CONFLICT)")
    ok = (
        r["winners_201"] == 1
        and r["rejected_409"] == r["n"] - 1
        and r["other"] == []
        and r["sold_in_memory"] == 0
        and rs["status"] == 201
        and rs["same"] is True
        and rc["status"] == 409
        and rc["reason"] == "IDEMPOTENCY_CONFLICT"
    )
    print("=" * 60)
    print(" RESULTADO: " + ("PASS" if ok else "FAIL"))
    print("=" * 60)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    _print(asyncio.run(run_fase2(n=n)))
