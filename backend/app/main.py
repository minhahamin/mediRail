"""FastAPI 진입점."""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from .auth import User, authenticate, create_token, current_user
from .config import get_settings
from .seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed(conn)
    conn.close()
    yield


app = FastAPI(title="MediRail API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


class LoginIn(BaseModel):
    username: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok", "model": get_settings().model}


@app.post("/auth/login")
def login(body: LoginIn, conn=Depends(db.get_db)):
    user = authenticate(conn, body.username, body.password)
    if not user:
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    return {"access_token": create_token(user), "role": user.role, "name": user.name, "patient_id": user.patient_id}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return user
