"""Bono C - Explicabilidad exportable.

Por cada pedido ``REJECTED``, genera un reporte estructurado (JSON) apto para
el equipo de soporte: reglas activadas, estado de los repartidores en ese
momento, timestamp, y una explicacion en lenguaje natural (via ``GLMClient``)
para responderle directamente al cliente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .glm_client import GLMClient


class RejectionReporter:
    def __init__(self, glm_client: GLMClient) -> None:
        self.glm = glm_client

    def build_report(self, order: dict, result: dict, couriers_snapshot: list[dict]) -> dict[str, Any]:
        report: dict[str, Any] = {
            "order_id": result["order_id"],
            "status": result["status"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "rules_triggered": result["reasons"],
            "couriers_state_snapshot": couriers_snapshot,
            "order_context": {
                "pickup_zone": order.get("pickup_zone"),
                "priority": order.get("priority"),
                "distance_km": order.get("distance_km"),
                "timestamp": order.get("timestamp"),
            },
        }
        report["customer_explanation"] = self.glm.explain_rejection(report)
        return report
