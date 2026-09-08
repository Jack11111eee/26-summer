"""聚合触发、模型获取/编辑/确认、stalled 处理（P3 人审 + 状态机流转）。"""
import json
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...core.security import require_admin
from ...db import get_conn
from ...services.aggregate import run_aggregate
from ...services.input_limits import clamp_pagination_limit
from ...services.pipeline import now_iso

router = APIRouter(prefix="/api/admin", tags=["admin-models"], dependencies=[Depends(require_admin)])


class ModelItem(BaseModel):
    """人审编辑的单个能力项（WR-07：std_name/category/weight 等字段强类型，
    缺字段/非法类型 422 而非 KeyError/ValueError→500）。"""

    std_name: str = Field(min_length=1)
    category: str = Field(pattern="^(hard_skill|soft_skill|experience|qualification)$")
    weight: float = Field(ge=0, le=1, allow_inf_nan=False)
    required_level: int | None = Field(default=None, ge=1, le=5)
    importance: Literal["required", "preferred", "plus"] | None = None
    years: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    gate: int = 0
    level_reason: str | None = None
    occurrence: dict = {}
    evidence: list = []


class ModelUpdateBody(BaseModel):
    items: list[ModelItem] = Field(min_length=1)


def _running_task_or_none(conn, position_id: str):
    """该岗位是否有 RUNNING 聚合任务行（409 守卫与收尾共用的单点查询）。"""
    return conn.execute(
        "SELECT task_id FROM aggregate_task WHERE position_id=? AND status='RUNNING' LIMIT 1",
        (position_id,),
    ).fetchone()


@router.post("/positions/{position_id}/aggregate")
def trigger_aggregate(position_id: str, background: BackgroundTasks) -> dict:
    """手动触发聚合（自动触发的兜底）。仅 active 岗位可聚合（WR-08）：
    pending_review 岗位聚合会产生 competency_model 行，使后续 reject 撞 FK（CR-03）；
    自动链（pipeline）同样只在 active 时触发，手动入口保持一致。
    并发守卫（SSOT §8.4，2026-09-08）：已有 RUNNING 任务行时 409——防双击/跨页并发
    撞版本号（run_aggregate 内部守卫为静默兜底，主动路径要显式回错）。"""
    conn = get_conn()
    pos = conn.execute("SELECT status FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "岗位不存在")
    if pos["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "仅上架岗位可触发聚合")
    if _running_task_or_none(conn, position_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该岗位聚合进行中，请等待完成后再触发")
    background.add_task(run_aggregate, position_id, "manual")
    return {"position_id": position_id, "aggregating": True}


@router.get("/positions/{position_id}/aggregate/progress")
def get_aggregate_progress(position_id: str) -> dict:
    """聚合任务进度（SSOT §8.4）：按岗位查最新一条 aggregate_task 行，无记录 404。

    前端轮询本端点（取代模型 404→200 二态轮询）；刚触发后头几轮 BackgroundTasks
    可能尚未起跑插行 → 404，前端视为「启动中」继续轮询。任务生命周期与页面组件
    解耦：离开页面不中断，重进页面认领 RUNNING 行即恢复展示。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT task_id, position_id, status, trigger_source, total, done, llm_total,"
        " llm_done, current_item, model_id, error, created_at, started_at, finished_at"
        " FROM aggregate_task WHERE position_id=?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (position_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该岗位暂无聚合任务记录")
    return dict(row)


@router.get("/positions/{position_id}/model")
def get_current_model(position_id: str) -> dict:
    """当前生效模型：draft/stalled 优先，否则最新 confirmed。无则 404。

    §8.5 读侧合并：draft/stalled 时附 evidence_exclusion active 行回各 item 的
    evidence（每条含 excluded: true + reason/excluded_by/excluded_at，前端灰显/
    恢复）；confirmed 返回入库快照不合并（快照存库前已剥离，天然不含排除条目）。
    excluded 标记是读取时实时合并的当期状态、非版本历史快照（历史以表内审计列为准）。
    """
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
    if d["status"] in ("draft", "stalled"):
        from ...services.aggregate import collect_excluded_entries
        excl = collect_excluded_entries(position_id)
        if excl:
            for it in d["model"].get("items", []):
                extra = excl.get((it["std_name"], it["category"]))
                if extra:
                    it.setdefault("evidence", []).extend(extra)
    return d


@router.put("/models/{model_id}")
def update_model(model_id: str, body: ModelUpdateBody) -> dict:
    """人审编辑草稿：整份 items 替换（改名/调级/调权/增删项/改类间配比）。

    body 为完整 model_json（Pydantic 只取其后端已知的结构化字段；前端提交的
    其余 model_json 元数据如 position_id/version 由 GET 模型时下发、编辑时
    原样透传，故存库时合并保留）。仅 draft/stalled 可编辑。
    """
    conn = get_conn()
    row = conn.execute("SELECT status FROM competency_model WHERE model_id=?", (model_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模型不存在")
    if row["status"] == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "已确认模型不可编辑（请走 diff 审阅流）")

    items = body.items

    # Σ=100% 服务端校验（容差 0.5%）
    total_weight = sum(it.weight for it in items)
    if abs(total_weight - 1.0) > 0.005:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"权重合计须为 100%（当前 {total_weight * 100:.1f}%）")

    # 同 category 内 std_name 重复拒绝（判重键 (std_name, category) 对齐 competency_item
    # 主键与 diff_models 的 "std_name|category" 对齐键，重复会破坏 diff）
    seen: set[tuple[str, str]] = set()
    for it in items:
        key = (it.std_name, it.category)
        if key in seen:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"同一类目内能力项重复：{it.std_name}({it.category})",
            )
        seen.add(key)

    # WR-04：ModelUpdateBody 仅声明 items（Pydantic extra='ignore' 丢弃 position_id/version
    # 等元数据），故存库须从既有 model_json 读取并保留非 items 元数据，仅以校验后的
    # items 覆盖（stall_reason 清除）——否则编辑后 GET /model 丢失 position_id/version。
    from ...services.pipeline import new_id
    existing = json.loads(conn.execute(
        "SELECT model_json FROM competency_model WHERE model_id=?", (model_id,)
    ).fetchone()["model_json"])
    stored_items = body.model_dump()["items"]
    # §8.5 PUT 剥离：前端 GET 时收到的实时合并 excluded 条目原样回传，存库前剥除——
    # 存储不变量：模型存储（model_json + evidence_json）只含未排除证据（排除状态
    # 唯一权威载体是 evidence_exclusion 表，读取时再实时合并）。
    for it in stored_items:
        it["evidence"] = [ev for ev in (it.get("evidence") or [])
                          if not (isinstance(ev, dict) and ev.get("excluded"))]
    existing["items"] = stored_items
    existing.pop("stall_reason", None)  # 编辑后清除 stalled 标记
    stored = existing
    conn.execute("UPDATE competency_model SET model_json=?, status='draft' WHERE model_id=?",
                 (json.dumps(stored, ensure_ascii=False), model_id))
    # 明细表同步重建（人审后的权威内容）——用剥离后的 stored_items（与 model_json 同源，
    # §8.5：两处落库均不含 excluded 条目）
    conn.execute("DELETE FROM competency_item WHERE model_id=?", (model_id,))
    for it in stored_items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, years, gate, level_reason, occurrence_json, evidence_json)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("c"), model_id, it["std_name"], it["category"], it["required_level"],
             it["importance"], it["weight"], it["years"], it["gate"],
             it["level_reason"], json.dumps(it["occurrence"]),
             json.dumps(it["evidence"], ensure_ascii=False)),
        )
    conn.commit()
    return {"model_id": model_id, "status": "draft", "saved": True}


# ---------- §8.5 证据排除（岗位作用域，源头治理级；详见 SSOT §8.5） ----------

_EXCLUSION_CATEGORIES = ("hard_skill", "soft_skill", "experience", "qualification")


class EvidenceExclusionBody(BaseModel):
    """标记排除：目标键 + 可选原因（who/when 服务端取当前管理员与时间）。"""

    jd_id: str = Field(min_length=1)
    std_name: str = Field(min_length=1)
    category: Literal["hard_skill", "soft_skill", "experience", "qualification"]
    text: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=500)


class EvidenceExclusionLiftBody(BaseModel):
    """解除排除：目标键（同标记，不携带 reason）。"""

    jd_id: str = Field(min_length=1)
    std_name: str = Field(min_length=1)
    category: Literal["hard_skill", "soft_skill", "experience", "qualification"]
    text: str = Field(min_length=1)


def _validate_exclusion_target(conn, position_id: str, body: EvidenceExclusionBody) -> None:
    """目标须为本岗位 parsed JD 的现存证据摘录（400），防脏数据静默入表——
    失配键（JD 重解析/词典改名后）靠 GET 端点 evidence_matched 标志可见，但新标记
    必须当前真实存在。"""
    jd = conn.execute(
        "SELECT position_id, status FROM jd_record WHERE jd_id=?", (body.jd_id,)
    ).fetchone()
    if jd is None or jd["position_id"] != position_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该 JD 不属于此岗位")
    if jd["status"] != "parsed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该 JD 未完成解析")
    items = json.loads(conn.execute(
        "SELECT std_items_json FROM jd_record WHERE jd_id=?", (body.jd_id,)
    ).fetchone()["std_items_json"] or "[]")
    hit = next((it for it in items
                if it["name"] == body.std_name and it["category"] == body.category), None)
    if hit is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该 JD 无此能力项")
    if body.text not in (hit.get("evidence") or []):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该能力项无此证据摘录")


@router.post("/positions/{position_id}/evidence-exclusions")
def mark_evidence_exclusion(position_id: str, body: EvidenceExclusionBody,
                            admin: dict = Depends(require_admin)) -> dict:
    """标记一条证据摘录为已排除（§8.5：语句粒度软标记 + who/when/reason 留痕）。

    幂等 upsert（同键重复标记最后写入者胜：覆盖 reason/操作人，复活 active）。
    聚合运行中标记 → 本次聚合不吃、下次生效（单写 SQLite 无一致性风险）。
    """
    conn = get_conn()
    if conn.execute("SELECT 1 FROM position WHERE position_id=?", (position_id,)).fetchone() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "岗位不存在")
    _validate_exclusion_target(conn, position_id, body)
    conn.execute(
        "INSERT INTO evidence_exclusion(position_id, jd_id, std_name, category, text,"
        " reason, excluded_by, excluded_at, status, lifted_by, lifted_at)"
        " VALUES(?,?,?,?,?,?,?,?,'active',NULL,NULL)"
        " ON CONFLICT(position_id, jd_id, std_name, category, text) DO UPDATE SET"
        " reason=excluded.reason, excluded_by=excluded.excluded_by,"
        " excluded_at=excluded.excluded_at, status='active', lifted_by=NULL, lifted_at=NULL",
        (position_id, body.jd_id, body.std_name, body.category, body.text,
         body.reason, admin["user_id"], now_iso()),
    )
    conn.commit()
    return {"position_id": position_id, "jd_id": body.jd_id, "std_name": body.std_name,
            "category": body.category, "text": body.text, "excluded": True}


@router.delete("/positions/{position_id}/evidence-exclusions")
def lift_evidence_exclusion(position_id: str, body: EvidenceExclusionLiftBody,
                            admin: dict = Depends(require_admin)) -> dict:
    """解除排除（§8.5：置 lifted 不删行，lifted_by/lifted_at 留痕；已 lifted 幂等 200）。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT status FROM evidence_exclusion"
        " WHERE position_id=? AND jd_id=? AND std_name=? AND category=? AND text=?",
        (position_id, body.jd_id, body.std_name, body.category, body.text),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该排除记录不存在")
    if row["status"] != "lifted":
        conn.execute(
            "UPDATE evidence_exclusion SET status='lifted', lifted_by=?, lifted_at=?"
            " WHERE position_id=? AND jd_id=? AND std_name=? AND category=? AND text=?",
            (admin["user_id"], now_iso(), position_id,
             body.jd_id, body.std_name, body.category, body.text),
        )
        conn.commit()
    return {"position_id": position_id, "jd_id": body.jd_id, "std_name": body.std_name,
            "category": body.category, "text": body.text, "excluded": False}


@router.get("/positions/{position_id}/evidence-exclusions")
def list_evidence_exclusions(position_id: str) -> list[dict]:
    """全量排除记录（含已解除，审计用），每行附 evidence_matched 实时标志：
    JD 重解析/词典合并改名后失配的排除据此可见（不做自动迁移，SSOT §8.5）。"""
    conn = get_conn()
    active_keys = set()
    for row in conn.execute(
        "SELECT jd_id, std_items_json FROM jd_record"
        " WHERE position_id=? AND status='parsed' AND std_items_json IS NOT NULL",
        (position_id,),
    ):
        for it in json.loads(row["std_items_json"]):
            for t in it.get("evidence") or []:
                active_keys.add((row["jd_id"], it["name"], it["category"], t))
    rows = conn.execute(
        "SELECT * FROM evidence_exclusion WHERE position_id=? ORDER BY excluded_at DESC",
        (position_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence_matched"] = (d["jd_id"], d["std_name"], d["category"], d["text"]) in active_keys
        out.append(d)
    return out


@router.post("/models/{model_id}/confirm")
def confirm_model(model_id: str, background: BackgroundTasks, admin: dict = Depends(require_admin)) -> dict:
    """确认模型：status→confirmed，记录确认人与时间；异步触发题库生成（07 §6.2）。"""
    conn = get_conn()
    row = conn.execute("SELECT version, status, position_id FROM competency_model WHERE model_id=?",
                       (model_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模型不存在")
    if row["status"] == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "模型已确认")
    if row["status"] == "stalled":
        raise HTTPException(status.HTTP_409_CONFLICT, "模型处于滞留状态，请先完成等级裁决")

    # WR-04：UPDATE confirmed 与 INSERT task 行同一事务——插行失败（磁盘满/DB busy）
    # 时 confirmed 一并回滚，避免出现"confirmed 但无 task 行"的不可恢复态（readiness
    # 第 3 项查不到行 → 按实际题量判定 → 永久 INCOMPLETE）
    conn.execute(
        "UPDATE competency_model SET status='confirmed', confirmed_by=?, confirmed_at=? WHERE model_id=?",
        (admin["user_id"], now_iso(), model_id),
    )
    # 题库生成任务行（D-12）：confirm 后插 QUEUED，生成任务开始/结束更新自身行；
    # 先于 add_task 落库，确保即使后台任务异常，三态仍真实可查
    from ...services.pipeline import new_id
    conn.execute(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (new_id("qbt"), row["position_id"], model_id, row["version"], "QUEUED", now_iso()),
    )
    # 旧版题库归档（SSOT §9.2 2026-09-08）：本 confirm 即「同岗位存在更新 confirmed
    # 模型」的成立时刻——同事务顺带归档旧版题库行（被 in_progress 会话引用的
    # model_id 由 helper 内部豁免；归档不依赖新库生成结果，正交于 readiness）
    from ...services.question_bank import archive_superseded_banks
    archive_superseded_banks(conn, row["position_id"])
    conn.commit()

    from ...services.question_bank import generate_question_bank
    background.add_task(generate_question_bank, row["position_id"], model_id)
    return {"model_id": model_id, "status": "confirmed", "version": row["version"],
            "question_bank_generating": True}


@router.post("/question-bank-tasks/{task_id}/retry")
def retry_question_bank_task(task_id: str, background: BackgroundTasks) -> dict:
    """重触发失败的题库生成任务（CR-02：FAILED 恢复入口，兑现"可手动重触发"契约）。

    confirm 对已确认模型恒 409，无此入口时 FAILED + 题库不足的岗位会被 readiness
    永久锁死（todos 的 question_bank_not_ready 也永不归零）。做法：新插一行 QUEUED
    task（保留旧行作审计）并后台重跑 generate_question_bank；最新行判定口径即 D-12。
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT position_id, model_id, model_version, status FROM question_bank_task"
        " WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if row["status"] != "FAILED":
        raise HTTPException(status.HTTP_409_CONFLICT, "仅失败任务可重试")
    # 归档护栏（SSOT §9.2 2026-09-08 规则⑤）：该岗位已存在更新 confirmed 模型时，
    # 旧模型的 FAILED 任务不可重试——重跑会经幂等查重「复活」出新的 active 行，
    # 污染归档标记与管理端计数。判定基准取岗位最新 confirmed 的 model_id
    # （version 高者为新，同 version 取 rowid 最新），!= 本 task 行的 model_id
    # 即视为已被取代（判定与归档行无关，无时序竞争窗口，讨论稿 C2）。
    latest = conn.execute(
        "SELECT model_id FROM competency_model"
        " WHERE position_id=? AND status='confirmed'"
        " ORDER BY version DESC, rowid DESC LIMIT 1",
        (row["position_id"],),
    ).fetchone()
    if latest is not None and latest["model_id"] != row["model_id"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "该岗位已存在更新的已确认模型，旧版题库任务不可重试",
        )

    from ...services.pipeline import new_id
    conn.execute(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (new_id("qbt"), row["position_id"], row["model_id"],
         row["model_version"], "QUEUED", now_iso()),
    )
    conn.commit()

    from ...services.question_bank import generate_question_bank
    background.add_task(generate_question_bank, row["position_id"], row["model_id"])
    return {"position_id": row["position_id"], "model_id": row["model_id"], "requeued": True}


@router.post("/positions/{position_id}/retry-level")
def retry_level(position_id: str, body: dict, background: BackgroundTasks) -> dict:
    """stalled 处理：action=retry 重跑聚合；action=manual 由前端编辑后走 PUT，此处仅重试。"""
    action = body.get("action")
    conn = get_conn()
    # 并发守卫（SSOT §8.4，2026-09-08）先于删除 stalled 模型——防「删了模型却因
    # RUNNING 撞守卫没跑起来」的不可恢复态
    if _running_task_or_none(conn, position_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该岗位聚合进行中，请等待完成后再重试")
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
        background.add_task(run_aggregate, position_id, "retry")
        return {"position_id": position_id, "retrying": True}
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "action 仅支持 retry（手动定级请用 PUT /models/{id}）")


@router.get("/positions/{position_id}/versions")
def list_versions(position_id: str) -> list[dict]:
    """版本历史。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT model_id, version, status, confirmed_by, confirmed_at, created_at"
        " FROM competency_model WHERE position_id=? ORDER BY version DESC",
        (position_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/models/{new_id}/diff")
def diff_models(new_id: str, against: str) -> dict:
    """两版本逐项 diff：added/removed/field 变更（P4 diff 审阅流）。

    以 std_name+category 为对齐键。返回每项的变更类型与字段级差异。
    """
    conn = get_conn()
    def load(mid):
        row = conn.execute("SELECT model_json FROM competency_model WHERE model_id=?", (mid,)).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"模型不存在: {mid}")
        return {f"{i['std_name']}|{i['category']}": i for i in json.loads(row["model_json"])["items"]}

    new_items, old_items = load(new_id), load(against)
    FIELD_LABELS = {"required_level": "等级", "importance": "重要性", "weight": "权重",
                    "years": "年限", "gate": "门槛"}
    changes = []
    for key, nitem in new_items.items():
        if key not in old_items:
            changes.append({"std_name": nitem["std_name"], "category": nitem["category"],
                            "change": "added", "new": nitem})
            continue
        oitem = old_items[key]
        field_diffs = [
            {"field": f, "label": FIELD_LABELS[f], "old": oitem.get(f), "new": nitem.get(f)}
            for f in FIELD_LABELS if oitem.get(f) != nitem.get(f)
        ]
        if field_diffs:
            changes.append({"std_name": nitem["std_name"], "category": nitem["category"],
                            "change": "field", "diffs": field_diffs, "new": nitem, "old": oitem})
    for key, oitem in old_items.items():
        if key not in new_items:
            changes.append({"std_name": oitem["std_name"], "category": oitem["category"],
                            "change": "removed", "old": oitem})
    return {"new_id": new_id, "against": against, "changes": changes}


# ---------- §8.6 聚合管理页列表（2026-09-08，与 §9.5 题库任务列表形态对齐） ----------

# 同岗位最新聚合任务行子句（NOT EXISTS 口径与 question_bank_tasks._latest_row_where 同构）
_AGG_LATEST_WHERE = (
    " NOT EXISTS (SELECT 1 FROM aggregate_task a2"
    " WHERE a2.position_id = at.position_id"
    " AND (a2.created_at > at.created_at"
    " OR (a2.created_at = at.created_at AND a2.rowid > at.rowid)))"
)

# 最新模型优先序：stalled > draft > confirmed（与 GET /positions/{id}/model 同口径）
_MODEL_LATEST_ROW = (
    "SELECT model_id, version, status FROM competency_model WHERE position_id=?"
    " ORDER BY CASE status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END,"
    " version DESC LIMIT 1"
)


@router.get("/aggregate-tasks")
def list_aggregate_tasks(page: int = 1, page_size: int = 20,
                         model_status: str | None = None,
                         task_status: str | None = None,
                         q: str | None = None) -> dict:
    """聚合管理页列表（SSOT §8.6）：行源 active 岗位 × 最新聚合任务行 + 左连最新模型。

    「有模型或有任务行」即入列——首次聚合进行中（模型行未落库）可见；两者皆无的
    岗位不出现在任何列表。筛选：model_status（draft/confirmed/stalled）、task_status
    （RUNNING/SUCCEEDED/FAILED）、q（岗位名子串）。响应附 summary 计数（不随筛选变）
    供 KPI 与侧栏徽标。
    """
    page = max(1, page)
    page_size = clamp_pagination_limit(page_size)
    offset = (page - 1) * page_size

    # 筛选子句（挂在 position 主表上）：模型状态筛「最新模型命中该状态」的岗位；
    # 任务状态筛「最新任务行命中该状态」的岗位——与行内取数口径一致，筛出即所见的
    where = ["p.status='active'"]
    params: list = []
    has_model = " EXISTS (SELECT 1 FROM competency_model m WHERE m.position_id=p.position_id)"
    has_task = " EXISTS (SELECT 1 FROM aggregate_task at2 WHERE at2.position_id=p.position_id)"
    if model_status in ("draft", "confirmed", "stalled"):
        # 最新模型命中筛选状态（与 _MODEL_LATEST_ROW 的 ORDER BY 完全镜像：「状态
        # 优先序 stalled>draft>confirmed 先分组、组内 version/rowid 取新」——低优先
        # 序状态的高版本不夺取最新资格）。m 合格 ⇔ 不存在排序更前的 m2。
        where.append(
            " EXISTS (SELECT 1 FROM competency_model m WHERE m.position_id=p.position_id"
            f" AND m.status=? AND NOT EXISTS ("
            "   SELECT 1 FROM competency_model m2 WHERE m2.position_id=m.position_id"
            "   AND ((CASE m2.status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END"
            "        < CASE m.status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END)"
            "    OR (CASE m2.status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END"
            "        = CASE m.status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END"
            "        AND (m2.version > m.version"
            "            OR (m2.version = m.version AND m2.rowid > m.rowid))))))"
        )
        params.append(model_status)
    if task_status in ("RUNNING", "SUCCEEDED", "FAILED"):
        where.append(
            " EXISTS (SELECT 1 FROM aggregate_task at3 WHERE at3.position_id=p.position_id"
            f" AND at3.status=?"
            " AND NOT EXISTS (SELECT 1 FROM aggregate_task at4"
            " WHERE at4.position_id=at3.position_id"
            " AND (at4.created_at>at3.created_at"
            " OR (at4.created_at=at3.created_at AND at4.rowid>at3.rowid))))"
        )
        params.append(task_status)
    if q:
        where.append(" p.name LIKE ?")
        params.append(f"%{q}%")
    where.append(f" ({has_model} OR {has_task})")

    where_clause = " WHERE " + " AND ".join(where)
    conn = get_conn()
    # 行源以岗位为主表（每岗位一行）；最新模型/最新任务行在 Python 侧按岗位取——
    # 本页规模（±百岗位、页 20）下每行常数主键查询，可读性优先于 NOT EXISTS join
    position_rows = conn.execute(
        "SELECT p.position_id, p.name FROM position p"
        + where_clause +
        " ORDER BY p.created_at DESC, p.position_id DESC LIMIT ? OFFSET ?",
        (*params, page_size, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) c FROM position p" + where_clause, params
    ).fetchone()["c"]

    items = []
    for r in position_rows:
        pid = r["position_id"]
        model = conn.execute(_MODEL_LATEST_ROW, (pid,)).fetchone()
        task = conn.execute(
            "SELECT task_id, status, trigger_source, total, done, llm_total, llm_done,"
            " current_item, model_id, error, created_at, started_at, finished_at"
            f" FROM aggregate_task at WHERE at.position_id=? AND{_AGG_LATEST_WHERE}",
            (pid,),
        ).fetchone()
        jd_count = conn.execute(
            "SELECT COUNT(*) c FROM jd_record WHERE position_id=? AND status='parsed'",
            (pid,),
        ).fetchone()["c"]
        item_count = 0
        if model is not None:
            item_count = conn.execute(
                "SELECT COUNT(*) c FROM competency_item WHERE model_id=?",
                (model["model_id"],),
            ).fetchone()["c"]
        d = {
            "position_id": pid,
            "position_name": r["name"],
            "jd_count": jd_count,
            "model": ({"model_id": model["model_id"], "version": model["version"],
                       "status": model["status"]} if model else None),
            "item_count": item_count,
        }
        if task is not None:
            d["task"] = {
                "task_id": task["task_id"], "status": task["status"],
                "trigger_source": task["trigger_source"],
                "progress": {"done": task["done"], "total": task["total"],
                             "llm_done": task["llm_done"], "llm_total": task["llm_total"],
                             "current_item": task["current_item"]},
                "error": task["error"],
                "created_at": task["created_at"], "finished_at": task["finished_at"],
            }
        else:
            d["task"] = None
        items.append(d)

    # summary（不随筛选变——KPI/徽标要的是全库口径）
    def _count_positions(sql: str) -> int:
        return conn.execute(sql).fetchone()["c"]
    summary = {
        "draft_positions": _count_positions(
            "SELECT COUNT(DISTINCT position_id) c FROM competency_model WHERE status='draft'"),
        "confirmed_positions": _count_positions(
            "SELECT COUNT(DISTINCT position_id) c FROM competency_model WHERE status='confirmed'"),
        "stalled_positions": _count_positions(
            "SELECT COUNT(DISTINCT position_id) c FROM competency_model WHERE status='stalled'"),
        "running_tasks": _count_positions(
            "SELECT COUNT(*) c FROM aggregate_task WHERE status='RUNNING'"),
    }
    return {"items": items, "total": total, "summary": summary}
