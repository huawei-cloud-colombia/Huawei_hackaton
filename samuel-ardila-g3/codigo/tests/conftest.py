import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ['PAYMENT_TIMEOUT_SECONDS'] = '0.5'
os.environ['CB_RECOVERY_SECONDS'] = '2'

import pytest
import config
import db
import circuit_breaker


@pytest.fixture
def fresh_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    config.DB_PATH = db_path
    config.HOLD_TTL_SECONDS = 120
    config.MAX_SEATS_PER_USER = 6
    db.init_schema()
    db.seed_seats()
    circuit_breaker.breaker.reset()
    yield db_path


@pytest.fixture
def client(fresh_db):
    import app as appmod
    appmod.app.config['TESTING'] = True
    with appmod.app.test_client() as c:
        yield c
