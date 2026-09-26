"""로그인, JWT 발급/검증, FastAPI 권한 의존성."""
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request

from .config import get_settings
from .db import get_db
from .rbac import has_permission
from .seed import verify_password


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    name: str
    patient_id: int | None
    read_only: bool = False   # 읽기 전용 관리자(공개 데모용): 어떤 변경도 할 수 없다


class AccountDisabled(Exception):
    """비밀번호는 맞지만 관리자가 사용을 중지시킨 계정."""


def _user(row) -> "User":
    return User(row["id"], row["username"], row["role"], row["name"], row["patient_id"], bool(row["read_only"]))


def authenticate(conn, username: str, password: str) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    if row["disabled"]:                      # 비밀번호가 맞은 뒤에만 알려 준다 (계정 존재 여부 노출 방지)
        raise AccountDisabled()
    return _user(row)


def create_token(user: User) -> str:
    s = get_settings()
    payload = {"sub": str(user.id), "role": user.role, "exp": int(time.time()) + s.token_ttl_min * 60}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def current_user(request: Request, conn=Depends(get_db)) -> User:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "인증이 필요합니다")
    try:
        payload = jwt.decode(header[7:], get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "토큰이 유효하지 않습니다")
    row = conn.execute("SELECT * FROM users WHERE id=?", (int(payload["sub"]),)).fetchone()
    if not row:  # 역할/사용자 정보는 토큰이 아니라 DB를 신뢰한다
        raise HTTPException(401, "존재하지 않는 사용자입니다")
    if row["disabled"]:                      # 이미 발급된 토큰도 즉시 무력화
        raise HTTPException(401, "사용이 중지된 계정입니다")
    return _user(row)


def require(perm: str):
    def dep(user: User = Depends(current_user)) -> User:
        if not has_permission(user.role, perm):
            raise HTTPException(403, f"권한이 없습니다 ({perm})")
        return user
    return dep
