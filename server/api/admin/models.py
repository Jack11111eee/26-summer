"""聚合触发、模型获取/编辑/确认、stalled 处理（P3 人审 + 状态机流转）。"""
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from ...core.security import require_admin
from ...db import get_conn
from ...services.aggregate import run_aggregate
from ...services.pipeline import now_iso

router = APIRouter(prefix="/api/admin", tags=["admin-models"], dependencies=[Depends(require_admin)])


@router.post("/positions/{position_id}/aggregate")
def trigger_aggregate(position_id: str, background: BackgroundTasks) -> dict:
    """手动触发聚合（自动触发的兜底）。"""
    conn = get_conn()
    pos = conn.execute("SELECT status FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "岗位不存在")
    background.add_task(run_aggregate, position_id)
    return {"position_id": position_id, "aggregating": True}


@router.get("/positions/{position_id}/model")
def get_current_model(position_id: str) -> dict:
    """当前生效模型：draft/stalled 优先，否则最新 confirmed。无则 404。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT model_id, version, status, model_json, created_at FROM competency_model"
        " WHERE position_id=? ORDER BY "
        "   CASE status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无模型，请先导入 JD 并聚合")
    d = dict(row)
    d["model"] = json.loads(d.pop("model_json"))
    return d


@router.put("/models/{model_id}")
def update_model(model_id: str, body: dict) -> dict:
    """人审编辑草稿：整份 items 替换（改名/调级/调权/增删项/改类间配比）。

    body 直接为完整 model_json。仅 draft/stalled 可编辑。
    """
    conn = get_conn()
    row = conn.execute("SELECT status FROM competency_model WHERE model_id=?", (model_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模型不存在")
    if row["status"] == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "已确认模型不可编辑（请走 diff 审阅流）")

    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "model_json.items 必须是非空数组")

    # Σ=100% 服务端校验（容差 0.5%）
    total_weight = sum(float(it.get("weight", 0)) for it in items)
    if abs(total_weight - 1.0) > 0.005:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"权重合计须为 100%（当前 {total_weight * 100:.1f}%）")

    body.pop("stall_reason", None)  # 编辑后清除 stalled 标记
    conn.execute("UPDATE competency_model SET model_json=?, status='draft' WHERE model_id=?",
                 (json.dumps(body, ensure_ascii=False), model_id))
    # 明细表同步重建（人审后的权威内容）
    conn.execute("DELETE FROM competency_item WHERE model_id=?", (model_id,))
    from ...services.pipeline import new_id
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, years, gate, level_reason, occurrence_json, evidence_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("c"), model_id, it["std_name"], it["category"], it.get("required_level"),
             it.get("importance"), it.get("weight"), it.get("years"), int(it.get("gate", 0)),
             it.get("level_reason"), json.dumps(it.get("occurrence", {})),
             json.dumps(it.get("evidence", []), ensure_ascii=False)),
        )
    conn.commit()
    return {"model_id": model_id, "status": "draft", "saved": True}


@router.post("/models/{model_id}/confirm")
def confirm_model(model_id: str, admin: dict = Depends(require_admin)) -> dict:
    """确认模型：status→confirmed，记录确认人与时间。版本号聚合时已分配。"""
    conn = get_conn()
    row = conn.execute("SELECT version, status, position_id FROM competency_model WHERE model_id=?",
                       (model_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模型不存在")
    if row["status"] == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "模型已确认")
    if row["status"] == "stalled":
        raise HTTPException(status.HTTP_409_CONFLICT, "模型处于滞留状态，请先完成等级裁决")

    conn.execute(
        "UPDATE competency_model SET status='confirmed', confirmed_by=?, confirmed_at=? WHERE model_id=?",
        (admin["user_id"], now_iso(), model_id),
    )
    conn.commit()
    return {"model_id": model_id, "status": "confirmed", "version": row["version"]}


@router.post("/positions/{position_id}/retry-level")
def retry_level(position_id: str, body: dict, background: BackgroundTasks) -> dict:
    """stalled 处理：action=retry 重跑聚合；action=manual 由前端编辑后走 PUT，此处仅重试。"""
    action = body.get("action")
    conn = get_conn()
    row = conn.execute(
        "SELECT model_id FROM competency_model WHERE position_id=? AND status='stalled'"
        " ORDER BY version DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位无 stalled 模型")
    if action == "retry":
        conn.execute("DELETE FROM competency_item WHERE model_id=?", (row["model_id"],))
        conn.execute("DELETE FROM competency_model WHERE model_id=?", (row["model_id"],))
        conn.commit()
        background.add_task(run_aggregate, position_id)
        return {"position_id": position_id, "retrying": True}
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "action 仅支持 retry（手动定级请用 PUT /models/{id}）")


@router.get("/positions/{position_id}/versions")
def list_versions(position_id: str) -> list[dict]:
    """版本历史（M3 diff 审阅流用，本期先提供列表）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT model_id, version, status, confirmed_by, confirmed_at, created_at"
        " FROM competency_model WHERE position_id=? ORDER BY version DESC",
        (position_id,),
    ).fetchall()
    return [dict(r) for r in rows]
