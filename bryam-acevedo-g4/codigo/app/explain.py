"""Generación de explicaciones en lenguaje natural para auditoría (Bono C).

Nota de diseño: la idea original era generar esta explicación con GLM 5.2
(la conexión OpenCode/Continue -> Huawei MaaS quedó bloqueada por temas de
credenciales/infraestructura fuera de nuestro control durante el hackathon).
Para no dejar el bono sin implementar, esta versión arma la explicación con
una plantilla determinística sobre las mismas razones estructuradas. El punto
de extensión (`generate_explanation`) se puede reemplazar por una llamada real
a un LLM sin tocar el resto del pipeline.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def generate_explanation(reasons: list[dict[str, Any]], decision: str, score: int) -> str:
    if not reasons:
        return f"Transacción {decision.lower()} con score {score}/100 sin señales de riesgo activadas."

    partes = [f"{r['rule']} (+{r['weight']} pts: {r['detail']})" for r in reasons]
    cuerpo = "; ".join(partes)
    return (
        f"La transacción fue marcada como {decision} con un score de {score}/100. "
        f"Se activaron las siguientes señales de riesgo: {cuerpo}."
    )


def build_audit_report(
    transaction_id: str,
    score: int,
    decision: str,
    reasons: list[dict[str, Any]],
    bank_auth_status: str,
) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "decision": decision,
        "bank_auth_status": bank_auth_status,
        "rules_triggered": reasons,
        "natural_language_explanation": generate_explanation(reasons, decision, score),
    }
