"""
Bono B - Procesamiento concurrente y control de cuota.
Prueba que el procesamiento concurrente no pierde ni duplica resultados.
"""
import pytest
import json
import sys
import concurrent.futures
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.triage_engine import TriageEngine

CONFIG_PATH = Path(__file__).parent.parent / "app" / "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)


class TestBonoBConcurrencia:
    """Bono B - Concurrencia segura."""

    def test_concurrent_processing_no_duplicates(self):
        """Procesamiento concurrente no duplica resultados."""
        engine = TriageEngine(CONFIG)
        tickets = [
            {"ticket_id": f"T-CONC-{i}", "text": f"Error 503 en API numero {i}."}
            for i in range(20)
        ]

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(engine.process_ticket, t) for t in tickets]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        ticket_ids = [r["ticket_id"] for r in results if "ticket_id" in r]
        assert len(ticket_ids) == len(set(ticket_ids)), "Se duplicaron resultados"
        assert len(results) == 20, f"Se perdieron resultados: {len(results)}/20"

    def test_concurrent_batch_integrity(self):
        """Un lote concurrente mantiene integridad."""
        engine = TriageEngine(CONFIG)
        tickets = [
            {"ticket_id": f"T-BATCH-{i}", "text": f"API error {i}."}
            for i in range(10)
        ]
        results = engine.process_batch(tickets)
        assert len(results) == 10
        ids = [r.get("ticket_id") for r in results]
        for i in range(10):
            assert f"T-BATCH-{i}" in ids
