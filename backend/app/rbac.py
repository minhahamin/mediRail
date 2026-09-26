"""역할(Role)과 권한(Permission) 정의. 모든 접근 제어의 단일 출처.

원칙: 최소 권한. 환자는 본인 데이터만, 원무는 임상 정보 없이 예약만, 최종 승인은 의사만.
"""
from enum import StrEnum


class Role(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    NURSE = "nurse"
    ADMIN = "admin"


PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.PATIENT: frozenset({
        "chat", "appointment.read_own", "appointment.book_own", "appointment.cancel_own", "intake.submit_own",
    }),
    Role.NURSE: frozenset({
        "chat", "appointment.read_all", "patient.read_demographics", "patient.read_clinical", "intake.read",
        "literature.search",
    }),
    Role.DOCTOR: frozenset({
        "chat", "appointment.read_all", "patient.read_demographics", "patient.read_clinical", "intake.read",
        "encounter.read", "soap.draft", "soap.approve", "literature.search",
    }),
    Role.ADMIN: frozenset({
        "chat", "appointment.read_all", "appointment.manage_all", "patient.read_demographics", "audit.read",
    }),
}


def has_permission(role: str, perm: str) -> bool:
    try:
        return perm in PERMISSIONS[Role(role)]
    except ValueError:
        return False


def has_any(role: str, perms: tuple[str, ...]) -> bool:
    return any(has_permission(role, p) for p in perms)
