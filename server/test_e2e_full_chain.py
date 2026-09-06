"""候选人端完整 E2E 全链 + 四场景脚本化测试（REF-7.6 / D-73）。

主链：注册→登录→建岗位→建模型(confirmed)→建 session→start→逐题作答/追问→表单
submit-v2→完成→评分→request_report→轮询报告→submit_feedback。
四场景：
- 刷新恢复：get_session 返回 messages（非空 role/content）+ position_name；
- 断线重试：同 idempotency_key 重发 POST /answer → 200 JSON 快照（resume 不丢已答题）；
- 越权拒绝：user B 访问 user A session → 404；非管理员访问 admin 路由 → 403；
- 超时：计时器到期 → 封存 seal_reason='timeout' + QUESTION_TIMEOUT 事件。

D-73 脚本化 API 层：全程 TestClient + 直接函数调用，不引 Playwright。
mock 三件套由 server/conftest.py 提供（本文件不设 env、不 import 其它测试模块——
「同一进程不 import 两测试模块」纪律）。
运行：cd server && python -m pytest test_e2e_full_chain.py -q
"""
import json
import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from server.db import get_conn
from server.main import app
from server.services.pipeline import new_id, now_iso

client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（hard/soft 普通 + gate=1 经验）。"""
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
        # 冲突协调（required soft）：N=10 → soft 配额 3 需 required tier 候选
        {"std_name": "冲突协调", "category": "soft_skill", "importance": "required", "weight": 0.15, "gate": 0},
        # 后端开发经验挂 gate=1（experience 走表单/简历事实核验，不占普通题）
        {"std_name": "后端开发经验", "category": "experience", "importance": "required", "weight": 0.1, "gate": 1},
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
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("c"), mid, it["std_name"], it["category"], 3, it["importance"], it["weight"],
             int(it.get("gate", 0))),
        )
    conn.commit()
    conn.close()
    return pid, mid


def _seed_question_bank(pid: str, mid: str) -> None:
    """岗位题 + 通用题：hard 7 / soft 3 / experience 2（含 py/mysql 难度链）。

    全部行写 model_id/model_version（Phase 4 消费侧收紧后，readiness/选题按
    model_id+model_version 过滤，直插题库必须绑定模型版本——D-50，规则 1 修复）。
    """
    conn = get_conn()
    now = now_iso()

    def _add(scope, position_id, std_name, category, difficulty, qtype, stem, answer_key, rubric,
             chain_key=None, chain_seq=None):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status,"
            " created_at, model_id, model_version)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), scope, position_id, std_name, category, difficulty, qtype, stem,
             answer_key, rubric, chain_key, chain_seq, "human", "active", now, mid, 1),
        )

    _add("position", pid, "Python", "hard_skill", "easy", "objective",
         "Python 中用什么关键字定义函数？", "def", None, "py-chain", 1)
    _add("position", pid, "Python", "hard_skill", "medium", "subjective",
         "讲一个你用 Python 解决过的性能问题。", None, "有具体场景/有数据/有方法", "py-chain", 2)
    _add("position", pid, "Python", "hard_skill", "hard", "subjective",
         "如何设计一个高并发 Python 服务？", None, "并发模型/限流/缓存", "py-chain", 3)
    _add("position", pid, "MySQL", "hard_skill", "easy", "objective",
         "MySQL 默认事务隔离级别是？", "REPEATABLE", None, "mysql-chain", 1)
    _add("position", pid, "MySQL", "hard_skill", "medium", "subjective",
         "讲一次慢查询优化经历。", None, "explain/索引/效果", "mysql-chain", 2)
    _add("position", pid, "Redis", "hard_skill", "easy", "objective",
         "Redis 常用字符串命令？", "GET", None)
    _add("position", pid, "Docker", "hard_skill", "easy", "objective",
         "构建镜像的命令是？", "docker build", None)

    _add("position", pid, "沟通能力", "soft_skill", "easy", "subjective",
         "讲一次跨团队沟通的经历。", None, "背景/冲突/结果")
    _add("position", pid, "沟通能力", "soft_skill", "medium", "subjective",
         "遇到意见分歧怎么处理？", None, "倾听/数据/共识")
    _add("position", pid, "冲突协调", "soft_skill", "medium", "subjective",
         "讲一次你化解团队冲突的经历。", None, "起因/方法/结果")

    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "介绍你最近一个后端项目。", None, "角色/规模/成果")
    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "最有挑战的项目？", None, "挑战/解决")
    conn.commit()
    conn.close()


def _auth_headers(username: str) -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _create_session(pid: str, headers: dict) -> str:
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


_LONG_ANSWER = (
    "我熟练使用 Python 完成后端开发，熟悉常见的数据结构与算法，"
    "并且在多个项目中处理过性能问题、并发问题与数据库优化，有可量化结果。"
)


def _start(sid: str, headers: dict) -> None:
    """POST /start 入场确认（PENDING_START→ACTIVE）；容忍 409（幂等重复调用）。"""
    r = client.post(f"/api/assessment/sessions/{sid}/start", headers=headers)
    assert r.status_code in (200, 409), r.text


def _first_question(sid: str, headers: dict) -> dict:
    _start(sid, headers)  # 03-05 phase 门：PENDING_START 不派发，须先 start
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    cur = r.json()["current_question"]
    assert cur is not None, "get_session 应已派发首题"
    return cur


def _stream_answer(sid: str, headers: dict, question_id: str, answer: str, *, key: str | None = None) -> dict:
    """流式消费 POST /answer → 组回旧 JSON 同构 dict；可选幂等键（断线重试场景）。"""
    body = {"question_id": question_id, "answer": answer}
    if key is not None:
        body["idempotency_key"] = key
    with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                       json=body, headers=headers) as r:
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


def _answer_whole_session(sid: str, headers: dict) -> None:
    """把一场会话全部题答完（长回答触发 next/finish），表单步骤走 submit-v2 收口。"""
    _start(sid, headers)
    while True:
        r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
        assert r.status_code == 200, r.text
        cur = r.json()["current_question"]
        if cur is None:
            break
        resp = _stream_answer(sid, headers, cur["question_id"], _LONG_ANSWER)
        assert resp["action"] in ("next", "finish", "form"), resp
        if resp["action"] == "form":
            m = re.search(r"📎\[form:([^\]]+)\]", resp.get("reply", ""))
            assert m, f"reply 应含 📎[form:id]，实得 {resp['reply']}"
            form_id = m.group(1)
            r = client.post(
                f"/api/assessment/sessions/{sid}/forms/submit-v2",
                json={"form_instance_id": form_id, "schema_version": "v1",
                      "expected_revision": 1, "payload": {"years_of_experience": 5}},
                headers=headers,
            )
            assert r.status_code in (200, 201), r.text
            assert r.json()["action"] in ("finish", "next"), r.text
    sess = _q("SELECT status FROM assessment_session WHERE session_id=?", (sid,))[0]
    assert sess["status"] == "completed"


# ---------- 主链 ----------

def test_full_chain_main():
    """候选人主链：注册→登录→session→作答→表单 submit-v2→完成→report→feedback。

    报告生成/异议对应 server/api/assessment.py 的 request_report / submit_feedback 端点；
    全链不显式调 POST /score（D-08 服务端串行链评分）。
    """
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("e2e_main")
    sid = _create_session(pid, headers)
    _answer_whole_session(sid, headers)

    # request_report（202 入队；TestClient 下 background task 同步执行完毕）
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202, r.text

    # 轮询报告（by-session）
    r = client.get(f"/api/assessment/reports/by-session/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    rpt = r.json()
    assert rpt["report_status"] in ("READY", "PROVISIONAL"), rpt["report_status"]
    assert rpt.get("coverage"), "coverage 应非空"
    assert isinstance(rpt.get("total_score"), (int, float))
    # 报告文本可序列化（LLM 产出文案段为字符串）
    assert isinstance(rpt.get("strengths_text", ""), str)
    assert isinstance(rpt.get("weaknesses_text", ""), str)

    # submit_feedback（异议）
    item_id = _q("SELECT item_id FROM competency_item WHERE model_id=?", (mid,))[0]["item_id"]
    r = client.post(f"/api/assessment/reports/{rpt['report_id']}/feedback",
                    json={"item_id": item_id, "feedback_text": "Python 分给低了"}, headers=headers)
    assert r.status_code == 201, r.text


# ---------- 四场景 ----------

def test_refresh_recovery_returns_messages():
    """刷新恢复：get_session 返回 messages（非空 role/content）+ position_name。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("e2e_refresh")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]
    _stream_answer(sid, headers, qid, _LONG_ANSWER)

    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("position_name") == "后端开发工程师"
    assert body.get("messages"), "get_session 应返回非空 messages（刷新恢复渲染契约）"
    assert any(m["role"] == "user" and m["content"] for m in body["messages"])


def test_disconnect_resume_idempotent():
    """断线重试：同 idempotency_key 重发 answer → 200 JSON 快照且消息零重复写（resume）。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("e2e_resume")
    sid = _create_session(pid, headers)
    qid = _first_question(sid, headers)["question_id"]
    key = "e2e-resume-1"

    first = _stream_answer(sid, headers, qid, _LONG_ANSWER, key=key)
    msg_before = _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"]

    # 断线后重连重发（同 key）→ JSON 快照直返，不丢已答题、不重复写消息
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": _LONG_ANSWER, "idempotency_key": key},
                    headers=headers)
    assert r.status_code == 200, r.text
    assert "application/json" in r.headers["content-type"], r.headers
    snap = r.json()
    assert snap["action"] == first["action"]
    assert _q("SELECT COUNT(*) c FROM assessment_message WHERE session_id=?", (sid,))[0]["c"] == msg_before


def test_unauthorized_rejected():
    """越权拒绝：B 读 A 的 session → 404；非管理员访问 admin 路由 → 403。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    a_headers = _auth_headers("e2e_authz_a")
    a_sid = _create_session(pid, a_headers)
    b_headers = _auth_headers("e2e_authz_b")

    r = client.get(f"/api/assessment/sessions/{a_sid}", headers=b_headers)
    assert r.status_code == 404, f"跨用户读会话应 404（D-01 统一不存在），实得 {r.status_code}"

    r = client.get("/api/admin/eval/history", headers=b_headers)
    assert r.status_code == 403, f"非管理员访问 admin 路由应 403，实得 {r.status_code}"


def test_timeout_seal():
    """超时：单题计时器到期（activated_at 时间旅行）→ seal_reason='timeout' + QUESTION_TIMEOUT 事件。"""
    pid, mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid, mid)
    headers = _auth_headers("e2e_timeout")
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

    row = _q("SELECT seal_reason, answered_at FROM assessment_question WHERE question_id=?", (qid,))[0]
    assert row["seal_reason"] == "timeout"
    assert row["answered_at"] is None  # timeout 封存 answered_at 保持 NULL

    evs = _q("SELECT event_type FROM assessment_state_event"
             " WHERE session_id=? AND assessment_question_id=?", (sid, qid))
    assert any(e["event_type"] == "QUESTION_TIMEOUT" for e in evs), evs
