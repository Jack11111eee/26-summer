"""Phase 5 证据链测试（05-01）：span 定位 / 降级 / Unicode / trace_link 校验 / 迁移 / 审计链闭合。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。
运行：cd server && python -m pytest test_phase5_evidence.py -v
"""
import hashlib
import os
import sqlite3
import sys
import tempfile

import pytest

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase5_evidence.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn, set_db_path, _migrate_trace_link  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.trace_link import LINK_ROLES, link_entity  # noqa: E402

# 06-01 conftest 先 import server.db 冻结 DB_PATH，模块级 os.environ["DB_PATH"] 赋值已失效；
# 用 function 级 autouse fixture 把 init_db()/get_conn() 指向自建 _tmp_db（隔离于 conftest
# session 共享库），测试结束复位 None，避免 module 级 set_db_path 泄漏到其他测试文件。
# 本文件 test_ref_id_import_migration 用裸 sqlite3.connect(_tmp_db) 直插行，故须先在 _tmp_db 建表。
@pytest.fixture(autouse=True)
def _point_evidence_db():
    set_db_path(_tmp_db)
    init_db()  # 幂等，在 _tmp_db 建表（TestClient 不触发 startup 事件，显式建表）
    yield
    set_db_path(None)


client = TestClient(app)  # noqa: F841


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _sha(quote: str) -> str:
    return hashlib.sha256(quote.encode("utf-8")).hexdigest()


# ---------- REF-2.10：span 定位 / 降级 / Unicode ----------

def test_span_located_in_original():
    from server.services.scoring import _locate_span  # noqa: E402 (Task 3 落地后可用)
    answer_text = "我们在压测时发现了一个性能问题，主要是连接池配置不当。"
    quote = "性能问题"
    span = _locate_span(answer_text, quote, source_message_id="msg_located")
    assert span is not None
    assert span["source_message_id"] == "msg_located"
    assert span["source_content_type"] == "raw"
    assert span["start_offset"] == answer_text.find(quote)
    assert span["end_offset"] == span["start_offset"] + len(quote)
    assert span["quote_hash"] == _sha(quote)


def test_span_degrade_on_mock_quote():
    from server.services.scoring import _locate_span  # noqa: E402 (Task 3 落地后可用)
    answer_text = "候选人的真实回答文本，不含 mock 占位。"
    quote = "mock quote"
    assert _locate_span(answer_text, quote, source_message_id="msg_degrade") is None


def test_span_unicode_code_point():
    from server.services.scoring import _locate_span  # noqa: E402 (Task 3 落地后可用)
    # 😀 是单 code point（UTF-16 双码元）；𠀀𠀁 是 CJK 扩展 B 生僻字（UTF-16 各双码元）
    answer_text = "😀开头，然后𠀀𠀁生僻字，最后是中文。"
    quote = "𠀀𠀁生僻字"
    span = _locate_span(answer_text, quote, source_message_id="msg_uni")
    assert span is not None
    assert span["start_offset"] == answer_text.find(quote)
    assert span["end_offset"] == span["start_offset"] + len(quote)
    assert answer_text[span["start_offset"]:span["end_offset"]] == quote
    # emoji 单 code point 定位精确
    emoji_span = _locate_span(answer_text, "😀", source_message_id="msg_uni")
    assert emoji_span is not None
    assert answer_text[emoji_span["start_offset"]:emoji_span["end_offset"]] == "😀"


# ---------- REF-2.3：trace_link link_role 枚举校验 ----------

def test_trace_link_role_validation():
    assert set(LINK_ROLES) == {"input", "output", "caused_by", "scored", "reported", "source"}
    conn = get_conn()
    try:
        with pytest.raises(ValueError):
            link_entity(conn, trace_id="t_x", entity_type="question_score",
                        entity_id="qs_x", link_role="bogus")
    finally:
        conn.close()


# ---------- REF-8.7：旧 ref_id 导入 trace_link ----------

def test_ref_id_import_migration():
    # 用无 FK 的裸连接直插（assessment_session 外键链不必齐备——迁移只看 SELECT 1 命中）
    conn = sqlite3.connect(_tmp_db)
    try:
        sid = "sess_refid_hit"
        conn.execute(
            "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
            " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (sid, "u_x", "pos_x", "cm_x", 1, "completed", now_iso(), now_iso()),
        )
        hit_trace = "t_refid_hit"
        miss_trace = "t_refid_miss"
        for trace_id, ref_id in ((hit_trace, sid), (miss_trace, "no_such_entity")):
            conn.execute(
                "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response,"
                " success, error, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (trace_id, "score", ref_id, 1, "p", "r", 1, None, now_iso()),
            )
        conn.commit()
    finally:
        conn.close()

    conn = get_conn()
    try:
        _migrate_trace_link(conn)
        conn.commit()
    finally:
        conn.close()

    links = _q("SELECT trace_id, entity_type, entity_id FROM trace_link")
    hit = [l for l in links if l["trace_id"] == hit_trace]
    assert len(hit) == 1, f"命中行应拆出 1 条 trace_link，实际 {hit}"
    assert hit[0]["entity_type"] == "assessment_session"
    assert hit[0]["entity_id"] == sid
    assert all(l["trace_id"] != miss_trace for l in links), "未命中行不应导入 trace_link"
    miss_row = _q("SELECT ref_id FROM llm_trace WHERE trace_id=?", (miss_trace,))
    assert miss_row and miss_row[0]["ref_id"] == "no_such_entity", "未命中行 ref_id 应保留原值"


# ---------- 审计链闭合（REF-2.3 五要素可达性） ----------

def _resolve(report_id: str, step: str):
    """审计链只读遍历助手（测试内，非生产代码）。

    report→session 经 trace_link('reported'→report / 'source'→assessment_session)——
    该腿 05-03 落地；score→trace 经 trace_link('scored'→question_score) 05-01 落地。
    """
    conn = get_conn()
    try:
        if step == "session":
            row = conn.execute(
                "SELECT tl2.entity_id FROM trace_link tl1"
                " JOIN trace_link tl2 ON tl1.trace_id = tl2.trace_id"
                " WHERE tl1.entity_type='report' AND tl1.entity_id=? AND tl1.link_role='reported'"
                "   AND tl2.entity_type='assessment_session' AND tl2.link_role='source'",
                (report_id,),
            ).fetchone()
            return row["entity_id"] if row else None
        sid = _resolve(report_id, "session")
        if not sid:
            return None
        if step == "model":
            row = conn.execute(
                "SELECT model_id, model_version FROM assessment_session WHERE session_id=?",
                (sid,),
            ).fetchone()
            return (row["model_id"], row["model_version"]) if row else None
        if step == "question":
            row = conn.execute(
                "SELECT question_id FROM assessment_question WHERE session_id=? LIMIT 1", (sid,)
            ).fetchone()
            return row["question_id"] if row else None
        if step == "message":
            row = conn.execute(
                "SELECT message_id FROM assessment_message WHERE session_id=? AND role='user' LIMIT 1",
                (sid,),
            ).fetchone()
            return row["message_id"] if row else None
        if step == "score":
            row = conn.execute(
                "SELECT score_id FROM question_score WHERE session_id=? LIMIT 1", (sid,)
            ).fetchone()
            return row["score_id"] if row else None
        if step == "trace":
            row = conn.execute(
                "SELECT tl.trace_id FROM question_score qs"
                " JOIN trace_link tl ON tl.entity_id=qs.score_id AND tl.entity_type='question_score'"
                "   AND tl.link_role='scored'"
                " WHERE qs.session_id=? LIMIT 1",
                (sid,),
            ).fetchone()
            return row["trace_id"] if row else None
        return None
    finally:
        conn.close()


def _seed_audit_chain() -> str:
    """直插完整审计链：user→position→model→item→session→question→message→score→report→trace。"""
    conn = get_conn()
    try:
        now = now_iso()
        uid, pid, mid, iid = new_id("u"), new_id("pos"), new_id("cm"), new_id("c")
        sid = new_id("sess")
        qbid, qid, msgid = new_id("qb"), new_id("aq"), new_id("msg")
        score_id, report_id, trace_id = new_id("qs"), new_id("rep"), new_id("t")

        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,?,?)", (uid, uid, "x", "candidate", 1, now),
        )
        conn.execute("INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
                     (pid, "岗位", "active", now))
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
            " VALUES(?,?,?,?,?,?)", (mid, pid, 1, "confirmed", "{}", now),
        )
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, gate)"
            " VALUES(?,?,?,?,?)", (iid, mid, "Python", "hard_skill", 0),
        )
        conn.execute(
            "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
            " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (sid, uid, pid, mid, 1, "completed", now, now),
        )
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, std_name, category, qtype, stem,"
            " source, status, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (qbid, "general", "Python", "hard_skill", "subjective", "讲一个性能问题。",
             "human", "active", now),
        )
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " created_at) VALUES(?,?,?,?,?)", (qid, sid, qbid, 1, now),
        )
        conn.execute(
            "INSERT INTO assessment_message(message_id, session_id, question_id, role, content,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (msgid, sid, qid, "user", "我们发现了性能问题，主要是连接池。", now),
        )
        conn.execute(
            "INSERT INTO question_score(score_id, session_id, question_id, item_id, score_final,"
            " score_state, evidence_quote, reason, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (score_id, sid, qid, iid, 3, "SCORED", "性能问题", "mock", now),
        )
        conn.execute(
            "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (report_id, sid, 3.0, 1, "{}", now),
        )
        conn.execute(
            "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response,"
            " success, error, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (trace_id, "score", qid, 1, "p", "r", 1, None, now),
        )
        # 05-01 落地写点：score→trace（scored→question_score / source→assessment_question）
        link_entity(conn, trace_id=trace_id, entity_type="question_score",
                    entity_id=score_id, link_role="scored")
        link_entity(conn, trace_id=trace_id, entity_type="assessment_question",
                    entity_id=qid, link_role="source")
        # 05-03 落地写点：report→session（reported→report / source→assessment_session）
        report_trace = new_id("t")
        link_entity(conn, trace_id=report_trace, entity_type="report",
                    entity_id=report_id, link_role="reported")
        link_entity(conn, trace_id=report_trace, entity_type="assessment_session",
                    entity_id=sid, link_role="source")
        conn.commit()
        return report_id
    finally:
        conn.close()


def test_audit_chain_closure():
    report_id = _seed_audit_chain()
    for step in ["session", "model", "question", "message", "score", "trace"]:
        assert _resolve(report_id, step) is not None, f"审计链断裂 @ {step}"
