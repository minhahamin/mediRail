"""시스템 관리자(superadmin): 사용자·권한 관리, 읽기 전용 데모 관리자, break-glass, 계정 중지, 부트스트랩, 마이그레이션."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import admin, db
from app.main import app
from tests.conftest import USE_PG, _reset_pg, login

BOSS, BOSS_PW = "boss_admin", "correct-horse-battery"


@pytest.fixture
def client(tmp_path, monkeypatch, pg_uri):
    """이 모듈의 client는 실제 최상위 관리자(boss_admin)가 환경변수로 만들어진 상태로 시작한다."""
    monkeypatch.setenv("MEDIRAIL_SUPERADMIN_USERNAME", BOSS)
    monkeypatch.setenv("MEDIRAIL_SUPERADMIN_PASSWORD", BOSS_PW)
    if USE_PG:
        _reset_pg(pg_uri)
        monkeypatch.setenv("DATABASE_URL", pg_uri)
    else:
        monkeypatch.setenv("MEDIRAIL_DB", str(tmp_path / "admin.db"))
    with TestClient(app) as c:
        yield c


def H(client, user, pw="demo1234"):
    return login(client, user, pw)


def boss(client):
    return H(client, BOSS, BOSS_PW)


def signup(client, username="newpat01", **over):
    r = client.post("/auth/register", json={"username": username, "password": "pass1234", "name": "새싹", "birth_year": 1995, "sex": "F", **over})
    assert r.status_code == 201, r.text
    return r.json()["patient_id"], {"Authorization": f"Bearer {r.json()['access_token']}"}


def user_id(client, username):
    return next(u["id"] for u in client.get("/admin/users", headers=boss(client)).json() if u["username"] == username)


# ---------- 부트스트랩 ----------
def test_real_and_demo_superadmins_exist(client):
    real = client.post("/auth/login", json={"username": BOSS, "password": BOSS_PW}).json()
    demo = client.post("/auth/login", json={"username": "superadmin_demo", "password": "demo1234"}).json()
    assert (real["role"], real["read_only"]) == ("superadmin", False)
    assert (demo["role"], demo["read_only"]) == ("superadmin", True)


def test_bootstrap_is_idempotent_and_rotates_password(client):
    c = db.connect()
    try:
        admin.ensure_system_accounts(c)
        admin.ensure_system_accounts(c)
        assert c.execute("SELECT COUNT(*) FROM users WHERE role='superadmin'").fetchone()[0] == 2     # 실제 1 + 데모 1
    finally:
        c.close()


def test_password_rotation_via_env(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_SUPERADMIN_PASSWORD", "a-brand-new-long-secret")
    c = db.connect()
    try:
        admin.ensure_system_accounts(c)
    finally:
        c.close()
    assert client.post("/auth/login", json={"username": BOSS, "password": BOSS_PW}).status_code == 401
    assert client.post("/auth/login", json={"username": BOSS, "password": "a-brand-new-long-secret"}).status_code == 200


@pytest.mark.parametrize("env,needle", [
    ({"MEDIRAIL_SUPERADMIN_PASSWORD": "short"}, "12자"),
    ({"MEDIRAIL_SUPERADMIN_USERNAME": "superadmin_demo"}, "형식"),
    ({"MEDIRAIL_SUPERADMIN_USERNAME": "AB"}, "형식"),
    ({"MEDIRAIL_SUPERADMIN_USERNAME": "doctor1"}, "다른 역할"),
])
def test_bootstrap_validation(client, monkeypatch, env, needle):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    c = db.connect()
    try:
        with pytest.raises(RuntimeError, match=needle):
            admin.ensure_system_accounts(c)
    finally:
        c.close()


def test_no_real_superadmin_without_env(tmp_path, monkeypatch, pg_uri):
    monkeypatch.delenv("MEDIRAIL_SUPERADMIN_USERNAME", raising=False)
    monkeypatch.delenv("MEDIRAIL_SUPERADMIN_PASSWORD", raising=False)
    if USE_PG:
        _reset_pg(pg_uri)
        monkeypatch.setenv("DATABASE_URL", pg_uri)
    else:
        monkeypatch.setenv("MEDIRAIL_DB", str(tmp_path / "n.db"))
    with TestClient(app) as c:
        users = [r["username"] for r in [dict(x) for x in c.get("/admin/users", headers=login(c, "superadmin_demo")).json()]]
        assert BOSS not in users and "superadmin_demo" in users


# ---------- 접근 제어 ----------
ADMIN_PATHS = [("GET", "/admin/users"), ("GET", "/admin/stats"), ("POST", "/admin/break-glass"),
               ("PATCH", "/admin/users/1/role"), ("POST", "/admin/users/1/disable")]


@pytest.mark.parametrize("user", ["patient1", "nurse1", "doctor1", "admin1"])
def test_no_other_role_can_use_admin_api(client, user):
    h = H(client, user)
    for method, path in ADMIN_PATHS:
        r = client.request(method, path, headers=h, json={"role": "doctor", "patient_id": 1, "reason": "사유가 충분히 긴 문장입니다"} if method != "GET" else None)
        assert r.status_code == 403, (user, method, path, r.status_code)


def test_unauthenticated_admin_api_is_401(client):
    assert client.get("/admin/users").status_code == 401


def test_superadmin_has_no_ai_chat_and_no_direct_clinical_access(client):
    b = boss(client)
    assert client.post("/chat", headers=b, json={"message": "안녕"}).status_code == 403
    for path in ("/patients", "/patients/1", "/patients/1/intake", "/patients/1/encounters", "/soap", "/appointments"):
        assert client.get(path, headers=b).status_code == 403, path
    assert client.post("/soap/1/approve", headers=b).status_code == 403          # SOAP 승인은 의사만
    assert client.get("/audit", headers=b).status_code == 200


# ---------- 권한 부여 ----------
def test_role_change_takes_effect_immediately_and_is_audited(client):
    pid, h = signup(client)
    assert client.get("/patients", headers=h).status_code == 403                  # 환자
    uid = user_id(client, "newpat01")
    r = client.patch(f"/admin/users/{uid}/role", headers=boss(client), json={"role": "nurse"})
    assert r.status_code == 200 and r.json() == {"id": uid, "role": "nurse", "changed": True}
    assert client.get("/patients", headers=h).status_code == 200                  # 같은 토큰으로 즉시 간호사 권한 (DB의 role을 매번 확인)
    client.patch(f"/admin/users/{uid}/role", headers=boss(client), json={"role": "patient"})
    assert client.get("/patients", headers=h).status_code == 403                  # 회수도 즉시
    log = [x for x in client.get("/audit", headers=boss(client)).json() if x["action"] == "admin.role_change"]
    assert [x["detail"] for x in log][:2] == [f"user={uid} nurse->patient", f"user={uid} patient->nurse"]
    assert {x["role"] for x in log} == {"superadmin"}


def test_same_role_is_a_noop_without_audit(client):
    signup(client)
    uid = user_id(client, "newpat01")
    assert client.patch(f"/admin/users/{uid}/role", headers=boss(client), json={"role": "patient"}).json()["changed"] is False
    assert not [x for x in client.get("/audit", headers=boss(client)).json() if x["action"] == "admin.role_change"]


@pytest.mark.parametrize("role", ["superadmin", "root", "", "ADMIN"])
def test_cannot_grant_superadmin_or_unknown_roles_via_api(client, role):
    signup(client)
    r = client.patch(f"/admin/users/{user_id(client, 'newpat01')}/role", headers=boss(client), json={"role": role})
    assert r.status_code == 400 and "부여할 수 있는 역할이 아닙니다" in r.json()["detail"]


def test_protected_targets(client):
    b = boss(client)
    users = {u["username"]: u["id"] for u in client.get("/admin/users", headers=b).json()}
    for target, needle in ((BOSS, "자기 자신"), ("superadmin_demo", "최상위"), ("doctor1", "데모 계정"), ("patient1", "데모 계정"), ("admin1", "데모 계정")):
        r = client.patch(f"/admin/users/{users[target]}/role", headers=b, json={"role": "nurse"})
        assert r.status_code == 403 and needle in r.json()["detail"], (target, r.text)
        assert client.post(f"/admin/users/{users[target]}/disable", headers=b).status_code == 403


def test_unknown_user_is_404(client):
    assert client.patch("/admin/users/99999/role", headers=boss(client), json={"role": "nurse"}).status_code == 404


def test_cannot_make_patient_without_patient_record(client):
    signup(client)
    uid = user_id(client, "newpat01")
    c = db.connect()
    try:
        c.execute("UPDATE users SET patient_id=NULL, role='nurse' WHERE id=?", (uid,))
        c.commit()
    finally:
        c.close()
    r = client.patch(f"/admin/users/{uid}/role", headers=boss(client), json={"role": "patient"})
    assert r.status_code == 400 and "환자 기록이 없는" in r.json()["detail"]


# ---------- 계정 중지 ----------
def test_disable_blocks_login_and_existing_tokens_then_enable_restores(client):
    _, h = signup(client)
    uid = user_id(client, "newpat01")
    assert client.post(f"/admin/users/{uid}/disable", headers=boss(client)).json() == {"id": uid, "disabled": True}
    assert client.get("/me", headers=h).status_code == 401                          # 이미 발급된 토큰도 즉시 무력화
    r = client.post("/auth/login", json={"username": "newpat01", "password": "pass1234"})
    assert r.status_code == 403 and "중지" in r.json()["detail"]
    assert client.post("/auth/login", json={"username": "newpat01", "password": "wrong-pass1"}).status_code == 401   # 틀린 비밀번호에는 존재 여부를 알리지 않는다
    assert client.post(f"/admin/users/{uid}/enable", headers=boss(client)).json()["disabled"] is False
    assert client.post("/auth/login", json={"username": "newpat01", "password": "pass1234"}).status_code == 200
    actions = [x["action"] for x in client.get("/audit", headers=boss(client)).json()]
    assert "admin.disable" in actions and "admin.enable" in actions


# ---------- 읽기 전용 데모 관리자 ----------
def test_read_only_admin_cannot_change_anything(client):
    signup(client)
    ro = H(client, "superadmin_demo")
    uid = user_id(client, "newpat01")
    for r in (client.patch(f"/admin/users/{uid}/role", headers=ro, json={"role": "nurse"}), client.post(f"/admin/users/{uid}/disable", headers=ro)):
        assert r.status_code == 403 and "읽기 전용" in r.json()["detail"]
    assert client.get("/admin/stats", headers=ro).status_code == 200                  # 보는 것은 가능


def test_read_only_admin_sees_masked_signups_but_full_demo_accounts(client):
    signup(client, "privateuser1", name="비밀이름")
    users = {u["id"]: u for u in client.get("/admin/users", headers=H(client, "superadmin_demo")).json()}
    signed = next(u for u in users.values() if u["role"] == "patient" and not u["is_demo"])
    assert "privateuser1" not in str(users) and "비밀이름" not in str(users)             # 가입자의 아이디·이름은 가려진다
    assert signed["username"].startswith("p") and "*" in signed["username"]
    assert {"doctor1", "nurse1", "admin1", "patient1", "superadmin_demo"} <= {u["username"] for u in users.values()}
    real = {u["username"] for u in client.get("/admin/users", headers=boss(client)).json()}
    assert "privateuser1" in real                                                      # 실제 관리자에게는 그대로 보인다


def test_read_only_break_glass_is_limited_to_seed_patients(client):
    signup_pid, _ = signup(client)
    ro = H(client, "superadmin_demo")
    ok = client.post("/admin/break-glass", headers=ro, json={"patient_id": 2, "reason": "포트폴리오 시연을 위한 열람 사유"})
    assert ok.status_code == 200 and ok.json()["patient"]["name"] == "이도윤"
    denied = client.post("/admin/break-glass", headers=ro, json={"patient_id": signup_pid, "reason": "포트폴리오 시연을 위한 열람 사유"})
    assert denied.status_code == 403 and "시드" in denied.json()["detail"]


# ---------- break-glass ----------
def test_break_glass_requires_a_real_reason(client):
    for reason in ("", "짧음", "   열람   ", "x" * 301):
        r = client.post("/admin/break-glass", headers=boss(client), json={"patient_id": 1, "reason": reason})
        assert r.status_code in (400, 422), reason
    assert "10~300자" in client.post("/admin/break-glass", headers=boss(client), json={"patient_id": 1, "reason": "짧음"}).json()["detail"]


def test_break_glass_returns_clinical_data_and_records_who_why_what(client):
    r = client.post("/admin/break-glass", headers=boss(client), json={"patient_id": 1, "reason": "환자 본인 요청에 따른 기록 정정 검토"})
    assert r.status_code == 200
    body = r.json()
    assert body["patient"]["allergies"] == "페니실린" and body["intake"]["text"].startswith("3일 전부터") and "감사 로그" in body["notice"]
    row = next(x for x in client.get("/audit", headers=boss(client)).json() if x["action"] == "admin.break_glass")
    assert row["role"] == "superadmin" and "patient=1" in row["detail"] and "본인 요청에 따른 기록 정정 검토" in row["detail"]


def test_break_glass_unknown_patient_and_unauthorized_roles(client):
    assert client.post("/admin/break-glass", headers=boss(client), json={"patient_id": 99999, "reason": "존재하지 않는 환자 조회 시도"}).status_code == 404
    assert client.post("/admin/break-glass", headers=H(client, "doctor1"), json={"patient_id": 1, "reason": "의사는 이 경로를 쓸 수 없다"}).status_code == 403


def test_break_glass_includes_encounters_and_soap_notes(client):
    from app import services
    from tests.test_agent import u
    c = db.connect()
    try:
        services.save_soap_draft(c, u(c, "doctor1"), 1, "기침", "37.9", "상기도감염 의심", "휴식")
    finally:
        c.close()
    body = client.post("/admin/break-glass", headers=boss(client), json={"patient_id": 2, "reason": "감사 대응을 위한 진료 기록 확인"}).json()
    assert body["encounters"][0]["chief_complaint"] == "기침 5일" and body["soap_notes"][0]["status"] == "draft"


# ---------- 현황 ----------
def test_stats_reflect_reality(client):
    signup(client)
    s = client.get("/admin/stats", headers=boss(client)).json()
    assert s["users_by_role"]["superadmin"] == 2 and s["users_by_role"]["patient"] == 5
    assert s["patients"] == 9 and s["users"] == 11 and s["appointments_booked"] == 3     # 시드 8 + 읽기 전용 관리자 + 실제 관리자 + 가입 1
    assert s["ai_requests_limit"] == 300 and s["ai_requests_today"] == 0 and s["model"] == "qwen/qwen3.7-flash"


def test_stats_counts_security_and_break_glass_events(client):
    client.post("/admin/break-glass", headers=boss(client), json={"patient_id": 1, "reason": "통계 집계 확인을 위한 열람"})
    assert client.get("/admin/stats", headers=boss(client)).json()["break_glass_events"] == 1


# ---------- 가입 예약어 ----------
@pytest.mark.parametrize("name", ["superadmin_x", "sysadmin1", "sudo_user", "root_user"])
def test_signup_cannot_impersonate_system_accounts(client, name):
    r = client.post("/auth/register", json={"username": name, "password": "pass1234", "name": "x", "birth_year": 1990, "sex": "F"})
    assert r.status_code == 400 and "사용할 수 없는" in r.json()["detail"]


# ---------- 마이그레이션 (이미 배포된 DB) ----------
OLD_SQLITE_USERS = """
CREATE TABLE patients (id INTEGER PRIMARY KEY, name TEXT NOT NULL, birth_year INTEGER, sex TEXT, allergies TEXT DEFAULT '', medications TEXT DEFAULT '');
CREATE TABLE users (
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('patient','doctor','nurse','admin')),
  name TEXT NOT NULL, patient_id INTEGER REFERENCES patients(id)
);
CREATE TABLE encounters (id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id), doctor_id INTEGER NOT NULL REFERENCES users(id), visit_date TEXT NOT NULL, chief_complaint TEXT NOT NULL, notes TEXT NOT NULL);
INSERT INTO patients (id, name) VALUES (1, '기존환자');
INSERT INTO users (id, username, password_hash, role, name, patient_id) VALUES (1, 'olddoc', 'h$x', 'doctor', '기존의사', NULL), (2, 'oldpat', 'h$y', 'patient', '기존환자', 1);
INSERT INTO encounters VALUES (1, 1, 1, '2026-01-01', '기침', '메모');
"""


@pytest.mark.skipif(USE_PG, reason="SQLite 마이그레이션 경로")
def test_sqlite_migration_preserves_data_and_allows_superadmin(tmp_path):
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.executescript(OLD_SQLITE_USERS)
    raw.close()
    c = db.connect(path)
    db.init_db(c)
    db.init_db(c)                                                                     # 멱등
    assert [tuple(r) for r in c.execute("SELECT id, username, role, read_only, disabled FROM users ORDER BY id")] == [(1, "olddoc", "doctor", 0, 0), (2, "oldpat", "patient", 0, 0)]
    c.execute("INSERT INTO users (username, password_hash, role, name) VALUES ('boss', 'h$z', 'superadmin', 'b')")     # 새 제약 허용
    assert c.execute("SELECT chief_complaint FROM encounters").fetchone()[0] == "기침"                                  # 딸린 테이블 유지
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    c.close()


@pytest.mark.skipif(not USE_PG, reason="PostgreSQL 마이그레이션 경로")
def test_postgres_migration_relaxes_role_check_and_adds_columns(pg_uri):
    _reset_pg(pg_uri)
    c = db.connect(pg_uri)
    c._c.execute("CREATE TABLE patients (id SERIAL PRIMARY KEY, name TEXT NOT NULL, birth_year INTEGER, sex TEXT, allergies TEXT DEFAULT '', medications TEXT DEFAULT '')")
    c._c.execute("CREATE TABLE users (id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('patient','doctor','nurse','admin')), name TEXT NOT NULL, patient_id INTEGER REFERENCES patients(id))")
    c._c.execute("INSERT INTO users (username, password_hash, role, name) VALUES ('olddoc', 'h$x', 'doctor', '기존의사')")
    c.commit()
    db.init_db(c)
    db.init_db(c)                                                                     # 멱등
    assert [tuple(r) for r in c.execute("SELECT username, role, read_only, disabled FROM users")] == [("olddoc", "doctor", 0, 0)]
    c.execute("INSERT INTO users (username, password_hash, role, name) VALUES ('boss', 'h$z', 'superadmin', 'b')")
    c.commit()
    with pytest.raises(Exception):
        c.execute("INSERT INTO users (username, password_hash, role, name) VALUES ('x', 'h', 'hacker', 'x')")            # 제약은 여전히 유효
    c.close()
