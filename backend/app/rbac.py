"""역할(Role)과 권한(Permission) 정의. 모든 접근 제어의 단일 출처.

원칙: 최소 권한. 환자는 본인 데이터만, 원무는 임상 정보 없이 예약만, 최종 승인은 의사만.
"""
from enum import StrEnum


class Role(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    NURSE = "nurse"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"   # 시스템 관리자: 사용자·권한·감사·현황. 임상 데이터는 사유를 남기는 break-glass로만.


PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.PATIENT: frozenset({
        "chat", "appointment.read_own", "appointment.book_own", "appointment.cancel_own", "intake.submit_own", "drug.check",
    }),
    Role.NURSE: frozenset({
        "chat", "appointment.read_all", "patient.read_demographics", "patient.read_clinical", "intake.read",
        "literature.search", "drug.check",
    }),
    Role.DOCTOR: frozenset({
        "chat", "appointment.read_all", "patient.read_demographics", "patient.read_clinical", "intake.read",
        "encounter.read", "soap.draft", "soap.approve", "literature.search", "drug.check",
    }),
    # 시스템 관리자는 채팅(AI)과 임상 기능이 없고, 임상 기록은 admin.break_glass로 사유를 남기고 열람한다.
    Role.SUPERADMIN: frozenset({"audit.read", "admin.users", "admin.stats", "admin.break_glass"}),
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
