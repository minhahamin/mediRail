from datetime import date, datetime

from app import clinic
from app.auth import authenticate
from tests.conftest import login


def test_seed_counts(conn):
    assert conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 8
    roles = {r[0] for r in conn.execute("SELECT DISTINCT role FROM users")}
    assert roles == {"patient", "doctor", "nurse", "admin"}


def test_password_not_stored_plain(conn):
    assert all("demo1234" not in r[0] for r in conn.execute("SELECT password_hash FROM users"))


def test_authenticate(conn):
    assert authenticate(conn, "doctor1", "demo1234").role == "doctor"
    assert authenticate(conn, "doctor1", "wrong") is None
    assert authenticate(conn, "nobody", "demo1234") is None


def test_clinic_hours():
    assert clinic.is_bookable(datetime(2026, 10, 5, 9, 0))        # 월 09:00
    assert not clinic.is_bookable(datetime(2026, 10, 5, 12, 30))  # 점심
    assert not clinic.is_bookable(datetime(2026, 10, 5, 18, 0))   # 마감 이후
    assert clinic.is_bookable(datetime(2026, 10, 10, 12, 30))     # 토 12:30 (13:00 마감 전 마지막 슬롯)
    assert not clinic.is_bookable(datetime(2026, 10, 10, 15, 0))  # 토 오후
    assert not clinic.is_bookable(datetime(2026, 10, 11, 10, 0))  # 일 휴진
    assert not clinic.is_bookable(datetime(2026, 10, 5, 9, 10))   # 30분 단위 아님


def test_slots_count():
    assert len(clinic.slots_for(date(2026, 10, 5))) == 16  # 09:00-18:00 30분 슬롯 18개 - 점심 2개
    assert len(clinic.slots_for(date(2026, 10, 10))) == 8   # 토 09:00-13:00, 점심 없음
    assert clinic.slots_for(date(2026, 10, 11)) == []


def test_login_and_me(client):
    h = login(client, "patient1")
    me = client.get("/me", headers=h).json()
    assert me["role"] == "patient" and me["patient_id"] == 1


def test_login_wrong_password(client):
    assert client.post("/auth/login", json={"username": "patient1", "password": "x"}).status_code == 401


def test_me_requires_token(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_health_shows_default_model(client):
    assert client.get("/health").json()["model"] == "qwen/qwen3.7-flash"
