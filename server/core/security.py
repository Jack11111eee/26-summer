"""JWT 签发/校验、密码哈希、角色依赖注入。"""
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from .. import config
from ..db import get_conn

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def _current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = jwt.decode(cred.credentials, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效或已过期")
    conn = get_conn()
    row = conn.execute(
        "SELECT user_id, username, role, is_active FROM user WHERE user_id=?",
        (payload["sub"],),
    ).fetchone()
    if row is None or not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return dict(row)


def require_login(user: dict = Depends(_current_user)) -> dict:
    return user


def require_admin(user: dict = Depends(_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要管理员权限")
    return user


def load_owned_session(conn, session_id: str, user: dict, *, allow_admin_read: bool = False) -> dict:
    """按所有权加载测评会话，无权访问返回 404（D-01：统一"不存在"，不引入 403）。

    判定顺序（Pitfall 10）：owner 条件 user_id=? 命中即返回（admin 本人资源走通）；
    仅非 owner 且 allow_admin_read 且 role=admin 时放宽为仅按 session_id 查询（读豁免）。
    写路由不传 allow_admin_read（默认 False）→ admin 与其他候选人同路径 404（D-03）。
    """
    row = conn.execute(
        "SELECT * FROM assessment_session WHERE session_id=? AND user_id=?",
        (session_id, user["user_id"]),
    ).fetchone()
    if row is None and allow_admin_read and user["role"] == "admin":
        row = conn.execute(
            "SELECT * FROM assessment_session WHERE session_id=?",
            (session_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    return dict(row)


def load_owned_report(conn, report_id: str, user: dict, *, allow_admin_read: bool = False) -> dict:
    """按所有权加载报告（report→session join，Pitfall 5：submit_feedback 亦经此链）。

    admin 读豁免语义与 load_owned_session 一致：非 owner 且 allow_admin_read 且
    role=admin 时放宽为仅按 report_id 查询；写路由不传（owner-only）。
    """
    row = conn.execute(
        "SELECT r.* FROM report r JOIN assessment_session s ON s.session_id=r.session_id"
        " WHERE r.report_id=? AND s.user_id=?",
        (report_id, user["user_id"]),
    ).fetchone()
    if row is None and allow_admin_read and user["role"] == "admin":
        row = conn.execute("SELECT * FROM report WHERE report_id=?", (report_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    return dict(row)
