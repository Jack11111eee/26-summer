"""反馈管理（P8 测试中心 tab）：候选人异议的查看与处理。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.security import require_admin
from ...db import get_conn
from ...services.pipeline import now_iso

router = APIRouter(prefix="/api/admin/feedback", tags=["feedback"], dependencies=[Depends(require_admin)])


@router.get("/list")
def list_feedback(status: str | None = None) -> list[dict]:
    """列出全部反馈，带报告与能力项上下文。"""
    conn = get_conn()
    clause = " WHERE f.status=?" if status else ""
    params = (status,) if status else ()
    rows = conn.execute(
        "SELECT f.feedback_id, f.report_id, f.item_id, f.feedback_text, f.status, f.created_at,"
        " ci.std_name, ci.category, r.session_id, r.total_score"
        f" FROM feedback f"
        f" JOIN competency_item ci ON ci.item_id=f.item_id"
        f" JOIN report r ON r.report_id=f.report_id"
        f"{clause} ORDER BY f.created_at DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


class _ReviewBody(BaseModel):
    note: str = ""


@router.post("/{feedback_id}/review")
def review_feedback(feedback_id: str, body: _ReviewBody) -> dict:
    """标记反馈为已处理（不做改分，仅留痕）。"""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE feedback SET status='reviewed' WHERE feedback_id=?", (feedback_id,)
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "反馈不存在")
    return {"feedback_id": feedback_id, "status": "reviewed"}


@router.post("/{feedback_id}/bad-case")
def mark_bad_case(feedback_id: str, body: _ReviewBody) -> dict:
    """标记为 bad case（沉淀为评测素材）。"""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE feedback SET status='bad_case' WHERE feedback_id=?", (feedback_id,)
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "反馈不存在")
    return {"feedback_id": feedback_id, "status": "bad_case"}
