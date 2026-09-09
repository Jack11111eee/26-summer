"""Phase 5 REF-7.3 feedback 审计字段测试：submit_feedback 落 user_id + REVIEW_FEEDBACK_RECEIVED 事件、
admin review/bad-case note 持久化、question_reviews 补 item_id。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。
运行：cd server && python -m pytest test_phase5_feedback.py -v
"""
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase5_feedback.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.report import _load_question_reviews  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ---------- admin helpers（照 test_m7_backend.py 内联） ----------

def _ensure_admin() -> None:
    """测试库首跑造 admin（幂等）。"""
    conn = get_conn()
    conn.execute("PRAGMA foreign_keys=ON")
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


_ensure_admin()


def _admin_token() -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {_admin_token()}"}


# ---------- seed helpers ----------

def _seed_candidate_report_item() -> tuple[str, str, str, str, str]:
    """造可登录候选用户 + report + competency_item（外键全链），返回
    (report_id, item_id, session_id, user_id, username)。item 挂 session 锚定模型（WR-06 可过）。"""
    from passlib.context import CryptContext

    pwd_ctx = CryptContext(schemes=["bcrypt"])
    conn = get_conn()
    item_id, report_id = new_id("ci"), new_id("rp")
    pos_id = new_id("p")
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pos_id, "测试岗", "active", now_iso()),
    )
    model_id = new_id("cm")
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,1,'confirmed','{}',?)",
        (model_id, pos_id, now_iso()),
    )
    conn.execute(
        "INSERT INTO competency_item(item_id, model_id, std_name, category) VALUES(?,?,?,?)",
        (item_id, model_id, "Python", "hard_skill"),
    )
    uid = new_id("u")
    username = f"cand_{uid}"
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (uid, username, pwd_ctx.hash("candpass"), "candidate", now_iso()),
    )
    session_id = new_id("as")
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, ended_at, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (session_id, uid, pos_id, model_id, 1, "completed", now_iso(), now_iso(), now_iso()),
    )
    conn.execute(
        "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (report_id, session_id, 80.0, 1, "{}", now_iso()),
    )
    conn.commit()
    conn.close()
    return report_id, item_id, session_id, uid, username


def _candidate_token(username: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": "candpass"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


# ---------- REF-7.3 三条断言 ----------

def test_feedback_audit_fields():
    """submit_feedback 成功后 feedback 行 user_id 非空且等于候选人 user_id；
    assessment_state_event 存在 REVIEW_FEEDBACK_RECEIVED 且 actor_type='candidate'。"""
    report_id, item_id, session_id, uid, username = _seed_candidate_report_item()
    token = _candidate_token(username)
    r = client.post(
        f"/api/assessment/reports/{report_id}/feedback",
        json={"item_id": item_id, "feedback_text": "我对 Python 的分数有异议"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201, r.text
    fb = _q("SELECT user_id FROM feedback WHERE report_id=?", (report_id,))
    assert fb and fb[0]["user_id"] == uid, f"feedback.user_id 应落候选人 {uid}"
    ev = _q(
        "SELECT event_type, actor_type, actor_id FROM assessment_state_event"
        " WHERE session_id=? AND event_type='REVIEW_FEEDBACK_RECEIVED'",
        (session_id,),
    )
    assert ev, "应写 REVIEW_FEEDBACK_RECEIVED 事件"
    assert ev[0]["actor_type"] == "candidate"


def test_admin_note_persisted():
    """admin review/bad-case 持久化 note + reviewer_id + reviewed_at（不再丢弃 body.note）。"""
    headers = _auth()
    report_id, item_id, _session_id, _uid, _username = _seed_candidate_report_item()
    conn = get_conn()
    fid = new_id("fb")
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (fid, report_id, item_id, "对 Python 分数有异议", "pending", now_iso()),
    )
    conn.commit()
    conn.close()
    admin_uid = _q("SELECT user_id FROM user WHERE username='admin'")[0]["user_id"]

    r = client.post(f"/api/admin/feedback/{fid}/review", json={"note": "核实无误"}, headers=headers)
    assert r.status_code == 200, r.text
    row = _q(
        "SELECT status, review_note, reviewer_id, reviewed_at FROM feedback WHERE feedback_id=?",
        (fid,),
    )[0]
    assert row["status"] == "reviewed"
    assert row["review_note"] == "核实无误"
    assert row["reviewer_id"] == admin_uid
    assert row["reviewed_at"]

    r2 = client.post(f"/api/admin/feedback/{fid}/bad-case", json={"note": "进 bad case"}, headers=headers)
    assert r2.status_code == 200, r2.text
    row2 = _q(
        "SELECT status, review_note, reviewer_id, reviewed_at FROM feedback WHERE feedback_id=?",
        (fid,),
    )[0]
    assert row2["status"] == "bad_case"
    assert row2["review_note"] == "进 bad case"
    assert row2["reviewer_id"] == admin_uid
    assert row2["reviewed_at"]


def test_question_reviews_has_item_id():
    """_load_question_reviews 返回的每条逐题回顾携带 item_id（前端 itemReason 可锚定能力项）。"""
    _report_id, item_id, session_id, _uid, _username = _seed_candidate_report_item()
    conn = get_conn()
    bq_id = new_id("qb")
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category, qtype,"
        " stem, source, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (bq_id, "position", None, "Python", "hard_skill", "objective", "测试题",
         "human", "active", now_iso()),
    )
    qid = new_id("aq")
    conn.execute(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq, created_at)"
        " VALUES(?,?,?,?,?)",
        (qid, session_id, bq_id, 1, now_iso()),
    )
    conn.execute(
        "INSERT INTO question_score(score_id, session_id, question_id, item_id, score_live,"
        " score_final, score_state, evidence_quote, reason, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (new_id("qs"), session_id, qid, item_id, 3, 3, "SCORED", "证据引用", "理由", now_iso()),
    )
    conn.commit()
    conn.close()

    reviews = _load_question_reviews(session_id)
    assert reviews, "应有至少一条逐题回顾"
    for rv in reviews:
        assert rv.get("item_id"), f"question_reviews 缺 item_id: {rv}"


# ---------- §22.2 异议详情与列表补列 ----------

def test_feedback_detail_contract():
    """GET /admin/feedback/{id}：admin 200 全字段（原文/提交人/留痕/回溯锚点）/ unknown 404。"""
    headers = _auth()
    report_id, item_id, session_id, uid, username = _seed_candidate_report_item()
    conn = get_conn()
    fid = new_id("fb")
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at, user_id)"
        " VALUES(?,?,?,?,?,?,?)",
        (fid, report_id, item_id, "该题我的实际经历是三年分布式系统开发", "pending", now_iso(), uid),
    )
    conn.commit()
    conn.close()

    r = client.get(f"/api/admin/feedback/{fid}", headers=headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["feedback_id"] == fid
    assert d["feedback_text"] == "该题我的实际经历是三年分布式系统开发"
    assert d["username"] == username
    assert d["std_name"] == "Python"
    assert d["category"] == "hard_skill"
    assert d["report_id"] == report_id
    assert d["item_id"] == item_id
    assert d["session_id"] == session_id
    assert d["status"] == "pending"
    assert d["review_note"] is None and d["reviewed_at"] is None

    r404 = client.get("/api/admin/feedback/fb_nonexistent", headers=headers)
    assert r404.status_code == 404, r404.text


def test_feedback_detail_requires_admin():
    """候选端 token 访问详情端点 403（报告页深链 ?feedback_id= 的静默降级依据）。"""
    report_id, item_id, _session_id, _uid, username = _seed_candidate_report_item()
    conn = get_conn()
    fid = new_id("fb")
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at, user_id)"
        " VALUES(?,?,?,?,?,?,?)",
        (fid, report_id, item_id, "对分数有异议", "pending", now_iso(), _uid),
    )
    conn.commit()
    conn.close()
    r = client.get(f"/api/admin/feedback/{fid}",
                   headers={"Authorization": f"Bearer {_candidate_token(username)}"})
    assert r.status_code == 403, r.text


def test_feedback_list_has_username():
    """GET /admin/feedback/list 行含 username；存量行 user_id NULL（LEFT JOIN）不消失。"""
    headers = _auth()
    report_id, item_id, _session_id, uid, username = _seed_candidate_report_item()
    conn = get_conn()
    fid_new, fid_legacy = new_id("fb"), new_id("fb")
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at, user_id)"
        " VALUES(?,?,?,?,?,?,?)",
        (fid_new, report_id, item_id, "新行带提交人", "pending", now_iso(), uid),
    )
    # 存量形态：Phase 5 审计列加列前的老行（user_id NULL）
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (fid_legacy, report_id, item_id, "旧行无提交人", "pending", now_iso()),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/admin/feedback/list", headers=headers)
    assert r.status_code == 200, r.text
    by_id = {row["feedback_id"]: row for row in r.json()}
    assert fid_new in by_id, "新行应在列表中"
    assert fid_legacy in by_id, "存量 NULL 行不应因 LEFT JOIN 消失"
    assert by_id[fid_new]["username"] == username
    assert by_id[fid_legacy]["username"] is None
