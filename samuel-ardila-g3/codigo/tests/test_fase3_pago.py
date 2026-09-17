from services import hold_service, payment_service, seat_service
import circuit_breaker


def test_pago_approved(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    assert r['result'] == 'APPROVED'
    assert r['status'] == 'SOLD'
    assert seat_service.get_seat('VIP-A-001')['status'] == 'SOLD'


def test_pago_declined_libera(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'DECLINED')
    assert r['result'] == 'DECLINED'
    assert r['status'] == 'RELEASED'
    assert seat_service.get_seat('VIP-A-001')['status'] == 'AVAILABLE'


def test_pago_error_mantiene_hold(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'ERROR')
    assert r['result'] == 'ERROR'
    assert r['pending_retry'] == True
    assert seat_service.get_seat('VIP-A-001')['status'] == 'HELD'


def test_pago_timeout_mantiene_hold(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'TIMEOUT')
    assert r['result'] == 'TIMEOUT'
    assert r['pending_retry'] == True
    assert seat_service.get_seat('VIP-A-001')['status'] == 'HELD'


def test_confirmar_dos_veces(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    assert r['error'] == 'hold_already_sold'


def test_confirmar_hold_inexistente(fresh_db):
    r = payment_service.confirm_hold('hold_inexistente', 'tok_1', 'APPROVED')
    assert r['error'] == 'hold_not_found'


def test_pago_token_vacio(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = payment_service.confirm_hold(h['hold_id'], '', 'APPROVED')
    assert r['error'] == 'empty_payment_token'
