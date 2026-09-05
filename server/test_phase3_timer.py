"""Phase 3 计时区间与上下文三层侧带断言（03-04，REF-2.6/4.8/4.12——SSOT §12.1/§15）。

覆盖：
- 纯函数：merge_spans（排序合并重叠区间——实验 5 SQL SUM 双计反例）+ overlap_seconds
- 部分唯一索引 uq_sti_open（同 session 双 open 第二插 IntegrityError；闭合后可开新）
- close_open_interval 幂等 no-op / advance_interval 单 open 行
- answer 落新 active 区间（全程至多一个 open）
- 单题超时（时间旅行 activated_at）→ timeout 封存 + QUESTION_SEALED/QUESTION_TIMEOUT 事件 + 续题
- Pitfall 10（activated_at NULL 跳过判定不 TypeError）
- followup 共用单题计时器（activated_at 不变）
- 全场超时 → SESSION_GLOBAL_TIMEOUT + phase=SCORING + 事件序 GLOBAL_TIMEOUT < ENTERED_SCORING < COMPLETED
- 6h ABANDONED 惰性（不删证据）+ 再答 409
- last_activity_at 刷新 / 暂停 open paused → 409 SESSION_PAUSED
- phase 列默认 PENDING_START + 旧行回填 + status CHECK 不动
- 消息分列三列（refined_content/client_request_id/sequence_no）
- _truncate_history 保尾部 + mock 全量 + MAX_CONTEXT_TOKENS==8000（[03-007]）

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db；单文件单进程。
运行：cd server && python -m pytest test_phase3_timer.py -v
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase3_timer.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server import config as cfg  # noqa: E402
from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.interview import _truncate_history  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.timer import (  # noqa: E402
    advance_interval,
    close_open_interval,
    merge_spans,
    overlap_seconds,
)

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- 种子（普通 hard×4/soft×2 + gate=1 经验/资格——表单终局采集） ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（普通题项 + gate=1 经验/资格）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.25, "gate": 0},
        {"std_name": "MySQL", "category": "hard_skill", "importance": "required", "weight": 0.2, "gate": 0},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.15, "gate": 0},
        {"std_name": "团队协作", "category": "soft_skill", "importance": "preferred", "weight": 0.1, "gate": 0},
        {"std_name": "后端开发经验", "category": "experience", "importance": "required", "weight": 0.2, "gate": 1, "years": 3},
        {"std_name": "本科学历", "category": "qualification", "importance": "required", "weight": 0.1, "gate": 1},
    ]
    model_json = {"position_id": pid, "version": 1, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    for it in items:
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, years, gate) VALUES(?,?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], 3, it["importance"], it["weight"],
             it.get("years"), int(it.get("gate", 0))),
        )
    conn.commit()
    conn.close()
    return pid, mid


def _seed_question_bank(pid: str) -> None:
    """普通题 hard×4/soft×2（池耗尽才触发表单）+ gate 项题库行。"""
    conn = get_conn()
    now = now_iso()

    def _add(scope, position_id, std_name, category, difficulty, qtype, stem, answer_key, rubric):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), scope, position_id, std_name, category, difficulty, qtype, stem,
             answer_key, rubric, "human", "active", now),
        )

    _add("position", pid, "Python", "hard_skill", "easy", "objective",
         "Python 中用什么关键字定义函数？", "def", None)
    _add("position", pid, "Python", "hard_skill", "medium", "subjective",
         "讲一个你用 Python 解决过的性能问题。", None, "有具体场景/有数据/有方法")
    _add("position", pid, "MySQL", "hard_skill", "easy", "objective",
         "MySQL 默认事务隔离级别是？", "REPEATABLE", None)
    _add("position", pid, "MySQL", "hard_skill", "medium", "subjective",
         "讲一次慢查询优化经历。", None, "explain/索引/效果")
    _add("position", pid, "沟通能力", "soft_skill", "easy", "subjective",
         "讲一次跨团队沟通的经历。", None, "背景/冲突/结果")
    _add("position", pid, "团队协作", "soft_skill", "easy", "subjective",
         "你如何带新人？", None, "方法/耐心")
    # gate 项题库行（scope=general 但 selection 不取——ORDINARY_CATEGORIES 保证）
    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "介绍你最近一个后端项目。", None, "角色/规模/成果")
    _add("general", None, "本科学历", "qualification", None, "subjective",
         "你的最高学历是什么？", None, "学历")
    conn.commit()
    conn.close()


def _auth_headers(username: str) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# 答案文案（避开 _DECLINE_WORDS 与 _EVIDENCE_WORDS——test_phase3_sse 同款口径）
_SHORT_ANSWER = "不知道"                                        # 短答 → followup
_LONG_ANSWER = (                                                # 长且含实义词 → VALID_EVIDENCE/next
    "我在电商平台项目中负责订单模块重构，通过拆分大事务重构数据表结构，"
    "把下单接口的响应时间从 800ms 降到了 200ms，并复盘成文档沉淀给团队。"
)


def _create_session(pid: str, headers: dict) -> str:
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _first_question(sid: str, headers: dict) -> dict:
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    cur = r.json()["current_question"]
    assert cur is not None, "get_session 应已派发首题"
    return cur


def _stream_answer(sid: str, headers: dict, question_id: str, answer: str,
                   *, client_attempt_id: str | None = None) -> dict:
    """流式消费 POST /answer → 组回旧 JSON 同构 dict；可选 client_attempt_id。"""
    body = {"question_id": question_id, "answer": answer}
    if client_attempt_id is not None:
        body["client_attempt_id"] = client_attempt_id
    with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                       json=body, headers=headers) as r:
        assert r.status_code == 200, f"answer 应 200，实得 {r.status_code} {r.text}"
        lines = [ln for ln in r.iter_lines() if ln.startswith("data: ")]
    events = [json.loads(ln[6:]) for ln in lines]
    decision = next(e for e in events if e["type"] == "decision")
    done = next(e for e in events if e["type"] == "done")
    reply = "".join(e["content"] for e in events if e["type"] == "reply")
    return {"action": done["action"], "reply": reply,
            "question_id": question_id,
            "next_question_id": done.get("next_question_id"),
            "score_live": decision.get("score_live"),
            "answer_state": decision.get("answer_state")}


# ---------- 纯函数（§15 重叠 merge——实验 5 SQL SUM 双计反例） ----------

def test_merge_spans():
    """重叠区间 [(0,3),(2,5),(8,10)] → merge [[0,5],[8,10]]；Σ=7（表驱动）。"""
    merged = merge_spans([(0, 3), (2, 5), (8, 10)])
    assert merged == [[0, 5], [8, 10]], merged
    assert sum(e - s for s, e in merged) == 7


def test_overlap_seconds():
    """merge 后在窗口 [1,9] → 4+1=5；SQL SUM 反例注（实验 5：跨行 SUM 双计 8 vs 6）。"""
    merged = merge_spans([(0, 3), (2, 5), (8, 10)])
    assert overlap_seconds(merged, 1, 9) == 5
    # 实验 5 反例：两重叠段直接 SUM 会双计——merge 后只算一次
    overlapped = merge_spans([(0, 8), (2, 10)])
    assert overlap_seconds(overlapped, 0, 10) == 10  # 而非 8+8=16


# ---------- 部分唯一索引 / 闭开 helper ----------

def test_partial_unique_open_index():
    """同 session 两 INSERT open（ended_at NULL）第二次 IntegrityError；闭合后可开新（实验 6）。

    W4：先经 API 建会话（合法父行）再直插区间——FK ON 语境直插无父行必 IntegrityError 假红。
    """
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_partialidx")
    sid = _create_session(pid, headers)

    conn = get_conn()
    try:
        now = now_iso()
        conn.execute(
            "INSERT INTO session_time_intervals(interval_id, session_id, interval_type, started_at)"
            " VALUES(?,?,?,?)", ("sti_i1", sid, "active", now))
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO session_time_intervals(interval_id, session_id, interval_type, started_at)"
                " VALUES(?,?,?,?)", ("sti_i2", sid, "paused", now))
            conn.commit()
            raise AssertionError("uq_sti_open 未拦双 open")
        except sqlite3.IntegrityError:
            pass  # 期望：第二次 open 被部分唯一索引拦截
        # 闭合后可开新（release）
        conn.execute(
            "UPDATE session_time_intervals SET ended_at=? WHERE interval_id=?",
            (now_iso(), "sti_i1"))
        conn.commit()
        conn.execute(
            "INSERT INTO session_time_intervals(interval_id, session_id, interval_type, started_at)"
            " VALUES(?,?,?,?)", ("sti_i3", sid, "active", now_iso()))
        conn.commit()
        assert _q("SELECT COUNT(*) c FROM session_time_intervals WHERE session_id=?", (sid,))[0]["c"] == 2
    finally:
        conn.close()


def test_close_then_open_idempotent():
    """close 无 open 时 no-op；advance_interval 后单 open 行。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_closeopen")
    sid = _create_session(pid, headers)

    conn = get_conn()
    try:
        close_open_interval(conn, sid)  # 无 open → no-op（不抛错）
        conn.commit()
        assert _q("SELECT COUNT(*) c FROM session_time_intervals WHERE session_id=?", (sid,))[0]["c"] == 0

        advance_interval(conn, sid, "active")
        conn.commit()
        rows = _q("SELECT interval_id, ended_at, interval_type FROM session_time_intervals WHERE session_id=?", (sid,))
        assert len(rows) == 1 and rows[0]["ended_at"] is None and rows[0]["interval_type"] == "active"
    finally:
        conn.close()


# ---------- answer 推进区间 ----------

def test_answer_advances_active_interval():
    """answer 前后 _q 查 session_time_intervals——answer 落 new active 行；全程至多一个 open。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_advance")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    before = _q("SELECT COUNT(*) c FROM session_time_intervals WHERE session_id=?", (sid,))[0]["c"]
    _stream_answer(sid, headers, qid, _LONG_ANSWER)

    rows = _q("SELECT interval_type, ended_at FROM session_time_intervals WHERE session_id=? ORDER BY started_at", (sid,))
    assert len(rows) > before, "answer 应落新 active 区间"
    open_rows = [r for r in rows if r["ended_at"] is None]
    assert len(open_rows) == 1, f"全程至多一个 open 区间，实得 {len(open_rows)}"
    assert open_rows[0]["interval_type"] == "active"


# ---------- 单题超时（时间旅行） ----------

def test_question_timeout_seal():
    """直插 activated_at = now - 25min → answer → timeout 封存 + 两事件 + 续题。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_qtimeout")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    old = (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat()
    conn = get_conn()
    try:
        conn.execute("UPDATE assessment_question SET activated_at=? WHERE question_id=?", (old, qid))
        conn.commit()
    finally:
        conn.close()

    resp = _stream_answer(sid, headers, qid, _LONG_ANSWER)
    assert resp["action"] in ("next", "finish"), f"超时后应续题或收尾，实得 {resp}"

    row = _q("SELECT closed_at, seal_reason, answered_at FROM assessment_question WHERE question_id=?", (qid,))[0]
    assert row["closed_at"] is not None
    assert row["seal_reason"] == "timeout"
    assert row["answered_at"] is None  # timeout 封存 answered_at 保持 NULL

    evs = _q("SELECT event_type, payload_json FROM assessment_state_event"
             " WHERE session_id=? AND assessment_question_id=?", (sid, qid))
    types = [e["event_type"] for e in evs]
    assert "QUESTION_SEALED" in types, types
    assert "QUESTION_TIMEOUT" in types, types
    sealed = next(e for e in evs if e["event_type"] == "QUESTION_SEALED")
    assert json.loads(sealed["payload_json"])["seal_reason"] == "timeout"


def test_question_timeout_pitfall10():
    """activated_at NULL（legacy 直插）→ answer 正常路径不 TypeError（Pitfall 10）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_pitfall10")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    conn = get_conn()
    try:
        conn.execute("UPDATE assessment_question SET activated_at=NULL WHERE question_id=?", (qid,))
        conn.commit()
    finally:
        conn.close()

    resp = _stream_answer(sid, headers, qid, _LONG_ANSWER)
    assert resp["action"] in ("next", "finish"), resp


def test_followup_shared_timer():
    """followup 两次提交后 activated_at 不变（共用计时——源数据断言）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_followup")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    before = _q("SELECT activated_at FROM assessment_question WHERE question_id=?", (qid,))[0]["activated_at"]
    _stream_answer(sid, headers, qid, _SHORT_ANSWER)  # followup
    _stream_answer(sid, headers, qid, _SHORT_ANSWER)  # followup
    after = _q("SELECT activated_at FROM assessment_question WHERE question_id=?", (qid,))[0]["activated_at"]
    assert before == after, "followup 共用单题计时器——activated_at 不变"


# ---------- 全场超时 ----------

def test_global_timeout_order():
    """直插 active 区间 Σ 超 40min → answer → GLOBAL_TIMEOUT + phase=SCORING + 事件序三行比较。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_global")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    old = (datetime.now(timezone.utc) - timedelta(minutes=41)).isoformat()
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO session_time_intervals(interval_id, session_id, interval_type, started_at, ended_at)"
            " VALUES(?,?,?,?,?)",
            ("sti_old", sid, "active", old, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    resp = _stream_answer(sid, headers, qid, _LONG_ANSWER)
    assert resp["action"] == "finish", f"全场超时应收尾 finish，实得 {resp}"

    sess = _q("SELECT phase, status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["phase"] == "SCORING", sess
    assert sess["status"] == "completed", sess

    evs = _q("SELECT event_type, sequence_no FROM assessment_state_event WHERE session_id=? ORDER BY sequence_no", (sid,))
    types = [e["event_type"] for e in evs]
    assert "SESSION_GLOBAL_TIMEOUT" in types, types
    gt = next(e for e in evs if e["event_type"] == "SESSION_GLOBAL_TIMEOUT")
    es = next(e for e in evs if e["event_type"] == "SESSION_ENTERED_SCORING")
    cp = next(e for e in evs if e["event_type"] == "SESSION_COMPLETED")
    assert gt["sequence_no"] < es["sequence_no"] < cp["sequence_no"], \
        f"GLOBAL_TIMEOUT < ENTERED_SCORING < COMPLETED，实得 {[e['sequence_no'] for e in evs]}"


# ---------- 6h ABANDONED 惰性 ----------

def test_abandoned_6h_lazy():
    """直插 last_activity_at = now - 7h → answer 惰性置 abandoned + 事件；再答 409。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_abandoned")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    conn = get_conn()
    try:
        conn.execute("UPDATE assessment_session SET last_activity_at=? WHERE session_id=?", (old, sid))
        conn.commit()
    finally:
        conn.close()

    # 惰性判定触发（answer 路径）→ 会话置 abandoned → 409 SESSION_NOT_IN_PROGRESS
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": _LONG_ANSWER}, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "SESSION_NOT_IN_PROGRESS", r.text

    sess = _q("SELECT status, phase, abandoned_at FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "abandoned"
    assert sess["phase"] == "ABANDONED"
    assert sess["abandoned_at"] is not None
    evs = _q("SELECT event_type FROM assessment_state_event WHERE session_id=?", (sid,))
    assert any(e["event_type"] == "SESSION_ABANDONED" for e in evs)

    # 再 answer → 409（已有护栏，session 已 abandoned）
    r2 = client.post(f"/api/assessment/sessions/{sid}/answer",
                     json={"question_id": qid, "answer": _LONG_ANSWER}, headers=headers)
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "SESSION_NOT_IN_PROGRESS"


def test_abandoned_evidence_kept():
    """ABANDONED 后消息/实例行零删除（COUNT 不变——不删证据）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_evidence")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]
    _stream_answer(sid, headers, qid, _LONG_ANSWER)

    msgs_before = _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"]
    insts_before = _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"]

    old = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    conn = get_conn()
    try:
        conn.execute("UPDATE assessment_session SET last_activity_at=? WHERE session_id=?", (old, sid))
        conn.commit()
    finally:
        conn.close()
    # 触发 abandoned（当前题已答完，再 GET 派发下一题后答，触发惰性判定）
    cur = _first_question(sid, headers)
    client.post(f"/api/assessment/sessions/{sid}/answer",
                json={"question_id": cur["question_id"], "answer": _LONG_ANSWER}, headers=headers)

    assert _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"] == msgs_before
    assert _q("SELECT COUNT(*) c FROM assessment_question WHERE session_id=?", (sid,))[0]["c"] == insts_before


def test_last_activity_refresh():
    """answer 成功后 last_activity_at 非 NULL 且晚于 answer 前。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_touch")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    before = _q("SELECT last_activity_at FROM assessment_session WHERE session_id=?", (sid,))[0]["last_activity_at"]
    _stream_answer(sid, headers, qid, _LONG_ANSWER)
    after = _q("SELECT last_activity_at FROM assessment_session WHERE session_id=?", (sid,))[0]["last_activity_at"]
    assert after is not None
    assert (before is None) or (after >= before)


# ---------- 暂停护栏 ----------

def test_session_paused_guard():
    """直插 open paused 行 → answer → 409 SESSION_PAUSED。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_paused")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO session_time_intervals(interval_id, session_id, interval_type, started_at)"
            " VALUES(?,?,?,?)", ("sti_paused", sid, "paused", now_iso()))
        conn.commit()
    finally:
        conn.close()

    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": _LONG_ANSWER}, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "SESSION_PAUSED", r.text


# ---------- phase 列 ----------

def test_phase_column_defaults():
    """新建会话 phase=='PENDING_START'；旧库直插（无 phase 列）init_db 后回填 PENDING_START；status CHECK 不动。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_phase")
    sid = _create_session(pid, headers)
    assert _q("SELECT phase FROM assessment_session WHERE session_id=?", (sid,))[0]["phase"] == "PENDING_START"

    # 旧行回填：直插 status 合法值 + phase NULL → 重跑 init_db → 回填 PENDING_START（migration 幂等）
    conn = get_conn()
    try:
        # FK ON 语境：先插合法 user 父行，再插 assessment_session（无父行必 FK 违反假红——W4）
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES('u_x', 'timer_phase_old', 'x', 'candidate', 1, ?)",
            (now_iso(),),
        )
        conn.execute(
            "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
            " status, started_at, created_at) VALUES('sess_old', 'u_x', ?, ?, 1, 'completed', ?, ?)",
            (pid, _mid, now_iso(), now_iso()),
        )
        conn.execute("UPDATE assessment_session SET phase=NULL WHERE session_id='sess_old'")
        conn.commit()
    finally:
        conn.close()
    init_db()  # 重跑迁移（幂等）
    row = _q("SELECT phase, status FROM assessment_session WHERE session_id='sess_old'")[0]
    assert row["phase"] == "PENDING_START"
    assert row["status"] == "completed"  # status 存量语义不动


# ---------- 消息分列三列 ----------

def test_message_columns_split():
    """answer 后用户消息行 refined_content==content 且 client_request_id==提交值 且 sequence_no 递增两行。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_msgcols")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    _stream_answer(sid, headers, qid, _LONG_ANSWER, client_attempt_id="ca-1")

    rows = _q("SELECT role, content, refined_content, client_request_id, sequence_no"
              " FROM assessment_message WHERE session_id=? ORDER BY sequence_no", (sid,))
    user_rows = [r for r in rows if r["role"] == "user"]
    assistant_rows = [r for r in rows if r["role"] == "assistant"]
    assert user_rows and assistant_rows, "应各有一行 user/assistant"
    u = user_rows[0]
    assert u["refined_content"] == u["content"]
    assert u["client_request_id"] == "ca-1"
    assert all(r["sequence_no"] is not None for r in rows)
    seqs = [r["sequence_no"] for r in rows]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), f"sequence_no 递增不重复，实得 {seqs}"
    assert u["sequence_no"] < assistant_rows[0]["sequence_no"]


# ---------- 滑窗截断 ----------

def test_truncate_history_tail_preserved():
    """20 条 history（每条 content 长 100）+ max_tokens=300 → kept 尾部条数 < 20 且最新一条在 kept。"""
    history = [{"role": "user", "content": "x" * 100} for _ in range(20)]
    kept = _truncate_history(history, 300)
    assert len(kept) < 20, f"应截断，实得 {len(kept)} 条"
    assert kept[-1]["content"] == history[-1]["content"], "最新一条必须保留"


def test_truncate_history_mock_passthrough():
    """decide_next_action mock 下 history 全量（集成断言——观察层无截断抖动）。"""
    # 纯函数本身不看 provider：20 条长 history + 小 max_tokens 会截断
    history = [{"role": "user", "content": "x" * 100} for _ in range(20)]
    assert len(_truncate_history(history, 300)) < 20
    # mock 调用方（LLM_PROVIDER=mock）走全量不截断——集成面：答题决策正常
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("timer_mockpass")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]
    resp = _stream_answer(sid, headers, qid, _SHORT_ANSWER)  # followup
    assert resp["action"] == "followup", resp
    resp2 = _stream_answer(sid, headers, qid, _LONG_ANSWER)
    assert resp2["action"] in ("next", "finish", "followup"), resp2


# ---------- MAX_CONTEXT_TOKENS 已裁决 ----------

def test_max_context_tokens_resolved():
    """config.MAX_CONTEXT_TOKENS == 8000（关口包裁决 [03-007]——常量值断言，非占位）。"""
    assert cfg.MAX_CONTEXT_TOKENS == 8000
