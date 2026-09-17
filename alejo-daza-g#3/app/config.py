from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = os.environ.get("SEATLOCK_DB_PATH", "seatlock.db")
    hold_ttl_seconds: int = int(os.environ.get("SEATLOCK_HOLD_TTL", "120"))
    max_seats_per_user: int = int(os.environ.get("SEATLOCK_MAX_SEATS", "6"))
    sweeper_interval_seconds: int = int(os.environ.get("SEATLOCK_SWEEPER_INTERVAL", "5"))
    server_host: str = os.environ.get("SEATLOCK_HOST", "127.0.0.1")
    server_port: int = int(os.environ.get("SEATLOCK_PORT", "8000"))


settings = Settings()
