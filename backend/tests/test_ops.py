"""배포(운영) 관련: DB 어댑터, 요청 제한, 새 엔드포인트, 운영 보호 장치."""
import pytest
from fastapi.testclient import TestClient

from app import db, services
from app.db import PgConnection, Row
from app.main import app
from app.ratelimit import DailyCounter, RateLimitExceeded, SlidingWindow
from tests.conftest import USE_PG, login
from tests.test_agent import u


# ---------- DB 어댑터 ----------
def test_backend_under_test_is_the_one_requested(conn):
    """MEDIRAIL_TEST_DB=postgres 로 돌리면 정말 PostgreSQL 경로를 타는지 스스로 증명한다."""
    assert db.is_postgres(conn) is USE_PG


def test_row_supports_name_index_and_dict():
    r = Row(["id", "name"], (7, "김하늘"))
    assert r["name"] == "김하늘" and r[0] == 7 and dict(r) == {"id": 7, "name": "김하늘"} and r.keys() == ["id", "name"]


def test_placeholder_translation_escapes_percent():
    assert PgConnection._sql("SELECT * FROM t WHERE slot LIKE ? AND x=?") == "SELECT * FROM t WHERE slot LIKE %s AND x=%s"
    assert PgConnection._sql("SELECT '100%' , ?") == "SELECT '100%%' , %s"


def test_insert_returns_lastrowid_and_sequences_are_in_sync(conn):
    """시드가 id를 직접 넣어도 다음 INSERT가 충돌하지 않아야 한다 (PostgreSQL 시퀀스 동기화)."""
    a = conn.execute("INSERT INTO patients (name, birth_year, sex) VALUES (?,?,?)", ("새환자", 2000, "F"))
    b = conn.execute("INSERT INTO patients (name, birth_year, sex) VALUES (?,?,?)", ("또새환자", 2001, "M"))
    assert a.lastrowid == 9 and b.lastrowid == 10       # 시드 환자 8명 다음


def test_count_star_index_access(conn):
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 8


# ---------- 요청 제한 (단위) ----------
def test_sliding_window_blocks_then_recovers():
    now = [0.0]
    w = SlidingWindow(clock=lambda: now[0])
    w.hit("k", 2, 60)
    w.hit("k", 2, 60)
    with pytest.raises(RateLimitExceeded) as e:
        w.hit("k", 2, 60)
    assert "다시 시도" in e.value.message and e.value.retry_after >= 1
    now[0] += 61
    w.hit("k", 2, 60)                                   # 창이 지나면 다시 허용
    w.hit("other", 2, 60)                               # 키별로 독립


def test_daily_counter_resets_on_new_day():
    day = ["2030-01-01"]
    d = DailyCounter(today=lambda: day[0])
    d.hit(2)
    d.hit(2)
    with pytest.raises(RateLimitExceeded, match="오늘의 데모"):
        d.hit(2)
    day[0] = "2030-01-02"
    d.hit(2)


# ---------- 요청 제한 (API) ----------
def fake_llm(monkeypatch):
    calls = []

    def fake(messages, tools=None, *, model=None):
        calls.append(1)
        return {"message": {"role": "assistant", "content": "안녕하세요."}, "usage": {}, "model": "fake"}
    monkeypatch.setattr("app.llm.chat", fake)
    return calls


def chat(client, headers, message="안녕"):
    return client.post("/chat", json={"message": message}, headers=headers)


def test_chat_is_limited_per_user(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_CHAT_PER_USER_HOUR", "2")
    calls = fake_llm(monkeypatch)
    h = login(client, "doctor1")
    assert [chat(client, h).status_code for _ in range(3)] == [200, 200, 429]
    r = chat(client, h)
    assert "AI 요청이 너무 많습니다" in r.json()["detail"] and int(r.headers["Retry-After"]) >= 1
    assert len(calls) == 2                              # 제한된 요청은 LLM을 호출하지 않는다 (비용 0)
    assert chat(client, login(client, "nurse1")).status_code == 200   # 다른 사용자는 영향 없음


def test_chat_is_limited_per_ip(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_CHAT_PER_IP_HOUR", "2")
    fake_llm(monkeypatch)
    hs = [login(client, n) for n in ("doctor1", "nurse1", "admin1")]
    assert [chat(client, h).status_code for h in hs] == [200, 200, 429]
    assert chat(client, {**hs[0], "X-Forwarded-For": "203.0.113.9"}).status_code == 200   # 프록시 뒤에서는 X-Forwarded-For로 구분


def test_daily_cap_across_all_users(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_DAILY_CHAT_LIMIT", "2")
    fake_llm(monkeypatch)
    assert [chat(client, login(client, n)).status_code for n in ("doctor1", "nurse1", "admin1")] == [200, 200, 429]
    assert "오늘의 데모" in chat(client, login(client, "doctor2")).json()["detail"]


def test_emergency_is_never_rate_limited(client, monkeypatch):
    """한도가 소진돼도 환자의 응급 문장에는 119 안내가 나가야 한다 (안전이 비용보다 우선)."""
    monkeypatch.setenv("MEDIRAIL_DAILY_CHAT_LIMIT", "1")
    monkeypatch.setenv("MEDIRAIL_CHAT_PER_USER_HOUR", "1")
    fake_llm(monkeypatch)
    h = login(client, "patient1")
    assert chat(client, h, "안녕하세요").status_code == 200
    assert chat(client, h, "안녕하세요").status_code == 429
    for _ in range(3):
        r = chat(client, h, "가슴이 쥐어짜듯 아프고 식은땀이 나요")
        assert r.status_code == 200 and "119" in r.json()["answer"]


def test_login_attempts_are_limited_per_ip(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_LOGIN_PER_IP_MIN", "3")

    def bad():
        return client.post("/auth/login", json={"username": "patient1", "password": "x"}).status_code
    assert [bad() for _ in range(4)] == [401, 401, 401, 429]
    ok = client.post("/auth/login", json={"username": "patient1", "password": "demo1234"}, headers={"X-Forwarded-For": "198.51.100.7"})
    assert ok.status_code == 200                        # 다른 IP는 영향 없음


# ---------- 새 엔드포인트 ----------
def test_soap_list_is_doctor_only_and_filterable(client):
    doc = login(client, "doctor1")
    assert client.get("/soap", headers=doc).json() == []
    for name in ("nurse1", "admin1", "patient1"):
        assert client.get("/soap", headers=login(client, name)).status_code == 403
    assert client.get("/soap?status=bogus", headers=doc).status_code == 400


def test_soap_list_contains_drafts_and_approval_moves_them(client):
    doc = login(client, "doctor1")
    c = db.connect()
    try:
        services.save_soap_draft(c, u(c, "doctor1"), 1, "기침 5일", "37.9", "상기도감염 의심", "휴식")
    finally:
        c.close()
    drafts = client.get("/soap?status=draft", headers=doc).json()
    assert len(drafts) == 1 and drafts[0]["patient_name"] == "이도윤" and drafts[0]["status"] == "draft"
    assert client.post(f"/soap/{drafts[0]['id']}/approve", headers=doc).json()["status"] == "approved"
    assert client.get("/soap?status=draft", headers=doc).json() == []
    assert len(client.get("/soap?status=approved", headers=doc).json()) == 1


def test_encounters_endpoint_permissions(client):
    assert client.get("/patients/2/encounters", headers=login(client, "doctor1")).json()[0]["chief_complaint"] == "기침 5일"
    for name in ("nurse1", "admin1", "patient2"):
        assert client.get("/patients/2/encounters", headers=login(client, name)).status_code == 403


# ---------- 운영 보호 ----------
def test_production_refuses_default_jwt_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIRAIL_ENV", "production")
    monkeypatch.delenv("MEDIRAIL_JWT_SECRET", raising=False)
    monkeypatch.setenv("MEDIRAIL_DB", str(tmp_path / "x.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="MEDIRAIL_JWT_SECRET"):
        with TestClient(app):
            pass


def test_production_starts_with_real_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIRAIL_ENV", "production")
    monkeypatch.setenv("MEDIRAIL_JWT_SECRET", "x" * 40)
    monkeypatch.setenv("MEDIRAIL_DB", str(tmp_path / "x.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200


def test_cors_origins_come_from_settings(monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("MEDIRAIL_CORS_ORIGINS", "https://medirail-web.up.railway.app, https://medirail.example.com")
    assert get_settings().cors_origins == ("https://medirail-web.up.railway.app", "https://medirail.example.com")
