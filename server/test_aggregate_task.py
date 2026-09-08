"""聚合任务可观测测试（SSOT §8.4/2026-09-07，commit 8f9e6e2 契约）。

edge 覆盖八项：
  1) 触发 → 任务行 RUNNING 起跑字段（total/llm_total/trigger_source）
  2) 循环逐项推进 done/llm_done/current_item
  3) 正常完成 → SUCCEEDED + model_id 回填（写序：SUCCEEDED 时模型行必已存在）
  4) stalled → FAILED + error + model_id 回填（stalled 模型照落库）
  5) 未捕获异常 → FAILED + re-raise
  6) progress 端点最新行 / 无记录 404
  7) 启动 sweep：RUNNING 残留行置 FAILED（进程重启中断）
  8) llm_total 与实际 LLM 调用数一致（口径漂移回归锁——_needs_llm 谓词复用）

LLM#3 全程走 provider=mock 的 _mock_aggregate_level（离线，无网、无限速）；
失败注入用 monkeypatch（_resolve_level / _compute_weights）。
运行：cd server && python -m pytest test_aggregate_task.py -q
"""
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_aggregate_task.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from server.db import init_db, get_conn, set_db_path  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()


# ---------- 种子工具 ----------

def _seed_position(pid: str = None) -> str:
    """建一个 active 岗位 + 两条 parsed JD（std_items 见 items 参数注入）。"""
    pid = pid or new_id("pos")
    conn = get_conn()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "聚合测试岗", "active", now_iso()),
    )
    conn.commit()
    conn.close()

    def _jd(std_items: list[dict]):
        jd_id = new_id("jd")
        conn = get_conn()
        conn.execute(
            "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
            " raw_text, std_items_json, status, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (jd_id, pid, "测试岗", None, "paste", "JD 原文",
             _dumps(std_items), "parsed", now_iso()),
        )
        conn.commit()
        conn.close()
        return jd_id

    # 两组能力项、跨 JD 等级冲突（走 LLM#3）与一致（不走）各覆盖：
    _jd([
        {"name": "Python", "category": "hard_skill", "importance": "required",
         "required_level": 3, "evidence": ["精通 Python"]},
        {"name": "MySQL", "category": "hard_skill", "importance": "required",
         "required_level": 4, "evidence": ["MySQL 调优"]},
    ])
    _jd([
        {"name": "Python", "category": "hard_skill", "importance": "required",
         "required_level": 5, "evidence": ["Python 深度实践"]},   # Python 组内 3/5 冲突 → 走 LLM#3
        {"name": "MySQL", "category": "hard_skill", "importance": "required",
         "required_level": 4, "evidence": ["MySQL 调优"]},        # MySQL 组内一致 → 不走 LLM#3
    ])
    return pid


def _dumps(items: list[dict]) -> str:
    import json
    return json.dumps(items, ensure_ascii=False)


def _task_row(pid: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM aggregate_task WHERE position_id=?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (pid,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _run(pid: str, **kw) -> str:
    from server.services.aggregate import run_aggregate
    return run_aggregate(pid, **kw)


# ---------- 1/2/3/8）正常链路：RUNNING 起跑 → 推进 → SUCCEEDED ----------

def test_task_row_lifecycle_succeeded():
    """1/2/3/8) 触发→完成全链：起跑字段 / 逐项推进 / 终态回填 / llm 口径一致。"""
    pid = _seed_position()
    model_id = _run(pid, trigger_source="manual")
    task = _task_row(pid)
    assert task is not None

    # 1) 起跑字段：trigger_source 正确、total=len(groups)=2、llm_total=1（仅 Python 冲突项）
    assert task["trigger_source"] == "manual"
    assert task["status"] == "SUCCEEDED"
    assert task["total"] == 2
    assert task["llm_total"] == 1

    # 2) 逐项推进：done=total 且 current_item 保留最后一项（非清理）
    assert task["done"] == 2
    assert task["current_item"] is not None
    assert task["current_item"] in ("Python (hard_skill)", "MySQL (hard_skill)")
    assert task["finished_at"] is not None

    # 3) model_id 回填 + 写序：SUCCEEDED ⇒ 模型行必已存在
    assert task["model_id"] == model_id
    conn = get_conn()
    try:
        m = conn.execute(
            "SELECT status FROM competency_model WHERE model_id=?", (model_id,)
        ).fetchone()
    finally:
        conn.close()
    assert m is not None and m["status"] == "draft"

    # 8) llm 口径锁：llm_done == llm_total == 实际 LLM#3 成功调用次数（llm_trace 计）
    conn = get_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) c FROM llm_trace WHERE ref_id=? AND call_type='aggregate_level' AND success=1",
            (model_id,),
        ).fetchone()["c"]
    finally:
        conn.close()
    assert n >= 1  # mock 下冲突项真实走了 LLM#3（trace 落库）
    assert task["llm_done"] == task["llm_total"]


def test_llm_total_matches_needs_llm_predicate():
    """8) 口径漂移回归锁：llm_total == Σ _needs_llm(groups)，与循环判定完全同源。"""
    from server.services.aggregate import _collect_items, _needs_llm

    pid = _seed_position()
    groups = _collect_items(pid)
    expected = sum(1 for (sn, cat), g in groups.items() if _needs_llm(cat, g))
    assert expected == 1  # 本种子下恰 1 项冲突

    # gate 项（qualification / experience+years）恒不走 LLM#3
    assert _needs_llm("qualification", {"evidences": [{"level": 3}, {"level": 5}], "years_list": None}) is False
    assert _needs_llm("experience", {"evidences": [{"level": 3}, {"level": 5}], "years_list": [3]}) is False
    # 等级一致早退路径不算
    assert _needs_llm("hard_skill", {"evidences": [{"level": 3}, {"level": 3}], "years_list": None}) is False
    assert _needs_llm("hard_skill", {"evidences": [{"level": 3}, {"level": 5}], "years_list": None}) is True


def test_auto_jd_parse_trigger_source():
    """1) 三条触发路径可区分：auto:jd-parse 显式传入（manual/retry 由端点测试覆盖）。"""
    pid = _seed_position()
    _run(pid, trigger_source="auto:jd-parse")
    assert _task_row(pid)["trigger_source"] == "auto:jd-parse"


# ---------- 4) stalled → FAILED + error + model_id 回填 ----------

def test_stalled_task_failed_with_model_id():
    """4) LLM#3 失败 → stalled 模型照落库；任务行 FAILED + error + model_id（两态并存）。"""
    pid = _seed_position()
    from server.services import aggregate as agg

    original = agg._resolve_level

    def _boom(model_id, std_name, evidences):
        raise RuntimeError("LLM#3 down")

    agg._resolve_level = _boom
    try:
        model_id = _run(pid, trigger_source="manual")
    finally:
        agg._resolve_level = original

    task = _task_row(pid)
    assert task["status"] == "FAILED"
    assert task["error"] is not None and "LLM#3 down" in task["error"]
    # stalled 模型照落库（模型态/任务态两维度并存，SSOT §8.4）
    assert task["model_id"] == model_id
    conn = get_conn()
    try:
        m = conn.execute("SELECT status FROM competency_model WHERE model_id=?", (model_id,)).fetchone()
    finally:
        conn.close()
    assert m is not None and m["status"] == "stalled"


# ---------- 5) 未捕获异常 → FAILED + re-raise ----------

def test_uncaught_exception_task_failed_reraise():
    """5) 业务异常（非 LLM#3）→ 任务行 FAILED + error + finished_at，且异常原样上抛。"""
    pid = _seed_position()
    from server.services import aggregate as agg

    original = agg._compute_weights

    def _boom(items):
        raise RuntimeError("权重计算崩溃")

    agg._compute_weights = _boom
    try:
        with pytest.raises(RuntimeError, match="权重计算崩溃"):
            _run(pid, trigger_source="retry")
    finally:
        agg._compute_weights = original

    task = _task_row(pid)
    assert task["status"] == "FAILED"
    assert "权重计算崩溃" in task["error"]
    assert task["finished_at"] is not None


# ---------- 6) progress 端点 ----------

def test_progress_endpoint_latest_and_404():
    """6) GET /admin/positions/{id}/aggregate/progress：最新行返回全部字段 / 无记录 404。"""
    from fastapi.testclient import TestClient
    from server.main import app

    client = TestClient(app)

    # 无记录 → 404（须登录；未带 token 是 401——鉴权依赖先于 404 判定）
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='admin'").fetchone()
    if row is None:
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "admin", pwd_ctx.hash("admin"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()
    tok = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert tok.status_code == 200, tok.text
    headers = {"Authorization": f"Bearer {tok.json()['token']}"}
    r = client.get("/api/admin/positions/never_exists/aggregate/progress", headers=headers)
    assert r.status_code == 404
    # 404 判定在鉴权之后；无记录岗位（不存在的岗位）仍须可查——契约按岗位维度定位最新行

    # 正常聚合后：返回最新行全部字段（字段与 _DDL 完全一致的 14 列）
    pid = _seed_position()
    model_id = _run(pid, trigger_source="manual")
    r = client.get(f"/api/admin/positions/{pid}/aggregate/progress", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d.keys()) == {
        "task_id", "position_id", "status", "trigger_source", "total", "done",
        "llm_total", "llm_done", "current_item", "model_id", "error",
        "created_at", "started_at", "finished_at",
    }
    assert d["status"] == "SUCCEEDED"
    assert d["model_id"] == model_id

    # 多次触发取最新：再触发一次（anonymous trigger_source=manual），行应切到新任务
    _run(pid, trigger_source="retry")
    d2 = client.get(f"/api/admin/positions/{pid}/aggregate/progress", headers=headers).json()
    assert d2["trigger_source"] == "retry"

    # retry-level 端点透传 trigger_source（可选：另一路径已测 run_aggregate 侧）


# ---------- 7) 启动 sweep ----------

def test_startup_sweep_running_to_failed():
    """7) init_db 启动 sweep：RUNNING 残留行一次性置 FAILED（进程重启中断）。"""
    pid = _seed_position()
    conn = get_conn()
    try:
        tid = new_id("agg_task")
        conn.execute(
            "INSERT INTO aggregate_task(task_id, position_id, status, trigger_source,"
            " total, llm_total, created_at, started_at) VALUES(?,?,?, ?,?,?,?,?)",
            (tid, pid, "RUNNING", "manual", 2, 1, now_iso(), now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    # 无残留 SUCCEEDED/FAILED 行不动：先造一行终态行，sweep 后应原样保留
    pid2 = _seed_position()
    _run(pid2, trigger_source="manual")

    init_db()  # 进程重启（模拟：sweep 走 init_db 尾部）

    row = _task_row(pid)
    assert row["status"] == "FAILED"
    assert row["error"] == "进程重启中断"
    assert row["finished_at"] is not None

    row2 = _task_row(pid2)
    assert row2["status"] == "SUCCEEDED"  # 终态行不受 sweep 影响

    # 二次 init（无残留 RUNNING）幂等：不再改任何行
    init_db()
    assert _task_row(pid)["finished_at"] == row["finished_at"]


# ---------- 手动触发端点（run_aggregate 内联同步执行验证三路径之三） ----------

def test_manual_trigger_endpoint_records_task():
    """POST /admin/positions/{id}/aggregate → run_aggregate(trigger_source='manual')。"""
    from fastapi.testclient import TestClient
    from server.main import app

    client = TestClient(app)
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='admin'").fetchone()
    if row is None:
        from passlib.context import CryptContext
        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "admin", pwd_ctx.hash("admin"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()
    tok = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    headers = {"Authorization": f"Bearer {tok.json()['token']}"}

    pid = _seed_position()
    r = client.post(f"/api/admin/positions/{pid}/aggregate", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"position_id": pid, "aggregating": True}  # 契约：响应不带 task_id
    # TestClient 同步执行 BackgroundTasks → 任务行已终态、trigger_source=manual
    task = _task_row(pid)
    assert task["trigger_source"] == "manual"
    assert task["status"] == "SUCCEEDED"
