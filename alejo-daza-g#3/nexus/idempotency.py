from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .config import settings
from .models import Reason

CONFLICT_BODY = {
    "status": "REJECTED",
    "reason": Reason.IDEMPOTENCY_CONFLICT.value,
    "detail": "Idempotency-Key reused with a different payload",
}


@dataclass
class _Entry:
    future: asyncio.Future
    fingerprint: str
    created_at: float
    completed: bool = False
    status: int = 0
    body: dict | None = None


class IdempotencyStore:
    def __init__(self, ttl_seconds: int = settings.idempotency_ttl_seconds):
        self.ttl = ttl_seconds
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()
        self.executions = 0
        self.cache_hits = 0
        self.conflict_hits = 0

    async def run(self, key: str, fingerprint: str, coro_factory):
        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.fingerprint != fingerprint:
                self.conflict_hits += 1
                return 409, CONFLICT_BODY
            if entry is not None and entry.completed:
                self.cache_hits += 1
                return entry.status, entry.body
            if entry is not None:
                fut = entry.future
                is_leader = False
            else:
                fut = asyncio.get_running_loop().create_future()
                entry = _Entry(future=fut, fingerprint=fingerprint, created_at=time.monotonic())
                self._entries[key] = entry
                is_leader = True

        if not is_leader:
            return await fut

        try:
            self.executions += 1
            status, body, cache = await coro_factory()
        except Exception as e:
            async with self._lock:
                self._entries.pop(key, None)
            fut.set_exception(e)
            raise

        if cache:
            entry.completed = True
            entry.status = status
            entry.body = body
        else:
            async with self._lock:
                self._entries.pop(key, None)
        fut.set_result((status, body))
        return status, body

    async def cleanup(self) -> int:
        cutoff = time.monotonic() - self.ttl
        async with self._lock:
            stale = [k for k, e in self._entries.items() if e.created_at < cutoff and e.completed]
            for k in stale:
                del self._entries[k]
        return len(stale)

    def size(self) -> int:
        return len(self._entries)
