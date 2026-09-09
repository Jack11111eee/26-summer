"""岗位审核、待办统计、JD 改归（P1 岗位库后端）。"""
from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import require_admin
from ...db import get_conn
from ...services.input_limits import clamp_pagination_limit
from ...services.pipeline import new_id, now_iso

router = APIRouter(prefix="/api/admin", tags=["admin-positions"], dependencies=[Depends(require_admin)])


@router.get("/todos")
def get_todos() -> dict:
    """管理员待办：待审新岗位数、stalled 模型数、待归属 JD 数、题库未就绪岗位数。"""
    conn = get_conn()
    pending_positions = conn.execute(
        "SELECT COUNT(*) c FROM position WHERE status='pending_review'"
    ).fetchone()["c"]
    stalled = conn.execute(
        "SELECT COUNT(*) c FROM competency_model WHERE status='stalled'"
    ).fetchone()["c"]
    orphan_jds = conn.execute(
        "SELECT COUNT(*) c FROM jd_record WHERE position_id IS NULL AND status != 'failed'"
    ).fetchone()["c"]
    # 题库未就绪（D-13/WR-02）：按 (position_id, model_id, model_version) 取最新 task 行判定。
    # retry 保留旧 FAILED 行作审计并新增 QUEUED 行（models.py retry_question_bank_task），
    # 故须「无更新行」（NOT EXISTS）口径——重试成功后旧 FAILED 行不误计入未就绪/失败明细
    # （与 readiness.py ORDER BY created_at DESC LIMIT 1 取最新行的口径一致）。
    question_bank_not_ready = conn.execute(
        "SELECT COUNT(DISTINCT position_id) c FROM question_bank_task qbt"
        " WHERE status != 'SUCCEEDED'"
        " AND NOT EXISTS (SELECT 1 FROM question_bank_task q2"
        "   WHERE q2.position_id = qbt.position_id AND q2.model_id = qbt.model_id"
        "   AND q2.model_version = qbt.model_version"
        "   AND (q2.created_at > qbt.created_at"
        "        OR (q2.created_at = qbt.created_at AND q2.rowid > qbt.rowid)))"
    ).fetchone()["c"]
    # 题库生成失败明细（D-51/REF-8.4）：最新 task 行为 FAILED 的岗位
    question_bank_failed = [
        dict(r) for r in conn.execute(
            "SELECT position_id, model_id, model_version, error_msg FROM question_bank_task qbt"
            " WHERE status='FAILED'"
            " AND NOT EXISTS (SELECT 1 FROM question_bank_task q2"
            "   WHERE q2.position_id = qbt.position_id AND q2.model_id = qbt.model_id"
            "   AND q2.model_version = qbt.model_version"
            "   AND (q2.created_at > qbt.created_at"
            "        OR (q2.created_at = qbt.created_at AND q2.rowid > qbt.rowid)))"
        ).fetchall()
    ]
    return {
        "pending_positions": pending_positions,
        "stalled_models": stalled,
        "orphan_jds": orphan_jds,
        "question_bank_not_ready": question_bank_not_ready,
        "question_bank_failed": question_bank_failed,
    }


@router.get("/positions/pending")
def list_pending_positions(page: int = 1, page_size: int = 20) -> dict:
    """待审核新岗位列表（含 JD 数与示例 job_title）。"""
    page = max(1, page)
    page_size = clamp_pagination_limit(page_size)
    offset = (page - 1) * page_size
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) c FROM position p WHERE p.status='pending_review'"
    ).fetchone()["c"]
    rows = conn.execute(
        "SELECT p.position_id, p.name, p.created_at,"
        " (SELECT COUNT(*) FROM jd_record j WHERE j.position_id=p.position_id) AS jd_count"
        " FROM position p WHERE p.status='pending_review' ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total}


@router.post("/positions/{position_id}/review")
def review_position(position_id: str, body: dict) -> dict:
    """新岗位审核：approve → active；reject → 撤销岗位，其下 JD 归 NULL 进待归属。"""
    action = body.get("action")
    conn = get_conn()
    pos = conn.execute("SELECT status FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "岗位不存在")
    if pos["status"] != "pending_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "仅 pending_review 岗位可审核")

    if action == "approve":
        conn.execute("UPDATE position SET status='active' WHERE position_id=?", (position_id,))
        conn.commit()
        return {"position_id": position_id, "status": "active"}
    if action == "reject":
        # CR-03：reject 会 DELETE position，FK 开启下若子表（competency_model /
        # question_bank_task / assessment_session）已有该岗位数据，会触发未捕获的
        # IntegrityError → 500。先检查子表占用，命中则 409 引导改用上架/下架等处理。
        blocking = conn.execute(
            "SELECT (SELECT COUNT(*) FROM competency_model WHERE position_id=?) m,"
            " (SELECT COUNT(*) FROM question_bank_task WHERE position_id=?) t,"
            " (SELECT COUNT(*) FROM assessment_session WHERE position_id=?) s",
            (position_id, position_id, position_id),
        ).fetchone()
        if blocking["m"] or blocking["t"] or blocking["s"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "岗位已产生模型/题库/会话数据，不可撤销删除（可在岗位清单将该岗位下架后处理）",
            )
        # 撤销岗位：其下 JD 归 NULL（待归属队列），别名删除，岗位本身删除
        conn.execute("UPDATE jd_record SET position_id=NULL WHERE position_id=?", (position_id,))
        conn.execute("DELETE FROM position_alias WHERE position_id=?", (position_id,))
        conn.execute("DELETE FROM position WHERE position_id=?", (position_id,))
        conn.commit()
        return {"position_id": position_id, "status": "rejected", "jds_orphaned": True}
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "action 仅支持 approve/reject")


@router.post("/positions/{position_id}/status")
def set_position_status(position_id: str, body: dict) -> dict:
    """岗位手动上架/下架（SSOT §8 岗位生命周期，2026-09-09）：active⇄inactive。

    pending_review 岗禁用本端点（入口态须经审核流 approve/reject，不是停车场）；
    目标态=当前态 409；下架（目标 inactive）时同岗位存在 RUNNING 聚合任务 409
    （防下架中途聚合把模型落在刚下架的岗位上）。
    """
    target = body.get("status")
    conn = get_conn()
    pos = conn.execute("SELECT status FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "岗位不存在")
    if target not in ("active", "inactive"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "status 仅支持 active/inactive")
    if pos["status"] == "pending_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "pending_review 岗位须经审核流处理")
    if target == pos["status"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"岗位已是 {target} 状态")
    if target == "inactive":
        running = conn.execute(
            "SELECT task_id FROM aggregate_task WHERE position_id=? AND status='RUNNING' LIMIT 1",
            (position_id,),
        ).fetchone()
        if running is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "该岗位聚合进行中，请等待完成后再下架")
    conn.execute("UPDATE position SET status=? WHERE position_id=?", (target, position_id))
    conn.commit()
    return {"position_id": position_id, "status": target}


@router.post("/positions/{source_id}/merge")
def merge_position(source_id: str, body: dict) -> dict:
    """岗位合并（SSOT §8 岗位生命周期，2026-09-09）：source 的 JD + 名/别名胜全量迁入 target、
    source 删除。单事务先全部校验后变异（校验命中即 409/404，不动任何行）。

    source 须为数据壳（无 competency_model/question_bank_task/assessment_session 子表数据，
    口径同 review reject 的 FK 检查）——模型属岗位聚合产物不可搬运，有数据岗走逐条
    改归 JD + 壳岗下架。合并后不触发任何聚合：升版本须 diff 人审（SSOT 明文）。
    """
    target_id = body.get("target_id")
    conn = get_conn()
    source = conn.execute(
        "SELECT position_id, name FROM position WHERE position_id=?", (source_id,)
    ).fetchone()
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合并源岗位不存在")
    target = conn.execute(
        "SELECT position_id, name, status FROM position WHERE position_id=?", (target_id,)
    ).fetchone()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "合并目标岗位不存在")
    if source_id == target_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "合并源与目标不能是同一岗位")
    if target["status"] != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "合并目标岗位须为上架状态")
    blocking = conn.execute(
        "SELECT (SELECT COUNT(*) FROM competency_model WHERE position_id=?) m,"
        " (SELECT COUNT(*) FROM question_bank_task WHERE position_id=?) t,"
        " (SELECT COUNT(*) FROM assessment_session WHERE position_id=?) s",
        (source_id, source_id, source_id),
    ).fetchone()
    if blocking["m"] or blocking["t"] or blocking["s"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "source 岗位已产生模型/题库/会话数据，不可合并（请逐条改归其 JD 后将壳岗下架）",
        )
    # 别名冲突预检：将迁入 target 的集合 = source.name + source 现有 alias 全体。
    # 任一被其他岗位占用（UNIQUE alias 全表唯一）或与 target.name 撞名（名字即岗位
    # 本身，撞名说明数据脏）→ 409 列出冲突项。逐项即时查（alias 集合为个位数）。
    source_aliases = [
        r["alias"] for r in conn.execute(
            "SELECT alias FROM position_alias WHERE position_id=?", (source_id,)
        ).fetchall()
    ]
    incoming = [source["name"]] + source_aliases
    conflicts = []
    for name in incoming:
        if name.lower() == target["name"].lower():
            conflicts.append(f"{name}（与目标岗位名相同）")
            continue
        clash = conn.execute(
            "SELECT p.name FROM position_alias a JOIN position p ON p.position_id=a.position_id"
            " WHERE a.alias=? COLLATE NOCASE AND a.position_id != ? LIMIT 1",
            (name, source_id),
        ).fetchone()
        if clash is not None:
            conflicts.append(f"{name}（已被岗位「{clash['name']}」占用）")
    if conflicts:
        raise HTTPException(status.HTTP_409_CONFLICT, f"别名冲突：{'、'.join(conflicts)}")
    # 变异（一事务）：①JD 全量改归（全部状态，不筛）→ source 为数据分析过岗的条件；
    # ②source 名插为 target 别名（若 source 名已伴生于自身 alias 表则随行迁移、不重复插，
    # 防 UNIQUE 自撞）+ source 既有 alias 行整体改挂 target；③删 source。
    # 迁移后不触发任何聚合——升版本须 diff 人审（SSOT §8 明文）。
    moved_jds = conn.execute(
        "UPDATE jd_record SET position_id=? WHERE position_id=?", (target_id, source_id)
    ).rowcount
    moved_aliases = 0
    if source["name"] not in source_aliases:
        conn.execute(
            "INSERT INTO position_alias(alias_id, position_id, alias) VALUES(?,?,?)",
            (new_id("pa"), target_id, source["name"]),
        )
        moved_aliases += 1
    moved_aliases += conn.execute(
        "UPDATE position_alias SET position_id=? WHERE position_id=?", (target_id, source_id)
    ).rowcount
    conn.execute("DELETE FROM position WHERE position_id=?", (source_id,))
    conn.commit()
    return {
        "source_id": source_id,
        "target_id": target_id,
        "moved_jds": moved_jds,
        "moved_aliases": moved_aliases,
    }


@router.post("/jds/{jd_id}/reassign")
def reassign_jd(jd_id: str, body: dict) -> dict:
    """待归属 JD 手动改归到指定岗位。"""
    target = body.get("position_id")
    conn = get_conn()
    jd = conn.execute("SELECT position_id FROM jd_record WHERE jd_id=?", (jd_id,)).fetchone()
    if jd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "JD 不存在")
    pos = conn.execute("SELECT status FROM position WHERE position_id=?", (target,)).fetchone()
    if pos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "目标岗位不存在")
    conn.execute("UPDATE jd_record SET position_id=? WHERE jd_id=?", (target, jd_id))
    conn.commit()
    return {"jd_id": jd_id, "position_id": target}
