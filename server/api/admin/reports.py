"""报告发布（REF-5.9 + SSOT §21.1 发布语义收紧，U6 2026-09-09）：管理员明确 POST publish 才 PUBLISHED。

状态机（D-025）：仅 PROVISIONAL/READY 可发布；PUBLISHED 已发布、GENERATING/FAILED
不可发布；HUMAN_REVIEW_REQUIRED 报告须携带明确复核结果（body 缺 review_outcome →
422；不在允许枚举集 → 409 需明确复核结果——默认值 CONFIRMED 免审直通已作废，
§21.1「发布请求必须携带明确复核结果与必要理由」）。review_note 同为必填
（发布须有理由记录）。

发布实现（§21.1 接口一致性）：同事务更新表列 + report_json 内复核字段
（review_outcome/review_note/reviewed_at——JSON 与表列一致，不得一处新一处旧）。
发布动作不改变证据完整性：total_score 不变、coverage 不变（发布不能补出
不存在的证据；PROVISIONAL 照常发布为带范围限制的部分报告）。
发布时同事务写 report 行 + REVIEW_REPORT_PUBLISH_CONFIRMED 事件（§13.1 append-only）。
"""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from ...core.security import require_admin
from ...db import get_conn
from ...services.pipeline import now_iso
from ...services.report import _assert_report_transition
from ...services.state_events import append_event

router = APIRouter(prefix="/api/admin", tags=["admin-reports"], dependencies=[Depends(require_admin)])

# §21.1 复核结果枚举（U6 2026-09-09 定稿）——两组语义：
# - HUMAN_REVIEW_REQUIRED 报告：必须显式选择其一才能发布（维持原判或纠正后发布）
#   UPHELD（维持原判：复核确认原结论照常发布）/ CONFIRMED（复核通过：要求已被
#   人工确认满足，按原结论发布）/ PARTIAL（部分纠正：复核后部分结论需修订说明
#   ——以 review_note 记录修订范围）/ CORRECTED（全部纠正：复核推翻原结论；
#   修订版报告须走重新生成流程，本 action 只登记结果）。
# - 无人工复核要求（review_status 非 HUMAN_REVIEW_REQUIRED）的报告：CONFIRMED
#   （正常发布确认）。该形态发布即常规动作，不需要 UPHELD/PARTIAL/CORRECTED。
ALLOWED_REVIEW_OUTCOMES = ("CONFIRMED", "UPHELD", "PARTIAL", "CORRECTED")


class _PublishBody(BaseModel):
    """发布请求体（§21.1）：review_outcome 必填（无默认值——免审直通作废）、
    review_note 必填（发布须有理由记录——全空白字符串不算理由，置 422）。"""
    review_outcome: str = Field(min_length=1)
    review_note: str

    @model_validator(mode="after")
    def _nonempty(self) -> "_PublishBody":
        if not self.review_note.strip():
            raise ValueError("review_note 不能为空白（发布须有理由记录）")
        if not self.review_outcome.strip():
            raise ValueError("review_outcome 不能为空白")
        return self


@router.post("/reports/{report_id}/publish")
def publish_report(report_id: str, body: _PublishBody, admin: dict = Depends(require_admin)) -> dict:
    """管理员明确发布报告：report_status='PUBLISHED' + 发布字段 +
    REVIEW_REPORT_PUBLISH_CONFIRMED；同事务同步 report_json 内复核字段（§21.1）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT report_id, session_id, report_status, review_status, report_json"
        " FROM report WHERE report_id=?",
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
    # review_outcome 枚举校验（§21.1：明确复核结果；空/未提供由 Pydantic 422 拦截）
    if body.review_outcome not in ALLOWED_REVIEW_OUTCOMES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"需明确复核结果（review_outcome 须为 {'/'.join(ALLOWED_REVIEW_OUTCOMES)} 之一）")
    if row["review_status"] == "HUMAN_REVIEW_REQUIRED" and body.review_outcome not in (
        "CONFIRMED", "UPHELD", "PARTIAL", "CORRECTED"
    ):
        # HUMAN_REVIEW_REQUIRED：四值均满足「明确复核结果」——免审直通已作废，
        # 缺省（Pydantic 422）/未知值（上方枚举 409）都不得发布
        raise HTTPException(status.HTTP_409_CONFLICT, "需先完成人工复核")

    now = now_iso()
    # §21.1 接口一致性：表列与 JSON 内复核字段同事务更新（不得一处新一处旧）
    try:
        report_data = json.loads(row["report_json"])
        if not isinstance(report_data, dict):
            report_data = {}
    except (json.JSONDecodeError, TypeError):
        report_data = {}
    report_data["review_outcome"] = body.review_outcome
    report_data["review_note"] = body.review_note
    report_data["reviewed_at"] = now
    review_status = "CONFIRMED" if body.review_outcome in ("CONFIRMED", "UPHELD") else row["review_status"]
    conn.execute(
        "UPDATE report SET report_status='PUBLISHED', review_status=?, publish_confirmed_by=?,"
        " published_at=?, review_outcome=?, review_note=?, reviewer_id=?, reviewed_at=?,"
        " report_json=?"
        " WHERE report_id=?",
        (review_status, admin["user_id"], now, body.review_outcome, body.review_note,
         admin["user_id"], now, json.dumps(report_data, ensure_ascii=False), report_id),
    )
    append_event(conn, session_id=row["session_id"], event_type="REVIEW_REPORT_PUBLISH_CONFIRMED",
                 from_state=from_state, to_state="PUBLISHED", actor_type="admin",
                 actor_id=admin["user_id"],
                 payload={"report_id": report_id, "review_outcome": body.review_outcome})
    conn.commit()
    return {"report_id": report_id, "report_status": "PUBLISHED"}
