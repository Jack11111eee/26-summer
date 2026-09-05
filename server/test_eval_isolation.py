"""eval 隔离测试（REF-8.8）：评测运行期间业务库零写入，结果经独立业务库连接写回。

验收口径（对齐 checker W5）：b/c 得分契约（b 分差≤1 / c 强>中>弱）只经 eval/*.py CLI
脚本跑、不走 pytest，故本测试用「业务库 assessment_session 行数不变 + eval_results 增
且新写回行 status='completed'（非 failed）」作隔离与写回兜底断言。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_conn, set_db_path
from server.api.admin.eval import _run
from server.services.pipeline import new_id, now_iso


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """只读查询：开连接→读→关，避免持锁（SQLite 单写者）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """业务库播种 position + confirmed model + 一个 hard_skill 能力项（供虚拟考生）。"""
    conn = get_conn()
    uid = new_id("u")
    pid = new_id("p")
    mid = new_id("m")
    item_id = new_id("ci")
    try:
        conn.execute(
            "INSERT INTO user(user_id, username, password_hash, role, is_active, created_at)"
            " VALUES(?,?,?,?,1,?)",
            (uid, "eval_iso_user", "x", "candidate", now_iso()),
        )
        conn.execute(
            "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
            (pid, "eval隔离测试岗", "active", now_iso()),
        )
        conn.execute(
            "INSERT INTO competency_model(model_id, position_id, version, status, model_json,"
            " created_at) VALUES(?,?,?,?,?,?)",
            (mid, pid, 1, "confirmed", "{}", now_iso()),
        )
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, importance,"
            " weight, gate) VALUES(?,?,?,?,?,?,?)",
            (item_id, mid, "数据库", "hard_skill", "required", 1.0, 0),
        )
        conn.commit()
    finally:
        conn.close()
    return pid, mid


def test_eval_isolation():
    set_db_path(None)  # 防御：确保起点无残留 override（业务库 = conftest session 临时库）
    pid, _mid = _seed_position_with_confirmed_model()

    before_sessions = _q("SELECT COUNT(*) c FROM assessment_session")[0]["c"]
    before_results = _q("SELECT COUNT(*) c FROM eval_results")[0]["c"]

    task_id = new_id("ev")
    from eval.virtual_candidates import test_virtual_candidates
    _run(task_id, "virtual_candidates", test_virtual_candidates, pid)

    # 隔离生效：评测运行期间业务库 assessment_session 行数不变（写入全落临时库）
    after_sessions = _q("SELECT COUNT(*) c FROM assessment_session")[0]["c"]
    assert after_sessions == before_sessions, (
        f"业务库 session 被评测写入：{before_sessions} -> {after_sessions}"
    )

    # 写回：eval_results 增 1 行且新写回行 status='completed'（非 failed）
    rows = _q("SELECT status FROM eval_results WHERE task_id=?", (task_id,))
    assert len(rows) == 1, f"eval_results 未写回该 task_id：{task_id}"
    assert rows[0]["status"] == "completed", f"写回状态异常：{rows[0]['status']}"
    after_results = _q("SELECT COUNT(*) c FROM eval_results")[0]["c"]
    assert after_results == before_results + 1
