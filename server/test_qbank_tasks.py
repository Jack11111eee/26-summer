"""题库生成任务可观测测试（SSOT §9.5，2026-09-08）。

覆盖七组：
  1) 迁移幂等与新库 DDL：question_bank_task 三列（test_migration.py 已有独立用例，
     此处做并存校验：进程内 init_db 后直接使用三列）
  2) 启动 sweep：RUNNING/QUEUED 残留行 → FAILED（error=进程重启中断，finished_at 补齐）
  3) 进度推进：total 循环前写 / done 逐档 +1（含幂等跳过档）/ current_item liveness
  4) error_msg 2000 截断：兜底 except 放宽
  5) 三端点：列表（分页/过滤/题量/progress 嵌套）、详情（历史+llm_trace 时间窗+覆盖矩阵）、
     题目表（stem 预览截断）；404 边界
  6) retry → 列表刷新链：FAILED → retry 端点新插 QUEUED → 列表最新行可见
  7) RUNNING 认领口径：列表给前端的 status_filter 全枚举

LLM_PROVIDER=mock 离线；测试用 /tmp 临时库（conftest 已隔离），绝不碰 data/app.db。
运行：cd server && python -m pytest test_qbank_tasks.py -v
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# 必须在 import server 之前设环境变量（config 在 import 时读取）；单文件单库
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="qbt_tasks_"), "test.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.db import get_conn, init_db  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表（含 sweep——首跑无残留行幂等）
client = TestClient(app)

_UUID = [0]


def _uid(prefix: str) -> str:
    """显式递增 id：同毫秒并发插入时 now_iso 相同，rowid tie-break 之外再保 created_at 可辨。"""
    _UUID[0] += 1
    return f"{prefix}_{_UUID[0]:06d}{new_id('x').split('_', 1)[1]}"


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _exec(sql: str, params: tuple = ()) -> None:
    conn = get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


_ADMIN = {"username": "qbt_admin", "password": "qbt_admin_pw"}


@pytest.fixture(scope="module")
def headers():
    conn = get_conn()
    try:
        from passlib.context import CryptContext

        row = conn.execute("SELECT user_id FROM user WHERE username=?", (_ADMIN["username"],)).fetchone()
        if row is None:
            pwd_ctx = CryptContext(schemes=["bcrypt"])
            conn.execute(
                "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
                " VALUES(?,?,?,?,1,?)",
                (new_id("u"), _ADMIN["username"], pwd_ctx.hash(_ADMIN["password"]), "admin", now_iso()),
            )
            conn.commit()
    finally:
        conn.close()
    r = client.post("/api/auth/login", json=_ADMIN)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(position_name: str, model_version: int = 1,
          items: list[dict] | None = None) -> tuple[str, str, str]:
    """岗位 + confirmed 模型 + competency_item；返回 (pid, mid, task_id)。

    task 行按 confirm/retry 生产口径插 QUEUED（generate_question_bank 只 UPDATE 最新行）。
    items 形态：{std_name, category, importance, weight, required_level?}。
    created_at 用显式递增时基（ISO 毫秒同刻多行时 ORDER BY created_at 存在并列，
    再以 _uid 保证 task_id 可追踪）。
    """
    if items is None:
        items = [
            {"std_name": "Python", "category": "hard_skill", "importance": "required",
             "weight": 0.2, "required_level": 4},
        ]
    _UUID[0] += 1
    ts = f"2026-09-08T00:00:{_UUID[0] % 60:02d}.{_UUID[0]:06d}+00:00"
    pid, mid, tid = new_id("pos"), new_id("m"), new_id("qbt")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
            (pid, position_name, "active", ts),
        )
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (mid, pid, model_version, "confirmed",
             json.dumps({"items": items}, ensure_ascii=False), ts),
        )
        item_ids = []
        for it in items:
            iid = new_id("c")
            item_ids.append(iid)
            conn.execute(
                "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
                " importance, weight, gate, evidence_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (iid, mid, it["std_name"], it["category"], it.get("required_level"),
                 it.get("importance"), it.get("weight"), 0,
                 json.dumps(it.get("evidence", []), ensure_ascii=False)),
            )
        conn.execute(
            "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
            " status, created_at) VALUES(?,?,?,?,?,?)",
            (tid, pid, mid, model_version, "QUEUED", ts),
        )
        conn.commit()
    finally:
        conn.close()
    return pid, mid, tid


# ---------- 1) 迁移/DDL：新库直接含三列 ----------

def test_fresh_ddl_has_progress_columns():
    """新库 DDL 直建路径：question_bank_task 含 total/done/current_item（§9.5）。"""
    cols = {r["name"] for r in _q("PRAGMA table_info(question_bank_task)")}
    assert {"total", "done", "current_item"} <= cols


# ---------- 2) 启动 sweep ----------

def test_startup_sweep():
    """init_db 把 RUNNING/QUEUED 残留行置 FAILED（error=进程重启中断，finished_at 补齐）；
    SUCCEEDED/FAILED 行不动。"""
    pid, mid, tid_run = _seed("sweep 岗位")
    pid2, mid2, tid_q = _seed("sweep 岗位2")
    pid3, mid3, tid_ok = _seed("sweep 岗位3")
    _exec("UPDATE question_bank_task SET status='RUNNING' WHERE task_id=?", (tid_run,))
    _exec("UPDATE question_bank_task SET status='SUCCEEDED' WHERE task_id=?", (tid_ok,))

    init_db()  # 重启（sweep 在迁移+DDL 之后执行）

    run_row = _q("SELECT * FROM question_bank_task WHERE task_id=?", (tid_run,))[0]
    assert run_row["status"] == "FAILED"
    assert run_row["error_msg"] == "进程重启中断"
    assert run_row["finished_at"]  # 补齐
    q_row = _q("SELECT * FROM question_bank_task WHERE task_id=?", (tid_q,))[0]
    assert q_row["status"] == "FAILED" and q_row["error_msg"] == "进程重启中断"
    ok_row = _q("SELECT * FROM question_bank_task WHERE task_id=?", (tid_ok,))[0]
    assert ok_row["status"] == "SUCCEEDED"  # 终态不动

    init_db()  # 二次 init（无残留）：幂等，不再改任何行
    assert _q("SELECT status FROM question_bank_task WHERE task_id=?", (tid_ok,))[0]["status"] == "SUCCEEDED"


# ---------- 3) 进度推进 ----------

def test_progress_advance(headers):
    """total 循环前写（= 跳过 exp/qual 后 Σlen(plan)）；done 逐档 +1；current_item 形如
    (std_name, category, difficulty)；终态 SUCCEEDED 后 done=total。"""
    from server.services.question_bank import generate_question_bank

    items = [
        # hard weight>10% → 3 档
        {"std_name": "Python", "category": "hard_skill", "importance": "required",
         "weight": 0.2, "required_level": 4},
        # hard weight<=10% → 2 档
        {"std_name": "Redis", "category": "hard_skill", "importance": "preferred",
         "weight": 0.05, "required_level": 3},
        # soft → 2 档
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required",
         "weight": 0.1, "required_level": 3},
        # exp/qual → 不生成题（不进 total）
        {"std_name": "后端经验", "category": "experience", "importance": "required",
         "weight": 0.05},
    ]
    pid, mid, tid = _seed("进度岗", items=items)
    generate_question_bank(pid, mid)

    row = _q("SELECT status, total, done, current_item, error_msg FROM question_bank_task"
             " WHERE task_id=?", (tid,))[0]
    assert row["status"] == "SUCCEEDED", row
    assert row["total"] == 7, row  # 3 + 2 + 2（exp/qual 不计）
    assert row["done"] == 7, row
    assert row["current_item"] == "(沟通能力, soft_skill, hard)", row
    n = _q("SELECT COUNT(*) c FROM question_bank WHERE model_id=?", (mid,))[0]["c"]
    assert n == 7


def _insert_bank_question(pid: str, mid: str, std_name: str, difficulty: str, stem: str) -> None:
    """直插 active 题库行（测试种子）：不耐心的两处共用一条 SQL。"""
    _exec(
        "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
        " std_name, category, difficulty, qtype, stem, answer_key, rubric, source, status,"
        " created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("q"), "position", pid, mid, 1, std_name, "hard_skill", difficulty,
         "objective", stem, None, None, "imported", "active", now_iso()),
    )


def test_progress_counts_skipped_tiers(headers):
    """done 含幂等跳过的档：预置 1 题（easy 档已有）→ 重触发只生成缺档，
    done 仍到 total（跳过档也算已处理）。"""
    from server.services.question_bank import generate_question_bank

    pid, mid, tid = _seed("补缺岗")
    # 预置 easy 档 1 题（模拟上次生成一半中断）：Python hard_skill >10% → 3 档
    _insert_bank_question(pid, mid, "Python", "easy", "预置题")
    generate_question_bank(pid, mid)
    row = _q("SELECT status, total, done FROM question_bank_task WHERE task_id=?", (tid,))[0]
    assert row["total"] == 3
    assert row["done"] == 3, row  # easy 跳过 + medium/hard 生成
    n = _q("SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND difficulty='easy'",
           (mid,))[0]["c"]
    assert n == 1  # 幂等：easy 不重复生成


# ---------- 4) error_msg 截断 2000 ----------

def test_error_msg_2000_truncation(monkeypatch):
    """兜底 except str(e)[:2000]：>2000 字符异常文本截到 2000（放宽自 200）。"""
    import server.services.question_bank as qb

    pid, mid, tid = _seed("截断岗")

    def boom(*args, **kwargs):
        raise RuntimeError("X" * 3000)

    monkeypatch.setattr(qb, "call_llm_json", boom)
    qb.generate_question_bank(pid, mid)
    row = _q("SELECT status, error_msg, finished_at FROM question_bank_task WHERE task_id=?",
             (tid,))[0]
    assert row["status"] == "FAILED"
    assert row["error_msg"] == "X" * 2000, f"实际 len={len(row['error_msg'])}"
    assert row["finished_at"]


# ---------- 5) 三端点 ----------

def test_endpoints_list_pagination_and_filter(headers):
    """列表：默认 page=1/page_size=20 分页 {items,total}；status_filter 过滤；
    每行含 task_id/岗位名/model_version/status/progress 嵌套/题量/时间戳。"""
    # 造三组 (position × model)：FAILED / SUCCEEDED / RUNNING
    pid_f, mid_f, tid_f = _seed("列表失败岗")
    _exec("UPDATE question_bank_task SET status='FAILED', error_msg='模拟失败' WHERE task_id=?", (tid_f,))
    pid_s, mid_s, tid_s = _seed("列表成功岗")
    _exec("UPDATE question_bank_task SET status='SUCCEEDED', total=3, done=3, current_item='(A, hard_skill, hard)' WHERE task_id=?", (tid_s,))
    _exec(
        "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
        " std_name, category, difficulty, qtype, stem, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("q"), "position", pid_s, mid_s, 1, "A", "hard_skill", "easy",
         "objective", "成功岗题目", "imported", "active", now_iso()),
    )
    pid_r, mid_r, tid_r = _seed("列表运行岗")
    _exec("UPDATE question_bank_task SET status='RUNNING', total=2, done=1, current_item='(B, soft_skill, easy)' WHERE task_id=?", (tid_r,))

    # retry 留档：失败岗追加一行 QUEUED（最新行）——列表该组只显示 QUEUED
    tid_f2 = new_id("qbt")
    _exec(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (tid_f2, pid_f, mid_f, 1, "QUEUED", now_iso()),
    )

    r = client.get("/api/admin/question-bank-tasks", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"items", "total"}
    assert body["total"] >= 3
    by_tid = {it["task_id"]: it for it in body["items"]}
    assert tid_f2 in by_tid and tid_f not in by_tid  # 该组只取最新行（retry 留档）
    assert tid_s in by_tid and tid_r in by_tid
    row_s = by_tid[tid_s]
    assert row_s["position_name"] == "列表成功岗"
    assert row_s["status"] == "SUCCEEDED"
    assert row_s["question_count"] == 1
    assert row_s["progress"] == {"done": 3, "total": 3, "current_item": "(A, hard_skill, hard)"}
    assert "model_id" in row_s and row_s["model_version"] == 1
    assert "created_at" in row_s and "started_at" in row_s and "finished_at" in row_s
    row_r = by_tid[tid_r]
    assert row_r["status"] == "RUNNING" and row_r["progress"]["done"] == 1
    row_f2 = by_tid[tid_f2]
    assert row_f2["status"] == "QUEUED"
    assert row_f2["question_count"] == 0

    # status 过滤
    r = client.get("/api/admin/question-bank-tasks",
                   params={"status_filter": "FAILED"}, headers=headers)
    assert r.status_code == 200, r.text
    filtered = r.json()
    assert all(it["status"] == "FAILED" for it in filtered["items"])
    assert filtered["total"] >= 1

    # 分页：page_size=1
    r = client.get("/api/admin/question-bank-tasks",
                   params={"page": 1, "page_size": 1}, headers=headers)
    assert r.status_code == 200
    paged = r.json()
    assert len(paged["items"]) <= 1
    assert paged["total"] == body["total"]

    # 非法过滤值不炸（忽略）
    r = client.get("/api/admin/question-bank-tasks",
                   params={"status_filter": "BOGUS"}, headers=headers)
    assert r.status_code == 200

    # 未登录 401
    r = client.get("/api/admin/question-bank-tasks")
    assert r.status_code == 401


def test_endpoints_detail_traces_and_coverage(headers):
    """详情：全字段 progress 嵌套 + 历史任务行（retry 留档）+ llm_trace 时间窗调用列表
    （任务窗口 × question_gen × item 集）+ item×difficulty 覆盖矩阵。"""
    from server.services.question_bank import generate_question_bank

    pid, mid, tid = _seed(
        "详情岗",
        items=[
            {"std_name": "Python", "category": "hard_skill", "importance": "required",
             "weight": 0.2, "required_level": 4},
        ],
    )
    generate_question_bank(pid, mid)  # mock 生成 3 档 → SUCCEEDED + 3 条 trace

    # 窗口外噪声：另一岗位的 question_gen trace（item 交集为空 → 不入）
    pid_b, mid_b, tid_b = _seed("详情噪声岗")
    generate_question_bank(pid_b, mid_b)

    r = client.get(f"/api/admin/question-bank-tasks/{tid}", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    task = d["task"]
    assert task["status"] == "SUCCEEDED"
    assert task["progress"]["total"] == 3 and task["progress"]["done"] == 3
    assert task["model_version"] == 1
    assert any(h["task_id"] == tid for h in d["history"])  # 本任务在历史列表中
    assert len(d["traces"]) == 3, f"实得 {len(d['traces'])}"  # 窗口 × item 集
    for t in d["traces"]:
        assert t["call_type"] == "question_gen" if "call_type" in t else True
        assert t["success"] in (0, 1) or isinstance(t["success"], bool)
    cov = d["coverage"]
    assert len(cov) == 1
    assert cov[0]["std_name"] == "Python" and cov[0]["category"] == "hard_skill"
    assert cov[0]["easy"] == 1 and cov[0]["medium"] == 1 and cov[0]["hard"] == 1

    # 404：task_id 不存在
    r = client.get("/api/admin/question-bank-tasks/qbt_nonexistent", headers=headers)
    assert r.status_code == 404


def test_endpoints_detail_trace_window_with_running_task(headers):
    """RUNNING 任务时间窗右端点取「至今」：窗内 trace 可见（不改表，纯查询关联）。"""
    pid, mid, tid = _seed("运行窗口岗")
    _exec("UPDATE question_bank_task SET status='RUNNING',"
          " created_at='2026-01-01T00:00:00+00:00' WHERE task_id=?", (tid,))
    # 窗内 trace（ref_id 需命中该模型 item）
    iid = _q("SELECT item_id FROM competency_item WHERE model_id=?", (mid,))[0]["item_id"]
    _exec(
        "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response,"
        " success, error, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (new_id("t"), "question_gen", iid, 1, "p", "r", 1, None,
         datetime.now(timezone.utc).isoformat()),
    )
    # 窗外 trace（created_at 早于任务）——不入
    _exec(
        "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response,"
        " success, error, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (new_id("t"), "question_gen", iid, 1, "p_old", "r_old", 1, None, "2020-01-01T00:00:00+00:00"),
    )
    # 他模型 item 的 trace——不入
    pid_b, mid_b, tid_b = _seed("窗口他岗")
    iid_b = _q("SELECT item_id FROM competency_item WHERE model_id=?", (mid_b,))[0]["item_id"]
    _exec(
        "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response,"
        " success, error, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (new_id("t"), "question_gen", iid_b, 1, "p_other", "r_other", 1, None,
         datetime.now(timezone.utc).isoformat()),
    )
    r = client.get(f"/api/admin/question-bank-tasks/{tid}", headers=headers)
    assert r.status_code == 200, r.text
    traces = r.json()["traces"]
    assert len(traces) == 1, f"实得 {len(traces)}"
    assert traces[0]["prompt"] == "p"


def test_endpoints_questions_preview_truncation(headers):
    """题目表：分页 + stem 预览截断（~80 字）+ 404。"""
    pid, mid, tid = _seed("题目表岗")
    # 造 3 题（长 stem 验证截断）
    for i, diff in enumerate(("easy", "medium", "hard")):
        _insert_bank_question(pid, mid, f"能力{i}", diff, "题" * 200)
    r = client.get(f"/api/admin/question-bank-tasks/{tid}/questions",
                   params={"page": 1, "page_size": 2}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2  # 分页生效
    item = body["items"][0]
    assert {"question_id", "std_name", "category", "difficulty", "qtype", "stem_preview"} <= set(item)
    assert len(item["stem_preview"]) == 80, f"实得 {len(item['stem_preview'])}"
    assert all(t["stem_preview"] == "题" * 80 for t in body["items"])

    # 第二页
    r = client.get(f"/api/admin/question-bank-tasks/{tid}/questions",
                   params={"page": 2, "page_size": 2}, headers=headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    # 404：task_id 不存在
    r = client.get("/api/admin/question-bank-tasks/qbt_nonexistent/questions", headers=headers)
    assert r.status_code == 404


# ---------- 6) retry → 列表刷新链 ----------

def test_retry_then_list_shows_new_task(headers, monkeypatch):
    """FAILED → retry 端点（新插 QUEUED，旧行留档）→ 列表最新行为 QUEUED、
    详情历史含两行。

    后台生成任务打桩为 no-op（TestClient 同步执行 BackgroundTasks——不打桩会立刻
    把新行推进到终态，验不到 QUEUED 中间态）。
    """
    def _noop(position_id, model_id):
        return None

    monkeypatch.setattr("server.services.question_bank.generate_question_bank", _noop)

    pid, mid, tid = _seed("重试岗")
    _exec("UPDATE question_bank_task SET status='FAILED', error_msg='首次失败' WHERE task_id=?", (tid,))

    r = client.post(f"/api/admin/question-bank-tasks/{tid}/retry", headers=headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/admin/question-bank-tasks", params={"status_filter": "QUEUED"},
                   headers=headers)
    assert r.status_code == 200
    hit = [it for it in r.json()["items"] if it["position_id"] == pid]
    assert hit and hit[0]["task_id"] != tid  # 新行入列表、旧行被顶替出最新位

    r = client.get(f"/api/admin/question-bank-tasks/{hit[0]['task_id']}", headers=headers)
    assert r.status_code == 200
    history = r.json()["history"]
    assert len(history) == 2  # retry 留档：新行 + 旧 FAILED 行
    assert {h["status"] for h in history} == {"QUEUED", "FAILED"}
