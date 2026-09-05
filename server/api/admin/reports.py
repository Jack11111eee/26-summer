"""报告发布（REF-5.9）：管理员明确 POST publish 才 PUBLISHED。

状态机（D-025）：仅 PROVISIONAL/READY 可发布；PUBLISHED 已发布、GENERATING/FAILED
不可发布；HUMAN_REVIEW_REQUIRED 且未 CONFIRMED → 409（需先完成人工复核）。发布时
同事务写 report 行 + REVIEW_REPORT_PUBLISH_CONFIRMED 事件（§13.1 append-only）。
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ...core.security import require_admin
from ...db import get_conn
from ...services.pipeline import now_iso
from ...services.report import _assert_report_transition
from ...services.state_events import append_event

router = APIRouter(prefix="/api/admin", tags=["admin-reports"], dependencies=[Depends(require_admin)])


class _PublishBody(BaseModel):
    review_outcome: str = "CONFIRMED"
    review_note: str = ""


@router.post("/reports/{report_id}/publish")
def publish_report(report_id: str, body: _PublishBody, admin: dict = Depends(require_admin)) -> dict:
    """管理员明确发布报告：report_status='PUBLISHED' + 发布字段 + REVIEW_REPORT_PUBLISH_CONFIRMED。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT report_id, session_id, report_status, review_status FROM report WHERE report_id=?",
        (report_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    from_state = row["report_status"]
    if from_state == "PUBLISHED":
        raise HTTPException(status.HTTP_409_CONFLICT, "报告已发布")
    try:
        _assert_report_transition(from_state, "PUBLISHED")
    except ValueError:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前状态不可发布")
    if row["review_status"] == "HUMAN_REVIEW_REQUIRED" and body.review_outcome != "CONFIRMED":
        raise HTTPException(status.HTTP_409_CONFLICT, "需先完成人工复核")

    now = now_iso()
    conn.execute(
        "UPDATE report SET report_status='PUBLISHED', publish_confirmed_by=?, published_at=?,"
        " review_outcome=?, review_note=?, reviewer_id=?, reviewed_at=? WHERE report_id=?",
        (admin["user_id"], now, body.review_outcome, body.review_note,
         admin["user_id"], now, report_id),
    )
    append_event(conn, session_id=row["session_id"], event_type="REVIEW_REPORT_PUBLISH_CONFIRMED",
                 from_state=from_state, to_state="PUBLISHED", actor_type="admin",
                 actor_id=admin["user_id"], payload={"report_id": report_id})
    conn.commit()
    return {"report_id": report_id, "report_status": "PUBLISHED"}
