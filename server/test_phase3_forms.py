"""Phase 3 wave 0：表单链全链断言（03-01，REF-2.4/REF-3.3/REF-4.7/REF-4.10）。

覆盖：form_instance 迁移双路径（老库放宽保数据 + 新库直建列集）、render 触发与幂等、
GET 只读白名单、submit 六维校验（422 三态 error_code + 409 两态）、gate 行结构化五列、
GATE_EVALUATED 事件、submit 后 finish/next 触发器、revision 不可变、admin 覆盖二次确认、
双源优先级（gate 行 > form_submission payload）、score_session 保留 gate 行、
experience/qualification 不进动态选题终局。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db；单文件单进程。
运行：cd server && python -m pytest test_phase3_forms.py -v
"""
import json
import os
import re
import sqlite3
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_dir = tempfile.mkdtemp()
_main_db = os.path.join(_tmp_dir, "test_phase3_forms.db")
os.environ["DB_PATH"] = _main_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
import server.db as db_module  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建主库（API 测试用）
client = TestClient(app)

_NOW = "2026-01-01T00:00:00"


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _cols(table: str) -> set[str]:
    """PRAGMA table_info 取列名集合（表名为测试内字面量，无用户输入）。"""
    return {r["name"] for r in _q(f"PRAGMA table_info({table})")}


# ---- 旧版 question_score DDL（Phase 3 之前：question_id/score_state 均 NOT NULL，
# 无 gate 五列 / 覆盖四列 / form_instance），模拟老业务库 ----
_OLD_DDL = """
CREATE TABLE question_score (
  score_id       TEXT PRIMARY KEY,
  session_id     TEXT NOT NULL REFERENCES assessment_session,
  question_id    TEXT NOT NULL REFERENCES assessment_question,
  item_id        TEXT NOT NULL REFERENCES competency_item,
  score_live     INTEGER,
  score_final    INTEGER,
  evidence_quote TEXT,
  reason         TEXT,
  created_at     TEXT NOT NULL,
  score_state    TEXT NOT NULL DEFAULT 'SCORED'
);
"""


def _build_old_db(db_path: str) -> None:
    """直连临时库用旧版 DDL 建 question_score 并插旧行（模拟 Phase 3 之前的业务库）。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_OLD_DDL)
        conn.execute(
            "INSERT INTO question_score(score_id, session_id, question_id, item_id, score_live,"
            " score_final, evidence_quote, reason, created_at, score_state)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("sc_old_1", "sess_old_1", "aq_old_1", "ci_old_1", 2, 2, None, None, _NOW, "SCORED"),
        )
        conn.commit()
    finally:
        conn.close()


# ---------- 种子（gate=1 experience years=3 + qualification + 普通 hard×2/soft×1） ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（gate=1 经验/资格 + 普通题项）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3, "gate": 0},
        {"std_name": "MySQL", "category": "hard_skill", "importance": "required", "weight": 0.25, "gate": 0},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.2, "gate": 0},
        # gate=1 经验（years=3）与资格各一——表单链终局采集，不进普通池
        {"std_name": "后端开发经验", "category": "experience", "importance": "required", "weight": 0.15, "gate": 1, "years": 3},
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


def _seed_question_bank(pid: str, mid: str) -> None:
    """普通题 hard 7 / soft 3（满足 §10.4 原始配额）+ gate 项题库行（general 不进普通池）。"""
    conn = get_conn()
    now = now_iso()

    def _add(scope, position_id, std_name, category, difficulty, qtype, stem, answer_key, rubric):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), scope, position_id, mid, 1, std_name, category, difficulty, qtype, stem,
             answer_key, rubric, "human", "active", now),
        )

    # 全 easy 难度：required_level=3 下 hard 档不可达，difficulty 快照落回 easy 不丢题
    for i in range(4):
        _add("position", pid, "Python", "hard_skill", "easy", "subjective",
             f"Python 经验题 {i+1}：讲一个用 Python 解决问题的场景。", None, "场景/方法/结果")
    for i in range(3):
        _add("position", pid, "MySQL", "hard_skill", "easy", "subjective",
             f"MySQL 经验题 {i+1}：讲一次数据库优化经历。", None, "场景/方法/结果")
    for i in range(3):
        _add("position", pid, "沟通能力", "soft_skill", "easy", "subjective",
             f"沟通题 {i+1}：讲一次跨团队沟通的经历。", None, "背景/冲突/结果")
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


def _ensure_admin() -> None:
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


def _admin_headers() -> dict:
    _ensure_admin()
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


_LONG_ANSWER = (
    "我熟练使用 Python 完成后端开发，熟悉常见的数据结构与算法，"
    "并且在多个项目中处理过性能问题、并发问题与数据库优化，有可量化结果。"
)


def _create_session(pid: str, headers: dict) -> str:
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _stream_answer(sid: str, headers: dict, question_id: str, answer: str) -> dict:
    """流式消费 POST /answer → 组回旧 JSON 同构 dict（action/reply/question_id/next_question_id/score_live）。"""
    with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                       json={"question_id": question_id, "answer": answer},
                       headers=headers) as r:
        assert r.status_code == 200, f"answer 应 200，实得 {r.status_code}"
        lines = [ln for ln in r.iter_lines() if ln.startswith("data: ")]
    events = [json.loads(ln[6:]) for ln in lines]
    decision = next(e for e in events if e["type"] == "decision")
    done = next(e for e in events if e["type"] == "done")
    reply = "".join(e["content"] for e in events if e["type"] == "reply")
    return {"action": done["action"], "reply": reply,
            "question_id": question_id,
            "next_question_id": done.get("next_question_id"),
            "score_live": decision.get("score_live")}


def _start(sid: str, headers: dict) -> None:
    """POST /start 入场确认（PENDING_START→ACTIVE）；容忍 409（幂等重复调用）。"""
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=headers)
    assert r.status_code in (200, 409), r.text


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
        action = resp["action"]
        if action == "form":
            reply = resp.get("reply", "")
            m = re.search(r"📎\[form:([^\]]+)\]", reply)
            assert m, f"reply 应含 📎[form:id] 标记，实得 {reply}"
            form_id = m.group(1)
            break
        assert action == "next", resp
    assert form_id is not None, "会话应触发表单渲染（action=form）"
    return form_id


# ---------- 迁移双路径 ----------

def test_old_db_gateway_relaxation():
    """老库路径：旧 question_score（NOT NULL question_id/score_state）→ init_db → gate 九列 +
    question_id/score_state 放宽可空（旧行值保留——放宽不丢数据）+ form_instance 表存在。"""
    old_db = os.path.join(tempfile.mkdtemp(), "old_gate.db")
    _build_old_db(old_db)
    original = db_module.DB_PATH
    db_module.DB_PATH = old_db
    try:
        init_db()
        assert _q("SELECT 1 FROM sqlite_master WHERE type='table' AND name='form_instance'")
        cols = _cols("question_score")
        for col in ("gate_result", "gate_status", "gate_reason", "evaluated_schema_version",
                    "evaluated_at", "automated_gate_result", "human_override",
                    "override_reason", "reviewer_id"):
            assert col in cols, f"question_score 缺 gate/覆盖列: {col}"
        info = {r["name"]: r for r in _q("PRAGMA table_info(question_score)")}
        assert info["question_id"]["notnull"] == 0, "question_id 应放宽为可空"
        assert info["score_state"]["notnull"] == 0, "score_state 应放宽为可空"
        sc = _q("SELECT question_id, score_state FROM question_score WHERE score_id='sc_old_1'")[0]
        assert sc["question_id"] == "aq_old_1", "放宽不得丢数据（question_id 保留）"
        assert sc["score_state"] == "SCORED", "放宽不得丢数据（score_state 保留）"
    finally:
        db_module.DB_PATH = original


def test_new_db_direct_path():
    """新库路径：_DDL 直建含 form_instance + gate 九列 + question_id/score_state 可空；二次幂等。"""
    fresh_db = os.path.join(tempfile.mkdtemp(), "new_gate.db")
    original = db_module.DB_PATH
    db_module.DB_PATH = fresh_db
    try:
        init_db()
        init_db()  # 幂等
        conn = sqlite3.connect(fresh_db)
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "form_instance" in tables
            fi_cols = {r[1] for r in conn.execute("PRAGMA table_info(form_instance)")}
            assert {"form_instance_id", "session_id", "form_type", "schema_version",
                    "schema_snapshot", "status", "revision", "payload_json",
                    "created_at", "submitted_at"} <= fi_cols
            qs_cols = {r[1] for r in conn.execute("PRAGMA table_info(question_score)")}
            for col in ("gate_result", "gate_status", "gate_reason", "evaluated_schema_version",
                        "evaluated_at", "automated_gate_result", "human_override",
                        "override_reason", "reviewer_id"):
                assert col in qs_cols, col
            notnull = {r[1]: r[3] for r in conn.execute("PRAGMA table_info(question_score)")}
            assert notnull["question_id"] == 0
            assert notnull["score_state"] == 0
        finally:
            conn.close()
    finally:
        db_module.DB_PATH = original


# ---------- render / GET 白名单 ----------

def test_render_on_exhaustion():
    """普通题答完（池耗尽）→ action=='form' + 📎[form:id] 标记 + form_instance rendered +
    schema_snapshot 可 json.loads 含 fields + assistant 消息 + FORM_RENDERED 事件。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_render")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)

    rows = _q("SELECT status, schema_snapshot FROM form_instance WHERE form_instance_id=?", (form_id,))
    assert len(rows) == 1, "应恰好一个 rendered 实例"
    assert rows[0]["status"] == "rendered"
    snapshot = json.loads(rows[0]["schema_snapshot"])
    assert snapshot.get("form_type") == "gate_combined"
    assert snapshot.get("fields"), "schema_snapshot 应含 fields"

    msgs = _q("SELECT content FROM assessment_message WHERE session_id=? AND role='assistant'", (sid,))
    assert any("📎[form:" in m["content"] for m in msgs), "assistant 消息应含 📎[form:id] 标记"
    assert _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=? AND event_type='FORM_RENDERED'", (sid,))[0]["c"] == 1


def test_render_idempotent_open():
    """同一会话再触发 render 不产生第二个 rendered 实例（open rendered 幂等复用）。"""
    from server.services.forms import render_form_instance

    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_idem")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)

    conn = get_conn()
    try:
        fi = render_form_instance(conn, sid)
    finally:
        conn.close()
    assert fi["form_instance_id"] == form_id, "应复用 open rendered 实例"
    assert _q("SELECT COUNT(*) c FROM form_instance WHERE session_id=? AND status='rendered'", (sid,))[0]["c"] == 1


def test_get_form_whitelist():
    """GET /api/assessment/forms/{id} → 200 + 键集合 ⊆ {form_type,title,fields} + fields 键白名单 +
    years 门槛值与 required_level 不出现在响应 JSON。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_wl")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)

    r = client.get(f"/api/assessment/forms/{form_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) <= {"form_type", "title", "fields"}, body.keys()
    field_keys = set()
    for f in body["fields"]:
        field_keys |= set(f.keys())
    assert field_keys <= {"name", "label", "type", "required", "options", "placeholder"}, field_keys
    raw = json.dumps(body, ensure_ascii=False)
    assert "required_level" not in raw, "required_level 不得泄露"
    assert "3" not in raw, "years 门槛值（3）不得进白名单响应"


def test_get_form_ownership():
    """他人 token GET → 404（D-01 统一不存在语义）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_owner")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)

    other = _auth_headers("p3_owner_other")
    r = client.get(f"/api/assessment/forms/{form_id}", headers=other)
    assert r.status_code == 404, r.text


# ---------- submit 六维校验 ----------

def test_submit_six_dimensions():
    """六维校验序：缺必填/枚举外值/超长 → 422 三态 error_code；revision 不匹配 → 409；
    成功 → 201 submitted + gate_results；重提交 → 409 FORM_ALREADY_SUBMITTED + 首次结果原样带回。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_sixdim")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)

    def _submit(payload, expected_revision=1):
        return client.post(
            f"/api/assessment/sessions/{sid}/forms/submit-v2",
            json={"form_instance_id": form_id, "schema_version": "v1",
                  "expected_revision": expected_revision, "payload": payload},
            headers=headers,
        )

    valid = {"years_of_experience": 5, "本科学历": "是"}

    # ④ 必填缺失 → 422 FORM_MISSING_FIELD
    r = _submit({"years_of_experience": 5})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == "FORM_MISSING_FIELD", r.text
    # ⑤ 枚举外值 → 422 FORM_INVALID_OPTION
    r = _submit({"years_of_experience": 5, "本科学历": "maybe"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == "FORM_INVALID_OPTION", r.text
    # ⑥ 超长 → 422 FORM_FIELD_TOO_LONG
    r = _submit({"years_of_experience": "12345678901", "本科学历": "是"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == "FORM_FIELD_TOO_LONG", r.text
    # ③ revision 不匹配 → 409 FORM_INSTANCE_REVISION_CONFLICT
    r = _submit(valid, expected_revision=2)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "FORM_INSTANCE_REVISION_CONFLICT", r.text

    # 成功
    r = _submit(valid)
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["status"] == "submitted"
    assert body["gate_results"], "gate_results 应非空"
    for g in body["gate_results"]:
        assert "item_id" in g and "gate_result" in g

    # ② 重提交 → 409 FORM_ALREADY_SUBMITTED + 首次结果 payload 原样带回
    r = _submit(valid)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error_code"] == "FORM_ALREADY_SUBMITTED", r.text
    assert r.json()["detail"]["payload"] == valid, r.text


def test_gate_row_written():
    """提交后 gate item 各一行（question_id/score_state NULL + gate_result/gate_reason/
    evaluated_schema_version 落值）；GATE_EVALUATED 事件行数 == gate item 数。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_gaterow")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)
    r = client.post(
        f"/api/assessment/sessions/{sid}/forms/submit-v2",
        json={"form_instance_id": form_id, "schema_version": "v1", "expected_revision": 1,
              "payload": {"years_of_experience": 5, "本科学历": "是"}},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text

    rows = _q("SELECT * FROM question_score WHERE session_id=? AND gate_result IS NOT NULL", (sid,))
    assert len(rows) == 2, f"应写 2 条 gate 行（experience+qualification），实得 {len(rows)}"
    for row in rows:
        assert row["question_id"] is None
        assert row["score_state"] is None
        assert row["gate_result"] in ("true", "false")
        assert row["gate_reason"], "gate_reason 应非空"
        assert row["evaluated_schema_version"] == "v1"
        assert row["gate_status"] == "EVALUATED"
    ev = _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=? AND event_type='GATE_EVALUATED'", (sid,))[0]["c"]
    assert ev == 2, f"GATE_EVALUATED 事件应 == gate item 数，实得 {ev}"


def test_submit_unblocks_finish():
    """表单提交后（池耗尽 + gate 全采集）→ action=='finish' + status=='completed' + SESSION_COMPLETED 事件。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_finish")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)
    r = client.post(
        f"/api/assessment/sessions/{sid}/forms/submit-v2",
        json={"form_instance_id": form_id, "schema_version": "v1", "expected_revision": 1,
              "payload": {"years_of_experience": 5, "本科学历": "是"}},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["action"] == "finish", r.text
    assert _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]["status"] == "completed"
    assert _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=? AND event_type='SESSION_COMPLETED'", (sid,))[0]["c"] >= 1


def test_submit_next_when_pool_left():
    """尚有普通题未答完先被引导提交 → submit-v2 action=='next' 且 next_question_id 非 None（防 finish 误触发）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_next")
    sid = _create_session(pid, headers)

    # 答 1 题（池未耗尽）
    _start(sid, headers)  # 03-05 phase 门：PENDING_START 不派发，须先 start
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    cur = r.json()["current_question"]
    resp = _stream_answer(sid, headers, cur["question_id"], _LONG_ANSWER)
    assert resp["action"] == "next", resp

    # 直插一个 rendered form_instance（模拟过早 render）
    snapshot = {
        "form_type": "gate_combined", "title": "资格核验",
        "fields": [
            {"name": "years_of_experience", "label": "工作年限（年）", "type": "number",
             "required": True, "max_len": 10},
            {"name": "本科学历", "label": "本科学历", "type": "select",
             "required": True, "options": ["是", "否"]},
        ],
    }
    fi_id = new_id("fi")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO form_instance(form_instance_id, session_id, form_type, schema_version,"
            " schema_snapshot, status, revision, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (fi_id, sid, "gate_combined", "v1", json.dumps(snapshot, ensure_ascii=False),
             "rendered", 1, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.post(
        f"/api/assessment/sessions/{sid}/forms/submit-v2",
        json={"form_instance_id": fi_id, "schema_version": "v1", "expected_revision": 1,
              "payload": {"years_of_experience": 5, "本科学历": "是"}},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["action"] == "next", r.text
    assert r.json()["next_question_id"] is not None, r.text


def test_revision_immutable():
    """修订 = 新行 revision+1（instance_id 不变）+ 旧行 status='superseded'；schema_snapshot 不被 UPDATE。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_rev")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)

    old_snap = _q("SELECT schema_snapshot FROM form_instance WHERE form_instance_id=? AND revision=1", (form_id,))[0]["schema_snapshot"]
    conn = get_conn()
    try:
        conn.execute("UPDATE form_instance SET status='superseded' WHERE form_instance_id=? AND revision=1", (form_id,))
        conn.execute(
            "INSERT INTO form_instance(form_instance_id, session_id, form_type, schema_version,"
            " schema_snapshot, status, revision, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (form_id, sid, "gate_combined", "v1", old_snap, "rendered", 2, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()

    old_row = _q("SELECT status FROM form_instance WHERE form_instance_id=? AND revision=1", (form_id,))[0]
    assert old_row["status"] == "superseded"
    new_row = _q("SELECT revision, schema_snapshot FROM form_instance WHERE form_instance_id=? AND revision=2", (form_id,))[0]
    assert new_row["revision"] == 2
    assert new_row["schema_snapshot"] == old_snap, "schema_snapshot 不应被 UPDATE（两行快照各自独立）"
    active = _q("SELECT revision FROM form_instance WHERE form_instance_id=? ORDER BY revision DESC LIMIT 1", (form_id,))[0]
    assert active["revision"] == 2


# ---------- admin 覆盖 / 双源 / score_session / 终局排除 ----------

def test_admin_override_requires_reason():
    """admin 覆盖：无 override_reason → 422；带 reason → 200 + human_override/reviewer_id 落值 +
    GATE_OVERRIDDEN 事件；非 admin → 403。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_admin")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)
    r = client.post(
        f"/api/assessment/sessions/{sid}/forms/submit-v2",
        json={"form_instance_id": form_id, "schema_version": "v1", "expected_revision": 1,
              "payload": {"years_of_experience": 5, "本科学历": "是"}},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text

    item_id = _q("SELECT item_id FROM question_score WHERE session_id=? AND gate_result IS NOT NULL LIMIT 1", (sid,))[0]["item_id"]
    admin = _admin_headers()

    r = client.post("/api/admin/forms/gate-override",
                    json={"session_id": sid, "item_id": item_id, "human_override": True}, headers=admin)
    assert r.status_code == 422, r.text

    r = client.post("/api/admin/forms/gate-override",
                    json={"session_id": sid, "item_id": item_id, "human_override": False,
                          "override_reason": "人工复核不通过"}, headers=admin)
    assert r.status_code == 200, r.text
    row = _q("SELECT human_override, reviewer_id FROM question_score WHERE session_id=? AND item_id=?", (sid, item_id))[0]
    assert row["human_override"] is not None
    assert row["reviewer_id"] is not None
    assert _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=? AND event_type='GATE_OVERRIDDEN'", (sid,))[0]["c"] >= 1

    # WR-05：覆盖须在聚合中生效（human_override 优先于自动化 gate_result）——
    # 本会话 gate 行自动化 gate_result='true'（years=5 ≥ 3），覆盖为 False 后
    # 聚合 gate_items.passed 应翻转为 False（覆盖不再是无下游消费者的 no-op）。
    from server.services.aggregation import aggregate_session_scores
    agg = aggregate_session_scores(sid)
    overridden = [g for g in agg["gate_items"] if g["item_id"] == item_id][0]
    assert overridden["passed"] is False, "human_override=False 应优先于 gate_result='true' 生效"

    r = client.post("/api/admin/forms/gate-override",
                    json={"session_id": sid, "item_id": item_id, "human_override": True,
                          "override_reason": "越权尝试"}, headers=headers)
    assert r.status_code in (401, 403), r.text


def test_dual_source_precedence():
    """gate 行优先：会话 A 走新链（gate 行 gate_result='false'）+ 旧 form_submission 判定 pass →
    passed==False；会话 B 只走旧链（form_submission）→ 旧 _gate_check 判定不变。"""
    from server.services.aggregation import aggregate_session_scores

    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_dual_a")
    sid_a = _create_session(pid, headers)
    form_id = _answer_until_form(sid_a, headers)
    r = client.post(
        f"/api/assessment/sessions/{sid_a}/forms/submit-v2",
        json={"form_instance_id": form_id, "schema_version": "v1", "expected_revision": 1,
              "payload": {"years_of_experience": 0, "本科学历": "是"}},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    conn = get_conn()
    try:
        uid = conn.execute("SELECT user_id FROM assessment_session WHERE session_id=?", (sid_a,)).fetchone()["user_id"]
        conn.execute(
            "INSERT INTO form_submission(form_id, session_id, user_id, form_type, payload_json, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (new_id("form"), sid_a, uid, "gate_combined",
             json.dumps({"years_of_experience": 10, "本科学历": "是"}, ensure_ascii=False), now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    res_a = aggregate_session_scores(sid_a)
    exp_a = [g for g in res_a["gate_items"] if g["std_name"] == "后端开发经验"][0]
    assert exp_a["passed"] is False, "gate 行应优先（gate_result='false'）"

    # 会话 B：仅旧链 form_submission
    pid2, mid2 = _seed_position_with_confirmed_model()
    _seed_question_bank(pid2, mid2)
    headers_b = _auth_headers("p3_dual_b")
    sid_b = _create_session(pid2, headers_b)
    conn = get_conn()
    try:
        uid_b = conn.execute("SELECT user_id FROM assessment_session WHERE session_id=?", (sid_b,)).fetchone()["user_id"]
        conn.execute(
            "INSERT INTO form_submission(form_id, session_id, user_id, form_type, payload_json, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (new_id("form"), sid_b, uid_b, "gate_combined",
             json.dumps({"years_of_experience": 10, "本科学历": "是"}, ensure_ascii=False), now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    res_b = aggregate_session_scores(sid_b)
    exp_b = [g for g in res_b["gate_items"] if g["std_name"] == "后端开发经验"][0]
    assert exp_b["passed"] is True, "旧链 form_submission 兜底判定应保留"


def test_score_session_preserves_gate_rows():
    """提交表单后调 score_session → gate 行仍在（DELETE 只清评分行，不吞 gate 行）。"""
    from server.services.scoring import score_session

    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_preserve")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)
    r = client.post(
        f"/api/assessment/sessions/{sid}/forms/submit-v2",
        json={"form_instance_id": form_id, "schema_version": "v1", "expected_revision": 1,
              "payload": {"years_of_experience": 5, "本科学历": "是"}},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text

    score_session(sid, allow_completed=True)
    n = _q("SELECT COUNT(*) c FROM question_score WHERE session_id=? AND gate_result IS NOT NULL", (sid,))[0]["c"]
    assert n == 2, f"score_session 后 gate 行应保留，实得 {n}"


def test_exp_qual_not_in_selection():
    """全 session aq JOIN question_bank 的 category 集合 ⊆ {hard_skill,soft_skill}（REF-3.3 终局）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_expqual")
    sid = _create_session(pid, headers)
    _answer_until_form(sid, headers)

    rows = _q(
        "SELECT DISTINCT b.category FROM assessment_question aq"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id WHERE aq.session_id=?",
        (sid,),
    )
    cats = {r["category"] for r in rows}
    assert cats and cats <= {"hard_skill", "soft_skill"}, f"终局选题不得含 experience/qualification，实得 {cats}"


def test_form_submit_idempotent():
    """携 idempotency_key 提交表单 → 重放 200 同体；gate 行与事件零重复写（幂等快照直返）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("p3_formidem")
    sid = _create_session(pid, headers)
    form_id = _answer_until_form(sid, headers)
    body = {"form_instance_id": form_id, "schema_version": "v1", "expected_revision": 1,
            "payload": {"years_of_experience": 5, "本科学历": "是"},
            "idempotency_key": "k-form-1"}
    r1 = client.post(f"/api/assessment/sessions/{sid}/forms/submit-v2", json=body, headers=headers)
    assert r1.status_code in (200, 201), r1.text
    r2 = client.post(f"/api/assessment/sessions/{sid}/forms/submit-v2", json=body, headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json() == r1.json(), "重放应返回首次返回体同构"
    # 零重复写：gate 行 / GATE_EVALUATED 事件均不增（validate_and_submit 未二次进入）
    assert _q("SELECT COUNT(*) c FROM question_score WHERE session_id=? AND gate_result IS NOT NULL", (sid,))[0]["c"] == 2
    assert _q("SELECT COUNT(*) c FROM assessment_state_event WHERE session_id=? AND event_type='GATE_EVALUATED'", (sid,))[0]["c"] == 2
    # 幂等记录 COMMITTED 恰好 1 行（endpoint='form_submit' 与 answer 三键隔离）
    assert _q("SELECT status FROM idempotency_record WHERE session_id=? AND endpoint='form_submit'", (sid,))[0]["status"] == "COMMITTED"
