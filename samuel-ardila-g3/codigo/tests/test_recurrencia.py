from services import hold_service, payment_service, recurrence_service


def test_recurrencia_crear(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001', 'VIP-A-002'])
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'RECURRENCE')
    assert r['result'] == 'APPROVED'
    assert r.get('recurrence') is not None
    rec = recurrence_service.get_recurrence(h['hold_id'])
    assert rec['installments_paid'] == 1
    assert rec['installments_total'] == 3
    assert rec['status'] == 'ACTIVE'


def test_recurrencia_cobrar_cuotas(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    payment_service.confirm_hold(h['hold_id'], 'tok_1', 'RECURRENCE')

    r2 = recurrence_service.charge_next(h['hold_id'], 'APPROVED')
    assert r2['installments_paid'] == 2
    assert r2['status'] == 'ACTIVE'

    r3 = recurrence_service.charge_next(h['hold_id'], 'APPROVED')
    assert r3['installments_paid'] == 3
    assert r3['status'] == 'COMPLETED'


def test_recurrencia_no_activa(fresh_db):
    r = recurrence_service.charge_next('hold_inexistente', 'APPROVED')
    assert r['error'] == 'no_active_recurrence'
