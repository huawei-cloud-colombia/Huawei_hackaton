import threading
import contextlib

import config


class QueueFullError(Exception):
    pass


class SessionQueue:
    def __init__(self, max_concurrent=None):
        if max_concurrent is None:
            max_concurrent = config.QUEUE_MAX_CONCURRENT
        self._max = max_concurrent
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._active = 0
        self._queued = 0
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def session(self, timeout=None):
        with self._lock:
            self._queued += 1
        acquired = self._semaphore.acquire(timeout=timeout)
        with self._lock:
            self._queued -= 1
            if acquired:
                self._active += 1
        if not acquired:
            raise QueueFullError("queue_full")
        try:
            yield
        finally:
            self._semaphore.release()
            with self._lock:
                self._active -= 1

    def stats(self):
        with self._lock:
            return {
                "max_concurrent": self._max,
                "active": self._active,
                "queued": self._queued,
            }


session_queue = SessionQueue()
