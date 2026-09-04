"""Phase 2 interviewer 两层化测试（REF-1.3/1.6/1.7/4.3/4.4/4.5——SSOT §11.3/§11.4/§11.5）。

- mock 分类器三向语义（短答/拒答词/实义词）+ 长但空（specificity=1 → insufficient）
- Pydantic 拒绝非法 answer_state（literal_error）+ 5 键契约锁定（Pitfall 8）
- 拒答确认流（首次 confirm → 二次 DECLINED 封存 seal_reason='refused' + QUESTION_SEALED）
- followup ≤2 硬约束（followup_count 列迁移后保持）
- OBSERVATION_CLASSIFIED / EVIDENCE_EVALUATED 事件留痕（§13.2 最小集）

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。单文件单进程。
运行：cd server && python -m pytest test_phase2_interview.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase2_interview.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from server import config  # noqa: E402
from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.schemas import InterviewObservation, ObservationDims  # noqa: E402
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


# ---------- fixtures（test_m5 种子复制压缩版：单 hard item 单链题） ----------

def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（hard×2 + soft×1）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.4},
        {"std_name": "MySQL", "category": "hard_skill", "importance": "required", "weight": 0.3},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.3},
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
    """岗位题：hard 7 / soft 3（N=10 → hard 7 / soft 3 配额可满足；主观题为主）。"""
    conn = get_conn()
    now = now_iso()

    def _add(std_name, category, difficulty, qtype, stem, answer_key, rubric):
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
            " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), "position", pid, std_name, category, difficulty, qtype,
             stem, answer_key, rubric, None, None, "human", "active", now),
        )

    # hard_skill：Python×4 + MySQL×3（easy/medium/hard 各层，主观链）
    for d in ("easy", "medium", "hard", "easy"):
        _add("Python", "hard_skill", d, "subjective",
             f"讲一个你用 Python 解决的 {d} 问题。", None, "场景/方法/结果")
    for d in ("easy", "medium", "hard"):
        _add("MySQL", "hard_skill", d, "subjective",
             f"讲一次 MySQL {d} 层面的优化经历。", None, "explain/索引/效果")
    # soft_skill：沟通能力×3
    for d in ("easy", "medium", "hard"):
        _add("沟通能力", "soft_skill", d, "subjective",
             f"讲一次跨团队沟通经历（{d}）。", None, "背景/冲突/结果")
    conn.commit()
    conn.close()


def _auth_headers(username: str = "p2_itv_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _new_session(username: str) -> tuple[str, dict]:
    """建会话并派发首题，返回 (sid, headers)。"""
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers(username)
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["current_question"] is not None, "首次 GET 应派发首题"
    return sid, headers


def _cur_q(sid: str, headers: dict) -> dict:
    r = client.get(f"/api/assessment/sessions/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    cur = r.json()["current_question"]
    assert cur is not None
    return cur


def _answer(sid: str, headers: dict, question_id: str, answer: str) -> dict:
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": question_id, "answer": answer}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# 答案文案：避开 _DECLINE_WORDS 与 _EVIDENCE_WORDS 的相近词（plan Task 1 提醒）
_DECLINE_ANSWER = "这道题我不方便回答，涉及隐私"          # 含 "不方便回答"+"隐私"
_SHORT_ANSWER = "不知道"                                   # 5 字 → 长度分支
_EVIDENCE_ANSWER = (                                     # 长且含 "项目/数据/负责"
    "我在电商平台项目中负责订单模块重构，通过拆分大事务重构数据表结构，"
    "把下单接口的响应时间从 800ms 降到了 200ms，并复盘成文档沉淀给团队。"
)
_LONG_EMPTY_ANSWER = (                                    # 长但无实义词
    "这个问题嘛，我觉得总体上来说还是挺有说道的地方的，"
    "不过具体细节方面当时的情况也是比较复杂的，各色各样的因素交织在一起。"
)


# ---------- 纯函数断言（Pydantic 契约 / 5 键契约） ----------

def test_pydantic_rejects_invalid_state():
    """非法 answer_state → ValidationError 且错误类型为 literal_error（T-02-16）。"""
    with pytest.raises(ValidationError) as ei:
        InterviewObservation(answer_state="HACKED",
                             observation=ObservationDims(relevance=True, specificity=2,
                                                          attribution=True))
    types = {e["type"] for e in ei.value.errors()}
    assert "literal_error" in types, f"错误类型应含 literal_error，实得 {types}"


def test_pydantic_accepts_all_11_states():
    """11 态 Literal 白名单全可通过校验（REF-4.4 schema 化）。"""
    for s in ("VALID_EVIDENCE", "NEED_CLARIFICATION", "OFF_TOPIC", "NO_RECALL", "DECLINED",
              "PROCESS_CHALLENGE", "CONDUCT_EVENT", "TECHNICAL_OR_ACCESS_BARRIER",
              "PROMPT_INJECTION", "MODEL_UNCERTAIN", "ITEM_INVALID"):
        obs = InterviewObservation(answer_state=s,
                                   observation=ObservationDims(relevance=True, specificity=1))
        assert obs.answer_state == s


def test_decision_contract_5keys():
    """decide_next_action 返回 dict 必含 5 基础键（前端 sse.js 消费面锁定，Pitfall 8）。"""
    from server.services.interview import decide_next_action
    sid, headers = _new_session("p2_itv_5keys")
    cur = _cur_q(sid, headers)
    decision = decide_next_action(sid, cur["question_id"], _EVIDENCE_ANSWER)
    for key in ("action", "reason", "reply", "score_live", "score_live_reason"):
        assert key in decision, f"5 键契约缺 {key}: {sorted(decision)}"


# ---------- mock 分类器三向语义（D-23） ----------

def test_mock_classifier_short_answer():
    """短答（<20 字）→ answer_state=NEED_CLARIFICATION 且 action=followup。"""
    sid, headers = _new_session("p2_itv_short")
    cur = _cur_q(sid, headers)
    resp = _answer(sid, headers, cur["question_id"], _SHORT_ANSWER)
    assert resp["action"] == "followup"


def test_mock_classifier_declined():
    """拒答关键词 → answer_state=DECLINED，首次 action='confirm'，reply 含确认话术。"""
    sid, headers = _new_session("p2_itv_declined")
    cur = _cur_q(sid, headers)
    resp = _answer(sid, headers, cur["question_id"], _DECLINE_ANSWER)
    assert resp["action"] == "confirm"
    assert "跳过" in resp["reply"] or "不再" in resp["reply"], \
        f"confirm reply 应含跳过提示，实得 {resp['reply']!r}"
    # 会话不中断：实例未封存，可继续操作
    row = _q("SELECT closed_at, seal_reason FROM assessment_question WHERE question_id=?",
             (cur["question_id"],))[0]
    assert row["closed_at"] is None and row["seal_reason"] is None


def test_mock_classifier_evidence():
    """长且含实义词 → answer_state=VALID_EVIDENCE，evidence_sufficient=True → next。"""
    sid, headers = _new_session("p2_itv_evidence")
    cur = _cur_q(sid, headers)
    resp = _answer(sid, headers, cur["question_id"], _EVIDENCE_ANSWER)
    assert resp["action"] in ("next", "finish"), f"实义词充分证据应推进，实得 {resp['action']}"
    # 实例已按 answered 封存（next 即封存——closed_at + seal_reason='answered'）
    row = _q("SELECT closed_at, seal_reason FROM assessment_question WHERE question_id=?",
             (cur["question_id"],))[0]
    assert row["closed_at"] is not None and row["seal_reason"] == "answered"


def test_mock_classifier_long_but_empty():
    """长但无实义词 → VALID_EVIDENCE 但 specificity=1/attribution=False → followup。"""
    sid, headers = _new_session("p2_itv_empty")
    cur = _cur_q(sid, headers)
    resp = _answer(sid, headers, cur["question_id"], _LONG_EMPTY_ANSWER)
    assert resp["action"] == "followup", \
        f"长但空的回答应 evidence_sufficient=False → followup，实得 {resp['action']}"


def test_decision_extended_keys():
    """decision dict 扩展键 answer_state/evidence_sufficient（只加不减——供测试与 02-03 消费）。"""
    sid, headers = _new_session("p2_itv_extkeys")
    cur = _cur_q(sid, headers)
    from server.services.interview import decide_next_action
    decision = decide_next_action(sid, cur["question_id"], _EVIDENCE_ANSWER)
    assert decision["answer_state"] == "VALID_EVIDENCE"
    assert decision["evidence_sufficient"] is True


# ---------- 拒答确认流（D-24：confirm 一次性 + 二次封存 refused） ----------

def test_refusal_confirm_skip():
    """首次 DECLINED → confirm；二次 DECLINED → 封存 refused + QUESTION_SEALED + 下一题。"""
    sid, headers = _new_session("p2_itv_refuse")
    cur = _cur_q(sid, headers)
    qid = cur["question_id"]

    # 首次拒答 → confirm（不封存）
    resp1 = _answer(sid, headers, qid, _DECLINE_ANSWER)
    assert resp1["action"] == "confirm"

    # 二次拒答 → 封存 + 跳下一题
    resp2 = _answer(sid, headers, qid, _DECLINE_ANSWER)
    assert resp2["action"] in ("next", "finish"), \
        f"二次拒答应封存后推进，实得 {resp2['action']}"
    assert resp2.get("next_question_id") is not None and resp2["next_question_id"] != qid, \
        "拒答封存后应正常派发下一题（会话不中断）"

    row = _q("SELECT closed_at, seal_reason FROM assessment_question WHERE question_id=?",
             (qid,))[0]
    assert row["closed_at"] is not None, "二次拒答后实例应封存（closed_at 非 NULL）"
    assert row["seal_reason"] == "refused", f"seal_reason 应为 refused，实得 {row['seal_reason']}"

    evs = _q("SELECT event_type, payload_json FROM assessment_state_event"
             " WHERE session_id=? AND assessment_question_id=?", (sid, qid))
    sealed = [e for e in evs if e["event_type"] == "QUESTION_SEALED"]
    assert sealed, f"应含 QUESTION_SEALED 事件，实得 {[e['event_type'] for e in evs]}"
    payload = json.loads(sealed[0]["payload_json"])
    assert payload.get("seal_reason") == "refused", payload


# ---------- followup ≤2 硬约束（D-25 迁列后保持） ----------

def test_followup_hard_limit():
    """同实例连续 3 次短回答 → 第 3 次强制 next；followup_count 列值 == 2。"""
    sid, headers = _new_session("p2_itv_limit")
    cur = _cur_q(sid, headers)
    qid = cur["question_id"]

    r1 = _answer(sid, headers, qid, _SHORT_ANSWER)
    assert r1["action"] == "followup"
    r2 = _answer(sid, headers, qid, _SHORT_ANSWER)
    assert r2["action"] == "followup"
    r3 = _answer(sid, headers, qid, _SHORT_ANSWER)
    assert r3["action"] in ("next", "finish"), \
        f"第 3 次短答应被强制推进（基线 ≤2 保持），实得 {r3['action']}"

    row = _q("SELECT followup_count FROM assessment_question WHERE question_id=?", (qid,))[0]
    assert row["followup_count"] == 2, \
        f"followup_count 列应记 2（拒答确认不计入 followup），实得 {row['followup_count']}"


# ---------- 事件留痕（§13.2 最小集——新增两组） ----------

def test_observation_events():
    """一次答题后事件表含 OBSERVATION_CLASSIFIED，payload 有 answer_state/evidence_sufficient。"""
    sid, headers = _new_session("p2_itv_events")
    cur = _cur_q(sid, headers)
    _answer(sid, headers, cur["question_id"], _EVIDENCE_ANSWER)

    evs = _q("SELECT event_type, payload_json FROM assessment_state_event"
             " WHERE session_id=? AND assessment_question_id=? AND event_type='OBSERVATION_CLASSIFIED'",
             (sid, cur["question_id"]))
    assert evs, "应含 OBSERVATION_CLASSIFIED 事件"
    payload = json.loads(evs[0]["payload_json"])
    assert "answer_state" in payload and "evidence_sufficient" in payload, payload


def test_evidence_evaluated_event_on_seal():
    """封存时机（answered/refused）应落 EVIDENCE_EVALUATED（evidence_sufficient + stable）。"""
    sid, headers = _new_session("p2_itv_eveval")
    cur = _cur_q(sid, headers)
    _answer(sid, headers, cur["question_id"], _EVIDENCE_ANSWER)

    evs = _q("SELECT event_type, payload_json FROM assessment_state_event"
             " WHERE session_id=? AND assessment_question_id=? AND event_type='EVIDENCE_EVALUATED'",
             (sid, cur["question_id"]))
    assert evs, "answered 封存时机应落 EVIDENCE_EVALUATED 事件"
    payload = json.loads(evs[0]["payload_json"])
    assert "evidence_sufficient" in payload and "stable_evidence" in payload, payload
