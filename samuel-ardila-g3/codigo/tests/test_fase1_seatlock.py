from services import hold_service, seat_service, audit_service


def test_crear_hold_normal(fresh_db):
    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001', 'VIP-A-002'])
    assert 'error' not in r
    assert r['status'] == 'HELD'
    assert r['total'] == 1000000
    assert r['currency'] == 'COP'


def test_double_booking_rechazado(fresh_db):
    hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = hold_service.create_hold('usr_2', 'aurora-bogota-2026', ['VIP-A-001'])
    assert r['error'] == 'seat_not_available'


def test_todo_o_nada(fresh_db):
    hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = hold_service.create_hold('usr_2', 'aurora-bogota-2026', ['GEN-A-101', 'VIP-A-001'])
    assert r['error'] == 'seat_not_available'
    assert seat_service.get_seat('GEN-A-101')['status'] == 'AVAILABLE'


def test_limite_6_asientos(fresh_db):
    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026',
                                ['GEN-A-101', 'GEN-A-102', 'GEN-A-103', 'GEN-A-104', 'GEN-A-105', 'GEN-A-106', 'GEN-A-107'])
    assert r['error'] == 'seat_limit_exceeded'
    assert r['limit'] == 6


def test_precio_del_servidor(fresh_db):
    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    assert r['total'] == 500000
    r2 = hold_service.create_hold('usr_2', 'aurora-bogota-2026', ['GEN-A-101'])
    assert r2['total'] == 210000


def test_liberar_hold(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    r = hold_service.release_hold(h['hold_id'])
    assert r['status'] == 'RELEASED'
    assert seat_service.get_seat('VIP-A-001')['status'] == 'AVAILABLE'


def test_expiracion_automatica(fresh_db):
    import config
    config.HOLD_TTL_SECONDS = 1
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    import time
    time.sleep(1.5)
    hold_service.expire_holds()
    assert seat_service.get_seat('VIP-A-001')['status'] == 'AVAILABLE'


def test_trazabilidad_hold(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001', 'VIP-A-002'])
    audit = audit_service.get_audit(h['hold_id'])
    assert len(audit) == 2
    assert all(a['reason'] == 'hold_created' for a in audit)
