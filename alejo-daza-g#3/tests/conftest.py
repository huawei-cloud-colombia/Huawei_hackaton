import os
import tempfile

_tmp_dir = tempfile.gettempdir()
_db_path = os.path.join(_tmp_dir, "seatlock_test.db")

os.environ.setdefault("SEATLOCK_DB_PATH", _db_path)
os.environ.setdefault("SEATLOCK_HOLD_TTL", "2")
os.environ.setdefault("SEATLOCK_MAX_SEATS", "6")
os.environ.setdefault("SEATLOCK_SWEEPER_INTERVAL", "1")
