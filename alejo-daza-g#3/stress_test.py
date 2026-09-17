from __future__ import annotations

import asyncio
import os
import socket
import sys
import tempfile
import threading
import time

DB = os.path.join(tempfile.gettempdir(), "nexus_stress.db")
for ext in ("", "-wal", "-shm"):
    p = DB + ext
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass
os.environ["NEXUS_DB_PATH"] = DB
os.environ.setdefault("NEXUS_HOLD_TTL", "600")
os.environ.setdefault("NEXUS_REAPER_INTERVAL", "0.5")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from nexus.main import app  # noqa: E402

EVENT = "nexus-live-2026"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _start_server(port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread


def _stop_server(server, thread):
    server.should_exit = True
    thread.join(timeout=10)


def _percentile(values, p):
    if not values:
        return 0.0
    xs = sorted(values)
    k = max(0, min(len(xs) - 1, int(round(p * (len(xs) - 1)))))
    return xs[k]


async def _post(client, path, payload, headers=None):
    t0 = time.perf_counter()
    r = await client.post(path, json=payload, headers=headers or {})
    dt = (time.perf_counter() - t0) * 1000
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, dt, body


async def run_stress(n: int = 500, seat: str = "VIP-0001") -> dict:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    server, thread = _start_server(port)

    limits = httpx.Limits(max_connections=max(1000, n + 10), max_keepalive_connections=100)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15.0, limits=limits) as client:
            for _ in range(40):
                try:
                    h = await client.get("/health")
                    if h.status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)

            tasks = [
                _post(client, "/holds", {"user_id": f"u{i}", "event_id": EVENT, "seat_ids": [seat]}, {"Idempotency-Key": f"race-{i}"})
                for i in range(n)
            ]
            results = await asyncio.gather(*tasks)
            latencies = [dt for _, dt, _ in results]
            statuses = [st for st, _, _ in results]
            wins = [b for st, _, b in results if st == 201]
            rejects = [b for st, _, b in results if st == 409]

            winner_hold = wins[0]["hold_id"] if wins else None
            checkout_status = None
            if winner_hold:
                await _post(client, "/admin/payment/mode", {"mode": "always_approved"})
                cst, _, _ = await _post(client, "/checkout", {"hold_id": winner_hold, "user_id": wins[0]["user_id"], "payment_token": "tok_winner"}, {"Idempotency-Key": f"co-{winner_hold}"})
                checkout_status = cst

            await asyncio.sleep(0.3)
            stats = (await client.get("/admin/stats")).json()
            bench = (await client.get("/admin/bench", params={"cycles": 300})).json()

            idem_seat = "VIP-0002"
            dup_key = "duplicate-key-xyz"
            idem_tasks = [
                _post(client, "/holds", {"user_id": "idem-user", "event_id": EVENT, "seat_ids": [idem_seat]}, {"Idempotency-Key": dup_key})
                for _ in range(2)
            ]
            idem_results = await asyncio.gather(*idem_tasks)
    finally:
        _stop_server(server, thread)

    report = {
        "n": n,
        "seat": seat,
        "winners_201": statuses.count(201),
        "rejected_409": statuses.count(409),
        "other": [st for st in statuses if st not in (201, 409)],
        "checkout_status": checkout_status,
        "writer_events_processed": stats["writer_events_processed"],
        "writer_errors": stats["writer_errors"],
        "writer_queue_depth": stats["writer_queue_depth"],
        "sold_in_memory": stats["sold"],
        "held_in_memory": stats["held"],
        "latency_ms_p50": round(_percentile(latencies, 0.50), 3),
        "latency_ms_p99": round(_percentile(latencies, 0.99), 3),
        "latency_ms_max": round(max(latencies), 3),
        "idem_status_codes": [st for st, _, _ in idem_results],
        "idem_same_hold": idem_results[0][2].get("hold_id") == idem_results[1][2].get("hold_id"),
        "idem_hold_id": idem_results[0][2].get("hold_id"),
        "engine_p99_ms": bench["p99_ms"],
        "engine_p50_us": bench["p50_us"],
        "engine_p99_us": bench["p99_us"],
    }
    return report


def _print(report: dict) -> None:
    print("\n" + "=" * 60)
    print(" NEXUS Live — Stress Test")
    print("=" * 60)
    print(f" Asiento disputado        : {report['seat']}")
    print(f" Intentos concurrentes    : {report['n']}")
    print(f" Ganadores (201)          : {report['winners_201']}   (esperado: 1)")
    print(f" Rechazados (409)         : {report['rejected_409']}  (esperado: {report['n'] - 1})")
    print(f" Otros status             : {report['other']}")
    print(f" Checkout del ganador     : HTTP {report['checkout_status']}  (esperado: 200 SOLD)")
    print("-" * 60)
    print(f" SQLite eventos volcados  : {report['writer_events_processed']}")
    print(f" SQLite errores ('locked'): {report['writer_errors']}   (esperado: 0)")
    print(f" Asientos SOLD en RAM     : {report['sold_in_memory']}")
    print(f" Latencia p50 / p99 / max : {report['latency_ms_p50']} / {report['latency_ms_p99']} / {report['latency_ms_max']} ms")
    print(f" Motor en RAM p50 / p99     : {report['engine_p50_us']} / {report['engine_p99_us']} us  (p99 = {report['engine_p99_ms']} ms, meta <5ms)")
    print("-" * 60)
    print(f" Idempotencia misma key   : status={report['idem_status_codes']} same_hold={report['idem_same_hold']} hold={report['idem_hold_id']}")
    ok = (
        report["winners_201"] == 1
        and report["rejected_409"] == report["n"] - 1
        and report["writer_errors"] == 0
        and report["checkout_status"] == 200
        and report["idem_same_hold"] is True
        and report["idem_status_codes"] == [201, 201]
    )
    print("=" * 60)
    print(" RESULTADO: " + ("PASS" if ok else "FAIL"))
    print("=" * 60)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    rep = asyncio.run(run_stress(n=n))
    _print(rep)
