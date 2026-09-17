import db


def get_seats(section=None):
    conn = db.get_connection()
    try:
        if section:
            rows = conn.execute(
                "SELECT seat_id, section, price, currency, status, version "
                "FROM seats WHERE section = ? ORDER BY seat_id",
                (section,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT seat_id, section, price, currency, status, version "
                "FROM seats ORDER BY seat_id"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_seat(seat_id):
    conn = db.get_connection()
    try:
        row = conn.execute(
            "SELECT seat_id, section, price, currency, status, version "
            "FROM seats WHERE seat_id = ?",
            (seat_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
