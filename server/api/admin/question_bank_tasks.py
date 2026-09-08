"""题库生成任务查询端点（SSOT §9.5，2026-09-08）：列表 / 详情 / 题目表。

- 列表：按 (position_id, model_id) 取最新任务行（岗位 × 模型版本一行），含题量计数；
- 详情：任务全字段 + 同 (position, model) 历史任务行（retry 留档审计）+
  llm_trace 时间窗调用列表（不改表：任务 created_at~finished_at × call_type=
  'question_gen' × 该模型 item 集 ref_id=item_id 关联）+ item×difficulty 覆盖统计；
- 题目表：该 (position, model) 题目分页（stem 预览）。

服务端分页契约 {items, total}（§31）；RUNNING 任务时间窗右端点取「至今」。
"""
from fastapi import APIRouter, Depends, HTTPException, status

from ...core.security import require_admin
from ...db import get_conn
from ...services.input_limits import clamp_pagination_limit
from ...services.pipeline import now_iso

router = APIRouter(prefix="/api/admin/question-bank-tasks",
                   tags=["admin-qbank-tasks"], dependencies=[Depends(require_admin)])

_STEM_PREVIEW = 80  # 题干预览长度（§9.5：stem 预览）


def _latest_row_where() -> str:
    """最新任务行判定子句（与 positions.todos 同口径）：

    同 (position_id, model_id) 内不存在更新行（created_at + rowid tie-break）
    ——retry 保留旧行审计，列表只展示每组最新一行。
    """
    return (
        " NOT EXISTS (SELECT 1 FROM question_bank_task q2"
        " WHERE q2.position_id = qbt.position_id AND q2.model_id = qbt.model_id"
        " AND (q2.created_at > qbt.created_at"
        " OR (q2.created_at = qbt.created_at AND q2.rowid > qbt.rowid)))"
    )


def _question_count(conn, position_id: str, model_id: str) -> int:
    """该 (position, model) 的 active 题量计数（题库单元 = 岗位 + 模型版本）。"""
    return conn.execute(
        "SELECT COUNT(*) c FROM question_bank WHERE status='active'"
        " AND model_id=? AND position_id=?",
        (model_id, position_id),
    ).fetchone()["c"]


@router.get("")
def list_question_bank_tasks(page: int = 1, page_size: int = 20,
                             status_filter: str | None = None) -> dict:
    """题库任务列表（§9.5）：按 (岗位 × 模型) 最新任务行，status 过滤 + 服务端分页。

    status_filter：RUNNING / QUEUED / SUCCEEDED / FAILED（query 参数名避让 FastAPI
    的 status）；缺省不过滤。progress 用嵌套对象 {done, total, current_item}——
    避免与分页契约的 total（行数）命名冲突。
    """
    page = max(1, page)
    page_size = clamp_pagination_limit(page_size)
    offset = (page - 1) * page_size
    latest = _latest_row_where()
    params: list = []
    status_clause = ""
    if status_filter and status_filter in ("RUNNING", "QUEUED", "SUCCEEDED", "FAILED"):
        status_clause = " AND qbt.status=?"
        params.append(status_filter)
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) c FROM question_bank_task qbt WHERE" + latest + status_clause,
        params,
    ).fetchone()["c"]
    rows = conn.execute(
        "SELECT qbt.task_id, qbt.position_id, p.name AS position_name, qbt.model_id,"
        " qbt.model_version, qbt.status, qbt.total, qbt.done, qbt.current_item,"
        " qbt.error_msg, qbt.created_at, qbt.started_at, qbt.finished_at"
        " FROM question_bank_task qbt JOIN position p ON p.position_id=qbt.position_id"
        " WHERE" + latest + status_clause +
        " ORDER BY qbt.created_at DESC, qbt.rowid DESC LIMIT ? OFFSET ?",
        (*params, page_size, offset),
    ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["question_count"] = _question_count(conn, d["position_id"], d["model_id"])
        d["progress"] = {"done": d.pop("done"), "total": d.pop("total"),
                         "current_item": d.pop("current_item")}
        items.append(d)
    conn.close()
    return {"items": items, "total": total}


def _load_task(conn, task_id: str):
    row = conn.execute(
        "SELECT task_id, position_id, model_id, model_version, status, error_msg,"
        " total, done, current_item, created_at, started_at, finished_at"
        " FROM question_bank_task WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return row


def _load_traces(conn, task) -> list[dict]:
    """llm_trace 时间窗调用列表（§9.5：不改表，按时间窗 + call_type + item 集关联）。

    窗口 [created_at, finished_at]（RUNNING/未终态行右端点取「至今」now_iso）；
    ref_id 限定该模型 competency_item 集（question_gen 的 ref_id=item_id）。
    """
    window_end = task["finished_at"] or now_iso()
    item_ids = [r["item_id"] for r in conn.execute(
        "SELECT item_id FROM competency_item WHERE model_id=?", (task["model_id"],)
    ).fetchall()]
    if not item_ids:
        return []
    marks = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"SELECT trace_id, ref_id, attempt, prompt, response, success, error, created_at"
        f" FROM llm_trace WHERE call_type='question_gen' AND ref_id IN ({marks})"
        " AND created_at >= ? AND created_at <= ? ORDER BY created_at, attempt",
        (*item_ids, task["created_at"], window_end),
    ).fetchall()
    return [dict(r) for r in rows]


def _coverage_matrix(conn, position_id: str, model_id: str) -> list[dict]:
    """item × difficulty 覆盖统计（§9.5）：该模型 active 题按 std_name×difficulty 计数。

    行 = std_name（附 category），列 = easy/medium/hard。
    """
    rows = conn.execute(
        "SELECT std_name, category, difficulty, COUNT(*) c FROM question_bank"
        " WHERE status='active' AND model_id=? AND position_id=?"
        " GROUP BY std_name, category, difficulty",
        (model_id, position_id),
    ).fetchall()
    matrix: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["std_name"], r["category"])
        if key not in matrix:
            matrix[key] = {"std_name": r["std_name"], "category": r["category"],
                           "easy": 0, "medium": 0, "hard": 0}
        if r["difficulty"] in ("easy", "medium", "hard"):
            matrix[key][r["difficulty"]] = r["c"]
    return list(matrix.values())


@router.get("/{task_id}")
def get_question_bank_task(task_id: str) -> dict:
    """单任务详情（§9.5）：全字段（progress 嵌套）+ 历史任务行 + llm_trace 时间窗 + 覆盖统计。"""
    conn = get_conn()
    task = _load_task(conn, task_id)
    history = [dict(r) for r in conn.execute(
        "SELECT task_id, status, error_msg, total, done, current_item,"
        " created_at, started_at, finished_at"
        " FROM question_bank_task WHERE position_id=? AND model_id=?"
        " ORDER BY created_at DESC, rowid DESC",
        (task["position_id"], task["model_id"]),
    ).fetchall()]
    traces = _load_traces(conn, task)
    coverage = _coverage_matrix(conn, task["position_id"], task["model_id"])
    conn.close()
    d = dict(task)
    d["progress"] = {"done": d.pop("done"), "total": d.pop("total"),
                     "current_item": d.pop("current_item")}
    return {"task": d, "history": history, "traces": traces, "coverage": coverage}


@router.get("/{task_id}/questions")
def list_question_bank_task_questions(task_id: str, page: int = 1,
                                      page_size: int = 20) -> dict:
    """该 (position, model) 题目表分页（§9.5）：std_name/category/difficulty/qtype/stem 预览。

    题库单元 = 岗位 + 模型版本；task 行必有 position/model 两列（建行口径），无模型
    一说不可达，仍保留缺失防御。
    """
    page = max(1, page)
    page_size = clamp_pagination_limit(page_size)
    offset = (page - 1) * page_size
    conn = get_conn()
    task = _load_task(conn, task_id)
    total = conn.execute(
        "SELECT COUNT(*) c FROM question_bank WHERE status='active'"
        " AND model_id=? AND position_id=?",
        (task["model_id"], task["position_id"]),
    ).fetchone()["c"]
    rows = conn.execute(
        f"SELECT question_id, std_name, category, difficulty, qtype,"
        f" substr(stem,1,{_STEM_PREVIEW}) AS stem_preview"
        " FROM question_bank WHERE status='active' AND model_id=? AND position_id=?"
        " ORDER BY std_name, difficulty LIMIT ? OFFSET ?",
        (task["model_id"], task["position_id"], page_size, offset),
    ).fetchall()
    conn.close()
    return {"items": [dict(r) for r in rows], "total": total}
