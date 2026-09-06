"""岗位审核、待办统计、JD 改归（P1 岗位库后端）。"""
from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import require_admin
from ...db import get_conn
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
def list_pending_positions() -> list[dict]:
    """待审核新岗位列表（含 JD 数与示例 job_title）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT p.position_id, p.name, p.created_at,"
        " (SELECT COUNT(*) FROM jd_record j WHERE j.position_id=p.position_id) AS jd_count"
        " FROM position p WHERE p.status='pending_review' ORDER BY p.created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


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
                "岗位已产生模型/题库/会话数据，不可撤销删除（请改用下架等处理）",
            )
        # 撤销岗位：其下 JD 归 NULL（待归属队列），别名删除，岗位本身删除
        conn.execute("UPDATE jd_record SET position_id=NULL WHERE position_id=?", (position_id,))
        conn.execute("DELETE FROM position_alias WHERE position_id=?", (position_id,))
        conn.execute("DELETE FROM position WHERE position_id=?", (position_id,))
        conn.commit()
        return {"position_id": position_id, "status": "rejected", "jds_orphaned": True}
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "action 仅支持 approve/reject")


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
