"""Phase 3 幂等与并发防护断言（03-03，REF-4.9——SSOT §13.4/D-36~D-38）。

覆盖：同 key 重复 answer 返回首次快照（200 application/json，消息/事件零重复写）、
同 key 异 payload 409 IDEMPOTENCY_KEY_REUSED（COMMITTED 命中先比 hash——W1）、
PENDING 命中 409 REQUEST_IN_PROGRESS、不同 key 独立、三键 endpoint 隔离、
revision 乐观锁（expected_revision 命中 revision+1 / stale 409 QUESTION_REVISION_CONFLICT /
无 expected_revision 零行为变化）、无 key 零 idempotency_record、UNIQUE 三键拦并发双插、
表单幂等（submit-v2 重发 200 首次 gate_results 快照 + form_instance/gate 行不重复写）、
快照白名单七键（A1——不含候选人输入原文）。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db；单文件单进程。
运行：cd server && python -m pytest test_phase3_idempotency.py -v
"""
import json
import os
import re
import sqlite3
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase3_idempotency.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
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
    """普通题 hard×4/soft×2（池耗尽才触发表单——三连答不耗尽）+ gate 项题库行。"""
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


def _start(sid: str, headers: dict) -> None:
    """POST /start 入场确认（PENDING_START→ACTIVE）；容忍 409（幂等重复调用）。"""
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=headers)
    assert r.status_code in (200, 409), r.text


def _first_question(sid: str, headers: dict) -> dict:
    _start(sid, headers)  # 03-05 phase 门：PENDING_START 不派发，须先 start（重复调用幂等）
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    cur = r.json()["current_question"]
    assert cur is not None, "get_session 应已派发首题"
    return cur


def _stream_answer(sid: str, headers: dict, question_id: str, answer: str, *,
                   key: str | None = None, expected_revision: int | None = None) -> dict:
    """流式消费 POST /answer → 组回旧 JSON 同构 dict；可选幂等键/乐观锁版本号。"""
    body = {"question_id": question_id, "answer": answer}
    if key is not None:
        body["idempotency_key"] = key
    if expected_revision is not None:
        body["expected_revision"] = expected_revision
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
            "score_live": decision.get("score_live")}


def _answer_until_form(sid: str, headers: dict) -> str:
    """答完普通题直到 action=='form'，返回 form_instance_id（reply 正则提取）。"""
    form_id = None
    _start(sid, headers)  # 03-05 phase 门：PENDING_START 不派发，须先 start
    while True:
        r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
        assert r.status_code == 200, r.text
        cur = r.json()["current_question"]
        if cur is None:
            break
        resp = _stream_answer(sid, headers, cur["question_id"], _LONG_ANSWER)
        if resp["action"] == "form":
            m = re.search(r"📎\[form:([^\]]+)\]", resp["reply"])
            assert m, f"reply 应含 📎[form:id] 标记，实得 {resp['reply']}"
            form_id = m.group(1)
            break
        assert resp["action"] == "next", resp
    assert form_id is not None, "会话应触发表单渲染（action=form）"
    return form_id


# ---------- 断言 ----------

def test_same_key_returns_first_snapshot():
    """同 key 同 payload 重发 → 200 application/json 快照（五键一致）+ 消息/事件零重复写。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_replay")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]
    key = "k-replay-1"

    first = _stream_answer(sid, headers, qid, _LONG_ANSWER, key=key)
    msg_before = _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"]
    ev_before = _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=?", (sid,))[0]["c"]

    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": _LONG_ANSWER, "idempotency_key": key},
                    headers=headers)
    assert r.status_code == 200, r.text
    assert "application/json" in r.headers["content-type"], r.headers
    snap = r.json()
    for k in ("action", "reply", "question_id", "next_question_id", "score_live"):
        assert snap[k] == first[k], f"快照键 {k} 应 == 首次组回值：{snap[k]!r} vs {first[k]!r}"
    # 消息/事件零新增（SC-4——不重复写）
    assert _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"] == msg_before
    assert _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=?", (sid,))[0]["c"] == ev_before


def test_hash_sensitivity():
    """同 key 不同 payload（answer 文本不同）→ 409 IDEMPOTENCY_KEY_REUSED（不回放首次快照）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_hash")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]
    key = "k-hash-1"

    _stream_answer(sid, headers, qid, _LONG_ANSWER, key=key)
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": "完全不同的答案内容", "idempotency_key": key},
                    headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REUSED", r.text


def test_pending_returns_409():
    """手工直插 PENDING 行 → 带 key 请求 → 409 REQUEST_IN_PROGRESS（并发进行中快速失败）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_pending")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO idempotency_record(id, session_id, endpoint, idempotency_key,"
            " request_hash, status, created_at) VALUES(?,?,?,?,?,?,?)",
            (new_id("idem"), sid, "answer", "k-pending", "somehash", "PENDING", now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": _LONG_ANSWER, "idempotency_key": "k-pending"},
                    headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "REQUEST_IN_PROGRESS", r.text


def test_distinct_keys_independent():
    """同 session 两个不同 key → 各自首次处理（消息表各追加行，两条 COMMITTED 记录）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_distinct")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    _stream_answer(sid, headers, qid, _LONG_ANSWER, key="k-dist-a")
    msg_after_a = _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"]

    qid2 = _first_question(sid, headers)["question_id"]
    _stream_answer(sid, headers, qid2, _LONG_ANSWER, key="k-dist-b")
    msg_after_b = _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"]
    assert msg_after_b > msg_after_a, "不同 key 应各自首次处理（消息追加）"

    rows = _q("SELECT status FROM idempotency_record WHERE session_id=? AND endpoint='answer'"
              " ORDER BY created_at", (sid,))
    assert len(rows) == 2, f"应两条幂等记录，实得 {len(rows)}"
    assert [r["status"] for r in rows] == ["COMMITTED", "COMMITTED"], rows


def test_cross_endpoint_isolation():
    """answer 与 form_submit 同串 key → 互不干扰（UNIQUE 三键含 endpoint，实验 4 语义）。"""
    conn = get_conn()
    try:
        now = now_iso()
        conn.execute(
            "INSERT INTO idempotency_record(id, session_id, endpoint, idempotency_key,"
            " request_hash, status, created_at) VALUES(?,?,?,?,?,?,?)",
            (new_id("idem"), "s-cross", "answer", "k-cross", "h1", "COMMITTED", now),
        )
        # 同 session 同 key 不同 endpoint 应放行（三键独立）
        conn.execute(
            "INSERT INTO idempotency_record(id, session_id, endpoint, idempotency_key,"
            " request_hash, status, created_at) VALUES(?,?,?,?,?,?,?)",
            (new_id("idem"), "s-cross", "form_submit", "k-cross", "h2", "COMMITTED", now),
        )
        conn.commit()
    finally:
        conn.close()
    assert _q("SELECT COUNT(*) c FROM idempotency_record WHERE session_id='s-cross'"
              " AND idempotency_key='k-cross'")[0]["c"] == 2


def test_revision_optimistic_lock():
    """expected_revision=1 答题 → 200 + revision 1→2；stale 再答 → 409 QUESTION_REVISION_CONFLICT。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_rev")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    # _SHORT_ANSWER 触发 followup（题目未封存——乐观锁 bump 后可再答触发 stale 判定）
    _stream_answer(sid, headers, qid, _SHORT_ANSWER, expected_revision=1)
    assert _q("SELECT revision FROM assessment_question WHERE question_id=?", (qid,))[0]["revision"] == 2

    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": _SHORT_ANSWER, "expected_revision": 1},
                    headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "QUESTION_REVISION_CONFLICT", r.text


def test_revision_absent_no_lock():
    """不带 expected_revision（sse.js 现状）→ 全程无 409，revision 不 bump（A/B 兼容）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_norev")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]

    resp = _stream_answer(sid, headers, qid, _LONG_ANSWER)
    assert resp["action"] == "next", resp
    assert _q("SELECT revision FROM assessment_question WHERE question_id=?", (qid,))[0]["revision"] == 1


def test_no_key_no_records():
    """无 key 三连答 → idempotency_record COUNT == 0（缺省不启用）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_nokey")
    sid = _create_session(pid, headers)
    for _ in range(3):
        cur = _first_question(sid, headers)
        if cur is None:
            break
        _stream_answer(sid, headers, cur["question_id"], _LONG_ANSWER)
    assert _q("SELECT COUNT(*) c FROM idempotency_record WHERE session_id=?", (sid,))[0]["c"] == 0


def test_concurrent_double_insert():
    """UNIQUE 三键存在（sqlite_master）+ 同三键双 INSERT 第二个 IntegrityError（并发拦）。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='idempotency_record'"
        ).fetchone()
        assert row is not None and "UNIQUE(session_id, endpoint, idempotency_key)" in row["sql"], \
            "idempotency_record 应含三键 UNIQUE 声明"
        now = now_iso()
        conn.execute(
            "INSERT INTO idempotency_record(id, session_id, endpoint, idempotency_key,"
            " status, created_at) VALUES(?,?,?,?,?,?)",
            (new_id("idem"), "s-dup", "answer", "k-dup", "PENDING", now),
        )
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO idempotency_record(id, session_id, endpoint, idempotency_key,"
                " status, created_at) VALUES(?,?,?,?,?,?)",
                (new_id("idem"), "s-dup", "answer", "k-dup", "PENDING", now),
            )
            conn.commit()
            raise AssertionError("UNIQUE 三键未拦并发双插")
        except sqlite3.IntegrityError:
            pass  # 期望：第二次 INSERT 被 UNIQUE 拦截
    finally:
        conn.close()


def test_form_submit_idempotent():
    """submit-v2 带 key 成功 → 重发同 key → 200 首次 gate_results 快照 + form_instance/gate 行零重复写。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_form")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)

    key = "k-form-1"
    payload = {"years_of_experience": 5, "本科学历": "是"}
    def _submit():
        return client.post(
            f"/api/assessment/sessions/{sid}/forms/submit-v2",
            json={"form_instance_id": form_id, "schema_version": "v1", "expected_revision": 1,
                  "payload": payload, "idempotency_key": key},
            headers=headers,
        )

    r = _submit()
    assert r.status_code in (200, 201), r.text
    first = r.json()
    fi_before = _q("SELECT COUNT(*) c FROM form_instance WHERE session_id=?", (sid,))[0]["c"]
    gate_before = _q("SELECT COUNT(*) c FROM question_score WHERE session_id=? AND gate_result IS NOT NULL", (sid,))[0]["c"]

    r2 = _submit()
    assert r2.status_code == 200, r2.text
    snap = r2.json()
    assert snap["gate_results"] == first["gate_results"], snap
    assert snap["form_instance_id"] == form_id
    assert _q("SELECT COUNT(*) c FROM form_instance WHERE session_id=?", (sid,))[0]["c"] == fi_before
    assert _q("SELECT COUNT(*) c FROM question_score WHERE session_id=? AND gate_result IS NOT NULL", (sid,))[0]["c"] == gate_before


def test_snapshot_schema():
    """COMMITTED 行 response_snapshot 可 json.loads 且键集合 ⊆ 白名单七键，且不含 answer 原文（A1）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("idem_snapshot")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]
    key = "k-snapshot-1"

    _stream_answer(sid, headers, qid, _LONG_ANSWER, key=key)
    row = _q("SELECT response_snapshot FROM idempotency_record"
             " WHERE session_id=? AND endpoint='answer' AND idempotency_key=?", (sid, key))[0]
    snap = json.loads(row["response_snapshot"])
    assert set(snap.keys()) <= {"action", "reply", "question_id", "next_question_id",
                                "score_live", "answer_state", "evidence_sufficient"}, snap.keys()
    # A1：快照字符串不含候选人输入原文文案片段
    assert _LONG_ANSWER not in row["response_snapshot"], "快照不得含 answer 原文"
