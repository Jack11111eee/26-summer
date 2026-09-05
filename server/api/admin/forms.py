"""表单链管理（SSOT §16.1）：gate 人工覆盖（二次确认 + reviewer_id 落库）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core.security import require_admin
from ...db import get_conn
from ...services.state_events import append_event

router = APIRouter(prefix="/api/admin/forms", tags=["admin_forms"],
                   dependencies=[Depends(require_admin)])


class GateOverrideBody(BaseModel):
    session_id: str = Field(min_length=1)
    item_id: str = Field(min_length=1)
    human_override: bool
    # D-31 二次确认：无 override_reason（或空串）被 Pydantic 422 拒绝
    override_reason: str = Field(min_length=1)


@router.post("/gate-override")
def gate_override(body: GateOverrideBody, admin: dict = Depends(require_admin)) -> dict:
    """gate 人工覆盖：UPDATE gate 行 human_override/override_reason/reviewer_id + 事件留痕。

    rowcount==0（无该 session+item 的 gate 行）→ 404；非 admin 已被路由级 require_admin 403。
    """
    conn = get_conn()
    cur = conn.execute(
        "UPDATE question_score SET human_override=?, override_reason=?, reviewer_id=?"
        " WHERE session_id=? AND item_id=? AND gate_result IS NOT NULL",
        ("true" if body.human_override else "false", body.override_reason, admin["user_id"],
         body.session_id, body.item_id),
    )
    if cur.rowcount == 0:
        conn.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "gate 行不存在")
    append_event(conn, session_id=body.session_id, event_type="GATE_OVERRIDDEN",
                 actor_type="admin", actor_id=admin["user_id"],
                 payload={"item_id": body.item_id, "override_reason": body.override_reason,
                          "reviewer_id": admin["user_id"]})
    conn.commit()
    return {"session_id": body.session_id, "item_id": body.item_id, "status": "overridden"}
