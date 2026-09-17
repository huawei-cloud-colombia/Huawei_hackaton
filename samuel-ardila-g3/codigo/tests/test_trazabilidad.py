from services import hold_service, payment_service, audit_service


def test_trazabilidad_reserva_completa(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001', 'VIP-A-002'])
    payment_service.confirm_hold(h['hold_id'], 'tok_1', 'APPROVED')
    audit = audit_service.get_audit(h['hold_id'])
    reasons = [a['reason'] for a in audit]
    assert 'hold_created' in reasons
    assert 'payment_approved' in reasons


def test_trazabilidad_estados(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    audit = audit_service.get_audit(h['hold_id'])
    assert audit[0]['from_state'] == 'AVAILABLE'
    assert audit[0]['to_state'] == 'HELD'


def test_trazabilidad_declined(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    payment_service.confirm_hold(h['hold_id'], 'tok_1', 'DECLINED')
    audit = audit_service.get_audit(h['hold_id'])
    reasons = [a['reason'] for a in audit]
    assert 'payment_declined' in reasons


def test_trazabilidad_export(fresh_db):
    h = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    audit = audit_service.get_audit(h['hold_id'])
    assert isinstance(audit, list)
    assert all('timestamp' in a for a in audit)
