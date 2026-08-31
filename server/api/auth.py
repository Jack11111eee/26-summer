"""认证接口：注册(candidate)/登录/me。"""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from .. import schemas
from ..core.security import (
    create_token,
    hash_password,
    require_login,
    verify_password,
)
from ..db import get_conn
from ..services.pipeline import now_iso

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(body: schemas.RegisterRequest) -> dict:
    conn = get_conn()
    exists = conn.execute("SELECT 1 FROM user WHERE username=?", (body.username,)).fetchone()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user_id = f"u_{uuid4().hex[:12]}"
    # 开放注册固定为 candidate，杜绝注册出 admin
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (user_id, body.username, hash_password(body.password), "candidate", now_iso()),
    )
    conn.commit()
    return {"user_id": user_id, "username": body.username, "role": "candidate"}


@router.post("/login", response_model=schemas.TokenResponse)
def login(body: schemas.LoginRequest) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT user_id, username, role, password_hash, is_active FROM user WHERE username=?",
        (body.username,),
    ).fetchone()
    if row is None or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号已停用")
    token = create_token(row["user_id"], row["role"])
    return {"token": token, "user": {"username": row["username"], "role": row["role"]}}


@router.get("/me")
def me(user: dict = Depends(require_login)) -> dict:
    return user
