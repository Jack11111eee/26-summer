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
        " ci.std_name, ci.category, r.session_id, r.total_score, u.username"
        f" FROM feedback f"
        f" JOIN competency_item ci ON ci.item_id=f.item_id"
        f" JOIN report r ON r.report_id=f.report_id"
        f" LEFT JOIN user u ON u.user_id=f.user_id"
        f"{clause} ORDER BY f.created_at DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{feedback_id}")
def get_feedback_detail(feedback_id: str) -> dict:
    """单条异议详情（SSOT §22.2，2026-09-09）：原文全文 + 提交人 + 处理留痕 + 回溯锚点，
    供报告页深链 ?feedback_id= 横幅渲染。存量行 user_id NULL → username 亦 NULL（前端显示 —）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT f.feedback_id, f.report_id, f.item_id, f.feedback_text, f.status, f.created_at,"
        " f.user_id, f.review_note, f.reviewed_at,"
        " ci.std_name, ci.category, r.session_id, r.report_status, r.total_score, u.username"
        " FROM feedback f"
        " JOIN competency_item ci ON ci.item_id=f.item_id"
        " JOIN report r ON r.report_id=f.report_id"
        " LEFT JOIN user u ON u.user_id=f.user_id"
        " WHERE f.feedback_id=?",
        (feedback_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "反馈不存在")
    return dict(row)


class _ReviewBody(BaseModel):
    note: str = ""


@router.post("/{feedback_id}/review")
def review_feedback(feedback_id: str, body: _ReviewBody, admin: dict = Depends(require_admin)) -> dict:
    """标记反馈为已处理（不做改分，仅留痕 note + reviewer + reviewed_at）。"""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE feedback SET status='reviewed', review_note=?, reviewer_id=?, reviewed_at=?"
        " WHERE feedback_id=?",
        (body.note, admin["user_id"], now_iso(), feedback_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "反馈不存在")
    return {"feedback_id": feedback_id, "status": "reviewed"}


@router.post("/{feedback_id}/bad-case")
def mark_bad_case(feedback_id: str, body: _ReviewBody, admin: dict = Depends(require_admin)) -> dict:
    """标记为 bad case（沉淀为评测素材），同样留痕 note + reviewer + reviewed_at。"""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE feedback SET status='bad_case', review_note=?, reviewer_id=?, reviewed_at=?"
        " WHERE feedback_id=?",
        (body.note, admin["user_id"], now_iso(), feedback_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "反馈不存在")
    return {"feedback_id": feedback_id, "status": "bad_case"}
