import pytest

from app.rbac import PERMISSIONS, Role, has_any, has_permission


def test_patient_has_only_own_scoped_permissions():
    p = PERMISSIONS[Role.PATIENT]
    assert "appointment.read_all" not in p and "patient.read_clinical" not in p and "soap.draft" not in p


def test_admin_has_no_clinical_access():
    for perm in ("patient.read_clinical", "intake.read", "encounter.read", "soap.draft", "soap.approve"):
        assert not has_permission("admin", perm)
    assert has_permission("admin", "appointment.manage_all")


def test_only_doctor_can_draft_and_approve_soap():
    for role in ("patient", "nurse", "admin"):
        assert not has_permission(role, "soap.draft") and not has_permission(role, "soap.approve")
    assert has_permission("doctor", "soap.draft") and has_permission("doctor", "soap.approve")


def test_nurse_reads_intake_but_not_encounters():
    assert has_permission("nurse", "intake.read") and not has_permission("nurse", "encounter.read")


def test_unknown_role_denied():
    assert not has_permission("hacker", "chat")
    assert not has_any("hacker", ("chat",))


@pytest.mark.parametrize("role", [r.value for r in Role if r is not Role.SUPERADMIN])
def test_every_clinical_role_can_chat(role):
    assert has_permission(role, "chat")


def test_superadmin_has_no_chat_and_no_clinical_access():
    """시스템 관리자는 AI 대화와 임상 권한이 없다. 임상 기록은 사유를 남기는 break-glass로만 본다."""
    for perm in ("chat", "patient.read_clinical", "intake.read", "encounter.read", "soap.draft", "soap.approve", "appointment.manage_all"):
        assert not has_permission("superadmin", perm)
    assert all(has_permission("superadmin", p) for p in ("admin.users", "admin.stats", "admin.break_glass", "audit.read"))


def test_no_other_role_has_admin_permissions():
    for role in ("patient", "nurse", "doctor", "admin"):
        assert not any(has_permission(role, p) for p in ("admin.users", "admin.stats", "admin.break_glass"))
