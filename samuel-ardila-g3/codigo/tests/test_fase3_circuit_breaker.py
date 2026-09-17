import time
from services import hold_service, payment_service
import circuit_breaker


def test_cb_3_fallos_open(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    for _ in range(3):
        payment_service.confirm_hold(h['hold_id'], 'tok_1', 'ERROR')
    cb = payment_service.get_circuit_breaker_state()
    assert cb['state'] == 'OPEN'


def test_cb_open_rechaza(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    for _ in range(3):
        payment_service.confirm_hold(h['hold_id'], 'tok_1', 'ERROR')
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    assert r['error'] == 'PAYMENT_SERVICE_UNAVAILABLE'


def test_cb_half_open_recupera(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    for _ in range(3):
        payment_service.confirm_hold(h['hold_id'], 'tok_1', 'ERROR')
    time.sleep(2.5)
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    assert r['result'] == 'APPROVED'
    cb = payment_service.get_circuit_breaker_state()
    assert cb['state'] == 'CLOSED'


def test_cb_reset(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    for _ in range(3):
        payment_service.confirm_hold(h['hold_id'], 'tok_1', 'ERROR')
    payment_service.reset_circuit_breaker()
    cb = payment_service.get_circuit_breaker_state()
    assert cb['state'] == 'CLOSED'
