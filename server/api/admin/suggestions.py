"""意见反馈管理（SSOT §22.1，2026-09-08——TestCenter 反馈区「意见反馈」tab）：
候选人通用系统建议的查看与处理（独立于 feedback 逐分异议管道——无 std_name/category/score
join 列、无 bad_case 沉淀语义，review 动作全盘镜像 admin/feedback.py）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.security import require_admin
from ...db import get_conn
from ...services.pipeline import now_iso

router = APIRouter(prefix="/api/admin/suggestions", tags=["suggestions"], dependencies=[Depends(require_admin)])


@router.get("")
def list_suggestions(status: str | None = None) -> list[dict]:
    """列出全部意见反馈（status 过滤 pending/reviewed；空=全部），附带提交用户名。"""
    conn = get_conn()
    clause = " WHERE s.status=?" if status else ""
    params = (status,) if status else ()
    rows = conn.execute(
        "SELECT s.suggestion_id, s.user_id, u.username, s.text, s.status, s.created_at,"
        " s.review_note, s.reviewer_id, s.reviewed_at"
        f" FROM suggestion s JOIN user u ON u.user_id=s.user_id"
        f"{clause} ORDER BY s.created_at DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


class _ReviewBody(BaseModel):
    note: str = ""


@router.post("/{suggestion_id}/review")
def review_suggestion(suggestion_id: str, body: _ReviewBody, admin: dict = Depends(require_admin)) -> dict:
    """标记意见反馈为已处理（reviewed + note + reviewer + reviewed_at 审计留痕）。"""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE suggestion SET status='reviewed', review_note=?, reviewer_id=?, reviewed_at=?"
        " WHERE suggestion_id=?",
        (body.note, admin["user_id"], now_iso(), suggestion_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "反馈不存在")
    return {"suggestion_id": suggestion_id, "status": "reviewed"}
