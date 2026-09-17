from __future__ import annotations

import asyncio
import os
import sys
import tempfile

DB = os.path.join(tempfile.gettempdir(), "nexus_gui_check.db")
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


async def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server, thread = start_server(app, port)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15.0) as c:
            await wait_ready(c)
            print("== 1. Visualizar asientos (PREMIUM) ==")
            _, seats = await get(c, "/events/aurora-bogota-2026/seats", {"section": "PREMIUM", "limit": "10"})
            print([f"{s['seat_id']}={s['status']}" for s in seats])

            print("\n== 2. Seleccionar y crear HOLD (usr_a, VIP-A-001) ==")
            st, _, hb = await post(c, "/holds", {"user_id": "usr_a", "event_id": EVENT, "seat_ids": ["VIP-A-001"]}, {"Idempotency-Key": "g-a"})
            print("status", st, "hold_id", hb.get("hold_id"), "total", hb.get("total"), hb.get("currency"))

            print("\n== 3. Mostrar info de la reserva ==")
            _, info = await get(c, f"/holds/{hb['hold_id']}")
            print("hold", info.get("hold_id"), "user", info.get("user_id"), "seats", info.get("seat_ids"), "status", info.get("status"), "expires", info.get("expires_at"))

            print("\n== 4. Confirmar compra (payment_token) ==")
            await post(c, "/admin/payment/mode", {"mode": "always_approved"})
            st, _, co = await post(c, "/checkout", {"hold_id": hb["hold_id"], "user_id": "usr_a", "payment_token": "tok_gui"}, {"Idempotency-Key": "g-co"})
            print("checkout", st, co)
            _, s1 = await get(c, "/seats/VIP-A-001")
            print("VIP-A-001 status", s1.get("status"))

            print("\n== release (usr_b, VIP-A-002) ==")
            st, _, hb2 = await post(c, "/holds", {"user_id": "usr_b", "event_id": EVENT, "seat_ids": ["VIP-A-002"]}, {"Idempotency-Key": "g-b"})
            st, _, rl = await post(c, "/release", {"hold_id": hb2["hold_id"], "user_id": "usr_b"}, {"Idempotency-Key": "g-r"})
            print("release", st, rl)

            print("\n== 5. Simular carrera: 20 usuarios sobre VIP-A-003 ==")
            tasks = [post(c, "/holds", {"user_id": f"race_{i}", "event_id": EVENT, "seat_ids": ["VIP-A-003"]}, {"Idempotency-Key": f"race-{i}"}) for i in range(20)]
            res = await asyncio.gather(*tasks)
            wins = [r for r in res if r[0] == 201]
            rejs = [r for r in res if r[0] == 409]
            print(f"20 solicitudes -> {len(wins)} ganador, {len(rejs)} rechazadas")

            print("\n== Trazabilidad ==")
            _, tr = await get(c, "/admin/traceability", {"limit": "10"})
            print(f"{len(tr)} transiciones; ejemplo:", tr[0] if tr else None)
    finally:
        stop_server(server, thread)


if __name__ == "__main__":
    asyncio.run(main())
