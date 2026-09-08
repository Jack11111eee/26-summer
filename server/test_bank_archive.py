"""旧版题库归档标记测试（SSOT §9.2/§9.5 2026-09-08 扩展，裁决链见临时讨论稿-20260908）。

覆盖七组（裁决测试矩阵）：
  1) confirm 旧版归档：新模型 confirm → 旧模型 active 题行变 archived（数对得上）、keep 行不动
  2) 在途豁免：旧 model_id 被 in_progress 会话引用时 confirm 新版，其行仍 active
  3) 会话终态补刀：豁免会话 completed（走被测代码路径）/ abandoned（timer sweep）后归档
  4) retry 409：岗位存在更新 confirmed 模型时其 FAILED 任务 retry → 409；最新版 FAILED → 正常 requeue
  5) 归档版管理端契约：bank_status 派生 / archived_count / bank_status 筛选 / questions
     全量+status 列 / coverage 放开
  6) 归档不回归：归档模型的在途会话答卷→评分→报告链路照常（join 不读 status 不变量）
  7) eval_seed 不受影响：归档谓词 status='active' 天然隔离 eval_seed 行（用例固化）

不修登记缺陷 C1（eval virtual_candidates 不带 model/version 绑定）/ C2（retry 时序）。
LLM_PROVIDER=mock 离线；单文件单库（/tmp 临时库），不碰 data/app.db。
运行：cd server && python -m pytest test_bank_archive.py -v
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# 必须在 import server 之前设环境变量（config 在 import 时读取）；单文件单库
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="bank_archive_"), "test.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.db import get_conn, init_db  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.question_bank import archive_superseded_banks  # noqa: E402
from server.services.scoring import score_session  # noqa: E402
from server.services.report import generate_report  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


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


_ADMIN = {"username": "bank_archive_admin", "password": "bank_archive_pw"}


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


# ---------- 种子 ----------

def _seed_confirmed_model(position_name: str, items: list[dict] | None = None,
                          model_version: int = 1) -> tuple[str, str]:
    """active 岗位 + confirmed 模型 + competency_item（与 _seed 同口径，供 confirm
    前后版本并存用）。返回 (pid, mid)。"""
    if items is None:
        items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
                  "weight": 1.0, "required_level": 4}]
    pid, mid = new_id("pos"), new_id("m")
    _exec(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, position_name, "active", now_iso()),
    )
    model_json = {"position_id": pid, "version": model_version, "items": items}
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json,"
        " confirmed_by, confirmed_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (mid, pid, model_version, "confirmed", json.dumps(model_json, ensure_ascii=False),
         None, now_iso(), now_iso()),
    )
    for it in items:
        _exec(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], it.get("required_level"),
             it["importance"], it["weight"], 0),
        )
    return pid, mid


def _insert_bank_question(pid: str, mid: str, model_version: int, std_name: str,
                          difficulty: str, stem: str, *, status: str = "active",
                          qtype: str = "subjective", answer_key=None, rubric="要点一/要点二") -> str:
    """直插题库行（默认 active；归档/eval_seed 走 status 参数）。返回 question_id。"""
    qid = new_id("q")
    _exec(
        "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
        " std_name, category, difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (qid, "position", pid, mid, model_version, std_name, "hard_skill", difficulty,
         qtype, stem, answer_key, rubric, "imported", status, now_iso()),
    )
    return qid


def _insert_task(pid: str, mid: str, model_version: int, status: str = "QUEUED") -> str:
    """按 confirm/retry 生产口径插 task 行。"""
    tid = new_id("qbt")
    _exec(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (tid, pid, mid, model_version, status, now_iso()),
    )
    return tid


def _register_candidate(username: str) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _create_session(pid: str, mid: str, model_version: int,
                    user_headers: dict) -> str:
    """创建会话并锚定指定模型版本（走被测 API 路径——readiness 按题库实况放行）。"""
    r = client.post("/api/assessment/sessions", json={"position_id": pid},
                    headers=user_headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    # 会话锚定的是岗位最新 confirmed——种子若最新即目标模型则无需干预
    sess = _q("SELECT model_id FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["model_id"] == mid, f"会话未锚定期望模型（want {mid} got {sess['model_id']}）"
    return sid


def _seed_inflight_session(pid: str, mid: str, model_version: int,
                           username: str, bank_qids: list[str]) -> tuple[str, str]:
    """在途豁免用：直插 in_progress 会话 + 已答 1 题（attach 给定旧版题）。

    直插而非走 API：被测谓词只看 (model_id, status='in_progress')——会话行存在
    即构成豁免；后续 completed/abandoned 补刀另走真实端点（见 test 3）。
    """
    uid = new_id("u")
    _exec(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (uid, username, "x", "candidate", 1, now_iso()),
    )
    sid = new_id("sess")
    now = now_iso()
    _exec(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at, phase)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid, model_version, "in_progress", now, now, "ACTIVE"),
    )
    return sid, uid


def _start_and_answer_all(sid: str, user_headers: dict, answer: str = None) -> None:
    """入场确认 + 逐题作答直至 finish（复用 test_m5_backend 全链路形态）。"""
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=user_headers)
    assert r.status_code in (200, 409), r.text

    def _current_q() -> dict | None:
        r = client.get(f"/api/assessment/sessions/{sid}", headers=user_headers)
        assert r.status_code == 200, r.text
        return r.json()["current_question"]

    long_answer = answer or ("我熟练使用 def 定义函数，也了解装饰器与生成器的原理，"
                             "做过性能优化，能给出具体结果数据。")
    while True:
        cur = _current_q()
        if cur is None:
            break
        with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                           json={"question_id": cur["question_id"], "answer": long_answer},
                           headers=user_headers) as r:
            assert r.status_code == 200, r.text
            events = [json.loads(ln[6:]) for ln in r.iter_lines() if ln.startswith("data: ")]
        done = next(e for e in events if e["type"] == "done")
        if done["action"] == "finish":
            break
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed", f"会话未完成：{sess}"


# ---------- 1) confirm 旧版归档 ----------

def test_confirm_archives_old_model_banks(headers):
    """confirm 新版 → 旧模型 active 题行变 archived（数对得上）；keep 模型行不动。"""
    # 岗位 v1：confirmed 模型 + 3 题 + QUEUED task 行
    pid, mid_v1 = _seed_confirmed_model("归档确认岗")
    _insert_bank_question(pid, mid_v1, 1, "Python", "easy", "v1 题干A")
    _insert_bank_question(pid, mid_v1, 1, "Python", "medium", "v1 题干B")
    _insert_bank_question(pid, mid_v1, 1, "Python", "hard", "v1 题干C")

    # v2：seed draft → POST confirm（走被测代码路径：confirm_model 事务内归档）
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    for it in items:
        _exec(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid_v2, it["std_name"], it["category"], 4, it["importance"], it["weight"], 0),
        )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text

    # 旧模型 3 行全部 archived；v2 无题库行（生成插行不在本断言面）
    v1_archived = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='archived'", (mid_v1,))[0]["c"]
    v1_active = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='active'", (mid_v1,))[0]["c"]
    assert v1_archived == 3, f"实际 archived={v1_archived}"
    assert v1_active == 0, f"实际 active={v1_active}"
    # keep（v2）无行——无回归点；行不灭：总数不变（不删数据）
    total_v1 = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=?", (mid_v1,))[0]["c"]
    assert total_v1 == 3

    # 幂等：再来一次（直接调 helper——confirm 端点对 confirmed 恒 409），不改任何行
    conn = get_conn()
    try:
        archive_superseded_banks(conn, pid)
        conn.commit()
    finally:
        conn.close()
    still = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='archived'", (mid_v1,))[0]["c"]
    assert still == 3


def test_confirm_keeps_old_model_when_no_newer_confirmed(headers):
    """反例：无可取代对象时 confirm 不动任何行（新版 confirm 且岗位只有它）。"""
    pid, mid = _seed_confirmed_model("归档孤版岗")
    _insert_bank_question(pid, mid, 1, "Python", "easy", "孤版题干")
    # 该岗位唯一 confirmed 就是本模型：helper 调用后行仍 active
    conn = get_conn()
    try:
        archive_superseded_banks(conn, pid)
        conn.commit()
    finally:
        conn.close()
    row = _q("SELECT status FROM question_bank WHERE model_id=?", (mid,))[0]
    assert row["status"] == "active"


# ---------- 2) 在途豁免 ----------

def test_inflight_session_exempts_from_archive(headers):
    """在途豁免：旧 model_id 被 in_progress 会话引用时 confirm 新版，其行仍 active。"""
    pid, mid_v1 = _seed_confirmed_model("归档豁免岗")
    qids = [_insert_bank_question(pid, mid_v1, 1, "Python", "easy", f"豁免题干{i}")
            for i in range(3)]
    sid, uid = _seed_inflight_session(pid, mid_v1, 1, "bank_exempt_user", qids)

    # confirm v2 → v1 行因在途豁免不动
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    active = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='active'", (mid_v1,))[0]["c"]
    archived = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='archived'", (mid_v1,))[0]["c"]
    assert active == 3, f"在途豁免失效：active={active}"
    assert archived == 0

    # 直接调 helper 同样保持（幂等豁免，非 confirm 时序偶得）
    conn = get_conn()
    try:
        archive_superseded_banks(conn, pid)
        conn.commit()
    finally:
        conn.close()
    active = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='active'", (mid_v1,))[0]["c"]
    assert active == 3, "直接调 helper 也应豁免在途"


# ---------- 3) 会话终态补刀 ----------

def test_completed_session_sweep_archives_exempted_banks(headers, monkeypatch):
    """终态补刀（completed）：上述豁免会话结束后归档（走被测路径——answer 全链路
    finish；非直插 UPDATE）。"""
    # N=2：种子 3 hard 题即满足 readiness + 会话两题即耗尽（不依赖生产默认 N=10）
    monkeypatch.setattr("server.config.ORDINARY_PLAN_N", 2)
    # 重建场景：v1 confirmed + 在途会话；v2 confirm（豁免）；随后会话完成 → 归档
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    pid, mid_v1 = _seed_confirmed_model("归档补刀岗", items=items)
    # 题库行（同题干差异 key 防幂等碰撞）
    for i, diff in enumerate(("easy", "medium", "hard")):
        _insert_bank_question(pid, mid_v1, 1, "Python", diff, f"补刀题干{i}")

    user_headers = _register_candidate("bank_sweep_user")
    sid = _create_session(pid, mid_v1, 1, user_headers)

    # v2 confirm（事务内归档）→ v1 在途豁免
    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    _exec(
        "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
        " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
        (new_id("c"), mid_v2, "Python", "hard_skill", 4, "required", 1.0, 0),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    active = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='active'", (mid_v1,))[0]["c"]
    assert active == 3, f"confirm 后应在途豁免 active=3，实得 {active}"

    # 会话走完整链路到 completed（answer 池耗尽 finish——被测补刀路径）
    _start_and_answer_all(sid, user_headers)
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed"

    # 补刀归档：v1 全部 3 行 archived
    archived = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='archived'", (mid_v1,))[0]["c"]
    active = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='active'", (mid_v1,))[0]["c"]
    assert archived == 3, f"终态补刀失效：archived={archived}"
    assert active == 0


def test_abandoned_sweep_archives_exempted_banks(headers, monkeypatch):
    """终态补刀（abandoned）：6h sweep（maybe_abandon_session——timer.py 被测函数）
    对豁免在途会话置 abandoned 后归档。"""
    # N=2：种子 3 hard 题满足 readiness（会话创建即派题锚定 v1，与生产 N=10 解耦）
    monkeypatch.setattr("server.config.ORDINARY_PLAN_N", 2)
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    pid, mid_v1 = _seed_confirmed_model("归档abandoned岗", items=items)
    for i, diff in enumerate(("easy", "medium", "hard")):
        _insert_bank_question(pid, mid_v1, 1, "Python", diff, f"abandoned题干{i}")

    # 在途会话（走 API——锚定 v1）
    user_headers = _register_candidate("bank_abandon_user")
    sid = _create_session(pid, mid_v1, 1, user_headers)

    # v2 confirm → v1 在途豁免
    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    active = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='active'", (mid_v1,))[0]["c"]
    assert active == 3, f"confirm 后应在途豁免 active=3，实得 {active}"

    # 6h 时限穷尽（last_activity_at 回拨 7h）→ 走 answer 路径惰性 abandon
    old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    _exec("UPDATE assessment_session SET last_activity_at=? WHERE session_id=?", (old, sid))
    # 入场确认（PENDING_START→ACTIVE）+ GET 派发首题 → answer 触发惰性判定
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=user_headers)
    assert r.status_code in (200, 409), r.text
    r = client.get(f"/api/assessment/sessions/{sid}", headers=user_headers)
    assert r.status_code == 200, r.text
    qid = r.json()["current_question"]["question_id"]
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": "随便答点什么，长度超过二十个字符以避免追问。"},
                    headers=user_headers)
    assert r.status_code == 409, r.text  # abandon 后 409 SESSION_NOT_IN_PROGRESS
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "abandoned"

    # 补刀归档：v1 行全部 archived
    archived = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='archived'", (mid_v1,))[0]["c"]
    active = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='active'", (mid_v1,))[0]["c"]
    assert archived == 3, f"abandoned sweep 补刀失效：archived={archived}"
    assert active == 0


# ---------- 4) retry 409 ----------

def test_retry_blocked_when_newer_confirmed_exists(headers, monkeypatch):
    """retry 409：岗位存在更新 confirmed 模型时其 FAILED 任务 retry → 409；最新版
    FAILED 任务 retry → 正常 requeue。"""
    # 岗位 v1 + FAILED task（后台生成任务打桩 no-op——只验 retry 端点行为）
    def _noop(position_id, model_id):
        return None
    monkeypatch.setattr("server.services.question_bank.generate_question_bank", _noop)

    pid, mid_v1 = _seed_confirmed_model("归档retry岗")
    tid_v1 = _insert_task(pid, mid_v1, 1, status="FAILED")
    _exec("UPDATE question_bank_task SET error_msg='模拟失败' WHERE task_id=?", (tid_v1,))
    _insert_bank_question(pid, mid_v1, 1, "Python", "easy", "retry 岗旧题")

    # 旧版 FAILED → 无更新 confirmed：正常 requeue（对照）
    r = client.post(f"/api/admin/question-bank-tasks/{tid_v1}/retry", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["requeued"] is True

    # confirm v2 → v1 FAILED 任务行（再造一行 FAILED）
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    tid_v1_failed = _insert_task(pid, mid_v1, 1, status="FAILED")
    _exec("UPDATE question_bank_task SET error_msg='模拟失败2' WHERE task_id=?", (tid_v1_failed,))

    # 旧版 FAILED retry → 409（conflict detail 给冲突原因）
    r = client.post(f"/api/admin/question-bank-tasks/{tid_v1_failed}/retry", headers=headers)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "更新" in detail and "不可重试" in detail, f"detail 应给冲突原因，实得 {detail!r}"

    # 最新版（v2）FAILED task → retry 正常 requeue（未被取代）
    tid_v2_failed = _insert_task(pid, mid_v2, 2, status="FAILED")
    r = client.post(f"/api/admin/question-bank-tasks/{tid_v2_failed}/retry", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["requeued"] is True


# ---------- 5) 归档版管理端契约 ----------

def test_archived_admin_endpoint_contracts(headers):
    """管理端契约：bank_status 派生 / archived_count / bank_status 筛选 / questions
    全量+status 列 / coverage 放开。"""
    # 岗位：v1 归档（3 题）+ v2 使用中（1 题），两组各插 task 行
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    pid, mid_v1 = _seed_confirmed_model("归档契约岗", items=items)
    for i, diff in enumerate(("easy", "medium", "hard")):
        _insert_bank_question(pid, mid_v1, 1, "Python", diff, f"契约归档题干{i}")
    tid_v1 = _insert_task(pid, mid_v1, 1, status="SUCCEEDED")

    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    # v2 无在途 → v1 3 行全归档
    tid_v2 = _insert_task(pid, mid_v2, 2, status="SUCCEEDED")
    _insert_bank_question(pid, mid_v2, 2, "Python", "easy", "契约新版题干")

    # ---- 列表：bank_status 派生 + archived_count ----
    r = client.get("/api/admin/question-bank-tasks",
                   params={"page_size": 50}, headers=headers)
    assert r.status_code == 200, r.text
    rows = {it["model_id"]: it for it in r.json()["items"] if it["position_id"] == pid}
    assert mid_v1 in rows and mid_v2 in rows
    assert rows[mid_v1]["bank_status"] == "archived", rows[mid_v1]
    assert rows[mid_v1]["archived_count"] == 3
    assert rows[mid_v1]["question_count"] == 0  # active 主计数归零（archived_count 补可辨）
    assert rows[mid_v2]["bank_status"] == "active", rows[mid_v2]
    assert rows[mid_v2]["archived_count"] == 0
    assert rows[mid_v2]["question_count"] == 1

    # ---- 列表：bank_status 筛选命中 ----
    r = client.get("/api/admin/question-bank-tasks",
                   params={"bank_status": "archived", "page_size": 50}, headers=headers)
    assert r.status_code == 200, r.text
    archived_pids = [it["position_id"] for it in r.json()["items"]]
    assert pid in archived_pids, f"archived 筛选应命中该岗位，实得 {archived_pids}"
    assert all(it["model_id"] != mid_v2 for it in r.json()["items"]), "active 模型不应出现在 archived 筛选"

    r = client.get("/api/admin/question-bank-tasks",
                   params={"bank_status": "active", "page_size": 50}, headers=headers)
    assert r.status_code == 200, r.text
    assert all(it["model_id"] != mid_v1 for it in r.json()["items"]), "已归档模型不应出现在 active 筛选"

    # ---- 归档版 questions：全量 + status 列 ----
    r = client.get(f"/api/admin/question-bank-tasks/{tid_v1}/questions",
                   params={"page": 1, "page_size": 2}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3, f"归档版应全量 3 题，实得 {body['total']}"
    assert len(body["items"]) == 2  # 分页仍生效
    for q in body["items"]:
        assert q["status"] in ("active", "archived"), q
        assert q["status"] == "archived", f"归档版题目行 status 应为 archived：{q}"
    # 第二页
    r = client.get(f"/api/admin/question-bank-tasks/{tid_v1}/questions",
                   params={"page": 2, "page_size": 2}, headers=headers)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    # ---- 使用中版 questions：口径不变（active-only）+ 兼容 status 列 ----
    r = client.get(f"/api/admin/question-bank-tasks/{tid_v2}/questions", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "active"

    # ---- 归档版详情：coverage 放开（不含 status 过滤口径重算）----
    r = client.get(f"/api/admin/question-bank-tasks/{tid_v1}", headers=headers)
    assert r.status_code == 200, r.text
    coverage = r.json()["coverage"]
    assert len(coverage) == 1, f"归档版 coverage 应重算，实得 {coverage}"
    assert coverage[0]["std_name"] == "Python"
    assert coverage[0]["easy"] == 1 and coverage[0]["medium"] == 1 and coverage[0]["hard"] == 1

    # ---- 使用中版详情：coverage 口径不变 ----
    r = client.get(f"/api/admin/question-bank-tasks/{tid_v2}", headers=headers)
    assert r.status_code == 200, r.text
    coverage = r.json()["coverage"]
    assert len(coverage) == 1 and coverage[0]["easy"] == 1 and coverage[0]["medium"] == 0


# ---------- 6) 归档不回归（评分/报告链路） ----------

def test_archived_model_session_scoring_report_chain(headers, monkeypatch):
    """归档模型的在途会话：答卷→评分（调 scoring 函数）→报告生成链路照常。

    场景：v1 在途会话（豁免）→ v2 confirm（v1 归档被豁免）→ 会话完成（补刀归档
    v1）→ 评分/报告按 bank_question_id 直连 join 不读 status，链路不炸不空。
    """
    # N=2：种子 2 题满足 readiness + 会话两题即耗尽（与生产默认 N=10 解耦）
    monkeypatch.setattr("server.config.ORDINARY_PLAN_N", 2)
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    pid, mid_v1 = _seed_confirmed_model("归档回归岗", items=items)
    # 客观题（answer_key 确定性判分——mock 主观恒 3 分亦可，客观便于断言非空）
    _insert_bank_question(pid, mid_v1, 1, "Python", "easy", "v1 用什么关键字定义函数？",
                          qtype="objective", answer_key="def")
    _insert_bank_question(pid, mid_v1, 1, "Python", "medium", "v1 主观题：谈谈函数式编程。",
                          rubric="概念/例子/取舍")

    user_headers = _register_candidate("bank_regress_user")
    sid = _create_session(pid, mid_v1, 1, user_headers)

    # v2 confirm（v1 在途豁免）→ 会话完成后补刀归档
    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    _exec(
        "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
        " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
        (new_id("c"), mid_v2, "Python", "hard_skill", 4, "required", 1.0, 0),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text

    # 全链路答题（评分读取题目 join 那步：answer 流内 refine/决策 join 不读 status）
    _start_and_answer_all(sid, user_headers,
                          answer="我用 def 定义函数，也了解装饰器和闭包的机制，写过生产代码，有结果数据。")

    # 补刀归档已生效（completed 路径）——此时跑评分/报告即「已归档模型的答卷链路」
    archived = _q(
        "SELECT COUNT(*) c FROM question_bank WHERE model_id=? AND status='archived'", (mid_v1,))[0]["c"]
    assert archived >= 1, f"会话完成后 v1 应已归档，实得 {archived}"

    # 评分（直接调 scoring.score_session——被测链路核心 join；completed 会话走
    # allow_completed 口径与串行链一致）
    result = score_session(sid, allow_completed=True)
    assert result is not None
    scores = _q("SELECT COUNT(*) c FROM question_score WHERE session_id=?", (sid,))[0]["c"]
    assert scores >= 1, f"归档模型评分行应照常落库，实得 {scores}"

    # 报告生成
    report = generate_report(sid)
    assert report.get("report_status") in ("READY", "PROVISIONAL"), report
    assert report.get("question_reviews"), "归档模型的报告逐题回顾应非空（join 不读 status）"


def test_archived_session_dynamic_question_pool_intact(headers, monkeypatch):
    """归档不回归补充：在途豁免会话的动态派题不被打断（答题期间题行仍 active）。"""
    # N=2：种子 2 hard 题满足 readiness + 会话两题即耗尽
    monkeypatch.setattr("server.config.ORDINARY_PLAN_N", 2)
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    pid, mid_v1 = _seed_confirmed_model("归档派题岗", items=items)
    _insert_bank_question(pid, mid_v1, 1, "Python", "easy", "派题题干1")
    _insert_bank_question(pid, mid_v1, 1, "Python", "medium", "派题题干2")

    user_headers = _register_candidate("bank_pool_user")
    sid = _create_session(pid, mid_v1, 1, user_headers)

    # v2 confirm → v1 在途豁免；会话照常派题作答
    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text
    _start_and_answer_all(sid, user_headers,
                          answer="关于这道题我从 def 关键字说起，结合装饰器与生成器举出实例，并给出结果。")
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed"


# ---------- 7) eval_seed 不受影响 ----------

def test_eval_seed_rows_untouched_by_archive_sweep(headers):
    """eval_seed 行不受影响：归档谓词 status='active' 天然隔离（用例固化）。"""
    items = [{"std_name": "Python", "category": "hard_skill", "importance": "required",
              "weight": 1.0, "required_level": 4}]
    pid, mid_v1 = _seed_confirmed_model("归档eval岗", items=items)
    # v1：1 active + 2 eval_seed；v2 confirm → 归档 sweep 跑过
    _insert_bank_question(pid, mid_v1, 1, "Python", "easy", "eval 岗 active 题")
    _insert_bank_question(pid, mid_v1, 1, "Python", "medium", "eval 占位题1", status="eval_seed")
    _insert_bank_question(pid, mid_v1, 1, "Python", "hard", "eval 占位题2", status="eval_seed")

    mid_v2 = new_id("m")
    _exec(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid_v2, pid, 2, "draft", json.dumps({"items": items}, ensure_ascii=False), now_iso()),
    )
    r = client.post(f"/api/admin/models/{mid_v2}/confirm", headers=headers)
    assert r.status_code == 200, r.text

    # active → archived；eval_seed 两行原样不动
    by_status = _q(
        "SELECT status, COUNT(*) c FROM question_bank WHERE model_id=? GROUP BY status", (mid_v1,))
    status_map = {row["status"]: row["c"] for row in by_status}
    assert status_map.get("archived") == 1, f"active 归档数：{status_map}"
    assert status_map.get("eval_seed") == 2, f"eval_seed 应保留 2 行：{status_map}"
    assert "active" not in status_map

    # archived_count（管理端旁列）也只统计 archived，不含 eval_seed
    tid = _insert_task(pid, mid_v1, 1, status="SUCCEEDED")
    r = client.get(f"/api/admin/question-bank-tasks/{tid}/questions", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # 整体归档判定：无 active 行且有 archived 行 → 放开全量（archived 1 + eval_seed 2）；
    # eval_seed 行照直输出 status 列（值直译）
    statuses = sorted(q["status"] for q in body["items"])
    assert statuses == ["archived", "eval_seed", "eval_seed"], statuses
