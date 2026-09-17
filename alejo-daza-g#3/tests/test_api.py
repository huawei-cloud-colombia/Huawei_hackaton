from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import app
from app.service import SeatLockError, create_hold, expire_holds, get_hold, list_seats

DB = settings.db_path


@pytest.fixture
def client():
    for ext in ("", "-wal", "-shm"):
        p = DB + ext
        if os.path.exists(p):
            os.remove(p)
    init_db()
    with TestClient(app) as c:
        yield c


def test_list_seeds_all_available(client):
    r = client.get("/events/aurora-bogota-2026/seats")
    assert r.status_code == 200
    seats = r.json()
    assert len(seats) == 60
    assert all(s["status"] == "AVAILABLE" for s in seats)
    assert any(s["seat_id"] == "A-101" for s in seats)


def test_create_hold_marks_held_and_server_price(client):
    r = client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101", "A-102"]})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "HELD"
    assert body["seat_ids"] == ["A-101", "A-102"]
    assert body["total"] == 420000
    assert body["currency"] == "COP"
    seats = {s["seat_id"]: s["status"] for s in client.get("/events/aurora-bogota-2026/seats").json()}
    assert seats["A-101"] == "HELD" and seats["A-102"] == "HELD"


def test_all_or_nothing_rejects_and_no_partial_hold(client):
    client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101", "A-102"]})
    r = client.post("/holds", json={"user_id": "u2", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101", "A-103"]})
    assert r.status_code == 409
    body = r.json()
    assert body["status"] == "REJECTED"
    assert body["reason"] == "seat_not_available"
    assert body["conflicting_seats"] == ["A-101"]
    seats = {s["seat_id"]: s["status"] for s in client.get("/events/aurora-bogota-2026/seats").json()}
    assert seats["A-103"] == "AVAILABLE"


def test_second_user_single_seat_rejected(client):
    client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101"]})
    r = client.post("/holds", json={"user_id": "u2", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101"]})
    assert r.status_code == 409 and r.json()["reason"] == "seat_not_available"


def test_max_seats_per_user_limit(client):
    r = client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": [f"A-{100+i}" for i in range(1, 7)]})
    assert r.status_code == 201
    r = client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["B-101"]})
    assert r.status_code == 409 and r.json()["reason"] == "max_seats_exceeded"


def test_release_makes_available_again(client):
    r = client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101"]})
    hid = r.json()["hold_id"]
    r = client.delete(f"/holds/{hid}?user_id=u1")
    assert r.status_code == 200 and r.json()["status"] == "RELEASED"
    seats = {s["seat_id"]: s["status"] for s in client.get("/events/aurora-bogota-2026/seats").json()}
    assert seats["A-101"] == "AVAILABLE"
    r2 = client.post("/holds", json={"user_id": "u2", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101"]})
    assert r2.status_code == 201


def test_confirm_marks_sold_and_terminal(client):
    r = client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101", "A-102"]})
    hid = r.json()["hold_id"]
    r = client.post(f"/holds/{hid}/confirm", json={"user_id": "u1"})
    assert r.status_code == 200 and r.json()["status"] == "SOLD"
    seats = {s["seat_id"]: s["status"] for s in client.get("/events/aurora-bogota-2026/seats").json()}
    assert seats["A-101"] == "SOLD" and seats["A-102"] == "SOLD"
    r = client.post("/holds", json={"user_id": "u2", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101"]})
    assert r.status_code == 409 and r.json()["reason"] == "seat_not_available"
    r = client.post(f"/holds/{hid}/confirm", json={"user_id": "u1"})
    assert r.status_code == 409


def test_cannot_confirm_other_users_hold(client):
    r = client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101"]})
    hid = r.json()["hold_id"]
    r = client.post(f"/holds/{hid}/confirm", json={"user_id": "u2"})
    assert r.status_code == 404


def test_auto_expiration_restores_available(client):
    r = client.post("/holds", json={"user_id": "u1", "event_id": "aurora-bogota-2026", "seat_ids": ["A-101", "A-102"]})
    assert r.status_code == 201
    time.sleep(3.5)
    seats = {s["seat_id"]: s["status"] for s in client.get("/events/aurora-bogota-2026/seats").json()}
    assert seats["A-101"] == "AVAILABLE" and seats["A-102"] == "AVAILABLE"
    hold = client.get(f"/holds/{r.json()['hold_id']}").json()
    assert hold["status"] == "EXPIRED"


def test_admin_expire_endpoint_ok(client):
    r = client.post("/admin/expire")
    assert r.status_code == 200 and "expired" in r.json()


def test_expire_holds_deterministic_service_level():
    for ext in ("", "-wal", "-shm"):
        p = DB + ext
        if os.path.exists(p):
            os.remove(p)
    init_db()
    h = create_hold("u1", "aurora-bogota-2026", ["A-101", "A-102"])
    time.sleep(2.5)
    n = expire_holds()
    assert n == 1
    seats = {s.seat_id: s.status.value for s in list_seats("aurora-bogota-2026")}
    assert seats["A-101"] == "AVAILABLE" and seats["A-102"] == "AVAILABLE"
    assert get_hold(h.hold_id).status.value == "EXPIRED"


def test_concurrency_single_winner_service_level():
    for ext in ("", "-wal", "-shm"):
        p = DB + ext
        if os.path.exists(p):
            os.remove(p)
    init_db()
    results = []

    def worker(i):
        try:
            h = create_hold(f"u{i}", "aurora-bogota-2026", ["A-101"])
            results.append(("ok", h.hold_id))
        except SeatLockError as e:
            results.append(("rej", e.reason))

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(worker, range(20)))
    wins = [r for r in results if r[0] == "ok"]
    rejs = [r for r in results if r[0] == "rej"]
    assert len(wins) == 1, f"expected 1 winner, got {len(wins)}: {results}"
    assert len(rejs) == 19
    assert all(r[1].value == "seat_not_available" for r in rejs)


def test_concurrency_single_winner_api_level(client):
    results = []

    def worker(i):
        r = client.post("/holds", json={"user_id": f"u{i}", "event_id": "aurora-bogota-2026", "seat_ids": ["B-101"]})
        results.append(r.status_code)

    with ThreadPoolExecutor(max_workers=15) as ex:
        list(ex.map(worker, range(15)))
    assert results.count(201) == 1
    assert results.count(409) == 14
