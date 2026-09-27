"""FastAPI 진입점. 라우트는 권한 의존성 + services 호출만 담당한다."""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import admin, agent, db, guardrails, ratelimit, services
from .auth import AccountDisabled, User, authenticate, create_token, current_user, require
from .config import get_settings
from .llm import LLMError
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.is_production and s.jwt_secret.startswith("dev-only"):   # 운영에서 기본 시크릿으로 뜨는 사고를 막는다
        raise RuntimeError("MEDIRAIL_JWT_SECRET을 설정하세요 (운영 환경에서는 기본 시크릿을 쓸 수 없습니다)")
    if s.is_production and s.fake_llm:      # 가짜 LLM이 운영에서 켜지면 사용자에게 가짜 의료 답변이 나간다
        raise RuntimeError("MEDIRAIL_FAKE_LLM은 운영 환경에서 쓸 수 없습니다")
    conn = db.connect()
    db.init_db(conn)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(conn)
    admin.ensure_system_accounts(conn)   # 읽기 전용 데모 관리자 + (환경변수가 있으면) 실제 최상위 관리자
    conn.close()
    yield


app = FastAPI(title="MediRail API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(get_settings().cors_origins), allow_methods=["*"], allow_headers=["*"])


def client_ip(request: Request) -> str:
    """프록시(Railway) 뒤에서는 X-Forwarded-For의 첫 값이 실제 클라이언트다."""
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


@app.exception_handler(ratelimit.RateLimitExceeded)
def _rate_limited(_, e):
    return JSONResponse({"detail": e.message}, status_code=429, headers={"Retry-After": str(e.retry_after)})


@app.exception_handler(services.PermissionDenied)
def _denied(_, e):
    return JSONResponse({"detail": str(e)}, status_code=403)


@app.exception_handler(services.NotFound)
def _not_found(_, e):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(AccountDisabled)
def _disabled(_, e):
    return JSONResponse({"detail": "사용이 중지된 계정입니다. 관리자에게 문의하세요."}, status_code=403)


@app.exception_handler(services.Conflict)
def _conflict(_, e):
    return JSONResponse({"detail": str(e)}, status_code=409)


@app.exception_handler(services.ServiceError)
def _bad_request(_, e):
    return JSONResponse({"detail": str(e)}, status_code=400)


class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    """가입은 항상 환자 계정이다. role 필드는 없으며, 요청에 넣어도 무시된다."""
    username: str = Field(max_length=40)
    password: str = Field(max_length=100)
    name: str = Field(max_length=60)
    birth_year: int
    sex: str = Field(max_length=2)
    allergies: str = Field(default="", max_length=400)
    medications: str = Field(default="", max_length=400)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = []
    patient_id: int | None = None  # 직원이 화면에서 선택한 환자


class IntakeIn(BaseModel):
    text: str


class BookIn(BaseModel):
    slot: str
    reason: str = ""
    patient_id: int | None = None


@app.get("/health")
def health():
    return {"status": "ok", "model": get_settings().model}


@app.post("/auth/login")
def login(body: LoginIn, request: Request, conn=Depends(db.get_db)):
    ratelimit.check_login(client_ip(request))
    user = authenticate(conn, body.username, body.password)
    if not user:
        services.audit(conn, None, "auth.login_failed", body.username[:40])
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    services.audit(conn, user, "auth.login")
    return {"access_token": create_token(user), "role": user.role, "name": user.name, "patient_id": user.patient_id, "read_only": user.read_only}


@app.post("/auth/register", status_code=201)
def register(body: RegisterIn, request: Request, conn=Depends(db.get_db)):
    ratelimit.check_register(client_ip(request))
    user = services.register_patient(conn, body.username, body.password, body.name, body.birth_year, body.sex,
                                     body.allergies, body.medications)
    return {"access_token": create_token(user), "role": user.role, "name": user.name, "patient_id": user.patient_id, "read_only": user.read_only}


@app.get("/auth/demo-accounts")
def demo_accounts(conn=Depends(db.get_db)):
    """로그인 전에 볼 수 있는 데모 계정 목록 (DB에서 조회)."""
    return services.list_demo_accounts(conn)


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user


@app.post("/chat")
def chat(body: ChatIn, request: Request, user: User = Depends(require("chat")), conn=Depends(db.get_db)):
    # 응급 안내는 LLM을 호출하지 않으므로 제한하지 않는다 (한도에 걸려 119 안내가 막히면 안 된다)
    if not (user.role == "patient" and guardrails.detect_emergency(body.message)):
        ratelimit.check_chat(user.id, client_ip(request))
    try:
        r = agent.run_agent(conn, user, body.message, history=body.history, patient_id=body.patient_id)
    except LLMError as e:
        raise HTTPException(502, f"AI 응답 생성에 실패했습니다: {e}")
    return {"answer": r.answer, "sources": r.sources, "tool_calls": r.tool_calls, "events": r.events,
            "emergency": r.emergency, "usage": r.usage, "model": r.model}


@app.get("/patients")
def patients(user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.list_patients(conn, user)


@app.get("/patients/{patient_id}")
def patient(patient_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.get_patient_profile(conn, user, patient_id)


@app.get("/patients/{patient_id}/encounters")
def patient_encounters(patient_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.list_encounters(conn, user, patient_id)


@app.get("/patients/{patient_id}/intake")
def patient_intake(patient_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    """문진이 아직 없는 것은 오류가 아니라 정상 상태이므로 null(200)로 응답한다 (권한 오류는 그대로 403)."""
    try:
        return services.get_latest_intake(conn, user, patient_id)
    except services.NotFound:
        return None


@app.post("/intake")
def intake(body: IntakeIn, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.submit_intake(conn, user, body.text)


@app.get("/appointments")
def appointments(patient_id: int | None = None, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.list_appointments(conn, user, patient_id)


@app.get("/appointments/slots")
def slots(date: str, conn=Depends(db.get_db), user: User = Depends(current_user)):
    return {"date": date, "slots": services.available_slots(conn, date)}


@app.post("/appointments")
def book(body: BookIn, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.book_appointment(conn, user, body.slot, body.reason, body.patient_id)


@app.delete("/appointments/{appointment_id}")
def cancel(appointment_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.cancel_appointment(conn, user, appointment_id)


@app.get("/soap")
def soaps(status: str | None = None, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.list_soaps(conn, user, status)


@app.get("/soap/{soap_id}")
def soap(soap_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.get_soap(conn, user, soap_id)


@app.post("/soap/{soap_id}/approve")
def approve(soap_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    """AI는 초안만 만들 수 있고, 승인은 의사가 이 엔드포인트로만 한다 (human-in-the-loop)."""
    return services.approve_soap(conn, user, soap_id)


class RoleIn(BaseModel):
    role: str = Field(max_length=20)


class BreakGlassIn(BaseModel):
    patient_id: int
    reason: str = Field(max_length=400)


@app.get("/admin/users")
def admin_users(user: User = Depends(current_user), conn=Depends(db.get_db)):
    return admin.list_users(conn, user)


@app.patch("/admin/users/{user_id}/role")
def admin_set_role(user_id: int, body: RoleIn, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return admin.set_user_role(conn, user, user_id, body.role)


@app.post("/admin/users/{user_id}/disable")
def admin_disable(user_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return admin.set_user_disabled(conn, user, user_id, True)


@app.post("/admin/users/{user_id}/enable")
def admin_enable(user_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return admin.set_user_disabled(conn, user, user_id, False)


@app.get("/admin/stats")
def admin_stats(user: User = Depends(current_user), conn=Depends(db.get_db)):
    return admin.stats(conn, user)


@app.post("/admin/break-glass")
def admin_break_glass(body: BreakGlassIn, user: User = Depends(current_user), conn=Depends(db.get_db)):
    """최상위 관리자의 임상 기록 열람: 사유가 필수이고 열람 사실이 감사 로그에 남는다."""
    return admin.break_glass(conn, user, body.patient_id, body.reason)


@app.get("/audit")
def audit(limit: int = 100, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.read_audit(conn, user, limit)
