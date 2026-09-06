"""Phase 4 题库生成失败可见测试（REF-8.4——SSOT §10.4 管理员待办 + readiness FAILED 明细）。

- readiness FAILED 分支返回 QUESTION_BANK_INCOMPLETE + detail 含 error_msg[:200]
- GET /api/admin/todos 返回 question_bank_failed 明细列表
  （position_id/model_id/model_version/error_msg）+ question_bank_not_ready 保持 int

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。单文件单进程。
运行：cd server && python -m pytest test_phase4_fail_visible.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase4_fail_visible.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.readiness import check_session_readiness  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_failed_bank() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + FAILED question_bank_task，返回 (pid, mid)。"""
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
    ]
    model_json = {"position_id": pid, "version": 1, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, 1, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    conn.execute(
        "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
        " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
        (new_id("c"), mid, "Python", "hard_skill", 3, "required", 0.3, 0),
    )
    conn.execute(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at, error_msg) VALUES(?,?,?,?,?,?,?)",
        (new_id("qbt"), pid, mid, 1, "FAILED", now, "LLM 解析异常堆栈：mock 生成失败"),
    )
    conn.commit()
    conn.close()
    return pid, mid


def _ensure_admin() -> None:
    """测试库首跑造 admin（m7 模式：CryptContext bcrypt 直插 user 行，幂等）。"""
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM user WHERE username='p4_admin'").fetchone()
    if row is None:
        from passlib.context import CryptContext

        pwd_ctx = CryptContext(schemes=["bcrypt"])
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (new_id("u"), "p4_admin", pwd_ctx.hash("admin123456"), "admin", now_iso()),
        )
        conn.commit()
    conn.close()


_ensure_admin()


def _admin_headers() -> dict:
    r = client.post("/api/auth/login", json={"username": "p4_admin", "password": "admin123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_readiness_failed_reports_error_msg():
    """REF-8.4：FAILED task → QUESTION_BANK_INCOMPLETE + detail 含 error_msg。"""
    pid, mid = _seed_failed_bank()
    model = _q(
        "SELECT model_id, version, model_json FROM competency_model WHERE model_id=?", (mid,))[0]
    result = check_session_readiness(pid, model=model)
    assert result is not None, "生成失败应阻止开考"
    assert result["error_code"] == "QUESTION_BANK_INCOMPLETE", result
    assert "LLM 解析异常" in result["detail"], f"detail 应含 error_msg: {result}"


def test_todos_reports_failed_detail():
    """REF-8.4：GET /api/admin/todos 含 question_bank_failed 明细 + question_bank_not_ready 为 int。"""
    pid, mid = _seed_failed_bank()
    headers = _admin_headers()
    r = client.get("/api/admin/todos", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["question_bank_not_ready"], int), body
    failed = body["question_bank_failed"]
    assert isinstance(failed, list), body
    match = [f for f in failed if f["position_id"] == pid]
    assert match, f"todos 应含本岗位失败明细: {body}"
    row = match[0]
    assert row["model_id"] == mid
    assert row["model_version"] == 1
    assert "LLM 解析异常" in row["error_msg"]
