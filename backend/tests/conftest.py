"""테스트 설정. 기본은 SQLite(빠름). MEDIRAIL_TEST_DB=postgres 로 실행하면 같은 테스트 전체를 임베디드 PostgreSQL에서 돌린다.

    python -m pytest -q                              # SQLite
    MEDIRAIL_TEST_DB=postgres python -m pytest -q    # PostgreSQL (pgserver 필요: pip install -r requirements-dev.txt)
"""
import os

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app
from app.ratelimit import reset_all
from app.seed import seed

USE_PG = os.environ.get("MEDIRAIL_TEST_DB") == "postgres"


@pytest.fixture(scope="session")
def pg_uri(tmp_path_factory):
    if not USE_PG:
        yield None
        return
    import pgserver

    server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"))
    yield server.get_uri()
    server.cleanup()


def _reset_pg(uri):
    c = db.connect(uri)
    c._c.execute("DROP SCHEMA public CASCADE")
    c._c.execute("CREATE SCHEMA public")
    c.commit()
    c.close()


@pytest.fixture(autouse=True)
def _clean_limits():
    reset_all()   # 요청 제한 상태는 테스트 간에 공유되면 안 된다
    yield


@pytest.fixture
def conn(pg_uri):
    if USE_PG:
        _reset_pg(pg_uri)
        c = db.connect(pg_uri)
    else:
        c = db.connect(":memory:")
    db.init_db(c)
    seed(c)
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch, pg_uri):
    if USE_PG:
        _reset_pg(pg_uri)
        monkeypatch.setenv("DATABASE_URL", pg_uri)
    else:
        monkeypatch.setenv("MEDIRAIL_DB", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def login(client, username, password="demo1234"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
