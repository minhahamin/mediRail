"""도메인 로직 + 권한 검사의 단일 지점.

REST 라우트와 에이전트 도구는 모두 이 계층을 호출한다. 그래서 LLM이 어떤 도구 호출을 시도해도
사람이 직접 API를 호출할 때와 동일한 접근 제어가 적용된다 (프롬프트가 아니라 코드로 강제).
"""
import re
from datetime import date, datetime

from . import clinic
from .auth import User
from .rbac import has_any, has_permission


class ServiceError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류."""


class PermissionDenied(ServiceError):
    pass


class NotFound(ServiceError):
    pass


class Conflict(ServiceError):
    pass


def _need(actor: User, *perms: str) -> None:
    if not has_any(actor.role, perms):
        raise PermissionDenied(f"권한이 없습니다: {' 또는 '.join(perms)}")


def audit(conn, actor: User | None, action: str, detail: str = "") -> None:
    conn.execute("INSERT INTO audit_log (ts, user_id, role, action, detail) VALUES (?,?,?,?,?)",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), actor.id if actor else None,
                  actor.role if actor else None, action, detail[:500]))
    conn.commit()


def read_audit(conn, actor: User, limit: int = 100) -> list[dict]:
    _need(actor, "audit.read")
    return [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 500),))]


def _resolve_patient(actor: User, patient_id: int | None, own: str) -> int:
    """환자는 본인 id로 고정하고, 다른 id를 요청하면 거부한다."""
    _need(actor, own)
    if patient_id is not None and patient_id != actor.patient_id:
        raise PermissionDenied("본인의 정보만 조회·변경할 수 있습니다")
    return actor.patient_id


# ---------- 회원가입 (환자 전용) ----------
USERNAME_RE = re.compile(r"^[a-z0-9_]{4,20}$")
# 직원·시스템을 사칭할 수 있는 아이디는 쓸 수 없다 (데모 계정 patient1~4 등은 중복 검사로 막힌다)
RESERVED_PREFIXES = ("doctor", "nurse", "admin", "staff", "root", "system", "medirail", "support", "superadmin", "sysadmin", "sudo")


def register_patient(conn, username: str, password: str, name: str, birth_year: int, sex: str,
                     allergies: str = "", medications: str = "") -> User:
    """새 환자 계정과 환자 기록을 만든다. 역할은 항상 patient다 (의료진·원무는 가입으로 만들 수 없다)."""
    from .config import get_settings
    from .seed import hash_password

    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ServiceError("아이디는 영문 소문자·숫자·밑줄(_) 4~20자여야 합니다")
    if username.startswith(RESERVED_PREFIXES):
        raise ServiceError("사용할 수 없는 아이디입니다")
    if not (8 <= len(password or "") <= 72 and re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise ServiceError("비밀번호는 8~72자이며 영문과 숫자를 모두 포함해야 합니다")
    name = _clean_text(name)
    if not 1 <= len(name) <= 20:
        raise ServiceError("이름(닉네임)은 1~20자여야 합니다")
    if not 1900 <= int(birth_year or 0) <= date.today().year:
        raise ServiceError("출생연도를 올바르게 입력해 주세요")
    if sex not in ("F", "M"):
        raise ServiceError("성별을 선택해 주세요")
    allergies, medications = _clean_text(allergies), _clean_text(medications)
    if len(allergies) > 200 or len(medications) > 200:
        raise ServiceError("알레르기·복용약은 각각 200자 이하여야 합니다")
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= get_settings().max_users:
        raise ServiceError("데모 계정 정원이 가득 찼습니다. 데모 계정으로 체험해 주세요.")
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise Conflict("이미 사용 중인 아이디입니다")
    try:
        pid = conn.execute("INSERT INTO patients (name, birth_year, sex, allergies, medications) VALUES (?,?,?,?,?)",
                           (name, int(birth_year), sex, allergies, medications)).lastrowid
        uid = conn.execute("INSERT INTO users (username, password_hash, role, name, patient_id) VALUES (?,?,?,?,?)",
                           (username, hash_password(password), "patient", name, pid)).lastrowid
        conn.commit()
    except Exception as e:  # 동시 가입으로 같은 아이디가 먼저 들어간 경우 (sqlite IntegrityError / PostgreSQL UniqueViolation)
        conn.rollback()
        if type(e).__name__ in ("IntegrityError", "UniqueViolation"):
            raise Conflict("이미 사용 중인 아이디입니다")
        raise
    user = User(uid, username, "patient", name, pid)
    audit(conn, user, "auth.register", f"patient={pid}")
    return user


def _clean_text(s) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def list_demo_accounts(conn) -> list[dict]:
    """데모 체험 화면에 보여줄 계정. 코드에 박아 둔 목록이 아니라 users 테이블에서 조회한다 (역할별 첫 계정).
    비밀번호나 해시는 돌려주지 않는다."""
    from .admin import DEMO_ADMIN
    from .seed import USERS

    names = [u[0] for u in USERS] + [DEMO_ADMIN]
    rows = conn.execute(f"SELECT username, role, name FROM users WHERE username IN ({','.join('?' for _ in names)}) AND disabled=0 ORDER BY id", names)
    order = ["patient", "nurse", "doctor", "admin", "superadmin"]
    first: dict = {}
    for r in rows:
        first.setdefault(r["role"], {"username": r["username"], "role": r["role"], "name": r["name"]})
    return sorted(first.values(), key=lambda x: order.index(x["role"]))


# ---------- 환자 정보 ----------
def list_patients(conn, actor: User) -> list[dict]:
    _need(actor, "patient.read_demographics")
    return [dict(r) for r in conn.execute("SELECT id, name, birth_year, sex FROM patients ORDER BY id")]


def get_patient_profile(conn, actor: User, patient_id: int) -> dict:
    """필드 단위 접근 제어: 원무는 인적사항만, 의사·간호사는 알레르기/복용약까지."""
    _need(actor, "patient.read_demographics")
    row = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    if not row:
        raise NotFound("환자를 찾을 수 없습니다")
    out = {"id": row["id"], "name": row["name"], "birth_year": row["birth_year"], "sex": row["sex"]}
    if has_permission(actor.role, "patient.read_clinical"):
        out |= {"allergies": row["allergies"] or "없음", "medications": row["medications"] or "없음"}
    return out


def get_latest_intake(conn, actor: User, patient_id: int) -> dict:
    _need(actor, "intake.read")
    row = conn.execute("SELECT * FROM intakes WHERE patient_id=? ORDER BY id DESC LIMIT 1", (patient_id,)).fetchone()
    if not row:
        raise NotFound("등록된 문진 기록이 없습니다")
    profile = get_patient_profile(conn, actor, patient_id)
    return {"id": row["id"], "patient_id": patient_id, "text": row["text"], "created_at": row["created_at"],
            "allergies": profile.get("allergies"), "medications": profile.get("medications")}


def submit_intake(conn, actor: User, text: str) -> dict:
    pid = _resolve_patient(actor, None, "intake.submit_own")
    text = (text or "").strip()
    if not 5 <= len(text) <= 3000:
        raise ServiceError("문진 내용은 5~3000자여야 합니다")
    cur = conn.execute("INSERT INTO intakes (patient_id, text, created_at) VALUES (?,?,?)",
                       (pid, text, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    audit(conn, actor, "intake.submit", f"patient={pid}")
    return {"id": cur.lastrowid, "patient_id": pid}


def get_encounter(conn, actor: User, encounter_id: int) -> dict:
    _need(actor, "encounter.read")
    row = conn.execute("SELECT * FROM encounters WHERE id=?", (encounter_id,)).fetchone()
    if not row:
        raise NotFound("진료 기록을 찾을 수 없습니다")
    return dict(row)


def latest_encounter_id(conn, actor: User, patient_id: int) -> int:
    _need(actor, "encounter.read")
    row = conn.execute("SELECT id FROM encounters WHERE patient_id=? ORDER BY visit_date DESC, id DESC LIMIT 1",
                       (patient_id,)).fetchone()
    if not row:
        raise NotFound("진료 기록이 없습니다")
    return row["id"]


def list_encounters(conn, actor: User, patient_id: int) -> list[dict]:
    _need(actor, "encounter.read")
    return [dict(r) for r in conn.execute(
        "SELECT id, visit_date, chief_complaint, notes FROM encounters WHERE patient_id=? ORDER BY visit_date DESC, id DESC", (patient_id,))]


# ---------- SOAP: AI는 초안만, 승인은 의사 ----------
def list_soaps(conn, actor: User, status: str | None = None) -> list[dict]:
    _need(actor, "encounter.read")
    if status not in (None, "draft", "approved"):
        raise ServiceError("status는 draft 또는 approved여야 합니다")
    where, args = ("WHERE s.status=?", (status,)) if status else ("", ())
    rows = conn.execute(
        "SELECT s.id, s.encounter_id, e.patient_id, p.name patient_name, e.visit_date, e.chief_complaint, "
        "s.subjective, s.objective, s.assessment, s.plan, s.status, s.created_at "
        "FROM soap_notes s JOIN encounters e ON e.id=s.encounter_id JOIN patients p ON p.id=e.patient_id "
        f"{where} ORDER BY s.id DESC", args)
    return [dict(r) for r in rows]


def save_soap_draft(conn, actor: User, encounter_id: int, subjective: str, objective: str,
                    assessment: str, plan: str) -> dict:
    _need(actor, "soap.draft")
    get_encounter(conn, actor, encounter_id)
    cur = conn.execute(
        "INSERT INTO soap_notes (encounter_id, subjective, objective, assessment, plan, status, created_by, created_at)"
        " VALUES (?,?,?,?,?,'draft',?,?)",
        (encounter_id, subjective, objective, assessment, plan, actor.id, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    audit(conn, actor, "soap.draft", f"encounter={encounter_id} soap={cur.lastrowid}")
    return {"soap_id": cur.lastrowid, "status": "draft"}


def approve_soap(conn, actor: User, soap_id: int) -> dict:
    _need(actor, "soap.approve")
    if not conn.execute("SELECT 1 FROM soap_notes WHERE id=?", (soap_id,)).fetchone():
        raise NotFound("SOAP 노트를 찾을 수 없습니다")
    conn.execute("UPDATE soap_notes SET status='approved', approved_by=? WHERE id=?", (actor.id, soap_id))
    conn.commit()
    audit(conn, actor, "soap.approve", f"soap={soap_id}")
    return {"soap_id": soap_id, "status": "approved"}


def get_soap(conn, actor: User, soap_id: int) -> dict:
    _need(actor, "encounter.read")
    row = conn.execute("SELECT * FROM soap_notes WHERE id=?", (soap_id,)).fetchone()
    if not row:
        raise NotFound("SOAP 노트를 찾을 수 없습니다")
    return dict(row)


# ---------- 예약 ----------
def available_slots(conn, day: str) -> list[str]:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise ServiceError("날짜 형식은 YYYY-MM-DD여야 합니다")
    n_doctors = conn.execute("SELECT COUNT(*) FROM users WHERE role='doctor'").fetchone()[0]
    booked = {r["slot"]: r["c"] for r in conn.execute(
        "SELECT slot, COUNT(*) c FROM appointments WHERE status='booked' AND slot LIKE ? GROUP BY slot", (f"{day}%",))}
    now = datetime.now()
    return [s.strftime(clinic.FMT) for s in clinic.slots_for(d)
            if s > now and booked.get(s.strftime(clinic.FMT), 0) < n_doctors]


def list_appointments(conn, actor: User, patient_id: int | None = None) -> list[dict]:
    if actor.role == "patient":
        pid = _resolve_patient(actor, patient_id, "appointment.read_own")
        where, args = "a.patient_id=?", (pid,)
    else:
        _need(actor, "appointment.read_all")
        where, args = ("a.patient_id=?", (patient_id,)) if patient_id else ("1=1", ())
    rows = conn.execute(
        "SELECT a.id, a.patient_id, p.name patient_name, u.name doctor_name, a.slot, a.reason, a.status "
        "FROM appointments a JOIN patients p ON p.id=a.patient_id JOIN users u ON u.id=a.doctor_id "
        f"WHERE {where} AND a.status='booked' ORDER BY a.slot", args)
    return [dict(r) for r in rows]


def book_appointment(conn, actor: User, slot: str, reason: str = "", patient_id: int | None = None,
                     now: datetime | None = None) -> dict:
    if actor.role == "patient":
        pid = _resolve_patient(actor, patient_id, "appointment.book_own")
    else:
        _need(actor, "appointment.manage_all")
        if patient_id is None:
            raise ServiceError("patient_id가 필요합니다")
        pid = patient_id
    try:
        dt = clinic.parse_slot(slot)
    except ValueError:
        raise ServiceError("슬롯 형식은 'YYYY-MM-DD HH:MM'이어야 합니다")
    if dt <= (now or datetime.now()):
        raise ServiceError("지난 시간에는 예약할 수 없습니다")
    if not clinic.is_bookable(dt):
        raise ServiceError("진료시간이 아닙니다 (평일 09:00-18:00 점심 12:30-13:30, 토 09:00-13:00, 일 휴진)")
    key = dt.strftime(clinic.FMT)
    if not conn.execute("SELECT 1 FROM patients WHERE id=?", (pid,)).fetchone():
        raise NotFound("환자를 찾을 수 없습니다")
    if conn.execute("SELECT 1 FROM appointments WHERE patient_id=? AND slot=? AND status='booked'", (pid, key)).fetchone():
        raise ServiceError("이미 같은 시간에 예약이 있습니다")
    doc = conn.execute(
        "SELECT id, name FROM users WHERE role='doctor' AND id NOT IN "
        "(SELECT doctor_id FROM appointments WHERE slot=? AND status='booked') ORDER BY id LIMIT 1", (key,)).fetchone()
    if not doc:
        raise ServiceError("해당 시간은 마감되었습니다")
    cur = conn.execute("INSERT INTO appointments (patient_id, doctor_id, slot, reason, created_at) VALUES (?,?,?,?,?)",
                       (pid, doc["id"], key, reason[:200], datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    audit(conn, actor, "appointment.book", f"patient={pid} slot={key}")
    return {"appointment_id": cur.lastrowid, "patient_id": pid, "slot": key, "doctor_name": doc["name"]}


def cancel_appointment(conn, actor: User, appointment_id: int, now: datetime | None = None) -> dict:
    row = conn.execute("SELECT * FROM appointments WHERE id=? AND status='booked'", (appointment_id,)).fetchone()
    if not row:
        raise NotFound("예약을 찾을 수 없습니다")
    if actor.role == "patient":
        _resolve_patient(actor, row["patient_id"], "appointment.cancel_own")  # 타인 예약이면 거부
        if (now or datetime.now()) > clinic.cancel_deadline(clinic.parse_slot(row["slot"])):
            raise ServiceError("취소 마감(진료 하루 전 18:00)이 지났습니다. 전화로 문의해 주세요.")
    else:
        _need(actor, "appointment.manage_all")
    conn.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (appointment_id,))
    conn.commit()
    audit(conn, actor, "appointment.cancel", f"appointment={appointment_id}")
    return {"appointment_id": appointment_id, "status": "cancelled"}
