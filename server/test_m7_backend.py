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
    model_id = new_id("cm")
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,1,'confirmed','{}',?)",
        (model_id, pos_id, now_iso()),
    )
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, model_id, model_version, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,"
        " source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (bq_id, "position", pos_id, model_id, 1, "Python", "hard_skill",
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


# ---------- eval 历史删除 + options banked 过滤（SSOT §23，2026-09-09） ----------


def _seed_eval_rows(n_terminal: int = 2) -> list[str]:
    """插 n_terminal 条终态 + 1 条 running 历史，返回终态 task_id 列表。"""
    conn = get_conn()
    ids = []
    for i in range(n_terminal):
        tid = new_id("ev")
        ids.append(tid)
        conn.execute(
            "INSERT INTO eval_results(task_id, test_name, status, created_at, completed_at)"
            " VALUES(?,?,?,?,?)",
            (tid, "scoring_consistency", "completed" if i % 2 == 0 else "failed",
             now_iso(), now_iso()),
        )
    conn.commit()
    conn.close()
    return ids


def _seed_running_eval_row() -> str:
    tid = new_id("ev")
    conn = get_conn()
    conn.execute(
        "INSERT INTO eval_results(task_id, test_name, status, created_at)"
        " VALUES(?,?, 'running', ?)",
        (tid, "virtual_candidates", now_iso()),
    )
    conn.commit()
    conn.close()
    return tid


def test_eval_delete_single_terminal():
    headers = _auth()
    ids = _seed_eval_rows(1)
    r = client.delete(f"/api/admin/eval/results/{ids[0]}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1
    # 历史中不再出现
    rows = [h for h in client.get("/api/admin/eval/history", headers=headers).json()
            if h["task_id"] == ids[0]]
    assert not rows


def test_eval_delete_running_409():
    headers = _auth()
    tid = _seed_running_eval_row()
    r = client.delete(f"/api/admin/eval/results/{tid}", headers=headers)
    assert r.status_code == 409, r.text
    # 行仍在
    r2 = client.get(f"/api/admin/eval/results/{tid}", headers=headers)
    assert r2.status_code == 200


def test_eval_delete_unknown_404():
    headers = _auth()
    r = client.delete("/api/admin/eval/results/not-exist", headers=headers)
    assert r.status_code == 404, r.text


def test_eval_batch_delete_happy_path():
    headers = _auth()
    ids = _seed_eval_rows(3)
    r = client.post("/api/admin/eval/results/batch-delete",
                    json={"task_ids": ids}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 3
    rows = [h for h in client.get("/api/admin/eval/history", headers=headers).json()
            if h["task_id"] in ids]
    assert not rows


def test_eval_batch_delete_containing_running_409_no_partial_delete():
    """批量含 running 行 → 整体 409，终态行也不删（不留半途状态）。"""
    headers = _auth()
    ids = _seed_eval_rows(2)
    running = _seed_running_eval_row()
    r = client.post("/api/admin/eval/results/batch-delete",
                    json={"task_ids": [*ids, running]}, headers=headers)
    assert r.status_code == 409, r.text
    # 部分删除防御：终态行原样保留
    rows = {h["task_id"] for h in client.get("/api/admin/eval/history", headers=headers).json()}
    assert set(ids) <= rows


def test_eval_batch_delete_unknown_404():
    headers = _auth()
    ids = _seed_eval_rows(1)
    r = client.post("/api/admin/eval/results/batch-delete",
                    json={"task_ids": [*ids, "ev_not_exist"]}, headers=headers)
    assert r.status_code == 404, r.text
    # 先校验后变异：合法行也不删
    rows = {h["task_id"] for h in client.get("/api/admin/eval/history", headers=headers).json()}
    assert set(ids) <= rows


def test_eval_batch_delete_empty_and_duplicate_422():
    headers = _auth()
    r = client.post("/api/admin/eval/results/batch-delete",
                    json={"task_ids": []}, headers=headers)
    assert r.status_code == 422, r.text
    ids = _seed_eval_rows(1)
    r = client.post("/api/admin/eval/results/batch-delete",
                    json={"task_ids": [ids[0], ids[0]]}, headers=headers)
    assert r.status_code == 422, r.text


def _seed_position_with_bank(pid: str, name: str, st: str,
                             qb_status: str | None) -> None:
    """造岗位 + 可选一条题库行（qb_status None = 不落题）。"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, name, st, now_iso()),
    )
    if qb_status:
        conn.execute(
            "INSERT INTO question_bank(question_id, scope, position_id, std_name,"
            " category, qtype, stem, source, status, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (new_id("qb"), "position", pid, "Python", "hard_skill", "objective",
             "题干", "human", qb_status, now_iso()),
        )
    conn.commit()
    conn.close()


def test_options_banked_filter():
    """?banked=1 只回有 active 题库行的岗位；archived 行不算；与 status 组合生效。"""
    headers = _auth()
    # 1: active+有题（应出现）；2: active+无题（排除——题库未落库）
    # 3: active+仅 archived 题（排除——非使用中）；4: inactive+有题（status 组合排除）；
    # 5: pending_review+有题（status 组合排除）
    _seed_position_with_bank(new_id("p"), "有题岗", "active", "active")
    _seed_position_with_bank(new_id("p"), "无题岗", "active", None)
    _seed_position_with_bank(new_id("p"), "归档题岗", "active", "archived")
    _seed_position_with_bank(new_id("p"), "下架有题岗", "inactive", "active")
    _seed_position_with_bank(new_id("p"), "待审有题岗", "pending_review", "active")

    r = client.get("/api/admin/positions/options",
                   params={"banked": 1}, headers=headers)
    assert r.status_code == 200, r.text
    names = {x["name"] for x in r.json()}
    assert "有题岗" in names
    assert "无题岗" not in names
    assert "归档题岗" not in names
    # banked 单独传（不与 status 组合）：inactive/pending 的有题岗也入列
    # （banked 只看题库，岗位状态过滤仍由 status 参数职责承担）
    assert "下架有题岗" in names
    assert "待审有题岗" in names

    # 组合（测试中心实际传参）：status=active&banked=1
    r2 = client.get("/api/admin/positions/options",
                    params={"status": "active", "banked": 1}, headers=headers)
    assert r2.status_code == 200, r2.text
    names2 = {x["name"] for x in r2.json()}
    assert "有题岗" in names2
    assert "无题岗" not in names2 and "归档题岗" not in names2
    assert "下架有题岗" not in names2 and "待审有题岗" not in names2

    # 不传 banked = 不过滤（改归/合并目标下拉既有语义不变）
    r3 = client.get("/api/admin/positions/options", headers=headers)
    names3 = {x["name"] for x in r3.json()}
    assert {"有题岗", "无题岗", "归档题岗", "下架有题岗", "待审有题岗"} <= names3
