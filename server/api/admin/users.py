"""用户管理（P7）：列表 / 建号 / 启用停用 / 重置密码。"""
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import hash_password, require_admin
from ...db import get_conn
from ...services.pipeline import now_iso

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"], dependencies=[Depends(require_admin)])


@router.get("")
def list_users() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT user_id, username, role, is_active, created_at FROM user ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("")
def create_user(body: dict) -> dict:
    """管理员手动建号（注册通道之外的补充）。"""
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = body.get("role", "candidate")
    if not username or len(password) < 6:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名必填，密码至少 6 位")
    if role not in ("admin", "candidate"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role 仅支持 admin/candidate")
    conn = get_conn()
    if conn.execute("SELECT 1 FROM user WHERE username=?", (username,)).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user_id = f"u_{uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (user_id, username, hash_password(password), role, now_iso()),
    )
    conn.commit()
    return {"user_id": user_id, "username": username, "role": role}


@router.patch("/{user_id}")
def update_user(user_id: str, body: dict, admin: dict = Depends(require_admin)) -> dict:
    """启用/停用、重置密码。不能停用自己。"""
    conn = get_conn()
    row = conn.execute("SELECT username FROM user WHERE user_id=?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if "is_active" in body:
        if not body["is_active"] and user_id == admin["user_id"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用自己的账号")
        conn.execute("UPDATE user SET is_active=? WHERE user_id=?",
                     (int(bool(body["is_active"])), user_id))
    if body.get("password"):
        if len(body["password"]) < 6:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "密码至少 6 位")
        conn.execute("UPDATE user SET password_hash=? WHERE user_id=?",
                     (hash_password(body["password"]), user_id))
    conn.commit()
    return {"user_id": user_id, "updated": True}
