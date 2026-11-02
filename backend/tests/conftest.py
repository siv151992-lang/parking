"""Test configuration.

By default tests run against a throw-away SQLite file. To run them against
PostgreSQL (recommended before deploying), set TEST_DATABASE_URL, e.g.
    TEST_DATABASE_URL=postgresql+psycopg2://parking:parking@localhost/smart_parking_test pytest
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_tmp = tempfile.mkdtemp(prefix="sp_test_")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["CAMERA_WORKERS_ENABLED"] = "false"
os.environ["AUTO_MIGRATE"] = "false"
os.environ["MEDIA_DIR"] = f"{_tmp}/media"
os.environ["ADMIN_PASSWORD"] = "Admin@123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app, bootstrap  # noqa: E402
from app.models import Camera, Direction, Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import settings_store  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    settings_store.invalidate()
    bootstrap()
    yield


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def cameras(db):
    entry = Camera(camera_code="E1", name="Entry 1", direction=Direction.ENTRY, is_simulated=True, cooldown_seconds=60, min_plate_confidence=0.6)
    entry2 = Camera(camera_code="E2", name="Entry 2", direction=Direction.ENTRY, is_simulated=True, cooldown_seconds=60, min_plate_confidence=0.6)
    exit_ = Camera(camera_code="X1", name="Exit 1", direction=Direction.EXIT, is_simulated=True, cooldown_seconds=60, min_plate_confidence=0.6)
    db.add_all([entry, entry2, exit_])
    db.commit()
    return {"entry": entry.id, "entry2": entry2.id, "exit": exit_.id}


@pytest.fixture
def admin(db):
    return db.query(User).filter(User.role == Role.SUPER_ADMIN).first()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_user(db, username, role, password="Passw0rd!"):
    u = User(username=username, email=f"{username}@t.local", role=role, hashed_password=hash_password(password))
    db.add(u)
    db.commit()
    return u


def login(client, username="admin", password="Admin@123"):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
