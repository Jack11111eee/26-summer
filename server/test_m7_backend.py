"""M7 测试闭环后端测试：trace 查看器 / feedback / eval runner API。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。
运行：cd server && python -m pytest test_m7_backend.py -v
"""
import json
import os
import sys
import tempfile

_tmp_db = os.path.join(tempfile.mkdtemp(), "test_m7.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()
client = TestClient(app)


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


def _seed_report_and_item() -> tuple[str, str]:
    """造一条 report + competency_item（外键全链），返回 (report_id, item_id)。"""
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
        "INSERT INTO competency_item(item_id, model_id, std_name, category)"
        " VALUES(?,?,?,?)",
        (item_id, model_id, "Python", "hard_skill"),
    )
    # 造 session（report 外键）
    uid = new_id("u")
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (uid, "cand_report", "hash", "candidate", now_iso()),
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
    return report_id, item_id


# ---------- trace viewer ----------


def test_trace_list_and_detail():
    headers = _auth()
    conn = get_conn()
    trace_id = new_id("t")
    conn.execute(
        "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response, success, created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (trace_id, "question_gen", "ref-1", 1, "提示词内容" * 40, "响应内容" * 40, 1, now_iso()),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/admin/trace/list?call_type=question_gen", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    row = next(t for t in body["traces"] if t["trace_id"] == trace_id)
    assert len(row["prompt_preview"]) <= 120
    assert row["success"] is True

    r2 = client.get(f"/api/admin/trace/{trace_id}", headers=headers)
    assert r2.status_code == 200, r2.text
    full = r2.json()
    assert full["prompt"].startswith("提示词内容")
    assert full["success"] is True

    r3 = client.get("/api/admin/trace/does-not-exist", headers=headers)
    assert r3.status_code == 404


def test_trace_by_session():
    headers = _auth()
    conn = get_conn()
    sid, qid = new_id("as"), new_id("aq")
    # 造一行真实 question_bank（外键要求）
    bq_id = new_id("qb")
    pos_id = new_id("p")
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pos_id, "测试岗位", "active", now_iso()),
    )
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,"
        " source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bq_id, "position", pos_id, "Python", "hard_skill",
         "easy", "objective", "测试题", "key", None, None, None,
         "human", "active", now_iso()),
    )
    # 造 assessment_session（外键）
    uid = new_id("u")
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
        " VALUES(?,?,?,?,1,?)",
        (uid, "cand_test", "hash", "candidate", now_iso()),
    )
    model_id = new_id("cm")
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,1,'confirmed','{}',?)",
        (model_id, pos_id, now_iso()),
    )
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id, model_version,"
        " status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pos_id, model_id, 1, "in_progress", now_iso(), now_iso()),
    )
    conn.execute(
        "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq, created_at)"
        " VALUES(?,?,?,?,?)",
        (qid, sid, bq_id, 1, now_iso()),
    )
    conn.execute(
        "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response, success, created_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (new_id("t"), "score", qid, 1, "p", "r", 1, now_iso()),
    )
    conn.commit()
    conn.close()

    r = client.get(f"/api/admin/trace/by-session/{sid}", headers=headers)
    assert r.status_code == 200, r.text
    traces = r.json()
    assert any(t["ref_id"] == qid for t in traces)


# ---------- feedback ----------


def test_feedback_lifecycle():
    headers = _auth()
    report_id, item_id = _seed_report_and_item()

    # 候选人通道（M6 已建）：直接 POST 到候选人端点需要先登录 candidate，
    # 这里绕过 API 直接插库，专注测 admin 侧闭环
    conn = get_conn()
    fid = new_id("fb")
    conn.execute(
        "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (fid, report_id, item_id, "我对 Python 的分数有异议", "pending", now_iso()),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/admin/feedback/list", headers=headers)
    assert r.status_code == 200, r.text
    rows = [f for f in r.json() if f["feedback_id"] == fid]
    assert rows and rows[0]["status"] == "pending"

    r2 = client.post(f"/api/admin/feedback/{fid}/review", json={"note": "核实无误"}, headers=headers)
    assert r2.status_code == 200 and r2.json()["status"] == "reviewed"

    r3 = client.post(f"/api/admin/feedback/{fid}/bad-case", json={"note": "进 bad case"}, headers=headers)
    assert r3.status_code == 200 and r3.json()["status"] == "bad_case"

    r4 = client.get("/api/admin/feedback/list?status=bad_case", headers=headers)
    assert any(f["feedback_id"] == fid for f in r4.json())


# ---------- eval runner ----------


def test_eval_runner_unknown_task():
    headers = _auth()
    r = client.get("/api/admin/eval/results/not-exist", headers=headers)
    assert r.status_code == 404


def test_eval_history_endpoint():
    headers = _auth()
    r = client.get("/api/admin/eval/history", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
