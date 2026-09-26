"""시스템 관리자(superadmin) 기능: 사용자·권한 관리, 현황, 임상 기록 열람(break-glass).

설계 원칙
- 최상위 관리자도 임상 데이터를 상시 볼 수 없다(최소 권한). 열람하려면 사유를 적어야 하고, 열람 사실이 감사 로그에 남는다.
- 최상위 관리자 계정은 API로 만들거나 부여할 수 없다. 환경변수로만 만들고(ensure_system_accounts) 회전한다.
- 자기 자신, 다른 최상위 관리자, 데모 계정의 권한은 바꿀 수 없다 (잠금 사고·데모 파손 방지).
- 읽기 전용 관리자(공개 데모용)는 어떤 변경도 할 수 없고, 가입자가 입력한 개인 정보는 마스킹되어 보인다.
- 권한 변경은 토큰이 아니라 DB의 role을 매 요청마다 확인하므로 즉시 반영된다.
"""
from . import ratelimit
from .auth import User
from .config import get_settings
from .seed import PATIENTS, USERS, hash_password, verify_password
from .services import (NotFound, PermissionDenied, ServiceError, USERNAME_RE, _clean_text, _need, audit,
                       get_latest_intake, get_patient_profile)

SEED_USERNAMES = frozenset(u[0] for u in USERS)
DEMO_ADMIN = "superadmin_demo"
DEMO_PASSWORD = "demo1234"
ASSIGNABLE = ("patient", "nurse", "doctor", "admin")    # superadmin은 API로 부여할 수 없다
SEED_PATIENT_MAX_ID = len(PATIENTS)


def _need_write(actor: User) -> None:
    if actor.read_only:
        raise PermissionDenied("읽기 전용 관리자 계정은 변경할 수 없습니다")


def _mask(s: str) -> str:
    return (s[:1] + "*" * min(len(s) - 1, 4)) if s else s


def _is_demo(username: str) -> bool:
    return username in SEED_USERNAMES or username == DEMO_ADMIN


# ---------- 사용자·권한 ----------
def list_users(conn, actor: User) -> list[dict]:
    _need(actor, "admin.users")
    out = []
    for r in conn.execute("SELECT id, username, role, name, patient_id, read_only, disabled FROM users ORDER BY id"):
        d = {"id": r["id"], "username": r["username"], "role": r["role"], "name": r["name"], "patient_id": r["patient_id"],
             "read_only": bool(r["read_only"]), "disabled": bool(r["disabled"]), "is_demo": _is_demo(r["username"])}
        if actor.read_only and not d["is_demo"]:    # 공개 데모: 가입자의 아이디·이름은 가려서 보여준다
            d["username"], d["name"] = _mask(d["username"]), _mask(d["name"])
        out.append(d)
    return out


def _target(conn, actor: User, user_id: int):
    _need(actor, "admin.users")
    _need_write(actor)
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise NotFound("사용자를 찾을 수 없습니다")
    if row["id"] == actor.id:
        raise PermissionDenied("자기 자신의 계정은 변경할 수 없습니다")
    if row["role"] == "superadmin":
        raise PermissionDenied("최상위 관리자 계정은 변경할 수 없습니다")
    if _is_demo(row["username"]):
        raise PermissionDenied("데모 계정은 보호되어 있어 변경할 수 없습니다")
    return row


def set_user_role(conn, actor: User, user_id: int, role: str) -> dict:
    if role not in ASSIGNABLE:
        raise ServiceError("부여할 수 있는 역할이 아닙니다 (최상위 관리자는 API로 부여할 수 없습니다)")
    row = _target(conn, actor, user_id)
    if role == "patient" and row["patient_id"] is None:
        raise ServiceError("환자 기록이 없는 계정은 환자로 바꿀 수 없습니다")
    if row["role"] == role:
        return {"id": user_id, "role": role, "changed": False}
    conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    conn.commit()
    audit(conn, actor, "admin.role_change", f"user={user_id} {row['role']}->{role}")
    return {"id": user_id, "role": role, "changed": True}


def set_user_disabled(conn, actor: User, user_id: int, disabled: bool) -> dict:
    row = _target(conn, actor, user_id)
    conn.execute("UPDATE users SET disabled=? WHERE id=?", (1 if disabled else 0, user_id))
    conn.commit()
    audit(conn, actor, "admin.disable" if disabled else "admin.enable", f"user={user_id} role={row['role']}")
    return {"id": user_id, "disabled": disabled}


# ---------- 현황 ----------
def stats(conn, actor: User) -> dict:
    _need(actor, "admin.stats")
    one = lambda sql: conn.execute(sql).fetchone()[0]
    used, limit = ratelimit.daily_usage()
    return {
        "users_by_role": {r["role"]: r["n"] for r in conn.execute("SELECT role, COUNT(*) n FROM users GROUP BY role")},
        "users": one("SELECT COUNT(*) FROM users"), "users_capacity": get_settings().max_users,
        "disabled_users": one("SELECT COUNT(*) FROM users WHERE disabled=1"),
        "patients": one("SELECT COUNT(*) FROM patients"),
        "appointments_booked": one("SELECT COUNT(*) FROM appointments WHERE status='booked'"),
        "soap_draft": one("SELECT COUNT(*) FROM soap_notes WHERE status='draft'"),
        "soap_approved": one("SELECT COUNT(*) FROM soap_notes WHERE status='approved'"),
        "audit_entries": one("SELECT COUNT(*) FROM audit_log"),
        "security_events": one("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'security.%'"),
        "break_glass_events": one("SELECT COUNT(*) FROM audit_log WHERE action='admin.break_glass'"),
        "ai_requests_today": used, "ai_requests_limit": limit,
        "model": get_settings().model,
    }


# ---------- break-glass: 사유를 남기고 임상 기록 열람 ----------
def break_glass(conn, actor: User, patient_id: int, reason: str) -> dict:
    _need(actor, "admin.break_glass")
    reason = _clean_text(reason)
    if not 10 <= len(reason) <= 300:
        raise ServiceError("열람 사유를 10~300자로 구체적으로 적어 주세요 (사유에 환자 개인정보는 쓰지 마세요)")
    if actor.read_only and patient_id > SEED_PATIENT_MAX_ID:
        raise PermissionDenied("읽기 전용 관리자는 시드(합성) 환자 기록만 열람할 수 있습니다")
    # 임상 필드까지 보려면 임상 권한이 필요하므로, 의사 권한의 서비스 호출에 필요한 조회를 관리자용으로 직접 수행한다
    p = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    if not p:
        raise NotFound("환자를 찾을 수 없습니다")
    intake = conn.execute("SELECT id, text, created_at FROM intakes WHERE patient_id=? ORDER BY id DESC LIMIT 1", (patient_id,)).fetchone()
    encounters = [dict(r) for r in conn.execute(
        "SELECT id, visit_date, chief_complaint, notes FROM encounters WHERE patient_id=? ORDER BY visit_date DESC, id DESC", (patient_id,))]
    soaps = [dict(r) for r in conn.execute(
        "SELECT s.id, s.encounter_id, s.subjective, s.objective, s.assessment, s.plan, s.status, s.created_at "
        "FROM soap_notes s JOIN encounters e ON e.id=s.encounter_id WHERE e.patient_id=? ORDER BY s.id DESC", (patient_id,))]
    audit(conn, actor, "admin.break_glass", f"patient={patient_id} reason={reason}")   # 열람 사실과 사유를 남긴다
    return {"patient": {"id": p["id"], "name": p["name"], "birth_year": p["birth_year"], "sex": p["sex"],
                        "allergies": p["allergies"] or "없음", "medications": p["medications"] or "없음"},
            "intake": dict(intake) if intake else None, "encounters": encounters, "soap_notes": soaps,
            "notice": "이 열람은 감사 로그에 기록되었습니다."}


# ---------- 시스템 계정 (시작 시) ----------
def ensure_system_accounts(conn) -> None:
    """(1) 읽기 전용 데모 관리자(공개). (2) 환경변수로 지정한 실제 최상위 관리자(비공개, 비밀번호 회전 지원). 멱등."""
    if not conn.execute("SELECT 1 FROM users WHERE username=?", (DEMO_ADMIN,)).fetchone():
        conn.execute("INSERT INTO users (username, password_hash, role, name, patient_id, read_only, disabled) VALUES (?,?,?,?,?,?,?)",
                     (DEMO_ADMIN, hash_password(DEMO_PASSWORD), "superadmin", "시스템 관리자 (읽기 전용)", None, 1, 0))
        conn.commit()

    s = get_settings()
    if not (s.superadmin_username and s.superadmin_password):
        return
    username, password = s.superadmin_username.strip().lower(), s.superadmin_password
    if not USERNAME_RE.match(username) or username == DEMO_ADMIN:
        raise RuntimeError("MEDIRAIL_SUPERADMIN_USERNAME 형식이 올바르지 않습니다 (영문 소문자·숫자·밑줄 4~20자)")
    if len(password) < 12:
        raise RuntimeError("MEDIRAIL_SUPERADMIN_PASSWORD는 12자 이상이어야 합니다")
    row = conn.execute("SELECT id, role, password_hash FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.execute("INSERT INTO users (username, password_hash, role, name, patient_id, read_only, disabled) VALUES (?,?,?,?,?,?,?)",
                     (username, hash_password(password), "superadmin", "시스템 관리자", None, 0, 0))
    elif row["role"] != "superadmin":
        raise RuntimeError("MEDIRAIL_SUPERADMIN_USERNAME이 이미 다른 역할의 계정으로 쓰이고 있습니다")
    elif not verify_password(password, row["password_hash"]):    # 환경변수를 바꾸면 비밀번호가 회전된다
        conn.execute("UPDATE users SET password_hash=?, disabled=0 WHERE id=?", (hash_password(password), row["id"]))
    conn.commit()
