"""Motor de scoring de riesgo (Fases 1, 2 y 3 + Bono A).

Diseño de concurrencia (Bono B): un único `threading.RLock` protege las
estructuras compartidas (ventanas deslizantes, blocklist, promedios por
tarjeta). La sección crítica solo cubre operaciones en memoria (sin I/O),
por lo que es muy corta; la llamada al banco simulado se hace *fuera* del
lock para no serializar innecesariamente las evaluaciones concurrentes.
"""
from __future__ import annotations

import copy
import threading
import time
from collections import deque
from typing import Any

from app.bank import CircuitBreaker, mock_bank_auth
from app.config import DEFAULT_CONFIG
from app.explain import build_audit_report


def _trim(window: deque, now: float, window_seconds: float) -> None:
    while window and (now - window[0][0] if isinstance(window[0], tuple) else now - window[0]) > window_seconds:
        window.popleft()


class RiskEngine:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = copy.deepcopy(config) if config else copy.deepcopy(DEFAULT_CONFIG)

        self._lock = threading.RLock()
        self.card_amount_stats: dict[str, tuple[int, float]] = {}
        self.card_velocity_window: dict[str, deque] = {}
        self.device_card_window: dict[str, deque] = {}
        self.ip_card_window: dict[str, deque] = {}
        self.blocklist: dict[str, float] = {}
        self.audit_reports: dict[str, dict[str, Any]] = {}

        bcfg = self.config["circuit_breaker"]
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=bcfg["failure_threshold"],
            open_duration_seconds=bcfg["open_duration_seconds"],
        )

    def reset(self) -> None:
        with self._lock:
            self.card_amount_stats.clear()
            self.card_velocity_window.clear()
            self.device_card_window.clear()
            self.ip_card_window.clear()
            self.blocklist.clear()
            self.audit_reports.clear()
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=self.config["circuit_breaker"]["failure_threshold"],
                open_duration_seconds=self.config["circuit_breaker"]["open_duration_seconds"],
            )

    @staticmethod
    def _now() -> float:
        return time.monotonic()

    def _is_blocked(self, key: str, now: float) -> bool:
        expiry = self.blocklist.get(key)
        if expiry is None:
            return False
        if now >= expiry:
            del self.blocklist[key]
            return False
        return True

    def evaluate(self, txn: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        card_key = f"card:{txn['card_id']}"
        device_key = f"device:{txn['device_id']}"

        with self._lock:
            if self._is_blocked(card_key, now):
                return self._blocked_result(txn, "card_temporarily_blocked")
            if self._is_blocked(device_key, now):
                return self._blocked_result(txn, "device_temporarily_blocked")

            score = 0
            reasons: list[dict[str, Any]] = []
            hard_decline = False

            rules = self.config["rules"]

            # --- Regla 1: monto anómalo (usa historial ANTES de esta transacción) ---
            cfg = rules["amount_anomaly"]
            count, total = self.card_amount_stats.get(txn["card_id"], (0, 0.0))
            if cfg["enabled"] and count > 0:
                avg = total / count
                if avg > 0 and txn["amount"] > cfg["multiplier"] * avg:
                    score += cfg["weight"]
                    reasons.append(
                        {
                            "rule": "amount_anomaly",
                            "weight": cfg["weight"],
                            "detail": f"amount={txn['amount']} > {cfg['multiplier']}x avg_hist={avg:.2f}",
                        }
                    )
            self.card_amount_stats[txn["card_id"]] = (count + 1, total + txn["amount"])

            # --- Regla 2: país distinto ---
            cfg = rules["country_mismatch"]
            if cfg["enabled"] and txn["country"] != txn["ip_country"]:
                score += cfg["weight"]
                reasons.append(
                    {
                        "rule": "country_mismatch",
                        "weight": cfg["weight"],
                        "detail": f"card_country={txn['country']}, ip_country={txn['ip_country']}",
                    }
                )

            # --- Regla 3: hora inusual ---
            cfg = rules["unusual_hour"]
            hour = txn["timestamp"].hour
            if cfg["enabled"] and cfg["start_hour"] <= hour < cfg["end_hour"]:
                score += cfg["weight"]
                reasons.append(
                    {
                        "rule": "unusual_hour",
                        "weight": cfg["weight"],
                        "detail": f"{txn['timestamp'].strftime('%H:%M')} local time",
                    }
                )

            # --- Fase 2: velocidad por tarjeta (ventana deslizante) ---
            cfg = rules["velocity_card"]
            card_window = self.card_velocity_window.setdefault(txn["card_id"], deque())
            card_window.append(now)
            _trim(card_window, now, cfg["window_seconds"])
            count_in_window = len(card_window)
            if cfg["enabled"] and count_in_window > cfg["max_count"]:
                score += cfg["weight"]
                reasons.append(
                    {
                        "rule": "velocity_limit_exceeded",
                        "weight": cfg["weight"],
                        "detail": (
                            f"{count_in_window} txns in {cfg['window_seconds']}s "
                            f"(limit: {cfg['max_count']} in {cfg['window_seconds']}s)"
                        ),
                    }
                )
                if cfg["hard_decline"]:
                    hard_decline = True
                self.blocklist[card_key] = now + self.config["blocklist"]["block_duration_seconds"]

            # --- Fase 2: velocidad por dispositivo (tarjetas distintas) ---
            cfg = rules["velocity_device"]
            dev_window = self.device_card_window.setdefault(txn["device_id"], deque())
            dev_window.append((now, txn["card_id"]))
            _trim(dev_window, now, cfg["window_seconds"])
            distinct_cards_device = {c for _, c in dev_window}
            if cfg["enabled"] and len(distinct_cards_device) > cfg["max_distinct_cards"]:
                score += cfg["weight"]
                reasons.append(
                    {
                        "rule": "device_card_hopping",
                        "weight": cfg["weight"],
                        "detail": (
                            f"device {txn['device_id']} used {len(distinct_cards_device)} "
                            f"distinct cards in {cfg['window_seconds']}s"
                        ),
                    }
                )
                if cfg["hard_decline"]:
                    hard_decline = True
                self.blocklist[device_key] = now + self.config["blocklist"]["block_duration_seconds"]

            # --- Bono A: detección de colusión (grafo device/ip -> tarjetas) ---
            cfg = rules["collusion_graph"]
            ip_window = self.ip_card_window.setdefault(txn["ip"], deque())
            ip_window.append((now, txn["card_id"]))
            _trim(ip_window, now, cfg["window_seconds"])
            distinct_cards_ip = {c for _, c in ip_window}
            ring_nodes = set()
            if cfg["enabled"]:
                if len(distinct_cards_ip) >= cfg["max_distinct_cards"]:
                    ring_nodes |= distinct_cards_ip
                if len(distinct_cards_device) >= cfg["max_distinct_cards"]:
                    ring_nodes |= distinct_cards_device
            if ring_nodes:
                score += cfg["weight"]
                reasons.append(
                    {
                        "rule": "possible_fraud_ring",
                        "weight": cfg["weight"],
                        "detail": (
                            f"device={txn['device_id']} / ip={txn['ip']} vinculado a tarjetas: "
                            f"{sorted(ring_nodes)}"
                        ),
                    }
                )
                if cfg["hard_decline"]:
                    hard_decline = True

            score = min(100, score)
            decision = self._decide(score, hard_decline)

        # --- Fase 3: autorización bancaria simulada + circuit breaker (fuera del lock) ---
        bank_status = "skipped_hard_decline"
        if not hard_decline:
            bcfg = self.config["bank_auth"]
            bank_status, _ = self.circuit_breaker.call(
                mock_bank_auth,
                bcfg["failure_probability"],
                bcfg["simulated_latency_seconds"],
                bcfg["timeout_threshold_seconds"],
            )
            if bank_status != "approved" and decision == "APPROVE":
                decision = "REVIEW"
                reasons.append(
                    {
                        "rule": "bank_auth_degraded",
                        "weight": 0,
                        "detail": f"bank_auth_status={bank_status}",
                    }
                )

        result = {
            "transaction_id": txn["id"],
            "score": score,
            "decision": decision,
            "reasons": reasons,
            "bank_auth_status": bank_status,
        }

        if decision == "DECLINE":
            with self._lock:
                self.audit_reports[txn["id"]] = build_audit_report(
                    txn["id"], score, decision, reasons, bank_status
                )

        return result

    def _decide(self, score: int, hard_decline: bool) -> str:
        if hard_decline:
            return "DECLINE"
        thresholds = self.config["thresholds"]
        if score >= thresholds["decline_at_or_above"]:
            return "DECLINE"
        if score >= thresholds["approve_below"]:
            return "REVIEW"
        return "APPROVE"

    def _blocked_result(self, txn: dict[str, Any], reason_code: str) -> dict[str, Any]:
        result = {
            "transaction_id": txn["id"],
            "score": 100,
            "decision": "DECLINE",
            "reasons": [{"rule": reason_code, "weight": 0, "detail": reason_code}],
            "bank_auth_status": "skipped_blocked",
        }
        self.audit_reports[txn["id"]] = build_audit_report(
            txn["id"], result["score"], result["decision"], result["reasons"], result["bank_auth_status"]
        )
        return result

    def get_audit_report(self, transaction_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self.audit_reports.get(transaction_id)

    def list_audit_reports(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.audit_reports.values())
