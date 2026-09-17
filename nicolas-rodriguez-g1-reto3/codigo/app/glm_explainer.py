"""
Bono D - Integración de GLM 5.2 dentro del producto.

Genera una explicación operacional estructurada a partir del historial
de una reserva: eventos de pago, cambios de estado y errores.

Maneja: timeout, respuesta vacía, error de API, formato inesperado.
"""
from __future__ import annotations

import os
from typing import Any

from .schemas import TraceEvent


class OperationsExplainer:
    """Genera explicaciones operacionales usando GLM 5.2 o fallback rule-based."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key or os.getenv("GLM_API_KEY", "")
        self._base_url = base_url or os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
        self._model = os.getenv("GLM_MODEL", "glm-5.2")

    def explain_hold_history(
        self,
        hold_id: str,
        trace_events: list[TraceEvent],
        hold_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generar explicación operacional estructurada.

        Intenta usar GLM 5.2 si hay API key, sino usa fallback rule-based.
        """
        events_summary = self._format_events(trace_events)

        if not self._api_key:
            return self._fallback_explain(hold_id, trace_events, hold_info, reason="no_api_key")

        try:
            return self._call_glm(hold_id, events_summary, hold_info)
        except TimeoutError:
            return self._fallback_explain(hold_id, trace_events, hold_info, reason="glm_timeout")
        except Exception as e:
            return self._fallback_explain(
                hold_id, trace_events, hold_info, reason=f"glm_error: {str(e)[:200]}"
            )

    def _format_events(self, events: list[TraceEvent]) -> str:
        lines = []
        for e in events:
            lines.append(
                f"  [{e.timestamp}] seat={e.seat_id} {e.from_state}→{e.to_state} reason={e.reason}"
            )
        return "\n".join(lines) if lines else "  (sin eventos)"

    def _call_glm(self, hold_id: str, events_summary: str, hold_info: dict[str, Any] | None) -> dict[str, Any]:
        """Llamar a GLM 5.2 para generar explicación."""
        import httpx

        prompt = self._build_prompt(hold_id, events_summary, hold_info)

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Eres un analista operacional de NEXUS LIVE, un motor de reservas. "
                        "Genera una explicación estructurada y concisa del historial de una reserva. "
                        "Responde en JSON con: summary, timeline, risk_assessment, recommendations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers, json=payload)

        if resp.status_code != 200:
            return self._fallback_explain(
                hold_id, [], hold_info, reason=f"glm_http_{resp.status_code}"
            )

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        if not content:
            return self._fallback_explain(hold_id, [], hold_info, reason="glm_empty_response")

        return {
            "ok": True,
            "source": "glm-5.2",
            "hold_id": hold_id,
            "explanation": content,
            "model": self._model,
        }

    def _build_prompt(self, hold_id: str, events_summary: str, hold_info: dict[str, Any] | None) -> str:
        parts = [f"Historial de la reserva {hold_id}:"]
        if hold_info:
            parts.append(f"Estado actual: {hold_info.get('status', 'desconocido')}")
            parts.append(f"Usuario: {hold_info.get('user_id', 'desconocido')}")
            parts.append(f"Asientos: {hold_info.get('seat_ids', [])}")
            parts.append(f"Total: {hold_info.get('total_price', 0)} {hold_info.get('currency', 'COP')}")
        parts.append(f"\nEventos de trazabilidad:\n{events_summary}")
        parts.append("\nGenera una explicación operacional estructurada.")
        return "\n".join(parts)

    def _fallback_explain(
        self,
        hold_id: str,
        events: list[TraceEvent],
        hold_info: dict[str, Any] | None,
        reason: str = "fallback",
    ) -> dict[str, Any]:
        """Explicación rule-based cuando GLM no está disponible."""
        timeline = []
        for e in events:
            timeline.append(
                f"[{e.timestamp}] Asiento {e.seat_id}: {e.from_state} → {e.to_state} ({e.reason})"
            )

        # Análisis de riesgo
        risks = []
        has_timeout = any("timeout" in e.reason.lower() for e in events)
        has_error = any("error" in e.reason.lower() for e in events)
        has_expired = any("expired" in e.reason.lower() for e in events)
        has_sold = any(e.to_state == "SOLD" for e in events)

        if has_timeout:
            risks.append("Se detectó un timeout - el cliente debería reintentar con idempotencia")
        if has_error:
            risks.append("Se detectaron errores - verificar salud del proveedor de pagos")
        if has_expired:
            risks.append("HOLD expirado - los asientos fueron liberados automáticamente")
        if not has_sold and not has_expired:
            risks.append("La reserva no fue confirmada - verificar estado del pago")
        if not risks:
            risks.append("Sin riesgos detectados - flujo normal")

        # Recomendaciones
        recommendations = []
        if has_timeout or has_error:
            recommendations.append("Reintentar la confirmación con el mismo payment_token")
            recommendations.append("Verificar estado del circuit breaker")
        if has_expired:
            recommendations.append("Crear un nuevo HOLD si el usuario aún desea reservar")
        if not recommendations:
            recommendations.append("No se requieren acciones adicionales")

        summary_parts = [f"Reserva {hold_id} con {len(events)} eventos."]
        if hold_info:
            summary_parts.append(f"Estado: {hold_info.get('status', 'desconocido')}.")
        if has_sold:
            summary_parts.append("Compra confirmada exitosamente.")
        elif has_expired:
            summary_parts.append("Reserva expirada sin confirmar.")

        return {
            "ok": True,
            "source": "fallback",
            "hold_id": hold_id,
            "explanation": {
                "summary": " ".join(summary_parts),
                "timeline": timeline,
                "risk_assessment": risks,
                "recommendations": recommendations,
            },
            "fallback_reason": reason,
        }
