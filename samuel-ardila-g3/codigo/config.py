import os

HOLD_TTL_SECONDS = int(os.environ.get("HOLD_TTL_SECONDS", 120))
MAX_SEATS_PER_USER = int(os.environ.get("MAX_SEATS_PER_USER", 6))
QUEUE_MAX_CONCURRENT = int(os.environ.get("QUEUE_MAX_CONCURRENT", 50))
QUEUE_TIMEOUT_SECONDS = int(os.environ.get("QUEUE_TIMEOUT_SECONDS", 30))
CB_FAILURE_THRESHOLD = int(os.environ.get("CB_FAILURE_THRESHOLD", 3))
CB_RECOVERY_SECONDS = int(os.environ.get("CB_RECOVERY_SECONDS", 15))
CB_HALF_OPEN_TRIALS = int(os.environ.get("CB_HALF_OPEN_TRIALS", 1))
PAYMENT_TIMEOUT_SECONDS = float(os.environ.get("PAYMENT_TIMEOUT_SECONDS", 2))
DB_PATH = os.environ.get("DB_PATH", "nexus.db")
EVENT_ID = os.environ.get("EVENT_ID", "aurora-bogota-2026")
CURRENCY = os.environ.get("CURRENCY", "COP")
