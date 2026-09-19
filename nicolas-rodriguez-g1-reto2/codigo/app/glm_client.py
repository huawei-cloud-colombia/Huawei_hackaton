"""Cliente para GLM 5.2 (Bono C - explicabilidad exportable).

Traduce un reporte estructurado de un pedido ``REJECTED`` (reglas activadas,
estado de los repartidores, contexto del pedido) en una explicacion breve en
lenguaje natural para el cliente final, sin tecnicismos internos.

Si no hay ``GLM_API_KEY`` configurada en el entorno, opera en **modo demo**
usando plantillas locales basadas en las reglas activadas -- para que el
proyecto funcione de punta a punta sin depender de credenciales durante la
evaluacion. Con la API key presente, llama a GLM 5.2 de verdad.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

EXPLAIN_SYSTEM_PROMPT = """Eres un asistente de soporte de QuickBite (app de domicilios).
Recibes un reporte JSON sobre por que un pedido no pudo asignarse a un repartidor de inmediato.
Escribe una explicacion breve (2 a 4 frases), clara y empatica, en espanol, dirigida al cliente.
No menciones tecnicismos internos (nada de "circuit breaker", "sliding window", "surge",
nombres de reglas en ingles ni codigos internos).
Si el estado es QUEUED, transmite que el pedido sigue activo y se reintentara.
Si el estado es REJECTED por saturacion, explica que hubo una demanda temporal muy alta.
Devuelve SOLO el texto de la explicacion, sin JSON, sin comillas, sin markdown."""


class GLMClient:
    def __init__(self, config: dict) -> None:
        cfg = config.get("glm", {})
        self.api_key = os.environ.get(cfg.get("api_key_env_var", "GLM_API_KEY"), "")
        self.api_base = cfg.get("api_base_url", "http://149.232.135.126:4000/v1")
        self.model = cfg.get("model", "glm-5.2")
        self.temperature = cfg.get("temperature", 0.2)
        self.max_tokens = cfg.get("max_tokens", 400)
        self.timeout = cfg.get("timeout_seconds", 20)
        self.demo_mode = not bool(self.api_key)
        if self.demo_mode:
            logger.info("GLM_API_KEY no configurada: explain_rejection usara plantillas locales (modo demo).")

    def explain_rejection(self, report: dict[str, Any]) -> str:
        if self.demo_mode:
            return self._demo_explain(report)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(report, ensure_ascii=False, default=str)},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.api_base}/chat/completions", json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # servicio externo: cualquier fallo degrada a la plantilla local
            logger.warning("Fallo llamando a GLM 5.2 (%s); usando explicacion local.", exc)
            return self._demo_explain(report)

    def _demo_explain(self, report: dict[str, Any]) -> str:
        rules = {r["rule"] for r in report.get("rules_triggered", [])}
        status = report.get("status")

        if "surge_protection_active" in rules or "surge_window_active" in rules:
            return (
                "En este momento tenemos una demanda muy alta y todos nuestros repartidores estan ocupados. "
                "Por seguridad del servicio tu pedido no pudo tomarse de inmediato; la demanda deberia "
                "normalizarse en pocos minutos. Lamentamos el inconveniente."
            )
        if "all_couriers_at_capacity" in rules and status == "QUEUED":
            return (
                "Todos los repartidores cercanos estan al maximo de su capacidad en este momento. Tu pedido "
                "quedo en espera y sera asignado automaticamente en cuanto se libere un repartidor."
            )
        if "no_couriers_available" in rules:
            return (
                "No encontramos repartidores disponibles en tu zona en este momento. Estamos trabajando para "
                "resolverlo; por favor intenta de nuevo en unos minutos."
            )
        if any(r.startswith("invalid_") for r in rules):
            return (
                "Tu pedido no pudo procesarse porque algunos datos no son validos. Por favor verifica la "
                "informacion e intenta de nuevo; si el problema persiste, contacta a soporte."
            )
        return (
            "Tu pedido no pudo procesarse automaticamente por una condicion temporal del sistema de "
            "asignacion. Nuestro equipo de soporte puede revisar el detalle si lo necesitas."
        )
