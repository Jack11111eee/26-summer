"""LLM trace 查看器（P8 测试中心 tab）：按条件检索调用留痕。"""
from fastapi import APIRouter, Depends, HTTPException

from ...core.security import require_admin
from ...db import get_conn

router = APIRouter(prefix="/api/admin/trace", tags=["trace"], dependencies=[Depends(require_admin)])

_PREVIEW = 120  # 列表页 prompt/response 预览长度


@router.get("/list")
def list_traces(
    call_type: str | None = None,
    ref_id: str | None = None,
    success: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """按筛选条件列出 trace（prompt/response 只给预览）。"""
    where, params = [], []
    if call_type:
        where.append("call_type=?")
        params.append(call_type)
    if ref_id:
        where.append("ref_id=?")
        params.append(ref_id)
    if success is not None:
        where.append("success=?")
        params.append(1 if success else 0)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    conn = get_conn()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM llm_trace{clause}", params).fetchone()["c"]
    rows = conn.execute(
        f"SELECT trace_id, call_type, ref_id, attempt, success, created_at,"
        f" substr(prompt,1,{_PREVIEW}) AS prompt_preview,"
        f" substr(response,1,{_PREVIEW}) AS response_preview"
        f" FROM llm_trace{clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    traces = [dict(r) for r in rows]
    for t in traces:
        t["success"] = bool(t["success"])
    return {"traces": traces, "total": total}


@router.get("/by-session/{session_id}")
def get_session_traces(session_id: str) -> list[dict]:
    """取一条测评会话的全部 trace：ref_id 可能是 session_id / question_id / report 相关 id。"""
    conn = get_conn()
    q_ids = [r["question_id"] for r in conn.execute(
        "SELECT question_id FROM assessment_question WHERE session_id=?", (session_id,)
    ).fetchall()]
    ids = [session_id, *q_ids]
    marks = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT trace_id, call_type, ref_id, attempt, success, created_at"
        f" FROM llm_trace WHERE ref_id IN ({marks}) ORDER BY created_at",
        ids,
    ).fetchall()
    out = [dict(r) for r in rows]
    for t in out:
        t["success"] = bool(t["success"])
    return out


@router.get("/{trace_id}")
def get_trace(trace_id: str) -> dict:
    """单条 trace 完整内容（prompt + response）。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM llm_trace WHERE trace_id=?", (trace_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "trace 不存在")
    d = dict(row)
    d["success"] = bool(d["success"])
    return d
