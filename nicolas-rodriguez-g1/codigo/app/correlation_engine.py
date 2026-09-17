"""
Motor de correlacion - Fase 3.
Agrupa tickets relacionados, detecta incidentes mayores y reprioriza.
"""
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict

from .schemas import IncidentGroupSummary
from .glm_client import GLMClient

logger = logging.getLogger(__name__)

PRIORITY_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


class CorrelationEngine:
    """Motor de correlacion de tickets e identificacion de incidentes."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config.get("correlation", {})
        self.enabled = self.config.get("enabled", True)
        self.time_window = self.config.get("time_window_minutes", 10)
        self.min_tickets = self.config.get("min_tickets_for_major", 5)
        self.min_priority = self.config.get("min_priority_for_major", ["P1", "P2"])
        self.similarity_threshold = self.config.get("similarity_threshold", 0.65)
        self.glm = GLMClient(config)

    def correlate(self, tickets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Correlaciona tickets y devuelve grupos de incidentes."""
        if not self.enabled or len(tickets) < 2:
            return []

        # Intentar correlacion con GLM
        glm_groups = self.glm.correlate_tickets(tickets)
        groups = []

        if glm_groups and "groups" in glm_groups:
            for i, g in enumerate(glm_groups["groups"]):
                group_tickets = [t for t in tickets if t.get("ticket_id") in g.get("ticket_ids", [])]
                if len(group_tickets) < 2:
                    continue

                group_summary = self._build_group_summary(f"INC-{i+1:03d}", g, group_tickets)
                groups.append(group_summary)
        else:
            # Fallback: correlacion por reglas
            groups = self._rule_based_correlation(tickets)

        # Detectar incidentes mayores
        for group in groups:
            group["major_incident_candidate"] = self._is_major_incident(group, tickets)
            if group["major_incident_candidate"]:
                group["operational_priority"] = self._compute_operational_priority(group, tickets)

        return groups

    def assign_groups_to_tickets(
        self, tickets: List[Dict[str, Any]], groups: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Asigna incident_group_id a cada ticket."""
        ticket_to_group = {}
        for g in groups:
            for tid in g.get("ticket_ids", []):
                ticket_to_group[tid] = g["incident_group_id"]

        for t in tickets:
            t["incident_group_id"] = ticket_to_group.get(t.get("ticket_id"))

        return tickets

    def _build_group_summary(
        self, group_id: str, glm_data: Dict, tickets: List[Dict]
    ) -> Dict[str, Any]:
        """Construye el resumen de un grupo."""
        priorities = [t.get("priority", "P4") for t in tickets]
        highest = min(priorities, key=lambda p: PRIORITY_ORDER.get(p, 4))

        regions = list(set(t.get("region", "unknown") for t in tickets))

        return {
            "incident_group_id": group_id,
            "title": glm_data.get("title", "Incidente correlacionado"),
            "ticket_count": len(tickets),
            "highest_priority": highest,
            "affected_module": glm_data.get("affected_module", tickets[0].get("product_or_module", "N/A")),
            "affected_region": ", ".join(regions),
            "summary": glm_data.get("summary", ""),
            "major_incident_candidate": False,
            "ticket_ids": [t.get("ticket_id") for t in tickets]
        }

    def _rule_based_correlation(self, tickets: List[Dict]) -> List[Dict]:
        """Correlacion por reglas: categoria + modulo + region + ventana temporal."""
        groups = []
        seen = set()

        for i, t1 in enumerate(tickets):
            if t1.get("ticket_id") in seen:
                continue

            group = [t1]
            seen.add(t1.get("ticket_id"))

            for j, t2 in enumerate(tickets[i+1:], i+1):
                if t2.get("ticket_id") in seen:
                    continue

                if self._are_related(t1, t2):
                    group.append(t2)
                    seen.add(t2.get("ticket_id"))

            if len(group) > 1:
                priorities = [t.get("priority", "P4") for t in group]
                highest = min(priorities, key=lambda p: PRIORITY_ORDER.get(p, 4))
                regions = list(set(t.get("region", "unknown") for t in group))

                groups.append({
                    "incident_group_id": f"INC-{len(groups)+1:03d}",
                    "title": group[0].get("summary", "Incidente correlacionado"),
                    "ticket_count": len(group),
                    "highest_priority": highest,
                    "affected_module": group[0].get("product_or_module", "N/A"),
                    "affected_region": ", ".join(regions),
                    "summary": f"{len(group)} tickets relacionados: {group[0].get('summary', '')}",
                    "major_incident_candidate": False,
                    "ticket_ids": [t.get("ticket_id") for t in group]
                })

        return groups

    def _are_related(self, t1: Dict, t2: Dict) -> bool:
        """Determina si dos tickets estan relacionados."""
        # Misma categoria
        if t1.get("category") != t2.get("category"):
            return False

        # Mismo modulo
        same_module = t1.get("product_or_module", "") == t2.get("product_or_module", "")

        # Misma region
        same_region = t1.get("region", "") == t2.get("region", "")

        # Similitud de texto
        text1 = t1.get("original_text") or t1.get("text", "")
        text2 = t2.get("original_text") or t2.get("text", "")
        sim = self._text_similarity(text1, text2)

        # Ventana temporal
        time_close = self._time_close(t1.get("created_at", ""), t2.get("created_at", ""))

        return (same_module or same_region) and sim >= 0.15 and time_close

    def _text_similarity(self, text1: str, text2: str) -> float:
        """Similitud simple basada en palabras compartidas (coeficiente Jaccard)."""
        stop = {"el", "la", "los", "las", "de", "del", "y", "a", "en", "que", "no", "con", "por", "para", "es", "se", "una", "un", "desde", "las", "lo", "al", "su", "sus"}
        words1 = set(re.findall(r'\b\w+\b', text1.lower())) - stop
        words2 = set(re.findall(r'\b\w+\b', text2.lower())) - stop

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def _time_close(self, ts1: str, ts2: str) -> bool:
        """Verifica si dos timestamps estan dentro de la ventana temporal."""
        try:
            dt1 = datetime.fromisoformat(ts1.replace("Z", "+00:00"))
            dt2 = datetime.fromisoformat(ts2.replace("Z", "+00:00"))
            diff = abs((dt1 - dt2).total_seconds()) / 60
            return diff <= self.time_window
        except Exception:
            return True

    def _is_major_incident(self, group: Dict, all_tickets: List[Dict]) -> bool:
        """Determina si un grupo es un incidente mayor."""
        ticket_ids = set(group.get("ticket_ids", []))
        relevant = [t for t in all_tickets if t.get("ticket_id") in ticket_ids]

        high_priority_count = sum(
            1 for t in relevant
            if t.get("priority") in self.min_priority
        )

        return (
            high_priority_count >= self.min_tickets
            and group.get("ticket_count", 0) >= 2
        )

    def _compute_operational_priority(self, group: Dict, all_tickets: List[Dict]) -> str:
        """Computa prioridad operacional del incidente (blast radius)."""
        ticket_ids = set(group.get("ticket_ids", []))
        relevant = [t for t in all_tickets if t.get("ticket_id") in ticket_ids]

        p1_count = sum(1 for t in relevant if t.get("priority") == "P1")
        total = len(relevant)

        if p1_count >= 2 or total >= 10:
            return "P1"
        elif total >= 5:
            return "P2"
        else:
            return group.get("highest_priority", "P3")
