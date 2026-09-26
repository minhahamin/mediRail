"""FastAPI 진입점. 라우트는 권한 의존성 + services 호출만 담당한다."""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import agent, db, services
from .auth import User, authenticate, create_token, current_user, require
from .config import get_settings
from .llm import LLMError
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(conn)
    conn.close()
    yield


app = FastAPI(title="MediRail API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(services.PermissionDenied)
def _denied(_, e):
    return JSONResponse({"detail": str(e)}, status_code=403)


@app.exception_handler(services.NotFound)
def _not_found(_, e):
    return JSONResponse({"detail": str(e)}, status_code=404)


@app.exception_handler(services.ServiceError)
def _bad_request(_, e):
    return JSONResponse({"detail": str(e)}, status_code=400)


class LoginIn(BaseModel):
    username: str
    password: str


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
def login(body: LoginIn, conn=Depends(db.get_db)):
    user = authenticate(conn, body.username, body.password)
    if not user:
        services.audit(conn, None, "auth.login_failed", body.username[:40])
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    services.audit(conn, user, "auth.login")
    return {"access_token": create_token(user), "role": user.role, "name": user.name, "patient_id": user.patient_id}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user


@app.post("/chat")
def chat(body: ChatIn, user: User = Depends(require("chat")), conn=Depends(db.get_db)):
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


@app.get("/patients/{patient_id}/intake")
def patient_intake(patient_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.get_latest_intake(conn, user, patient_id)


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


@app.get("/soap/{soap_id}")
def soap(soap_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.get_soap(conn, user, soap_id)


@app.post("/soap/{soap_id}/approve")
def approve(soap_id: int, user: User = Depends(current_user), conn=Depends(db.get_db)):
    """AI는 초안만 만들 수 있고, 승인은 의사가 이 엔드포인트로만 한다 (human-in-the-loop)."""
    return services.approve_soap(conn, user, soap_id)


@app.get("/audit")
def audit(limit: int = 100, user: User = Depends(current_user), conn=Depends(db.get_db)):
    return services.read_audit(conn, user, limit)
