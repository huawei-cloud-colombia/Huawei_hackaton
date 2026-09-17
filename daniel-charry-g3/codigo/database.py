"""
database.py — Conexión a PostgreSQL y esquema de la base de datos NEXUS LIVE.

Tablas:
  - seats: catálogo de asientos (seat_id, section, price, currency, status, hold_id)
  - holds: reservas temporales (hold_id, user_id, event_id, seat_ids, status, total, ...)
  - idempotency: cache de idempotencia (key, payload_hash, result_json)
  - audit_events: trazabilidad de cambios de estado

Usa asyncpg para operaciones asíncronas compatibles con FastAPI.
"""

import json
import asyncpg
from typing import Optional
from config import config


# ─── Esquema SQL ──────────────────────────────────────────────

SCHEMA_SQL = """
-- Tabla de asientos
CREATE TABLE IF NOT EXISTS seats (
    seat_id    VARCHAR(50) PRIMARY KEY,
    section    VARCHAR(50) NOT NULL,
    price      INTEGER NOT NULL,
    currency   VARCHAR(10) NOT NULL DEFAULT 'COP',
    status     VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
    hold_id    VARCHAR(50),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de reservas (HOLDs)
CREATE TABLE IF NOT EXISTS holds (
    hold_id    VARCHAR(50) PRIMARY KEY,
    user_id    VARCHAR(100) NOT NULL,
    event_id   VARCHAR(100) NOT NULL,
    seat_ids   JSONB NOT NULL,
    status     VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    total      INTEGER NOT NULL,
    currency   VARCHAR(10) NOT NULL DEFAULT 'COP',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de idempotencia
CREATE TABLE IF NOT EXISTS idempotency (
    key          VARCHAR(200) PRIMARY KEY,
    payload_hash VARCHAR(64) NOT NULL,
    result_json  JSONB NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Tabla de auditoría / trazabilidad
CREATE TABLE IF NOT EXISTS audit_events (
    id         SERIAL PRIMARY KEY,
    hold_id    VARCHAR(50),
    user_id    VARCHAR(100),
    seat_id    VARCHAR(50),
    from_state VARCHAR(20),
    to_state   VARCHAR(20),
    reason     VARCHAR(100) NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extra      JSONB
);

-- Índices para concurrencia y consultas frecuentes
CREATE INDEX IF NOT EXISTS idx_seats_status ON seats(status);
CREATE INDEX IF NOT EXISTS idx_seats_hold_id ON seats(hold_id);
CREATE INDEX IF NOT EXISTS idx_holds_user_id ON holds(user_id);
CREATE INDEX IF NOT EXISTS idx_holds_status ON holds(status);
CREATE INDEX IF NOT EXISTS idx_holds_expires_at ON holds(expires_at);
CREATE INDEX IF NOT EXISTS idx_audit_hold_id ON audit_events(hold_id);
CREATE INDEX IF NOT EXISTS idx_audit_seat_id ON audit_events(seat_id);
"""


# ─── Pool de conexiones ──────────────────────────────────────

_pool: Optional[asyncpg.Pool] = None


async def init_db():
    """Inicializa el pool de conexiones y crea el esquema si no existe."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=config.db_dsn,
        min_size=2,
        max_size=10,
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        # Inicializar asientos si la tabla está vacía
        count = await conn.fetchval("SELECT COUNT(*) FROM seats")
        if count == 0:
            await _init_seats(conn)


async def _init_seats(conn: asyncpg.Connection):
    """Puebla la tabla de asientos desde la configuración."""
    for section_name, (prefix, count, price) in config.seat_sections.items():
        for i in range(1, count + 1):
            seat_id = f"{prefix}-{i:03d}"
            await conn.execute(
                """INSERT INTO seats (seat_id, section, price, currency, status)
                   VALUES ($1, $2, $3, $4, 'AVAILABLE')
                   ON CONFLICT (seat_id) DO NOTHING""",
                seat_id, section_name, price, config.currency,
            )


async def close_db():
    """Cierra el pool de conexiones."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    """Retorna el pool de conexiones."""
    if _pool is None:
        await init_db()
    return _pool


async def reset_db():
    """Reinicia todas las tablas (para demo)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM audit_events")
        await conn.execute("DELETE FROM idempotency")
        await conn.execute("DELETE FROM holds")
        await conn.execute("DELETE FROM seats")
        await _init_seats(conn)
