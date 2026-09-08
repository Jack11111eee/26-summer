"""候选端会话历史与再入测试（SSOT §12.1/§12.6/§22.1 2026-09-08，裁决链见临时讨论稿
-候选端导航与断点续测-20260908；超时收尾 sweep 与软删除见同日「候选端入口整治三件套」）。

覆盖矩阵（讨论稿 §五 + 入口整治三件套）：
- get-or-create：无在途 201 新建 / 有在途 200 同 id 行数守恒 / 复用路径跳过 readiness
  （同岗位题库清空后在途行照常复用，新用户新建照常 409）/ PENDING_START 在途复用；
  在途超 6h → sweep 后 abandoned → 允许新建新场（201 新 session_id）
- sweep 6h 段（R8）：create 与历史两挂载点生效、状态翻转、SESSION_ABANDONED 事件
  （from in_progress → to abandoned）；岗位列表 active_session 随之作废行消失
- 全场超时收尾 sweep（§12.6 2026-09-08）：超时会话经 positions（挂载点三）/
  create（挂载点一）触发 → completed + 报告行 + 事件序 GLOBAL_TIMEOUT <
  ENTERED_SCORING < COMPLETED；PENDING_START 超 6h 走 abandoned 无报告（顺序先
  abandon 后收尾）；PENDING_START 未超时/在途未超时摘要照常（回归）
- 历史端点：{items,total} 信封 / 分页 / status 过滤 / created_at DESC 排序 /
  行字段（position_name join、answered_count、进行中行 session_elapsed_seconds、
  ended_at/abandoned_at）/ 本人隔离（他人会话不可见）
- 软删除（§12.1 2026-09-08）：DELETE completed（owner 历史不出/深度链接 404/
  admin 豁免 200/事件 from=completed）；DELETE in_progress（ABANDONED+HIDDEN 双
  事件并存、actor=candidate、摘要不给入口）；重复 DELETE 幂等；删除他人 404；
  列表不含 hidden 行（含 total）
- positions 摘要（§12.6）：active_session {session_id, phase, remaining_minutes}；
  无在途 null；PENDING_START 剩余 = 40 分钟满额；start 后秒级流逝仍 40
- suggestion（§22.1）：提交校验（空文本 422 / 超长 2001 → 422；边界 2000 放行）+ 本人历史
  隔离 + 管理端 list（status 过滤）/review（status→reviewed + note + 审计字段 +
  404）+ candidate 访问 admin 端点 403 + 候选人视角处理进度
- 回归：pause/resume 与 get-or-create 复用兼容；abandoned 后再点同岗位正常新建（R3）

全程 LLM_PROVIDER=mock 离线（不出现任何 LLM 调用——会话只建不答）；DB 用临时文件，
不碰 data/app.db。运行：cd server && python -m pytest test_candidate_history.py -v
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# 必须在 import server 之前设环境变量（config 在 import 时读取）；单文件单库
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="cand_hist_"), "test.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.db import get_conn, init_db  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

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


def _register_candidate(username: str) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


_ADMIN = {"username": "cand_hist_admin", "password": "cand_hist_admin_pw"}


@pytest.fixture(scope="module")
def admin_headers():
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


def _admin_user_id(headers: dict) -> str:
    """登录态取 admin user_id（review 审计字段断言用——同 token 主体）。"""
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


# ---------- 种子 ----------

def _seed_position(position_name: str) -> str:
    pid = new_id("pos")
    _exec(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, position_name, "active", now_iso()),
    )
    return pid


def _seed_confirmed_model(pid: str) -> str:
    """active 岗位 + confirmed 模型（单 hard 项）+ 12 行 active 题行（readiness 可通过）。

    返回 model_id。题行三 tier 循环落（12=4×3），readiness 的 tier 配额公式可满足。
    """
    conn = get_conn()
    try:
        model_id = new_id("cm")
        now = now_iso()
        items = [{"std_name": "Python", "category": "hard_skill",
                  "importance": "required", "weight": 1.0, "required_level": 3}]
        model_json = {"position_id": pid, "version": 1, "items": items}
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (model_id, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
        )
        for it in items:
            conn.execute(
                "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
                " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
                (new_id("c"), model_id, it["std_name"], it["category"], 3,
                 it["importance"], it["weight"], 0),
            )
        for i in range(12):
            tier = ["easy", "medium", "hard"][i % 3]
            conn.execute(
                "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version,"
                " std_name, category, difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (new_id("qb"), "position", pid, model_id, 1, "Python", "hard_skill",
                 tier, "subjective", f"Python 场景题 {i}",
                 None, "场景/方法/结果", "human", "active", now),
            )
        conn.commit()
        return model_id
    finally:
        conn.close()


def _create_session(pid: str, headers: dict) -> dict:
    """POST /sessions 薄封装（get-or-create 两形态均可，失败抛断言）。"""
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _seed_answered_question(sid: str, seq: int) -> str:
    """给会话直插一行已答 assessment_question（answered_count 口径断言用）。

    bank_question_id NOT NULL——挂任意存续题库行（直插种子不进选题四层，FK 合法即可）。
    """
    bank_qid = _q("SELECT question_id FROM question_bank LIMIT 1")[0]["question_id"]
    question_id = new_id("aq")
    _exec(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, item_id,"
        " seq, status, activated_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (question_id, sid, bank_qid, None, seq, "answered", now_iso(), now_iso(), now_iso()),
    )
    return question_id


def _seed_open_question(sid: str, seq: int) -> str:
    """给会话直插一行未答（answered_at NULL）的 assessment_question。"""
    bank_qid = _q("SELECT question_id FROM question_bank LIMIT 1")[0]["question_id"]
    question_id = new_id("aq")
    _exec(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, item_id,"
        " seq, status, activated_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (question_id, sid, bank_qid, None, seq, "active", now_iso(), None, now_iso()),
    )
    return question_id


def _age_session(sid: str, hours: float) -> None:
    """时间旅行：把会话的 created_at/last_activity_at 拨到 hours 小时前（sweep 断言用）。"""
    old = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    _exec(
        "UPDATE assessment_session SET created_at=?, last_activity_at=? WHERE session_id=?",
        (old, old, sid),
    )


def _seed_overdue_active_interval(sid: str, started_hours_ago: float = 2.0,
                                 ended_hours_ago: float = 1.0) -> None:
    """时间旅行（超时收尾 sweep 用）：给会话直插一段已闭合的 active 区间，
    Σactive = started-eded 差（>40min 即超时；模拟「人回来过但已超时离开」）。"""
    started = (datetime.now(timezone.utc) - timedelta(hours=started_hours_ago)).isoformat()
    ended = (datetime.now(timezone.utc) - timedelta(hours=ended_hours_ago)).isoformat()
    _exec(
        "INSERT INTO session_time_intervals(interval_id, session_id, interval_type,"
        " started_at, ended_at) VALUES(?,?,?,?,?)",
        (new_id("sti"), sid, "active", started, ended),
    )


# ---------- get-or-create（SSOT §12.1 2026-09-08 裁决）----------

def test_get_or_create_no_in_progress_creates_201():
    """无在途 → 201 新建 + resumed=False（estimated_duration_minutes 保持现状）。"""
    pid = _seed_position(f"岗位GOC新建{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"goc_new_{new_id('u')[-6:]}")

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["resumed"] is False
    assert body["estimated_duration_minutes"] is not None
    assert _q("SELECT COUNT(*) c FROM assessment_session WHERE session_id=?",
              (body["session_id"],))[0]["c"] == 1


def test_get_or_create_resumes_in_progress_200():
    """同 (user, position) 在途 → 200 同 session_id / resumed=True / 行数守恒（不重复 INSERT）。"""
    pid = _seed_position(f"岗位GOC复用{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"goc_resume_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    r2 = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r2.status_code == 200, f"复用应 HTTP 200，实得 {r2.status_code}"
    body2 = r2.json()
    assert body2["session_id"] == body1["session_id"]
    assert body2["resumed"] is True
    # 行数守恒：复用路径不得插入新行
    count = _q("SELECT COUNT(*) c FROM assessment_session WHERE position_id=?", (pid,))[0]["c"]
    assert count == 1, f"复用路径不得插入新行，实得 {count} 行"


def test_get_or_create_resumes_pending_start():
    """PENDING_START 在途复用（用户创建后未点开始就退出——再入见入场确认门，Chat.vue 逻辑）。"""
    pid = _seed_position(f"岗位GOCPENDING{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"goc_pending_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    sess = _q("SELECT phase FROM assessment_session WHERE session_id=?", (body1["session_id"],))[0]
    assert sess["phase"] == "PENDING_START"

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 200, r.text
    body2 = r.json()
    assert body2["session_id"] == body1["session_id"]
    assert body2["resumed"] is True


def test_get_or_create_resumes_skips_readiness():
    """复用路径豁免 readiness：在途行存在时把该岗位题库全清（新造本应 409 INCOMPLETE），
    POST /sessions 仍 200 复用原会话（§12.1 在途豁免——与 §9.2 归档裁决同精神）。"""
    pid = _seed_position(f"岗位GOC豁免{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"goc_ready_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    # 清空题库（archive 走 SSOT §9.2 状态语义，不复用已退役的删除语义）
    _exec("UPDATE question_bank SET status='archived' WHERE position_id=? AND status='active'", (pid,))

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 200, r.text
    body2 = r.json()
    assert body2["session_id"] == body1["session_id"]
    assert body2["resumed"] is True
    # 对照组：无在途用户在同岗位新建 → readiness 照常 409（既有路径不动）
    headers_b = _register_candidate(f"goc_ready_b_{new_id('u')[-6:]}")
    r_b = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers_b)
    assert r_b.status_code == 409, r_b.text
    assert r_b.json()["detail"]["error_code"] == "QUESTION_BANK_INCOMPLETE"


def test_get_or_create_stale_swept_then_new():
    """在途超 6h → create 复用查询前 sweep 转 abandoned → 不复用，新建新场 201。"""
    pid = _seed_position(f"岗位GOC超时{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"goc_stale_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    _age_session(body1["session_id"], hours=7)  # > ABANDON_HOURS=6

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    body2 = r.json()
    assert body2["session_id"] != body1["session_id"]
    assert body2["resumed"] is False
    # 旧会话被 sweep 成 abandoned，不删证据
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?",
              (body1["session_id"],))[0]
    assert sess["status"] == "abandoned"
    events = _q(
        "SELECT from_state, to_state FROM assessment_state_event"
        " WHERE session_id=? AND event_type='SESSION_ABANDONED'",
        (body1["session_id"],),
    )
    assert events, "sweep 作废应落 SESSION_ABANDONED 事件"
    assert events[0]["from_state"] == "in_progress"
    assert events[0]["to_state"] == "abandoned"


def test_sweep_mounted_on_create(monkeypatch):
    """create_session 复用查询前调用 sweep（挂载点之一——spy 断言，不信任实现自证）。"""
    from server.api import assessment as assessment_module
    from server.services import timer

    calls: list[str] = []
    real = timer.sweep_user_stale_sessions

    def spy(conn, user_id):
        calls.append(user_id)
        return real(conn, user_id)

    monkeypatch.setattr(assessment_module, "sweep_user_stale_sessions", spy)

    pid = _seed_position(f"岗位挂载{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"mount_{new_id('u')[-6:]}")

    who = client.get("/api/auth/me", headers=headers).json()
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    assert who["user_id"] in calls, f"create_session 未对本用户跑 sweep，实得 {calls}"


def test_sweep_mounted_on_history(monkeypatch):
    """历史端点列出前调用 sweep（挂载点之二）。"""
    from server.api import assessment as assessment_module
    from server.services import timer

    calls: list[str] = []
    real = timer.sweep_user_stale_sessions

    def spy(conn, user_id):
        calls.append(user_id)
        return real(conn, user_id)

    monkeypatch.setattr(assessment_module, "sweep_user_stale_sessions", spy)

    headers = _register_candidate(f"mount_hist_{new_id('u')[-6:]}")
    who = client.get("/api/auth/me", headers=headers).json()
    r = client.get("/api/assessment/sessions", headers=headers)
    assert r.status_code == 200, r.text
    assert who["user_id"] in calls, f"历史端点未对本用户跑 sweep，实得 {calls}"


# ---------- 历史端点（R4 / §12.1）----------

def test_history_envelope_and_fields():
    """{items,total} 信封 + 行字段（position_name join / answered_count / PENDING_START
    行 session_elapsed_seconds=None / ended_at/abandoned_at）。"""
    pid = _seed_position(f"岗位历史字段{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"hist_fields_{new_id('u')[-6:]}")
    pos_name = _q("SELECT name FROM position WHERE position_id=?", (pid,))[0]["name"]

    body1 = _create_session(pid, headers)
    _seed_answered_question(body1["session_id"], seq=1)
    # 再插一行未答（answered_at NULL——answered_count 只计非空）
    _seed_open_question(body1["session_id"], seq=2)

    r = client.get("/api/assessment/sessions", headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data.keys()) == {"items", "total"}, data.keys()
    row = [it for it in data["items"] if it["session_id"] == body1["session_id"]][0]
    assert row["position_id"] == pid
    assert row["position_name"] == pos_name
    assert row["model_version"] == 1
    assert row["status"] == "in_progress"
    assert row["phase"] == "PENDING_START"
    assert row["answered_count"] == 1
    # PENDING_START 行同为 in_progress——elapsed 有读数（无 active 区间自然为 0.0）
    assert row["session_elapsed_seconds"] is not None
    assert row["session_elapsed_seconds"] == 0
    assert row["ended_at"] is None
    assert row["abandoned_at"] is None


def test_history_active_row_elapsed_seconds():
    """进行中且已 start 的行 session_elapsed_seconds 非空（ACTIVE 区间读数）。"""
    pid = _seed_position(f"岗位历史计时{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"hist_elapsed_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    r = client.post(f"/api/assessment/sessions/{body1['session_id']}/start", headers=headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/assessment/sessions", headers=headers)
    row = [it for it in r.json()["items"]
           if it["session_id"] == body1["session_id"]][0]
    assert row["session_elapsed_seconds"] is not None
    assert row["session_elapsed_seconds"] >= 0


def test_history_pagination_filter_sort():
    """分页 {items,total}（默认 1/20）/ status 过滤（三值+空=全部）/ created_at DESC / 翻页衔接。

    同一用户同岗位连续 create 会被 get-or-create 复用——五行种子各用独立岗位，
    created_at 随插入顺序严格递增（排序断言前提）。
    """
    headers = _register_candidate(f"hist_page_{new_id('u')[-6:]}")
    pids = [_seed_position(f"岗位分页{i}{new_id('s')[-4:]}") for i in range(5)]
    for pid in pids:
        _seed_confirmed_model(pid)
        _create_session(pid, headers)

    sid_completed = _q("SELECT session_id FROM assessment_session WHERE position_id=?", (pids[3],))[0]["session_id"]
    _exec("UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
          (now_iso(), sid_completed))
    sid_abandoned = _q("SELECT session_id FROM assessment_session WHERE position_id=?", (pids[4],))[0]["session_id"]
    _exec("UPDATE assessment_session SET status='abandoned', abandoned_at=? WHERE session_id=?",
          (now_iso(), sid_abandoned))

    # 信封 + 全量（默认 page_size=20，全 5 行在同页）
    r = client.get("/api/assessment/sessions", headers=headers)
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 5

    # 过滤 in_progress：恰 3 行
    r = client.get("/api/assessment/sessions", params={"status": "in_progress"}, headers=headers)
    data = r.json()
    assert data["total"] == 3
    assert all(it["status"] == "in_progress" for it in data["items"])

    # 过滤 completed：1 行 + ended_at 非空
    r = client.get("/api/assessment/sessions", params={"status": "completed"}, headers=headers)
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["session_id"] == sid_completed
    assert data["items"][0]["ended_at"] is not None

    # 过滤 abandoned：1 行 + abandoned_at 非空
    r = client.get("/api/assessment/sessions", params={"status": "abandoned"}, headers=headers)
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["session_id"] == sid_abandoned
    assert data["items"][0]["abandoned_at"] is not None

    # status 空 = 全部（不过滤）
    r = client.get("/api/assessment/sessions", params={"status": ""}, headers=headers)
    assert r.json()["total"] == 5

    # 排序 created_at DESC（ISO 字符串字典序即时间序）
    items = client.get("/api/assessment/sessions", headers=headers).json()["items"]
    created_list = [it["created_at"] for it in items]
    assert created_list == sorted(created_list, reverse=True), created_list

    # 分页：page_size=2 → 3 页，翻页衔接不重叠（共 5 行）
    r1 = client.get("/api/assessment/sessions", params={"page_size": 2, "page": 1}, headers=headers).json()
    r2 = client.get("/api/assessment/sessions", params={"page_size": 2, "page": 2}, headers=headers).json()
    r3 = client.get("/api/assessment/sessions", params={"page_size": 2, "page": 3}, headers=headers).json()
    assert r1["total"] == r2["total"] == r3["total"] == 5
    assert len(r1["items"]) == 2 and len(r2["items"]) == 2 and len(r3["items"]) == 1
    ids1 = {it["session_id"] for it in r1["items"]}
    ids2 = {it["session_id"] for it in r2["items"]}
    assert not ids1 & ids2
    # page_size 超限钳到 MAX_PAGINATION_LIMIT=100、page=0 钳到 1，仍 200
    r4 = client.get("/api/assessment/sessions", params={"page_size": 9999, "page": 0}, headers=headers)
    assert r4.status_code == 200, r4.text
    assert r4.json()["total"] == 5


def test_history_owner_isolation():
    """本人所有权（§7 列表级）：B 的列表看不到 A 的会话。"""
    pid = _seed_position(f"岗位历史隔离{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers_a = _register_candidate(f"hist_iso_a_{new_id('u')[-6:]}")
    headers_b = _register_candidate(f"hist_iso_b_{new_id('u')[-6:]}")

    body_a = _create_session(pid, headers_a)
    r = client.get("/api/assessment/sessions", headers=headers_b)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 0
    assert all(it["session_id"] != body_a["session_id"] for it in data["items"])


def test_history_sweep_marks_abandoned():
    """历史端点前置 sweep：超 6h 的「不回来的会话」在历史如实显示已作废。"""
    pid = _seed_position(f"岗位历史作废{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"hist_sweep_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    _age_session(body1["session_id"], hours=7)

    r = client.get("/api/assessment/sessions", headers=headers)
    assert r.status_code == 200, r.text
    row = [it for it in r.json()["items"] if it["session_id"] == body1["session_id"]]
    assert row, "历史应含该行（abandoned 行仍列出，不删证据）"
    assert row[0]["status"] == "abandoned"
    assert row[0]["abandoned_at"] is not None


# ---------- positions active_session 摘要（§12.6）----------

def test_positions_active_session_summary():
    """列表每行附 active_session {session_id, phase, remaining_minutes}；无在途岗位 null；
    他人会话不出现在自己的摘要里。"""
    pid_a = _seed_position(f"岗位摘要A{new_id('s')[-6:]}")
    _seed_confirmed_model(pid_a)
    pid_b = _seed_position(f"岗位摘要B{new_id('s')[-6:]}")
    _seed_confirmed_model(pid_b)
    headers = _register_candidate(f"list_summary_{new_id('u')[-6:]}")

    body_a = _create_session(pid_a, headers)

    r = client.get("/api/assessment/positions", headers=headers)
    assert r.status_code == 200, r.text
    rows = {p["position_id"]: p for p in r.json()}
    assert set(rows[pid_a].keys()) >= {"position_id", "name", "version", "model_id",
                                       "item_count", "active_session"}
    active = rows[pid_a]["active_session"]
    assert active is not None
    assert active["session_id"] == body_a["session_id"]
    assert active["phase"] == "PENDING_START"
    assert active["remaining_minutes"] == 40  # 未 start：active 区间 0 秒 → 剩余满额

    # 无在途岗位 → null
    assert rows[pid_b]["active_session"] is None

    # 他人（新用户）视角：A 的在途摘要不出现在其列表
    headers_other = _register_candidate(f"list_other_{new_id('u')[-6:]}")
    r2 = client.get("/api/assessment/positions", headers=headers_other)
    rows_other = {p["position_id"]: p for p in r2.json()}
    assert rows_other[pid_a]["active_session"] is None


def test_positions_active_session_after_start_and_pause():
    """start 后 ACTIVE 态剩余 40（秒级流逝 int 截断）；pause 后相位 PAUSED 仍展示。"""
    pid = _seed_position(f"岗位摘要计时{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"list_minutes_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    r = client.post(f"/api/assessment/sessions/{body1['session_id']}/start", headers=headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/assessment/positions", headers=headers)
    row = [p for p in r.json() if p["position_id"] == pid][0]
    assert row["active_session"]["phase"] == "ACTIVE"
    # 刚 start 秒级流逝：剩余仍在满额附近（<1 分钟内可能 39 或 40，取区间断言）
    assert 39 <= row["active_session"]["remaining_minutes"] <= 40

    r = client.post(f"/api/assessment/sessions/{body1['session_id']}/pause", headers=headers)
    assert r.status_code == 200, r.text
    r = client.get("/api/assessment/positions", headers=headers)
    row = [p for p in r.json() if p["position_id"] == pid][0]
    assert row["active_session"]["phase"] == "PAUSED"


def test_positions_active_session_null_after_sweep():
    """sweep 作废（经 create/历史挂载点触发）后岗位摘要回落 null——abandoned 行不在
    in_progress 派生源。sweep 只挂 create 复用查询前与历史列出前（R8 两点），
    positions 端点自身不跑 sweep（by-design），故先经历史端点触发。"""
    pid = _seed_position(f"岗位摘要作废{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"list_swept_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    r = client.get("/api/assessment/positions", headers=headers)
    assert [p for p in r.json() if p["position_id"] == pid][0]["active_session"] is not None

    _age_session(body1["session_id"], hours=7)
    # 经历史端点触发 sweep（挂载点二）后再看岗位摘要
    r = client.get("/api/assessment/sessions", headers=headers)
    assert r.status_code == 200, r.text
    r = client.get("/api/assessment/positions", headers=headers)
    assert [p for p in r.json() if p["position_id"] == pid][0]["active_session"] is None


# ---------- 全场超时收尾 sweep（SSOT §12.6，2026-09-08）----------

def _overdue_in_progress_session(headers: dict) -> tuple[str, str]:
    """造一场 in_progress 且 Σactive 超 40 分钟的会话（active 区间 1h 前开、0.5h 前闭
    ——Σactive=30min 不超时？不：started 2h 前 ended 1h 前即 Σ=1h>40min 超时）。"""
    pid = _seed_position(f"岗位收尾超时{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    body = _create_session(pid, headers)
    _seed_overdue_active_interval(body["session_id"])
    return pid, body["session_id"]


def test_sweep_timeout_finalizes_via_positions():
    """超时会话（Σactive>40min，人不再回来）→ GET positions（挂载点三）→ 会话收尾
    completed + 0 分报告 + 事件序 GLOBAL_TIMEOUT < ENTERED_SCORING < COMPLETED +
    岗位摘要 active_session=null（「继续测评·回到中断处」入口消失——问题②）。"""
    headers = _register_candidate(f"sweep_to_{new_id('u')[-6:]}")
    pid, sid = _overdue_in_progress_session(headers)

    # 挂载点三即首个触发点（此前 sweep 只挂 create/历史——positions 不触发时
    # 「人不回来」的超时会话永挂 in_progress，岗位卡留「继续测评」入口——问题②）
    r = client.get("/api/assessment/positions", headers=headers)
    assert r.status_code == 200, r.text
    row = [p for p in r.json() if p["position_id"] == pid][0]
    assert row["active_session"] is None, "超时死会话收尾后岗位摘要不得留继续入口"

    sess = _q("SELECT status, phase FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed", sess
    assert sess["phase"] == "SCORING", sess
    # 0 分报告行（收尾链同步 _generate_report_task——D-005 演示约定，TestClient 同步执行）
    reports = _q("SELECT report_status FROM report WHERE session_id=?", (sid,))
    assert reports, "超时收尾应生成报告行"
    assert reports[0]["report_status"] in ("READY", "PROVISIONAL", "PUBLISHED"), reports[0]
    # 事件序（与 answer 路径收尾链完全同构——Pitfall 11 GLOBAL_TIMEOUT 最先）
    evs = _q("SELECT event_type, sequence_no FROM assessment_state_event"
             " WHERE session_id=? ORDER BY sequence_no", (sid,))
    gt = next(e for e in evs if e["event_type"] == "SESSION_GLOBAL_TIMEOUT")
    es = next(e for e in evs if e["event_type"] == "SESSION_ENTERED_SCORING")
    cp = next(e for e in evs if e["event_type"] == "SESSION_COMPLETED")
    assert gt["sequence_no"] < es["sequence_no"] < cp["sequence_no"], \
        f"GLOBAL_TIMEOUT < ENTERED_SCORING < COMPLETED，实得 {[e['event_type'] for e in evs]}"
    # 0 分：超时收尾不产生已答题，total_score 保持 0 占位
    rpt = _q("SELECT total_score FROM report WHERE session_id=?", (sid,))[0]
    assert rpt["total_score"] == 0.0


def test_sweep_timeout_then_create_new_session():
    """超时会话 → POST /sessions（挂载点一 create 复用查询前）→ 不复用超时会话，
    新建新场（201 resumed=False）——复用查询不命中自然开新，SSOT §12.6。"""
    headers = _register_candidate(f"sweep_cr_{new_id('u')[-6:]}")
    pid, sid = _overdue_in_progress_session(headers)

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["session_id"] != sid
    assert body["resumed"] is False
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed", "sweep（挂载点一）应已把超时会话收尾 completed"


def test_sweep_pending_start_over_6h_abandoned_not_finalized():
    """PENDING_START 且超 6h 无活动 → 走 abandoned（不生成报告）——先 abandon 后收尾
    的固定顺序：超 6h 的行第一段翻终态，第二段收尾查询（status='in_progress'）
    不再命中（作废无报告，§12.6「超 6h 的走作废（无报告）」）。"""
    pid = _seed_position(f"岗位收尾作废{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"sweep_ps_{new_id('u')[-6:]}")

    body = _create_session(pid, headers)
    _age_session(body["session_id"], hours=7)  # PENDING_START + 超 6h 无活动

    r = client.get("/api/assessment/positions", headers=headers)
    assert r.status_code == 200, r.text
    sess = _q("SELECT status, phase FROM assessment_session WHERE session_id=?",
              (body["session_id"],))[0]
    assert sess["status"] == "abandoned", sess
    assert sess["phase"] == "ABANDONED", sess
    assert not _q("SELECT 1 FROM report WHERE session_id=?", (body["session_id"],)), \
        "超 6h 走作废（无报告），不得走收尾完赛"
    row = [p for p in r.json() if p["position_id"] == pid][0]
    assert row["active_session"] is None


def test_sweep_pending_start_not_timed_out_keeps_resume_entry():
    """PENDING_START 未超时（Σactive=0、last_activity 新）→ 岗位摘要照常给出继续入口
    （active_session 非 null、phase=PENDING_START）——收尾 sweep 不误伤入场确认门。"""
    pid = _seed_position(f"岗位收尾PENDING{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"sweep_pn_{new_id('u')[-6:]}")
    body = _create_session(pid, headers)

    r = client.get("/api/assessment/positions", headers=headers)
    assert r.status_code == 200, r.text
    row = [p for p in r.json() if p["position_id"] == pid][0]
    assert row["active_session"] is not None
    assert row["active_session"]["session_id"] == body["session_id"]
    assert row["active_session"]["phase"] == "PENDING_START"
    # 剩余 = 全场满额 40 分钟
    assert row["active_session"]["remaining_minutes"] == 40
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?",
              (body["session_id"],))[0]
    assert sess["status"] == "in_progress"


def test_sweep_active_not_timed_out_summary_unchanged():
    """在途未超时会话（ACTIVE、Σactive 秒级）→ 岗位摘要不变（回归：活动中的会话
    不被 sweep 翻状态，active_session 照常给 phase 与剩余分钟）。"""
    pid = _seed_position(f"岗位收尾在途{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"sweep_ac_{new_id('u')[-6:]}")
    body = _create_session(pid, headers)
    r = client.post(f"/api/assessment/sessions/{body['session_id']}/start", headers=headers)
    assert r.status_code == 200, r.text

    r = client.get("/api/assessment/positions", headers=headers)
    assert r.status_code == 200, r.text
    row = [p for p in r.json() if p["position_id"] == pid][0]
    active = row["active_session"]
    assert active is not None and active["session_id"] == body["session_id"]
    assert active["phase"] == "ACTIVE"
    assert 39 <= active["remaining_minutes"] <= 40
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?",
              (body["session_id"],))[0]
    assert sess["status"] == "in_progress"


# ---------- 软删除（SSOT §12.1，2026-09-08）----------

def test_delete_completed_session_hides_for_owner(admin_headers):
    """DELETE completed 会话 → 200；owner 历史不出该行、GET /sessions/{id} 404、
    GET /reports/by-session/{id} 404；admin（allow_admin_read 读豁免）仍可 200。"""
    pid = _seed_position(f"岗位删除完赛{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"del_c_{new_id('u')[-6:]}")
    sid = _create_session(pid, headers)["session_id"]
    _exec("UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
          (now_iso(), sid))

    r = client.delete(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True

    # owner 历史不出该行（total 计数同步不含）
    data = client.get("/api/assessment/sessions", headers=headers).json()
    assert all(it["session_id"] != sid for it in data["items"])
    assert data["total"] == 0

    # owner 深度链接 404（会话与报告 bootstrap——load_owned_* owner 分支 hidden 过滤）
    assert client.get(f"/api/assessment/sessions/{sid}", headers=headers).status_code == 404
    assert client.get(f"/api/assessment/reports/by-session/{sid}",
                      headers=headers).status_code == 404

    # admin 读豁免仍可见（管理端审计全量可见——豁免分支不过滤）
    r = client.get(f"/api/assessment/sessions/{sid}", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == sid

    # 事件留痕：SESSION_HIDDEN from=completed to=hidden actor=candidate
    evs = _q("SELECT from_state, to_state FROM assessment_state_event"
             " WHERE session_id=? AND event_type='SESSION_HIDDEN'", (sid,))
    assert evs and evs[0]["from_state"] == "completed"
    assert evs[0]["to_state"] == "hidden"


def test_delete_in_progress_session_abandons_then_hides():
    """DELETE in_progress 会话 → 200；SESSION_ABANDONED（actor=candidate 用户主动作废）
    与 SESSION_HIDDEN 两事件并存；status=abandoned + hidden_at 非空；岗位摘要不再给
    继续入口。"""
    pid = _seed_position(f"岗位删除在途{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"del_i_{new_id('u')[-6:]}")
    sid = _create_session(pid, headers)["session_id"]
    # start 后再删（ACTIVE 在途，验证用户主动作废覆盖计时中途态）
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=headers)
    assert r.status_code == 200, r.text

    r = client.delete(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text

    sess = _q("SELECT status, phase, hidden_at, abandoned_at FROM assessment_session"
              " WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "abandoned", sess
    assert sess["phase"] == "ABANDONED", sess
    assert sess["hidden_at"] is not None
    assert sess["abandoned_at"] is not None

    evs = _q("SELECT event_type, actor_type FROM assessment_state_event"
             " WHERE session_id=? AND event_type IN"
             " ('SESSION_ABANDONED','SESSION_HIDDEN') ORDER BY sequence_no", (sid,))
    assert [e["event_type"] for e in evs] == ["SESSION_ABANDONED", "SESSION_HIDDEN"], evs
    assert all(e["actor_type"] == "candidate" for e in evs)

    # 岗位摘要不再给继续入口（隐藏行不计——§12.1）
    r = client.get("/api/assessment/positions", headers=headers)
    row = [p for p in r.json() if p["position_id"] == pid][0]
    assert row["active_session"] is None


def test_delete_session_idempotent():
    """重复 DELETE 已 hidden 行 → 幂等 200（不重复写事件——同 evidence-exclusions
    lift 先例）。"""
    pid = _seed_position(f"岗位删除幂等{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"del_d_{new_id('u')[-6:]}")
    sid = _create_session(pid, headers)["session_id"]
    _exec("UPDATE assessment_session SET status='abandoned', phase='ABANDONED',"
          " abandoned_at=? WHERE session_id=?", (now_iso(), sid))

    r1 = client.delete(f"/api/assessment/sessions/{sid}", headers=headers)
    r2 = client.delete(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    events = _q("SELECT COUNT(*) c FROM assessment_state_event"
                " WHERE session_id=? AND event_type='SESSION_HIDDEN'", (sid,))[0]["c"]
    assert events == 1, "重复 DELETE 不得重复写 SESSION_HIDDEN 事件"


def test_delete_session_owner_isolation():
    """删除他人会话 → 404（owner-only 写——load_owned_session 不传 allow_admin_read）。"""
    pid = _seed_position(f"岗位删除越权{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers_a = _register_candidate(f"del_a_{new_id('u')[-6:]}")
    headers_b = _register_candidate(f"del_b_{new_id('u')[-6:]}")
    sid = _create_session(pid, headers_a)["session_id"]

    r = client.delete(f"/api/assessment/sessions/{sid}", headers=headers_b)
    assert r.status_code == 404, r.text
    sess = _q("SELECT hidden_at FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["hidden_at"] is None, "越权删除不得写 hidden_at"


def test_history_list_excludes_hidden_rows():
    """GET /sessions 列表不含 hidden 行（含 total 计数）——软删除行从本人历史消失。"""
    pid_a = _seed_position(f"岗位隐藏A{new_id('s')[-6:]}")
    _seed_confirmed_model(pid_a)
    pid_b = _seed_position(f"岗位隐藏B{new_id('s')[-6:]}")
    _seed_confirmed_model(pid_b)
    headers = _register_candidate(f"del_l_{new_id('u')[-6:]}")
    sid_a = _create_session(pid_a, headers)["session_id"]
    sid_b = _create_session(pid_b, headers)["session_id"]

    # 删除前：2 行
    data = client.get("/api/assessment/sessions", headers=headers).json()
    assert data["total"] == 2

    r = client.delete(f"/api/assessment/sessions/{sid_a}", headers=headers)
    assert r.status_code == 200, r.text
    data = client.get("/api/assessment/sessions", headers=headers).json()
    assert data["total"] == 1
    ids = [it["session_id"] for it in data["items"]]
    assert sid_a not in ids and sid_b in ids


# ---------- suggestion（§22.1）----------

def test_suggestion_submit_and_my_list_isolation():
    """提交 201 + GET 本人历史（DESC）只含自己的行 + status pending 可见。"""
    headers_a = _register_candidate(f"sug_a_{new_id('u')[-6:]}")
    headers_b = _register_candidate(f"sug_b_{new_id('u')[-6:]}")

    r = client.post("/api/assessment/suggestions", json={"text": "希望能导出 PDF 报告"},
                    headers=headers_a)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    sid = body["suggestion_id"]

    r = client.post("/api/assessment/suggestions", json={"text": "B的建议"}, headers=headers_b)
    assert r.status_code == 201, r.text

    rows_a = client.get("/api/assessment/suggestions", headers=headers_a).json()
    assert any(it["suggestion_id"] == sid for it in rows_a)
    assert all(it["text"] != "B的建议" for it in rows_a)
    assert all(it["status"] in ("pending", "reviewed") for it in rows_a)
    # DESC：后提交的在前（A 只有一条，B 单独验证）
    rows_b = client.get("/api/assessment/suggestions", headers=headers_b).json()
    assert rows_b and rows_b[0]["text"] == "B的建议"


def test_suggestion_validation_422():
    """空文本 422 / 缺 text 422 / 超长（2001）422 / 边界 2000 放行。"""
    headers = _register_candidate(f"sug_v_{new_id('u')[-6:]}")
    r = client.post("/api/assessment/suggestions", json={"text": "   "}, headers=headers)
    assert r.status_code == 422, r.text
    r = client.post("/api/assessment/suggestions", json={"text": "x" * 2001}, headers=headers)
    assert r.status_code == 422, r.text
    r = client.post("/api/assessment/suggestions", json={}, headers=headers)
    assert r.status_code == 422, r.text
    r = client.post("/api/assessment/suggestions", json={"text": "x" * 2000}, headers=headers)
    assert r.status_code == 201, r.text


def test_suggestion_admin_review_flow(admin_headers):
    """admin list（status 过滤）+ review（status→reviewed + note + reviewer/reviewed_at
    审计字段）+ 不存在 404 + 候选人视角处理进度。"""
    headers = _register_candidate(f"sug_flow_{new_id('u')[-6:]}")
    sid = client.post("/api/assessment/suggestions", json={"text": "希望新增导出功能"},
                      headers=headers).json()["suggestion_id"]

    # list：pending 过滤命中
    r = client.get("/api/admin/suggestions", params={"status": "pending"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    row = [it for it in r.json() if it["suggestion_id"] == sid]
    assert row and row[0]["status"] == "pending"
    assert row[0]["review_note"] is None

    # review → reviewed + 审计三列
    r = client.post(f"/api/admin/suggestions/{sid}/review",
                    json={"note": "已排进下期迭代"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reviewed"

    r = client.get("/api/admin/suggestions", params={"status": "reviewed"}, headers=admin_headers)
    row = [it for it in r.json() if it["suggestion_id"] == sid][0]
    assert row["review_note"] == "已排进下期迭代"
    assert row["reviewer_id"] == _admin_user_id(admin_headers)
    assert row["reviewed_at"] is not None
    # pending 过滤不再命中
    r = client.get("/api/admin/suggestions", params={"status": "pending"}, headers=admin_headers)
    assert all(it["suggestion_id"] != sid for it in r.json())

    # 候选人视角：状态 + 处理备注
    mine = client.get("/api/assessment/suggestions", headers=headers).json()
    me_row = [it for it in mine if it["suggestion_id"] == sid][0]
    assert me_row["status"] == "reviewed"
    assert me_row["review_note"] == "已排进下期迭代"
    assert me_row["reviewed_at"] is not None

    # 不存在 id → 404
    r = client.post("/api/admin/suggestions/sug_nonexistent/review",
                    json={"note": "x"}, headers=admin_headers)
    assert r.status_code == 404, r.text


def test_suggestion_admin_list_no_filter_is_all(admin_headers):
    """admin list 不带 status = 全部（空参数语义）。"""
    headers = _register_candidate(f"sug_all_{new_id('u')[-6:]}")
    client.post("/api/assessment/suggestions", json={"text": "建议一"}, headers=headers)
    r = client.get("/api/admin/suggestions", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list) and len(r.json()) >= 1


def test_suggestion_candidate_forbidden_on_admin():
    """candidate 访问 admin suggestion 两端点 → 403。"""
    headers = _register_candidate(f"sug_f_{new_id('u')[-6:]}")
    r = client.get("/api/admin/suggestions", headers=headers)
    assert r.status_code == 403, r.text
    r = client.post("/api/admin/suggestions/sug_x/review", json={"note": "n"}, headers=headers)
    assert r.status_code == 403, r.text


# ---------- 回归：pause/resume/abandon 既有行为不破 ----------

def test_regression_pause_resume_with_get_or_create():
    """start→pause→再入 create（复用同 id）→resume 回 ACTIVE（既有端点语义不动）。"""
    pid = _seed_position(f"岗位回归暂停{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"reg_pr_{new_id('u')[-6:]}")

    sid = _create_session(pid, headers)["session_id"]
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=headers)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/assessment/sessions/{sid}/pause", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["phase"] == "PAUSED"

    # 再入（get-or-create）：PAUSED 在途行同样复用
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == sid

    r = client.post(f"/api/assessment/sessions/{sid}/resume", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["phase"] == "ACTIVE"


def test_regression_abandoned_never_resumed_by_create():
    """abandoned 后再点同岗位 = 正常新建一场（R3 维持现行为——历史多行并存，无重测门）。"""
    pid = _seed_position(f"岗位回归作废{new_id('s')[-6:]}")
    _seed_confirmed_model(pid)
    headers = _register_candidate(f"reg_ab_{new_id('u')[-6:]}")

    body1 = _create_session(pid, headers)
    _exec("UPDATE assessment_session SET status='abandoned', phase='ABANDONED', abandoned_at=?"
          " WHERE session_id=?", (now_iso(), body1["session_id"]))

    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    body2 = r.json()
    assert body2["session_id"] != body1["session_id"]
    assert body2["resumed"] is False
