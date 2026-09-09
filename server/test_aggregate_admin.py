"""聚合管理页与重复触发收敛测试（SSOT §8.4 行为增补 / §8.6，2026-09-08）。

覆盖五组：
  1) run_aggregate 入口并发守卫：同岗位 RUNNING 行存在时静默跳过（None，无新任务行/新版本）
  2) pipeline 收尾触发：同岗位仍有 imported/parsing JD 时尾部不触发；清空后触发（最后一根稻草）
  3) POST /aggregate 与 retry-level 的 409 守卫（retry-level 守卫先于删除 stalled 模型）
  4) GET /admin/aggregate-tasks 列表端点契约：行源 / 字段 / summary / 筛选 / 分页
  5) model_status 筛选与「最新模型」ORDER BY 口径对齐（stalled>draft>confirmed 先分组再版本）

LLM#3 全程 mock（离线）；TestClient 同步执行 BackgroundTasks。
运行：cd server && python -m pytest test_aggregate_admin.py -q
"""
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_aggregate_admin.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()


# ---------- 种子工具 ----------

def _seed_position(pid: str = None, name: str = "聚合管理页测试岗") -> str:
    pid = pid or new_id("pos")
    conn = get_conn()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, name, "active", now_iso()),
    )
    conn.commit()
    conn.close()
    return pid


def _seed_parsed_jd(pid: str, std_items: list[dict] | None = None,
                    job_title: str = "测试岗") -> str:
    jd_id = new_id("jd")
    if std_items is None:
        std_items = [
            {"name": "Python", "category": "hard_skill", "importance": "required",
             "required_level": 3, "evidence": ["精通 Python"]},
        ]
    if job_title is None:
        # None = 用调用方岗位名（reparse 归岗 assign_position 命中既有岗位）
        conn = get_conn()
        job_title = conn.execute(
            "SELECT name FROM position WHERE position_id=?", (pid,)
        ).fetchone()["name"]
        conn.close()
    conn = get_conn()
    conn.execute(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, std_items_json, status, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (jd_id, pid, job_title, None, "paste", "JD 原文",
         json.dumps(std_items, ensure_ascii=False), "parsed", now_iso()),
    )
    conn.commit()
    conn.close()
    return jd_id


def _seed_unparsed_jd(pid: str, status: str = "imported") -> str:
    jd_id = new_id("jd")
    conn = get_conn()
    conn.execute(
        "INSERT INTO jd_record(jd_id, position_id, job_title, company, source_type,"
        " raw_text, status, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (jd_id, pid, "测试岗", None, "paste", "JD 原文", status, now_iso()),
    )
    conn.commit()
    conn.close()
    return jd_id


def _run(pid: str, **kw):
    from server.services.aggregate import run_aggregate
    return run_aggregate(pid, **kw)


def _running_rows(pid: str) -> int:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM aggregate_task WHERE position_id=? AND status='RUNNING'",
            (pid,),
        ).fetchone()["c"]
    finally:
        conn.close()


def _task_count(pid: str) -> int:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM aggregate_task WHERE position_id=?", (pid,)
        ).fetchone()["c"]
    finally:
        conn.close()


def _model_count(pid: str) -> int:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM competency_model WHERE position_id=?", (pid,)
        ).fetchone()["c"]
    finally:
        conn.close()


def _insert_running_task(pid: str, trigger: str = "manual") -> str:
    """手工插一行 RUNNING 任务行（模拟在途聚合——不实际跑 run_aggregate）。"""
    tid = new_id("agg_task")
    conn = get_conn()
    conn.execute(
        "INSERT INTO aggregate_task(task_id, position_id, status, trigger_source,"
        " total, llm_total, created_at, started_at) VALUES(?,?,?,?,?,?,?,?)",
        (tid, pid, "RUNNING", trigger, 5, 3, now_iso(), now_iso()),
    )
    conn.commit()
    conn.close()
    return tid


def _client_and_login():
    from server.main import app
    client = TestClient(app, raise_server_exceptions=False)
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
    return client, {"Authorization": f"Bearer {tok.json()['token']}"}


# ---------- 1) 入口并发守卫 ----------

def test_entry_guard_skips_when_running():
    """守卫命中：RUNNING 行存在 → run_aggregate 返回 None、不新增任务行/模型行。"""
    pid = _seed_position()
    _seed_parsed_jd(pid)
    _insert_running_task(pid)  # 模拟在途聚合

    before_tasks, before_models = _task_count(pid), _model_count(pid)
    result = _run(pid, trigger_source="auto:jd-parse")
    assert result is None                      # 静默跳过
    assert _task_count(pid) == before_tasks    # 无新任务行
    assert _model_count(pid) == before_models  # 无新版本


def test_entry_guard_passes_when_no_running():
    """守卫放行：无 RUNNING 行（含 FAILED/SUCCEEDED 终态行在场）→ 照常聚合。"""
    pid = _seed_position()
    _seed_parsed_jd(pid)
    # 先跑一轮成功（终态 SUCCEEDED 行在场）
    mid = _run(pid, trigger_source="manual")
    assert mid is not None
    assert _task_count(pid) == 1
    # 再跑一轮：终态行不触发守卫
    mid2 = _run(pid, trigger_source="retry")
    assert mid2 is not None and mid2 != mid
    assert _task_count(pid) == 2
    assert _running_rows(pid) == 0


# ---------- 2) 收尾触发 ----------

def test_pipeline_tail_defers_while_sibling_unparsed():
    """同岗位仍有 imported JD → 尾部自动触发跳过（run_parse_pipeline 全链）。"""
    from server.services.pipeline import run_parse_pipeline

    pid = _seed_position(name="收尾触发测试岗A")
    jd_parsed = _seed_parsed_jd(pid)      # 已解析（前一条）
    _seed_unparsed_jd(pid, "imported")    # 批内另一条未解析

    # reparse 已解析条：解析完成后岗位仍有 imported → 不触发聚合
    run_parse_pipeline(jd_parsed)
    assert _task_count(pid) == 0          # 未产生任何聚合任务行
    assert _model_count(pid) == 0


def test_pipeline_tail_fires_when_last_parsed(monkeypatch):
    """批内最后一条解析完成（无 imported/parsing 残留）→ 触发一次自动聚合。"""
    pid = _seed_position(name="收尾触发测试岗B")
    # job_title=None → 用岗名（reparse 归岗 assign_position 命中本岗，不会漂走）
    jd_last = _seed_parsed_jd(pid, job_title=None)

    from server.services.pipeline import run_parse_pipeline
    run_parse_pipeline(jd_last)
    assert _task_count(pid) >= 1  # 解析完成且无 imported/parsing → 自动聚合触发
    assert _model_count(pid) >= 1


def test_pipeline_tail_pending_review_never_fires():
    """pending_review 岗位不聚合（既有规则）：守卫与收尾触发都不改变该边界。"""
    pid = _seed_position(name="待审岗")
    conn = get_conn()
    conn.execute("UPDATE position SET status='pending_review' WHERE position_id=?", (pid,))
    conn.commit()
    conn.close()
    jd = _seed_parsed_jd(pid)
    from server.services.pipeline import run_parse_pipeline
    run_parse_pipeline(jd)
    assert _task_count(pid) == 0
    assert _model_count(pid) == 0


# ---------- 3) 主动触发端点 409 守卫 ----------

def test_manual_trigger_endpoint_409_when_running():
    """POST /aggregate 命中同岗位 RUNNING 行 → 409，且不新增任务行。"""
    client, headers = _client_and_login()
    pid = _seed_position(name="手动触发守卫岗")
    _seed_parsed_jd(pid)
    _insert_running_task(pid)

    r = client.post(f"/api/admin/positions/{pid}/aggregate", headers=headers)
    assert r.status_code == 409
    assert "聚合进行中" in r.json()["detail"]
    assert _task_count(pid) == 1  # 仅手工插入的那行，端点未触发新任务


def test_retry_level_409_before_deleting_stalled_model():
    """retry-level 409 守卫先于删除：RUNNING 在场时 stalled 模型必须原样保留。"""
    client, headers = _client_and_login()
    pid = _seed_position(name="重试守卫岗")
    _seed_parsed_jd(pid)

    # 造一个 stalled 模型（直接落行，语义与 run_aggregate stalled 产物一致）
    mid = new_id("cm")
    conn = get_conn()
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "stalled", json.dumps({"position_id": pid, "items": []}), now_iso()),
    )
    conn.commit()
    conn.close()
    _insert_running_task(pid)

    r = client.post(f"/api/admin/positions/{pid}/retry-level",
                    json={"action": "retry"}, headers=headers)
    assert r.status_code == 409
    assert "聚合进行中" in r.json()["detail"]
    # 守卫先于删除：stalled 模型仍在
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) c FROM competency_model WHERE model_id=?", (mid,)).fetchone()["c"]
    conn.close()
    assert n == 1


# ---------- 4) 列表端点契约 ----------

def test_list_endpoint_contract():
    """/admin/aggregate-tasks：行源（有模型或有任务行）/ 字段 / summary / 分页。"""
    client, headers = _client_and_login()

    # a) 首聚进行中：只有 RUNNING 任务行、无模型 → 入列，进度字段可读
    pid_running = _seed_position(name="进行中岗")
    _seed_parsed_jd(pid_running)
    tid = _insert_running_task(pid_running)

    # b) 有 draft 模型 + 有 SUCCEEDED 任务行
    pid_draft = _seed_position(name="草稿岗ZZ")
    _seed_parsed_jd(pid_draft)
    _run(pid_draft, trigger_source="manual")  # SUCCEEDED 任务行 + draft 模型

    # c) 有 confirmed 模型的岗位
    pid_conf = _seed_position(name="已确认岗YY")
    _seed_parsed_jd(pid_conf)
    mid = _run(pid_conf, trigger_source="manual")
    conn = get_conn()
    conn.execute("UPDATE competency_model SET status='confirmed', confirmed_by=NULL, confirmed_at=?"
                 " WHERE model_id=?", (now_iso(), mid))
    conn.commit()
    conn.close()

    # d) 什么都没有的 active 岗位 → 不入列
    _seed_position(name="空岗XX")

    r = client.get("/api/admin/aggregate-tasks", headers=headers,
                   params={"page": 1, "page_size": 10})
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d.keys()) == {"items", "total", "summary"}

    row_running = next((x for x in d["items"] if x["position_id"] == pid_running), None)
    assert row_running is not None, "首聚进行中（无模型有任务行）岗位须入列"
    assert row_running["model"] is None
    assert row_running["task"]["status"] == "RUNNING"
    assert row_running["task"]["task_id"] == tid
    assert set(row_running["task"]["progress"].keys()) == {"done", "total", "llm_done", "llm_total", "current_item"}
    assert row_running["jd_count"] >= 1

    row_draft = next((x for x in d["items"] if x["position_id"] == pid_draft), None)
    assert row_draft is not None
    assert row_draft["model"]["status"] == "draft"
    assert row_draft["model"]["version"] == 1
    assert row_draft["task"]["status"] == "SUCCEEDED"
    assert (row_draft["model"] is None) is False

    row_conf = next((x for x in d["items"] if x["position_id"] == pid_conf), None)
    assert row_conf is not None and row_conf["model"]["status"] == "confirmed"

    # 空岗（无模型无任务行）不在列表
    assert all("空岗" not in (x["position_name"] or "") for x in d["items"])

    # summary：计数为全库口径（≥ 本测试库的构造数）
    assert d["summary"]["draft_positions"] >= 1
    assert d["summary"]["confirmed_positions"] >= 1
    assert d["summary"]["running_tasks"] >= 1

    # 分页：page_size=1 时两页合计 == total
    r1 = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"page": 1, "page_size": 1}).json()
    assert len(r1["items"]) == 1
    assert r1["total"] == d["total"]

    # 筛选：model_status=draft 只剩草稿岗（进行中岗 model=None 排除）
    rd = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"model_status": "draft", "page_size": 50}).json()
    assert all(x["model"] and x["model"]["status"] == "draft" for x in rd["items"])
    assert any(x["position_id"] == pid_draft for x in rd["items"])
    assert not any(x["position_id"] == pid_running for x in rd["items"])

    # 筛选：task_status=RUNNING 只剩进行中岗
    rr = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"task_status": "RUNNING", "page_size": 50}).json()
    assert all(x["task"] and x["task"]["status"] == "RUNNING" for x in rr["items"])
    assert any(x["position_id"] == pid_running for x in rr["items"])

    # 筛选：q 岗位名子串
    rq = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"q": "岗YY", "page_size": 50}).json()
    assert [x["position_id"] for x in rq["items"]] == [pid_conf]


def test_list_endpoint_latest_model_order():
    """最新模型优先序：stalled v1 + draft v2 → 行内 model.status=stalled（filter 同口径）。"""
    client, headers = _client_and_login()
    pid = _seed_position(name="优先序岗WW")
    _seed_parsed_jd(pid)

    conn = get_conn()
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("cm"), pid, 1, "stalled", json.dumps({"items": []}), now_iso()))
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (new_id("cm"), pid, 2, "draft", json.dumps({"items": []}), now_iso()))
    conn.commit()
    conn.close()

    r = client.get("/api/admin/aggregate-tasks", headers=headers,
                   params={"q": "优先序岗WW"}).json()
    row = next((x for x in r["items"] if x["position_id"] == pid), None)
    assert row is not None
    assert row["model"]["status"] == "stalled"   # stalled > draft（先分组再版本）
    assert row["model"]["version"] == 1

    # model_status=stalled 筛选命中；=draft 筛选不命中（draft v2 非最新）
    rs = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"q": "优先序岗WW", "model_status": "stalled"}).json()
    assert any(x["position_id"] == pid for x in rs["items"])
    rdf = client.get("/api/admin/aggregate-tasks", headers=headers,
                     params={"q": "优先序岗WW", "model_status": "draft"}).json()
    assert not any(x["position_id"] == pid for x in rdf["items"])


def test_list_endpoint_superseded_draft_shadow():
    """死草稿遮蔽（2026-09-09 修正口径）：被 confirm 取代的旧 draft 行不夺取
    「最新模型」资格——行内/筛选/summary 三处均按 confirmed 计（修前真实库形态：
    KPI 6 个已确认岗位、筛选 confirmed 命中 0）。变体：新草稿（版本高于最新
    confirmed）照常压过 confirmed 入草稿侧。
    """
    client, headers = _client_and_login()
    # 岗 1：v1 draft → v2 confirm（confirm 不动旧草稿行 → v1 成死草稿）
    pid_dead = _seed_position(name="死草稿遮蔽岗DD")
    _seed_parsed_jd(pid_dead)
    # 岗 2：v1 draft → v2 confirm → v3 新聚合（新草稿）
    pid_new = _seed_position(name="新草稿压过岗NN")
    _seed_parsed_jd(pid_new)

    conn = get_conn()
    for pid, rows in [(pid_dead, [(1, "draft"), (2, "confirmed")]),
                      (pid_new, [(1, "draft"), (2, "confirmed"), (3, "draft")])]:
        for version, status_val in rows:
            conn.execute(
                "INSERT INTO competency_model(model_id, position_id, version, status,"
                " model_json, created_at) VALUES(?,?,?,?,?,?)",
                (new_id("cm"), pid, version, status_val,
                 json.dumps({"items": []}), now_iso()))
    conn.commit()
    conn.close()

    # 行内取数：死草稿岗显示 confirmed v2；新草稿岗显示 draft v3
    r = client.get("/api/admin/aggregate-tasks", headers=headers,
                   params={"q": "DD", "page_size": 50}).json()
    row_dead = next((x for x in r["items"] if x["position_id"] == pid_dead), None)
    assert row_dead is not None
    assert row_dead["model"]["status"] == "confirmed"
    assert row_dead["model"]["version"] == 2

    r = client.get("/api/admin/aggregate-tasks", headers=headers,
                   params={"q": "NN", "page_size": 50}).json()
    row_new = next((x for x in r["items"] if x["position_id"] == pid_new), None)
    assert row_new is not None
    assert row_new["model"]["status"] == "draft"
    assert row_new["model"]["version"] == 3

    # 筛选：confirmed 命中死草稿岗（本 bug 修前命中 0）；draft 不命中死草稿岗
    rc = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"q": "DD", "model_status": "confirmed", "page_size": 50}).json()
    assert any(x["position_id"] == pid_dead for x in rc["items"])
    rd = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"q": "DD", "model_status": "draft", "page_size": 50}).json()
    assert not any(x["position_id"] == pid_dead for x in rd["items"])
    # 新草稿岗（v3 > 最新 confirmed v2）在 draft 筛选命中——压过 confirmed 不回落
    rn = client.get("/api/admin/aggregate-tasks", headers=headers,
                    params={"q": "NN", "model_status": "draft", "page_size": 50}).json()
    assert any(x["position_id"] == pid_new for x in rn["items"])

    # summary 与筛选口径互为镜像：无 q 时 total == summary 对应计数（修前两口径打架）
    for st, key in [("confirmed", "confirmed_positions"), ("draft", "draft_positions")]:
        cur = client.get("/api/admin/aggregate-tasks", headers=headers,
                         params={"model_status": st, "page_size": 200}).json()
        assert cur["total"] == cur["summary"][key]

    # GET /positions/{id}/model 同口径：死草稿岗的当前模型 = confirmed v2
    r = client.get(f"/api/admin/positions/{pid_dead}/model", headers=headers)
    assert r.status_code == 200
    assert r.json()["version"] == 2 and r.json()["status"] == "confirmed"


def test_list_endpoint_requires_admin():
    """/admin/aggregate-tasks 鉴权：无 token 401。"""
    from server.main import app
    client = TestClient(app)
    r = client.get("/api/admin/aggregate-tasks")
    assert r.status_code == 401
