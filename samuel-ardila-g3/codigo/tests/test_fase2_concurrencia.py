from concurrent.futures import ThreadPoolExecutor, as_completed
from services import hold_service


def test_carrera_20_usuarios_1_ganador(fresh_db):
    def attempt(i):
        return hold_service.create_hold(f'usr_{i}', 'aurora-bogota-2026', ['VIP-A-001'])

    results = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(attempt, i) for i in range(20)]
        for f in as_completed(futures):
            results.append(f.result())

    winners = [r for r in results if 'hold_id' in r]
    rejected = [r for r in results if 'error' in r]
    assert len(winners) == 1
    assert len(rejected) == 19
    assert max(0, len(winners) - 1) == 0


def test_carrera_100_usuarios_1_ganador(fresh_db):
    def attempt(i):
        return hold_service.create_hold(f'usr_{i}', 'aurora-bogota-2026', ['GEN-A-101'])

    results = []
    with ThreadPoolExecutor(max_workers=100) as pool:
        futures = [pool.submit(attempt, i) for i in range(100)]
        for f in as_completed(futures):
            results.append(f.result())

    winners = [r for r in results if 'hold_id' in r]
    rejected = [r for r in results if 'error' in r]
    assert len(winners) == 1
    assert len(rejected) == 99
    assert max(0, len(winners) - 1) == 0


def test_carrera_multiples_asientos_disponibles(fresh_db):
    def attempt(i):
        return hold_service.create_hold(f'usr_{i}', 'aurora-bogota-2026', [f'GEN-A-{101 + i}'])

    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(attempt, i) for i in range(10)]
        for f in as_completed(futures):
            results.append(f.result())

    winners = [r for r in results if 'hold_id' in r]
    assert len(winners) == 10
