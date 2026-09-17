"""
Configuracion de SentinelPay Risk Engine.

Carga la configuracion de reglas desde un archivo YAML y
variables de entorno (.env).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class Settings:
    """
    Configuracion centralizada del motor de riesgo.

    Carga:
        - Variables de entorno desde .env (si existe).
        - Configuracion de reglas desde YAML.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        load_dotenv()

        if config_path is None:
            env_path = os.getenv("SENTINELPAY_RULES_CONFIG", "")
            if env_path:
                config_path = Path(env_path)
            else:
                config_path = Path(__file__).parent / "rules_config.yaml"

        self.config_path = Path(config_path)
        self._config: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """Recarga la configuracion desde el archivo YAML."""
        with open(self.config_path, encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

    @property
    def rules_config(self) -> dict[str, Any]:
        """Configuracion de las reglas."""
        return self._config.get("rules", {})

    @property
    def scoring_config(self) -> dict[str, Any]:
        """Configuracion del motor de scoring."""
        return self._config.get("scoring", {})

    @property
    def default_timezone(self) -> str:
        """Zona horaria por defecto desde .env o YAML."""
        return os.getenv(
            "SENTINELPAY_DEFAULT_TIMEZONE",
            self.rules_config.get("unusual_hour", {}).get("default_timezone", "UTC"),
        )

    @property
    def reject_threshold(self) -> int:
        """Umbral de score para REJECT."""
        env_val = os.getenv("SENTINELPAY_REJECT_THRESHOLD")
        if env_val is not None:
            return int(env_val)
        return int(self.scoring_config.get("reject_threshold", 50))

    @property
    def review_threshold(self) -> int:
        """Umbral de score para REVIEW."""
        env_val = os.getenv("SENTINELPAY_REVIEW_THRESHOLD")
        if env_val is not None:
            return int(env_val)
        return int(self.scoring_config.get("review_threshold", 0))

    def get_rule_config(self, rule_name: str) -> dict[str, Any]:
        """Obtiene la configuracion de una regla especifica."""
        return self.rules_config.get(rule_name, {})
