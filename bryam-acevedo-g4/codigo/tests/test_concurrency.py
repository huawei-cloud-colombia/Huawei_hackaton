"""Bono B: demuestra con concurrencia real que el conteo por tarjeta no
pierde ni duplica actualizaciones bajo N hilos simultáneos evaluando la
misma tarjeta al mismo tiempo."""
import copy
import threading

from app.engine import RiskEngine
from tests.helpers import make_txn
from tests.test_phase1 import no_flake_config

N_THREADS = 60


def test_concurrent_evaluations_do_not_lose_updates():
    cfg = copy.deepcopy(no_flake_config())
    # Umbral alto para que la ráfaga concurrente no dispare el bloqueo:
    # lo que se mide aquí es la integridad del conteo, no la regla de negocio.
    cfg["rules"]["velocity_card"]["max_count"] = N_THREADS + 10
    engine = RiskEngine(cfg)
    card = "card_concurrent"

    barrier = threading.Barrier(N_THREADS)
    results: list[dict] = [None] * N_THREADS

    def worker(i: int) -> None:
        barrier.wait()  # maximiza la probabilidad de colisión real entre hilos
        results[i] = engine.evaluate(
            make_txn(id=f"txn_{i}", card_id=card, amount=1000 + i, country="CO", ip_country="CO")
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r is not None for r in results)
    assert len(engine.card_velocity_window[card]) == N_THREADS
    count, _total = engine.card_amount_stats[card]
    assert count == N_THREADS


def test_concurrent_evaluations_across_different_cards_are_independent():
    engine = RiskEngine(no_flake_config())
    n = 30
    results: list[dict] = [None] * n

    def worker(i: int) -> None:
        # device_id/ip únicos por tarjeta: si compartieran el mismo dispositivo,
        # la regla de device_card_hopping bloquearía las tarjetas siguientes
        # legítimamente, lo cual no es lo que queremos aislar en esta prueba.
        results[i] = engine.evaluate(
            make_txn(
                id=f"txn_{i}",
                card_id=f"card_{i}",
                device_id=f"dev_{i}",
                ip=f"10.0.0.{i}",
                amount=1000,
                country="CO",
                ip_country="CO",
            )
        )

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(engine.card_amount_stats) == n
    assert all(r["decision"] in {"APPROVE", "REVIEW", "DECLINE"} for r in results)
