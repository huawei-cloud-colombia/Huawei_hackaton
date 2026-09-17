from services import hold_service, payment_service, seat_service


def test_seat_ids_vacio(fresh_db):
    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', [])
    assert r['error'] == 'empty_seat_list'


def test_seat_ids_none(fresh_db):
    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', None)
    assert r['error'] == 'empty_seat_list'


def test_asiento_inexistente(fresh_db):
    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['NO-EXISTE'])
    assert r['error'] == 'seat_not_found'


def test_asiento_duplicado(fresh_db):
    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001', 'VIP-A-001'])
    assert r['error'] == 'duplicate_seat'


def test_usuario_vacio(fresh_db):
    r = hold_service.create_hold('', 'aurora-bogota-2026', ['VIP-A-001'])
    assert r['error'] == 'invalid_user'


def test_usuario_none(fresh_db):
    r = hold_service.create_hold(None, 'aurora-bogota-2026', ['VIP-A-001'])
    assert r['error'] == 'invalid_user'


def test_confirmar_hold_vendido(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    assert r['error'] == 'hold_already_sold'


def test_confirmar_hold_liberado(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    hold_service.release_hold(h['hold_id'])
    r = payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    assert r['error'] == 'hold_expired'


def test_payment_token_vacio(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = payment_service.confirm_hold(h['hold_id'], '', 'APPROVED')
    assert r['error'] == 'empty_payment_token'


def test_mismo_usuario_varios_holds(fresh_db):
    h1 = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001', 'VIP-A-002'])
    h2 = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-003', 'VIP-A-004'])
    assert 'error' not in h1
    assert 'error' not in h2


def test_liberar_hold_inexistente(fresh_db):
    r = hold_service.release_hold('hold_inexistente')
    assert r['error'] == 'hold_not_found'


def test_consultar_hold_inexistente(fresh_db):
    r = hold_service.get_hold('hold_inexistente')
    assert r is None
