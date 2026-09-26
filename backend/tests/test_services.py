"""권한 매트릭스: 서비스 계층이 역할/소유권을 코드로 강제하는지 검증."""
from datetime import datetime

import pytest

from app import services
from app.auth import User

MON = "2030-01-07"   # 월요일
SAT = "2030-01-12"
SUN = "2030-01-13"
NOW = datetime(2030, 1, 1, 9, 0)


def u(conn, username) -> User:
    r = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    return User(r["id"], r["username"], r["role"], r["name"], r["patient_id"])


# ---- 환자 스코프
def test_patient_lists_only_own_appointments(conn):
    appts = services.list_appointments(conn, u(conn, "patient1"))
    assert appts and {a["patient_id"] for a in appts} == {1}


def test_patient_cannot_request_other_patient_appointments(conn):
    with pytest.raises(services.PermissionDenied):
        services.list_appointments(conn, u(conn, "patient1"), patient_id=3)


def test_patient_cannot_read_intake_or_profile_of_anyone(conn):
    p = u(conn, "patient1")
    for fn in (services.get_latest_intake, services.get_patient_profile):
        with pytest.raises(services.PermissionDenied):
            fn(conn, p, 1)


def test_patient_cannot_book_for_someone_else(conn):
    with pytest.raises(services.PermissionDenied):
        services.book_appointment(conn, u(conn, "patient1"), f"{MON} 10:00", patient_id=3, now=NOW)


def test_patient_submit_intake_is_own(conn):
    r = services.submit_intake(conn, u(conn, "patient2"), "어제부터 두통이 있고 열이 조금 납니다.")
    assert r["patient_id"] == 2


# ---- 필드 단위 접근 제어
def test_profile_fields_by_role(conn):
    admin = services.get_patient_profile(conn, u(conn, "admin1"), 1)
    nurse = services.get_patient_profile(conn, u(conn, "nurse1"), 1)
    doctor = services.get_patient_profile(conn, u(conn, "doctor1"), 1)
    assert "allergies" not in admin and "medications" not in admin
    assert nurse["allergies"] == "페니실린" and doctor["allergies"] == "페니실린"


def test_admin_cannot_read_clinical(conn):
    a = u(conn, "admin1")
    with pytest.raises(services.PermissionDenied):
        services.get_latest_intake(conn, a, 1)
    with pytest.raises(services.PermissionDenied):
        services.get_encounter(conn, a, 1)


def test_nurse_reads_intake_but_not_encounter(conn):
    n = u(conn, "nurse1")
    assert "페니실린" in services.get_latest_intake(conn, n, 1)["text"]
    with pytest.raises(services.PermissionDenied):
        services.get_encounter(conn, n, 1)


# ---- 예약 규칙
def test_book_ok_and_double_booking_blocked(conn):
    p = u(conn, "patient1")
    r = services.book_appointment(conn, p, f"{MON} 10:00", "상담", now=NOW)
    assert r["slot"] == f"{MON} 10:00"
    with pytest.raises(services.ServiceError, match="이미"):
        services.book_appointment(conn, p, f"{MON} 10:00", now=NOW)


@pytest.mark.parametrize("slot", [f"{SAT} 15:00", f"{SUN} 10:00", f"{MON} 12:30", f"{MON} 18:00", f"{MON} 09:10"])
def test_book_outside_hours_rejected(conn, slot):
    with pytest.raises(services.ServiceError):
        services.book_appointment(conn, u(conn, "patient1"), slot, now=NOW)


def test_past_slot_rejected(conn):
    with pytest.raises(services.ServiceError, match="지난"):
        services.book_appointment(conn, u(conn, "patient1"), f"{MON} 10:00", now=datetime(2030, 1, 8))


def test_capacity_equals_number_of_doctors(conn):
    slot = f"{MON} 11:00"
    services.book_appointment(conn, u(conn, "patient1"), slot, now=NOW)
    services.book_appointment(conn, u(conn, "patient2"), slot, now=NOW)
    with pytest.raises(services.ServiceError, match="마감"):
        services.book_appointment(conn, u(conn, "patient3"), slot, now=NOW)
    assert slot not in services.available_slots(conn, MON)


def test_admin_books_for_patient_but_needs_patient_id(conn):
    a = u(conn, "admin1")
    assert services.book_appointment(conn, a, f"{MON} 14:00", patient_id=4, now=NOW)["patient_id"] == 4
    with pytest.raises(services.ServiceError):
        services.book_appointment(conn, a, f"{MON} 14:30", now=NOW)


def test_nurse_and_doctor_cannot_book(conn):
    for name in ("nurse1", "doctor1"):
        with pytest.raises(services.PermissionDenied):
            services.book_appointment(conn, u(conn, name), f"{MON} 15:00", patient_id=1, now=NOW)


def test_cancel_deadline_for_patient(conn):
    p = u(conn, "patient1")
    aid = services.book_appointment(conn, p, f"{MON} 10:00", now=NOW)["appointment_id"]
    with pytest.raises(services.ServiceError, match="전화"):
        services.cancel_appointment(conn, p, aid, now=datetime(2030, 1, 6, 19, 0))  # 전날 18:00 이후
    assert services.cancel_appointment(conn, p, aid, now=datetime(2030, 1, 6, 17, 0))["status"] == "cancelled"


def test_admin_cancels_after_deadline_and_patient_cannot_cancel_others(conn):
    aid = services.book_appointment(conn, u(conn, "patient1"), f"{MON} 10:30", now=NOW)["appointment_id"]
    with pytest.raises(services.PermissionDenied):
        services.cancel_appointment(conn, u(conn, "patient2"), aid, now=NOW)
    assert services.cancel_appointment(conn, u(conn, "admin1"), aid, now=datetime(2030, 1, 7, 9, 0))["status"] == "cancelled"


# ---- SOAP human-in-the-loop
def test_soap_draft_and_approval_flow(conn):
    doc = u(conn, "doctor1")
    d = services.save_soap_draft(conn, doc, 1, "기침 5일", "37.9", "상기도감염 의심", "휴식")
    assert d["status"] == "draft"
    assert services.get_soap(conn, doc, d["soap_id"])["status"] == "draft"
    assert services.approve_soap(conn, doc, d["soap_id"])["status"] == "approved"


@pytest.mark.parametrize("name", ["nurse1", "admin1", "patient1"])
def test_only_doctor_drafts_and_approves(conn, name):
    doc = u(conn, "doctor1")
    sid = services.save_soap_draft(conn, doc, 1, "s", "o", "a", "p")["soap_id"]
    with pytest.raises(services.PermissionDenied):
        services.save_soap_draft(conn, u(conn, name), 1, "s", "o", "a", "p")
    with pytest.raises(services.PermissionDenied):
        services.approve_soap(conn, u(conn, name), sid)


# ---- 감사 로그
def test_audit_only_for_admin_and_records_actions(conn):
    services.book_appointment(conn, u(conn, "patient1"), f"{MON} 16:00", now=NOW)
    log = services.read_audit(conn, u(conn, "admin1"))
    assert any(r["action"] == "appointment.book" for r in log)
    for name in ("doctor1", "nurse1", "patient1"):
        with pytest.raises(services.PermissionDenied):
            services.read_audit(conn, u(conn, name))
