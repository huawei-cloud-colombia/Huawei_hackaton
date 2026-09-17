from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import uvicorn


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(app, port: int):
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", loop="asyncio", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, thread


def stop_server(server, thread):
    server.should_exit = True
    thread.join(timeout=15)


async def post(client, path, payload, headers=None):
    t0 = time.perf_counter()
    r = await client.post(path, json=payload, headers=headers or {})
    dt = (time.perf_counter() - t0) * 1000
    try:
        body = r.json()
    except Exception:
        body = {}
    return r.status_code, dt, body


async def get(client, path, params=None):
    r = await client.get(path, params=params or {})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


async def wait_ready(client, retries=60):
    for _ in range(retries):
        try:
            if (await client.get("/health")).status_code == 200:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.1)
    return False
