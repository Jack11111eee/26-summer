"""测评端 API（P5）：仅 active 且有 confirmed 模型的岗位对候选人可见。"""
import json

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.security import require_login
from ..db import get_conn

router = APIRouter(prefix="/api/assessment", tags=["assessment"], dependencies=[Depends(require_login)])


@router.get("/positions")
def list_assessable_positions() -> list[dict]:
    """可测评岗位：active 且存在 confirmed 模型（附版本号与能力项数）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.position_id, p.name, m.version, m.model_id,"
        " json_array_length(json_extract(m.model_json,'$.items')) AS item_count"
        " FROM position p"
        " JOIN competency_model m ON m.position_id=p.position_id"
        " WHERE p.status='active' AND m.status='confirmed'"
        " ORDER BY m.version DESC"
    ).fetchall()
    # 同一岗位只展示最新 confirmed 版
    seen = set()
    out = []
    for r in rows:
        if r["position_id"] in seen:
            continue
        seen.add(r["position_id"])
        out.append(dict(r))
    return out


@router.get("/positions/{position_id}/model")
def get_confirmed_model(position_id: str) -> dict:
    """confirmed 模型快照（模块二出题的输入契约，本期用于占位页展示）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT model_id, version, model_json FROM competency_model"
        " WHERE position_id=? AND status='confirmed' ORDER BY version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无已确认模型")
    d = dict(row)
    d["model"] = json.loads(d.pop("model_json"))
    return d


@router.post("/sessions")
def create_session(body: dict) -> dict:
    """创建测评会话（模块二职责，本期预留接口位）。"""
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "测评功能由模块二提供，本接口为预留位（详见 05 文档 §7.3）",
    )
