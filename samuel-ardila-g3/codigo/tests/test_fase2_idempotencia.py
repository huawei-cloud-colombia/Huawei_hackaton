from services import hold_service, idempotency_service


def test_idempotency_replay(fresh_db):
    key = 'reserve-usr1-001'
    payload = {'user_id': 'usr_1', 'event_id': 'aurora-bogota-2026', 'seat_ids': ['VIP-A-001']}

    action, _ = idempotency_service.resolve(key, payload)
    assert action == 'new'

    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    idempotency_service.store(key, payload, r['hold_id'], r)

    action2, cached = idempotency_service.resolve(key, payload)
    assert action2 == 'replay'
    assert cached['hold_id'] == r['hold_id']


def test_idempotency_conflicto(fresh_db):
    key = 'reserve-usr1-002'
    payload = {'user_id': 'usr_1', 'event_id': 'aurora-bogota-2026', 'seat_ids': ['VIP-A-001']}
    payload_diff = {'user_id': 'usr_1', 'event_id': 'aurora-bogota-2026', 'seat_ids': ['VIP-A-002']}

    r = hold_service.create_hold('usr_1', 'aurora-bogota-2026', ['VIP-A-001'])
    idempotency_service.store(key, payload, r['hold_id'], r)

    action, _ = idempotency_service.resolve(key, payload_diff)
    assert action == 'conflict'


def test_idempotency_sin_key(fresh_db):
    action, cached = idempotency_service.resolve(None, {'seat_ids': ['VIP-A-001']})
    assert action is None
    assert cached is None


def test_idempotency_via_api(client):
    r1 = client.post('/api/holds', json={
        'user_id': 'usr_1', 'event_id': 'aurora-bogota-2026', 'seat_ids': ['VIP-A-001']
    }, headers={'Idempotency-Key': 'key-api-001'})
    r2 = client.post('/api/holds', json={
        'user_id': 'usr_1', 'event_id': 'aurora-bogota-2026', 'seat_ids': ['VIP-A-001']
    }, headers={'Idempotency-Key': 'key-api-001'})
    assert r1.get_json()['hold_id'] == r2.get_json()['hold_id']

    r3 = client.post('/api/holds', json={
        'user_id': 'usr_1', 'event_id': 'aurora-bogota-2026', 'seat_ids': ['VIP-A-002']
    }, headers={'Idempotency-Key': 'key-api-001'})
    assert r3.status_code == 409
    assert r3.get_json()['error'] == 'IDEMPOTENCY_CONFLICT'
