"""회원가입: 환자 전용, 권한 상승 불가, 검증, 남용 방지."""
import pytest

from app import services
from tests.conftest import login

VALID = {"username": "newuser01", "password": "pass1234", "name": "새싹", "birth_year": 1995, "sex": "F"}


def register(client, **over):
    return client.post("/auth/register", json={**VALID, **over})


def test_register_creates_patient_account_and_logs_in(client):
    r = register(client, allergies="땅콩", medications="")
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "patient" and body["name"] == "새싹" and body["patient_id"] >= 9      # 시드 환자 8명 다음
    h = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/me", headers=h).json()
    assert me["username"] == "newuser01" and me["role"] == "patient" and me["patient_id"] == body["patient_id"]
    assert login(client, "newuser01", "pass1234")            # 가입한 비밀번호로 다시 로그인 가능


def test_username_is_case_insensitive_and_trimmed(client):
    assert register(client, username="  MixedCase1 ").status_code == 201
    assert login(client, "mixedcase1", "pass1234")
    assert register(client, username="MIXEDCASE1").status_code == 409


def test_role_cannot_be_chosen_at_signup(client):
    """요청에 role을 넣어도 무시되어 항상 환자다 (권한 상승 방지)."""
    r = register(client, role="doctor", is_admin=True)
    assert r.status_code == 201 and r.json()["role"] == "patient"
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    for path in ("/patients", "/audit", "/soap"):
        assert client.get(path, headers=h).status_code == 403


def test_new_patient_cannot_see_other_patients(client):
    r = register(client)
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/appointments", headers=h).json() == []                      # 본인 예약만 (아직 없음)
    assert client.get("/appointments?patient_id=1", headers=h).status_code == 403
    assert client.get("/patients/1", headers=h).status_code == 403
    assert client.get(f"/patients/{r.json()['patient_id']}", headers=h).status_code == 403   # 환자 조회 API 자체가 직원 전용


def test_new_patient_can_use_patient_features(client):
    h = {"Authorization": f"Bearer {register(client).json()['access_token']}"}
    slots = client.get("/appointments/slots?date=2031-03-04", headers=h).json()["slots"]
    assert client.post("/appointments", headers=h, json={"slot": slots[0], "reason": "첫 방문"}).status_code == 200
    assert len(client.get("/appointments", headers=h).json()) == 1
    assert client.post("/intake", headers=h, json={"text": "어제부터 두통이 있습니다."}).status_code == 200


def test_staff_can_see_the_new_patient_with_entered_clinical_fields(client):
    r = register(client, allergies="땅콩", medications="비타민D")
    prof = client.get(f"/patients/{r.json()['patient_id']}", headers=login(client, "doctor1")).json()
    assert prof["allergies"] == "땅콩" and prof["medications"] == "비타민D"
    admin_view = client.get(f"/patients/{r.json()['patient_id']}", headers=login(client, "admin1")).json()
    assert "allergies" not in admin_view                                             # 원무는 여전히 임상 필드 차단


def test_password_is_hashed(client):
    register(client)
    from app import db
    c = db.connect()
    try:
        h = c.execute("SELECT password_hash FROM users WHERE username='newuser01'").fetchone()[0]
    finally:
        c.close()
    assert "pass1234" not in h and "$" in h


@pytest.mark.parametrize("over,needle", [
    ({"username": "ab"}, "4~20자"),
    ({"username": "한글아이디"}, "4~20자"),
    ({"username": "has space"}, "4~20자"),
    ({"username": "a" * 21}, "4~20자"),
    ({"username": "doctor99"}, "사용할 수 없는"),
    ({"username": "admin_x"}, "사용할 수 없는"),
    ({"username": "medirail1"}, "사용할 수 없는"),
    ({"password": "short1"}, "8~72자"),
    ({"password": "onlyletters"}, "영문과 숫자"),
    ({"password": "12345678"}, "영문과 숫자"),
    ({"name": "   "}, "1~20자"),
    ({"name": "가" * 21}, "1~20자"),
    ({"birth_year": 1800}, "출생연도"),
    ({"birth_year": 2999}, "출생연도"),
    ({"sex": "X"}, "성별"),
    ({"allergies": "가" * 201}, "200자"),
])
def test_validation(client, over, needle):
    r = register(client, **over)
    assert r.status_code == 400 and needle in r.json()["detail"]


def test_demo_account_usernames_are_taken(client):
    assert register(client, username="patient1").status_code == 409      # 데모 계정 사칭/덮어쓰기 불가


def test_duplicate_username_is_conflict(client):
    assert register(client).status_code == 201
    r = register(client)
    assert r.status_code == 409 and "이미 사용 중" in r.json()["detail"]


def test_extra_long_inputs_rejected_before_hashing(client):
    assert register(client, password="a1" * 60).status_code in (400, 422)
    assert register(client, username="x" * 100).status_code == 422


def test_signup_is_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_REGISTER_PER_IP_HOUR", "2")
    assert [register(client, username=f"limit{i:02d}").status_code for i in range(3)] == [201, 201, 429]
    assert register(client, username="limit99", **{}).status_code == 429
    other = client.post("/auth/register", json={**VALID, "username": "otherip1"}, headers={"X-Forwarded-For": "198.51.100.20"})
    assert other.status_code == 201


def test_total_users_are_capped(client, monkeypatch):
    monkeypatch.setenv("MEDIRAIL_MAX_USERS", "9")        # 시드 8명 + 1명
    assert register(client, username="cap00001").status_code == 201
    r = register(client, username="cap00002")
    assert r.status_code == 400 and "정원" in r.json()["detail"]


def test_register_writes_audit_without_sensitive_data(client):
    register(client, allergies="땅콩")
    log = client.get("/audit", headers=login(client, "admin1")).json()
    row = next(x for x in log if x["action"] == "auth.register")
    assert row["role"] == "patient" and "pass1234" not in (row["detail"] or "") and "땅콩" not in (row["detail"] or "")


def test_service_level_register_is_atomic_on_conflict(conn):
    services.register_patient(conn, "atomic01", "pass1234", "가", 2000, "F")
    before = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    with pytest.raises(services.Conflict):
        services.register_patient(conn, "atomic01", "pass1234", "나", 2000, "M")
    assert conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == before      # 실패한 가입이 환자 기록을 남기지 않는다
