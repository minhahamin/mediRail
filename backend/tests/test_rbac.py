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


@pytest.mark.parametrize("role", [r.value for r in Role])
def test_every_role_can_chat(role):
    assert has_permission(role, "chat")
