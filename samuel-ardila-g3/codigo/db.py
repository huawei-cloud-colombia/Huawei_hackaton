import sqlite3
import config


def get_connection():
    conn = sqlite3.connect(config.DB_PATH, timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema():
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seats (
                seat_id   TEXT PRIMARY KEY,
                section   TEXT NOT NULL,
                price     INTEGER NOT NULL,
                currency  TEXT NOT NULL,
                status    TEXT NOT NULL DEFAULT 'AVAILABLE',
                version   INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS holds (
                hold_id    TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                event_id   TEXT NOT NULL,
                status     TEXT NOT NULL,
                total      INTEGER NOT NULL,
                currency   TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS hold_seats (
                hold_id TEXT NOT NULL,
                seat_id TEXT NOT NULL,
                PRIMARY KEY (hold_id, seat_id),
                FOREIGN KEY (hold_id) REFERENCES holds(hold_id),
                FOREIGN KEY (seat_id) REFERENCES seats(seat_id)
            );

            CREATE TABLE IF NOT EXISTS idempotency_keys (
                key          TEXT PRIMARY KEY,
                payload_hash TEXT NOT NULL,
                hold_id      TEXT,
                response_json TEXT,
                created_at   TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                hold_id    TEXT,
                seat_id    TEXT,
                user_id    TEXT,
                from_state TEXT,
                to_state   TEXT,
                reason     TEXT,
                timestamp  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                hold_id    TEXT NOT NULL,
                token      TEXT NOT NULL,
                scenario   TEXT NOT NULL,
                result     TEXT NOT NULL,
                amount     INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recurrences (
                recurrence_id        TEXT PRIMARY KEY,
                hold_id              TEXT NOT NULL,
                interval_days        INTEGER NOT NULL,
                next_charge_at       TEXT NOT NULL,
                status               TEXT NOT NULL,
                installments_total   INTEGER NOT NULL,
                installments_paid    INTEGER NOT NULL,
                amount_per_installment INTEGER NOT NULL,
                currency             TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_holds_status ON holds(status);
            CREATE INDEX IF NOT EXISTS idx_holds_expires ON holds(expires_at);
            CREATE INDEX IF NOT EXISTS idx_audit_hold ON audit_log(hold_id);
            CREATE INDEX IF NOT EXISTS idx_seats_status ON seats(status);
            """
        )
    finally:
        conn.close()


def seed_seats():
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM seats").fetchone()[0]
        if count > 0:
            return
        rows = []
        for i in range(1, 11):
            rows.append((
                f"VIP-A-{i:03d}", "VIP", 500000, config.CURRENCY, "AVAILABLE", 1
            ))
        for i in range(101, 141):
            rows.append((
                f"GEN-A-{i}", "GENERAL", 210000, config.CURRENCY, "AVAILABLE", 1
            ))
        conn.executemany(
            "INSERT INTO seats (seat_id, section, price, currency, status, version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    finally:
        conn.close()
