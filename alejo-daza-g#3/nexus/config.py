from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = os.environ.get("NEXUS_DB_PATH", "nexus.db")
    event_id: str = os.environ.get("NEXUS_EVENT_ID", "nexus-live-2026")
    currency: str = os.environ.get("NEXUS_CURRENCY", "COP")

    hold_ttl_seconds: int = int(os.environ.get("NEXUS_HOLD_TTL", "600"))
    max_seats_per_user: int = int(os.environ.get("NEXUS_MAX_SEATS", "6"))

    num_shards: int = int(os.environ.get("NEXUS_SHARDS", "256"))
    reaper_interval_seconds: float = float(os.environ.get("NEXUS_REAPER_INTERVAL", "0.5"))

    writer_batch_size: int = int(os.environ.get("NEXUS_WRITER_BATCH", "200"))
    writer_flush_ms: int = int(os.environ.get("NEXUS_WRITER_FLUSH_MS", "50"))

    idempotency_ttl_seconds: int = int(os.environ.get("NEXUS_IDEM_TTL", "3600"))
    idempotency_cleanup_interval_seconds: float = float(os.environ.get("NEXUS_IDEM_CLEANUP", "60"))

    server_host: str = os.environ.get("NEXUS_HOST", "127.0.0.1")
    server_port: int = int(os.environ.get("NEXUS_PORT", "8000"))

    seat_sections: tuple = (
        ("PREMIUM", "VIP-A", 10, 2_500_000, 3),
        ("VIP", "VIP", 2000, 1_500_000, 4),
        ("PLATEA", "PLA", 10000, 650_000, 4),
        ("GENERAL", "GEN", 30000, 250_000, 4),
    )

    cb_failure_threshold: int = int(os.environ.get("NEXUS_CB_FAILURES", "3"))
    cb_recovery_seconds: float = float(os.environ.get("NEXUS_CB_RECOVERY", "15"))

    pay_prob_approved: float = float(os.environ.get("NEXUS_PAY_APPROVED", "0.70"))
    pay_prob_declined: float = float(os.environ.get("NEXUS_PAY_DECLINED", "0.10"))
    pay_prob_error: float = float(os.environ.get("NEXUS_PAY_ERROR", "0.10"))
    pay_prob_timeout: float = float(os.environ.get("NEXUS_PAY_TIMEOUT_PROB", "0.10"))
    pay_timeout_seconds: float = float(os.environ.get("NEXUS_PAY_TIMEOUT", "2.0"))


settings = Settings()
TOTAL_SEATS = sum(c for _, _, c, _, _ in settings.seat_sections)
