"""Phase 3 SSE 流式答题断言（03-02，REF-4.6/REF-4.7——SSOT §11.5/D-33/D-34）。

覆盖：Content-Type 断言、事件序 decision→reply×N→done、reply 块拼接 == 决策 reply 全文、
done next_question_id 落库一致、decision 扩展键（answer_state/evidence_sufficient）、
abort 先落库再推流（决策/消息/事件在流开始前已 commit）、generator 零 DB 静态断言、
Pydantic 422 三态、HTTPException 仍 JSON（409 在流开始前）、followup/finish 流、m5 返回体同构。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db；单文件单进程。
运行：cd server && python -m pytest test_phase3_sse.py -v
"""
import json
import os
import re
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase3_sse.db")
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


# ---------- fixtures（m5 种子模式——gate=0 全项：池耗尽直通 finish，无表单分支） ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（hard/soft/experience，全 gate=0）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
        {"std_name": "MySQL", "category": "hard_skill", "importance": "required", "weight": 0.25},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "preferred", "weight": 0.2},
        {"std_name": "后端开发经验", "category": "experience", "importance": "required", "weight": 0.25},
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
            (new_id("c"), mid, it["std_name"], it["category"], 3, it["importance"], it["weight"], 0),
        )
    conn.commit()
    conn.close()
    return pid, mid


def _seed_question_bank(pid: str) -> None:
    """岗位题 + 通用题：hard 7 / soft 3 / experience 2 / qualification 1（m5 同款）。"""
    conn = get_conn()
    now = now_iso()

    def _add(scope, position_id, std_name, category, difficulty, qtype, stem, answer_key, rubric,
             chain_key=None, chain_seq=None):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), scope, position_id, std_name, category, difficulty, qtype, stem,
             answer_key, rubric, chain_key, chain_seq, "human", "active", now),
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
    _add("position", pid, "团队协作", "soft_skill", "easy", "subjective",
         "你如何带新人？", None, "方法/耐心")

    _add("general", None, "后端开发经验", "experience", None, "subjective",
         "介绍你最近一个后端项目。", None, "角色/规模/成果")
    _add("general", None, "项目经验", "experience", None, "subjective",
         "最有挑战的项目？", None, "挑战/解决")
    _add("general", None, "学历", "qualification", None, "subjective",
         "最高学历？", None, "本科及以上")
    conn.commit()
    conn.close()


def _auth_headers(username: str = "sse_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# 答案文案（避开 _DECLINE_WORDS 与 _EVIDENCE_WORDS 相近词——test_phase2_interview 同款口径）
_SHORT_ANSWER = "不知道"                                        # 短答 → followup
_LONG_ANSWER = (                                                # 长且含实义词 → VALID_EVIDENCE/next
    "我在电商平台项目中负责订单模块重构，通过拆分大事务重构数据表结构，"
    "把下单接口的响应时间从 800ms 降到了 200ms，并复盘成文档沉淀给团队。"
)


def _stream_answer(sid: str, headers: dict, question_id: str, answer: str) -> dict:
    """流式消费 POST /answer → 组回旧 JSON 同构 dict（action/reply/question_id/
    next_question_id/score_live——回归适配兼容面）。"""
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


def _stream_raw(sid: str, headers: dict, question_id: str, answer: str) -> list[dict]:
    """流式消费，返回原始事件列表（供事件序/帧键断言）。"""
    with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                       json={"question_id": question_id, "answer": answer},
                       headers=headers) as r:
        assert r.status_code == 200, f"answer 应 200，实得 {r.status_code}"
        lines = [ln for ln in r.iter_lines() if ln.startswith("data: ")]
    return [json.loads(ln[6:]) for ln in lines]


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


# ---------- 断言 ----------

def test_answer_is_sse():
    """POST /answer 响应 Content-Type == text/event-stream（sse.js 形态 A 分支接管）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_ctype")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                       json={"question_id": cur["question_id"], "answer": _LONG_ANSWER},
                       headers=headers) as r:
        assert "text/event-stream" in r.headers["content-type"], r.headers
        _ = [ln for ln in r.iter_lines()]


def test_event_sequence():
    """事件序 decision → reply×N → done（reply ≥ 2 块——mock 4 分块），首 decision 末 done。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_seq")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    events = _stream_raw(sid, headers, cur["question_id"], _LONG_ANSWER)
    types = [e["type"] for e in events]
    assert types[0] == "decision", types
    assert types[-1] == "done", types
    reply_count = sum(1 for t in types if t == "reply")
    assert reply_count >= 2, f"reply 应 ≥ 2 块（mock 4 分块），实得 {reply_count}"


def test_reply_reassembled():
    """reply 块拼接 == 决策 reply 全文 == assistant 消息 content（sse.js onReply 语义对齐）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_reply")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    qid = cur["question_id"]
    events = _stream_raw(sid, headers, qid, _LONG_ANSWER)
    decision = next(e for e in events if e["type"] == "decision")
    reply = "".join(e["content"] for e in events if e["type"] == "reply")
    assert reply == decision.get("reply"), "reply 拼接应 == decision 帧 reply 键"
    msg = _q("SELECT content FROM assessment_message"
             " WHERE session_id=? AND role='assistant' AND question_id=?", (sid, qid))
    assert msg and msg[0]["content"] == reply, "reply 拼接应 == assistant 消息全文"


def test_done_next_question_consistency():
    """done next_question_id 非 None 时 assessment_question 该行存在（answered_at 仍 NULL）；done action=='next'。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_done")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    resp = _stream_answer(sid, headers, cur["question_id"], _LONG_ANSWER)
    assert resp["action"] == "next", resp
    assert resp["next_question_id"] is not None
    row = _q("SELECT answered_at FROM assessment_question WHERE question_id=? AND session_id=?",
             (resp["next_question_id"], sid))
    assert row, "done.next_question_id 应指向存在的实例"
    assert row[0]["answered_at"] is None, "下一题实例应仍 active（answered_at NULL）"


def test_decision_extension_keys():
    """decision 帧含 answer_state/evidence_sufficient 扩展键（D-34——VALID_EVIDENCE 路径）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_ext")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    events = _stream_raw(sid, headers, cur["question_id"], _LONG_ANSWER)
    decision = next(e for e in events if e["type"] == "decision")
    assert "answer_state" in decision and "evidence_sufficient" in decision, decision
    assert decision["answer_state"] == "VALID_EVIDENCE", decision
    assert decision["evidence_sufficient"] is True, decision


def test_decision_before_stream_persisted():
    """abort 语义：流建立后仅读 2 行即退出 → 用户消息/assistant 消息/OBSERVATION_CLASSIFIED 已落库
    （先落库再推流——决策在首个 yield 前全部 commit）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_abort")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    qid = cur["question_id"]
    with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                       json={"question_id": qid, "answer": _LONG_ANSWER},
                       headers=headers) as r:
        assert r.status_code == 200
        it = r.iter_lines()
        _l1 = next(it)
        _l2 = next(it)
        # 不消费完即退出（模拟客户端 abort）——已 commit 决策不回滚
    assert _q("SELECT COUNT(*) c FROM assessment_message"
              " WHERE session_id=? AND role='user' AND question_id=?", (sid, qid))[0]["c"] == 1
    assert _q("SELECT COUNT(*) c FROM assessment_message"
              " WHERE session_id=? AND role='assistant' AND question_id=?", (sid, qid))[0]["c"] == 1
    assert _q("SELECT COUNT(*) c FROM assessment_state_event"
              " WHERE session_id=? AND event_type='OBSERVATION_CLASSIFIED'"
              " AND assessment_question_id=?", (sid, qid))[0]["c"] == 1


def test_generator_no_db_access():
    """静态断言：_event_stream generator 函数体零 get_conn / conn.execute / conn.commit（Pitfall 1）。"""
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "server", "api", "assessment.py")
    src = open(src_path, encoding="utf-8").read()
    m = re.search(r"def _event_stream\b.*?(?=\ndef |\n@|\Z)", src, re.S)
    assert m, "_event_stream 未找到"
    body = m.group(0)
    for bad in ("get_conn", "conn.execute", "conn.commit"):
        assert bad not in body, f"generator 函数体含 {bad}"


def test_pydantic_422():
    """AnswerRequest 三态：缺 question_id / answer 纯空格 / answer 缺失 → 422（FastAPI 自动 + WR-02 validator）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_422")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    qid = cur["question_id"]
    url = f"/api/assessment/sessions/{sid}/answer"

    r = client.post(url, json={"answer": "hello"}, headers=headers)
    assert r.status_code == 422, r.text
    r = client.post(url, json={"question_id": qid, "answer": "   "}, headers=headers)
    assert r.status_code == 422, r.text
    r = client.post(url, json={"question_id": qid}, headers=headers)
    assert r.status_code == 422, r.text


def test_http_errors_json():
    """已答题再答 → 409 JSON body（非 SSE——HTTPException 在流开始前抛，普通 JSON 错误）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_409")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    qid = cur["question_id"]
    _stream_answer(sid, headers, qid, _LONG_ANSWER)
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": qid, "answer": _LONG_ANSWER}, headers=headers)
    assert r.status_code == 409, r.text
    assert "text/event-stream" not in r.headers["content-type"]
    assert r.json()["detail"]["error_code"] == "QUESTION_ALREADY_ANSWERED", r.text


def test_followup_and_finish_stream():
    """短答 followup 流；完卷最后一题 done next_question_id None + action=='finish'。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_finish")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)

    # followup：短答触发
    followup = _stream_answer(sid, headers, cur["question_id"], _SHORT_ANSWER)
    assert followup["action"] == "followup", followup

    # 完卷：长答推进直到 finish（gate=0 全项——池耗尽直通 finish，无表单分支）
    last = None
    while True:
        r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
        assert r.status_code == 200, r.text
        cur2 = r.json()["current_question"]
        if cur2 is None:
            break
        last = _stream_answer(sid, headers, cur2["question_id"], _LONG_ANSWER)
        if last["action"] == "finish":
            break
    assert last is not None and last["action"] == "finish", last
    assert last["next_question_id"] is None, "finish 时 next_question_id 应为 None"


def test_m5_answer_flow_parity():
    """_stream_answer 组回 dict 含 action/reply/question_id/next_question_id/score_live 五键（旧返回体同构）。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("sse_parity")
    sid = _create_session(pid, headers)
    cur = _first_question(sid, headers)
    resp = _stream_answer(sid, headers, cur["question_id"], _LONG_ANSWER)
    assert set(resp.keys()) == {"action", "reply", "question_id", "next_question_id", "score_live"}, \
        resp.keys()
