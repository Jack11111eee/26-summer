"""评测运行器（P8 测试中心 tab）：触发一致性/虚拟考生测试，异步执行 + 轮询结果。"""
import json
import sys
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from ...core.security import require_admin
from ...db import get_conn
from ...services.pipeline import new_id, now_iso

# eval/ 在仓库根，不在 server 包内，动态加路径
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

router = APIRouter(prefix="/api/admin/eval", tags=["eval"], dependencies=[Depends(require_admin)])


def _save_result(task_id: str, test_name: str, status: str, result: dict | None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO eval_results(task_id, test_name, status, result_json, created_at, completed_at)"
        " VALUES(?,?,?,?,?,?)",
        (
            task_id, test_name, status,
            json.dumps(result, ensure_ascii=False) if result else None,
            now_iso(), now_iso() if status != "running" else None,
        ),
    )
    conn.commit()


def _run(task_id: str, test_name: str, fn, *args) -> None:
    """后台执行评测，异常落 failed。"""
    try:
        result = fn(*args)
        _save_result(task_id, test_name, "completed", result)
    except Exception as e:  # noqa: BLE001 - 评测失败也要留痕
        _save_result(task_id, test_name, "failed", {"error": str(e)})


class _ConsistencyBody(BaseModel):
    session_id: str
    runs: int = 3


@router.post("/consistency")
def run_consistency(body: _ConsistencyBody, background_tasks: BackgroundTasks) -> dict:
    """触发评分一致性测试（异步）。"""
    from eval.consistency_test import test_scoring_consistency

    task_id = new_id("ev")
    _save_result(task_id, "scoring_consistency", "running", None)
    background_tasks.add_task(_run, task_id, "scoring_consistency",
                              test_scoring_consistency, body.session_id, body.runs)
    return {"task_id": task_id, "status": "running"}


class _VirtualBody(BaseModel):
    position_id: str


@router.post("/virtual-candidates")
def run_virtual(body: _VirtualBody, background_tasks: BackgroundTasks) -> dict:
    """触发虚拟考生三档测试（异步）。"""
    from eval.virtual_candidates import test_virtual_candidates

    task_id = new_id("ev")
    _save_result(task_id, "virtual_candidates", "running", None)
    background_tasks.add_task(_run, task_id, "virtual_candidates",
                              test_virtual_candidates, body.position_id)
    return {"task_id": task_id, "status": "running"}


@router.get("/results/{task_id}")
def get_result(task_id: str) -> dict:
    """轮询评测结果。"""
    conn = get_conn()
    row = conn.execute(
        "SELECT task_id, test_name, status, result_json, created_at, completed_at"
        " FROM eval_results WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "评测任务不存在")
    d = dict(row)
    d["result"] = json.loads(d.pop("result_json")) if d.get("result_json") else None
    return d


@router.get("/history")
def list_history(limit: int = 20) -> list[dict]:
    """评测历史列表。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT task_id, test_name, status, created_at, completed_at"
        " FROM eval_results ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
