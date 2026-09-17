"""
Motor de triage - Fases 1 y 2.
Procesa tickets, valida salida, maneja fallos y abstencion.
"""
import concurrent.futures
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from .schemas import (
    TriageResult, TicketInput, AuditRecord,
    CategoryEnum, PriorityEnum, SentimentEnum
)
from .glm_client import GLMClient

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {e.value for e in CategoryEnum}
VALID_PRIORITIES = {e.value for e in PriorityEnum}
VALID_SENTIMENTS = {e.value for e in SentimentEnum}


class TriageEngine:
    """Motor de triage con validacion, reintentos y abstencion."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.glm = GLMClient(config)
        self.confidence_threshold = config.get("confidence_threshold", 0.60)
        # Limite de peticiones concurrentes a GLM dentro de un mismo lote
        # (Bono B: concurrencia real sin exceder irresponsablemente la cuota).
        self.max_concurrent_requests = config.get("max_concurrent_requests", 5)
        self.audit_log: List[AuditRecord] = []

    def process_ticket(self, ticket: Dict[str, Any]) -> Dict[str, Any]:
        """Procesa un ticket individual y devuelve resultado + auditoria."""
        correlation_id = f"corr-{uuid.uuid4().hex[:6].upper()}"
        processed_at = datetime.now(timezone.utc).isoformat()

        # Validar entrada
        try:
            ticket_input = TicketInput(**ticket)
        except Exception as e:
            logger.warning(f"Ticket invalido: {e}")
            audit = AuditRecord(
                ticket_id=ticket.get("ticket_id", "UNKNOWN"),
                model=self.config.get("model", "glm-5.2"),
                attempts=0,
                validation_status="invalid_input",
                correlation_id=correlation_id,
                processed_at=processed_at,
                error=str(e)
            )
            self.audit_log.append(audit)
            return {
                "ticket_id": ticket.get("ticket_id", "UNKNOWN"),
                "error": f"Ticket invalido: {e}",
                "requires_human_review": True,
                "correlation_id": correlation_id
            }

        # Detectar prompt injection
        is_adversarial = self._detect_prompt_injection(ticket_input.text)

        # Clasificar con GLM
        glm_result = self.glm.classify_ticket(ticket_input.text)
        attempts = 1

        if glm_result is None:
            audit = AuditRecord(
                ticket_id=ticket_input.ticket_id,
                model=self.config.get("model", "glm-5.2"),
                attempts=attempts,
                validation_status="glm_failed",
                correlation_id=correlation_id,
                processed_at=processed_at,
                error="GLM no devolvio resultado valido"
            )
            self.audit_log.append(audit)
            return {
                "ticket_id": ticket_input.ticket_id,
                "error": "No se pudo clasificar el ticket",
                "requires_human_review": True,
                "correlation_id": correlation_id
            }

        # Validar y normalizar resultado
        validated = self._validate_result(glm_result, ticket_input.ticket_id)

        # Abstencion por baja confianza
        if validated.get("confidence", 0) < self.confidence_threshold:
            validated["requires_human_review"] = True
            logger.info(f"Ticket {ticket_input.ticket_id} marcado para revision humana (confianza {validated['confidence']})")

        # Si es adversarial, sobreescribir
        if is_adversarial:
            validated["requires_human_review"] = True
            validated["category"] = "Seguridad"
            validated["suggested_action"] = "Marcar para revision de seguridad. Contenido potencialmente malicioso."
            validated["suggested_response"] = "Hemos recibido su mensaje y lo estamos revisando con nuestro equipo de seguridad."
            logger.warning(f"Ticket {ticket_input.ticket_id} marcado como adversarial")

        # Construir resultado final
        result = {
            "ticket_id": ticket_input.ticket_id,
            "category": validated.get("category", "Otro"),
            "priority": validated.get("priority", "P3"),
            "sentiment": validated.get("sentiment", "neutral"),
            "product_or_module": validated.get("product_or_module", "N/A"),
            "summary": validated.get("summary", ""),
            "suggested_action": validated.get("suggested_action", ""),
            "suggested_response": validated.get("suggested_response", ""),
            "confidence": validated.get("confidence", 0.5),
            "requires_human_review": validated.get("requires_human_review", False),
            "correlation_id": correlation_id,
            "region": ticket_input.region,
            "customer_id": ticket_input.customer_id,
            "created_at": ticket_input.created_at,
            "original_text": ticket_input.text
        }

        audit = AuditRecord(
            ticket_id=ticket_input.ticket_id,
            model=self.config.get("model", "glm-5.2"),
            attempts=attempts,
            validation_status="valid" if not validated.get("requires_human_review") else "review",
            correlation_id=correlation_id,
            processed_at=processed_at
        )
        self.audit_log.append(audit)

        return result

    def process_batch(self, tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Procesa un lote de tickets concurrentemente (Bono B).

        Usa un ThreadPoolExecutor acotado por max_concurrent_requests para no
        exceder irresponsablemente la cuota del modelo. Los resultados se
        devuelven en el mismo orden que la entrada (indexados por posicion,
        no por orden de finalizacion), sin perder ni duplicar tickets. Un
        ticket malformado o que lance una excepcion no detiene el resto del
        lote.
        """
        if not tickets:
            return []

        results: List[Optional[Dict[str, Any]]] = [None] * len(tickets)
        max_workers = max(1, min(self.max_concurrent_requests, len(tickets)))

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(self.process_ticket, ticket): i
                for i, ticket in enumerate(tickets)
            }
            for future in concurrent.futures.as_completed(future_to_index):
                i = future_to_index[future]
                ticket = tickets[i]
                try:
                    results[i] = future.result()
                except Exception as e:
                    logger.error(f"Error procesando ticket {ticket.get('ticket_id', '?')}: {e}")
                    results[i] = {
                        "ticket_id": ticket.get("ticket_id", "UNKNOWN"),
                        "error": str(e),
                        "requires_human_review": True
                    }

        return results

    def _validate_result(self, glm_result: Dict[str, Any], ticket_id: str) -> Dict[str, Any]:
        """Valida y normaliza el resultado de GLM."""
        validated = {}

        # Categoria
        cat = glm_result.get("category", "Otro")
        validated["category"] = cat if cat in VALID_CATEGORIES else "Otro"
        if cat not in VALID_CATEGORIES:
            logger.warning(f"Ticket {ticket_id}: categoria invalida '{cat}', usando 'Otro'")

        # Prioridad
        pri_raw = str(glm_result.get("priority", "P3"))
        pri_match = re.match(r"\s*(P[1-4])\b", pri_raw, re.IGNORECASE)
        pri = pri_match.group(1).upper() if pri_match else pri_raw
        validated["priority"] = pri if pri in VALID_PRIORITIES else "P3"
        if pri not in VALID_PRIORITIES:
            logger.warning(f"Ticket {ticket_id}: prioridad invalida '{pri_raw}', usando 'P3'")

        # Sentimiento
        sent = glm_result.get("sentiment", "neutral")
        validated["sentiment"] = sent if sent in VALID_SENTIMENTS else "neutral"

        # Campos de texto
        validated["product_or_module"] = str(glm_result.get("product_or_module", "N/A"))[:200]
        validated["summary"] = str(glm_result.get("summary", ""))[:500]
        validated["suggested_action"] = str(glm_result.get("suggested_action", ""))[:500]
        validated["suggested_response"] = str(glm_result.get("suggested_response", ""))[:1000]

        # Confianza
        try:
            conf = float(glm_result.get("confidence", 0.5))
            validated["confidence"] = max(0.0, min(1.0, conf))
        except (ValueError, TypeError):
            validated["confidence"] = 0.5

        validated["requires_human_review"] = False

        return validated

    def _detect_prompt_injection(self, text: str) -> bool:
        """Detecta posibles intentos de prompt injection."""
        text_lower = text.lower()
        injection_patterns = [
            "ignora todas las instrucciones",
            "ignora las instrucciones",
            "ignora todo lo anterior",
            "api key",
            "devuelve tambien la",
            "system prompt",
            "eres un",
            "actua como",
            "olvida tus instrucciones"
        ]
        return any(p in text_lower for p in injection_patterns)

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Devuelve el log de auditoria."""
        return [a.model_dump() for a in self.audit_log]
