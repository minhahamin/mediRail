"""데모 계정 목록은 코드 상수가 아니라 DB에서 조회한다."""
from app import db


def test_returns_one_account_per_role_in_order_without_secrets(client):
    r = client.get("/auth/demo-accounts")           # 로그인 없이 조회 가능
    assert r.status_code == 200
    body = r.json()
    assert [a["role"] for a in body] == ["patient", "nurse", "doctor", "admin", "superadmin"]
    assert [a["username"] for a in body] == ["patient1", "nurse1", "doctor1", "admin1", "superadmin_demo"]   # 마지막은 읽기 전용 시스템 관리자
    assert all(set(a) == {"username", "role", "name"} for a in body)          # 비밀번호·해시·id 없음


def test_list_is_read_from_the_database_not_hardcoded(client):
    """DB의 이름을 바꾸면 응답이 바뀌고, 행을 지우면 응답에서 사라진다."""
    c = db.connect()
    try:
        c.execute("UPDATE users SET name=? WHERE username=?", ("DB에서 바꾼 이름", "admin1"))
        c.execute("DELETE FROM users WHERE username=?", ("nurse1",))
        c.commit()
    finally:
        c.close()
    body = {a["role"]: a for a in client.get("/auth/demo-accounts").json()}
    assert body["admin"]["name"] == "DB에서 바꾼 이름"
    assert "nurse" not in body and set(body) == {"patient", "doctor", "admin", "superadmin"}


def test_signed_up_users_are_not_listed_as_demo_accounts(client):
    client.post("/auth/register", json={"username": "newuser01", "password": "pass1234", "name": "새싹", "birth_year": 1995, "sex": "F"})
    assert "newuser01" not in [a["username"] for a in client.get("/auth/demo-accounts").json()]
