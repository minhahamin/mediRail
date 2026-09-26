import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.seed import seed


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    db.init_db(c)
    seed(c)
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def login(client, username, password="demo1234"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
