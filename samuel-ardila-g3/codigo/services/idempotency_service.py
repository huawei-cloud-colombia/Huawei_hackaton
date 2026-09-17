import hashlib
import json
from datetime import datetime, timezone

import db


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def compute_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def check_existing(key):
    if not key:
        return None
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT key, payload_hash, hold_id, response_json FROM idempotency_keys WHERE key = ?",
            (key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def store(key, payload, hold_id, response):
    if not key:
        return
    payload_hash = compute_hash(payload)
    conn = db.get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO idempotency_keys (key, payload_hash, hold_id, response_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, payload_hash, hold_id, json.dumps(response, default=str), now_iso()),
        )
    finally:
        conn.close()


def resolve(key, payload):
    """
    Returns:
      (None, None)           -> no key, proceed normally
      ("replay", response)   -> same key + same payload, return stored response
      ("conflict", None)     -> same key + different payload
      ("new", None)          -> key not seen before, proceed and store after
    """
    if not key:
        return (None, None)
    existing = check_existing(key)
    if existing is None:
        return ("new", None)
    payload_hash = compute_hash(payload)
    if existing["payload_hash"] == payload_hash:
        import json as _json
        return ("replay", _json.loads(existing["response_json"]))
    return ("conflict", None)
