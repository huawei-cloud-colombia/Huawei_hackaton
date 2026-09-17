"""
config.py — Configuración del motor de reservas NEXUS LIVE.
Todos los parámetros son configurables mediante variables de entorno.
"""

import os
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class NexusConfig:
    """Configuración global del sistema de reservas."""

    # TTL de reservas temporales (segundos)
    hold_ttl_seconds: int = int(os.getenv("HOLD_TTL_SECONDS", "120"))

    # Máximo de asientos por usuario en reservas activas
    max_seats_per_user: int = int(os.getenv("MAX_SEATS_PER_USER", "6"))

    # Moneda por defecto
    currency: str = os.getenv("CURRENCY", "COP")

    # Evento por defecto
    default_event_id: str = os.getenv("DEFAULT_EVENT_ID", "aurora-bogota-2026")

    # --- Circuit Breaker ---
    cb_failure_threshold: int = int(os.getenv("CB_FAILURE_THRESHOLD", "3"))
    cb_recovery_timeout: int = int(os.getenv("CB_RECOVERY_TIMEOUT", "15"))

    # --- Mock de pagos (probabilidades) ---
    pay_prob_approved: float = float(os.getenv("PAY_PROB_APPROVED", "0.70"))
    pay_prob_declined: float = float(os.getenv("PAY_PROB_DECLINED", "0.10"))
    pay_prob_error: float = float(os.getenv("PAY_PROB_ERROR", "0.10"))
    pay_prob_timeout: float = float(os.getenv("PAY_PROB_TIMEOUT", "0.10"))
    pay_timeout_seconds: float = float(os.getenv("PAY_TIMEOUT_SECONDS", "2.0"))

    # --- PostgreSQL ---
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("DB_NAME", "nexus_live")
    db_user: str = os.getenv("DB_USER", "postgres")
    db_password: str = os.getenv("DB_PASSWORD", "postgres")

    @property
    def db_url(self) -> str:
        """URL de conexión asyncpg para PostgreSQL."""
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def db_dsn(self) -> str:
        """DSN para asyncpg."""
        return f"host={self.db_host} port={self.db_port} dbname={self.db_name} user={self.db_user} password={self.db_password}"

    # --- Catálogo de asientos (sección → (prefijo, cantidad, precio)) ---
    seat_sections: Dict[str, tuple] = field(default_factory=lambda: {
        "VIP-A": ("VIP-A", 10, 500000),   # 10 asientos VIP
        "A": ("A", 20, 210000),           # 20 asientos sección A
        "B": ("B", 20, 120000),           # 20 asientos sección B
    })


# Instancia global de configuración
config = NexusConfig()
