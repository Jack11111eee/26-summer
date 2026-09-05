"""Phase 4 题库版本绑定测试（REF-2.5 / REF-3.4——SSOT §9.2「有效题目 = active 且 model/version 匹配」）。

- 落库绑定：generate_question_bank 每行写 model_id/model_version/item_id/rubric_version='v1'，
  measurement_target/evidence_requirement 留 NULL
- 判重键升级：v1 生成后 v2（新 model_id + version=2）生成不因 v1 active 行跳过
- 消费侧：v2 未生成题库时 readiness 返回 QUESTION_BANK_INCOMPLETE；selection 只取版本匹配行

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。单文件单进程。
运行：cd server && python -m pytest test_phase4_binding.py -v
"""
import json
import os
import sys
import tempfile

import pytest

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase4_binding.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import init_db, get_conn, set_db_path  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402
from server.services.question_bank import generate_question_bank  # noqa: E402
from server.services.question_selection import select_next_question  # noqa: E402
from server.services.readiness import check_session_readiness  # noqa: E402

# 06-01 conftest 先 import server.db 冻结 DB_PATH，模块级 os.environ["DB_PATH"] 赋值已失效；
# 用 function 级 autouse fixture 把 get_conn()/init_db() 指向自建 _tmp_db（隔离于 conftest
# session 共享库），测试结束复位 None，避免 module 级 set_db_path 泄漏到其他测试文件。
@pytest.fixture(autouse=True)
def _point_binding_db():
    set_db_path(_tmp_db)
    init_db()  # 幂等，在 _tmp_db 建表（本文件无 TestClient，显式建表保确定性）
    yield
    set_db_path(None)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _seed_position() -> str:
    conn = get_conn()
    pid = new_id("pos")
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now_iso()),
    )
    conn.commit()
    conn.close()
    return pid


def _seed_model(pid: str, version: int) -> tuple[str, dict]:
    """建 confirmed competency_model + competency_item，返回 (mid, {(std_name,category): item_id})。

    Python(weight>10% → 3 题) + 沟通能力(2 题) + 后端开发经验(scope=general 1 题) = 6 题。
    """
    conn = get_conn()
    mid = new_id("cm")
    now = now_iso()
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
        {"std_name": "沟通能力", "category": "soft_skill", "importance": "required", "weight": 0.25},
        {"std_name": "后端开发经验", "category": "experience", "importance": "required", "weight": 0.08},
    ]
    model_json = {"position_id": pid, "version": version, "items": items}
    conn.execute(
        "INSERT INTO competency_model(model_id, position_id, version, status, model_json, created_at)"
        " VALUES(?,?,?,?,?,?)",
        (mid, pid, version, "confirmed", json.dumps(model_json, ensure_ascii=False), now),
    )
    items_by_key = {}
    for it in items:
        item_id = new_id("c")
        items_by_key[(it["std_name"], it["category"])] = item_id
        conn.execute(
            "INSERT INTO competency_item(item_id, model_id, std_name, category, required_level,"
            " importance, weight, gate) VALUES(?,?,?,?,?,?,?,?)",
            (item_id, mid, it["std_name"], it["category"], 3, it["importance"], it["weight"], 0),
        )
    conn.commit()
    conn.close()
    return mid, items_by_key


def test_generate_writes_binding_columns():
    """REF-2.5：落库每行写 model_id/model_version/item_id/rubric_version='v1'，证据列留 NULL。"""
    pid = _seed_position()
    mid, items_by_key = _seed_model(pid, 1)
    generate_question_bank(pid, mid)

    rows = _q("SELECT * FROM question_bank")
    assert len(rows) == 6, f"期望 6 题（3+2+1），实得 {len(rows)}"
    for r in rows:
        assert r["model_id"] == mid, f"model_id 未绑定: {r['std_name']}"
        assert r["model_version"] == 1, f"model_version 未绑定: {r['std_name']}"
        expected_item_id = items_by_key[(r["std_name"], r["category"])]
        assert r["item_id"] == expected_item_id, \
            f"item_id 未绑定（{r['std_name']}/{r['category']}）: {r['item_id']} != {expected_item_id}"
        assert r["rubric_version"] == "v1", f"rubric_version 应为 'v1': {r['std_name']}"
        assert r["measurement_target"] is None, f"measurement_target 应留 NULL: {r['std_name']}"
        assert r["evidence_requirement"] is None, f"evidence_requirement 应留 NULL: {r['std_name']}"


def test_v2_generation_not_skipped_by_v1():
    """REF-3.4 判重键升级：v1 生成后 v2（新 model_id+version=2）生成不因 v1 active 行跳过。"""
    pid = _seed_position()
    mid1, _ = _seed_model(pid, 1)
    generate_question_bank(pid, mid1)
    v1_count = _q("SELECT COUNT(*) c FROM question_bank WHERE model_id=?", (mid1,))[0]["c"]
    assert v1_count == 6, f"v1 应生成 6 题，实得 {v1_count}"

    mid2, _ = _seed_model(pid, 2)
    generate_question_bank(pid, mid2)
    v2_rows = _q("SELECT * FROM question_bank WHERE model_id=?", (mid2,))
    assert len(v2_rows) == 6, f"v2 应生成 6 题（不因 v1 active 行跳过），实得 {len(v2_rows)}"
    assert all(r["model_version"] == 2 for r in v2_rows)


def test_readiness_blocks_v2_without_bank():
    """REF-3.4 消费侧：v2 confirmed 未生成题库 → check_session_readiness 返回 QUESTION_BANK_INCOMPLETE。"""
    pid = _seed_position()
    mid1, _ = _seed_model(pid, 1)
    generate_question_bank(pid, mid1)
    _mid2, _ = _seed_model(pid, 2)  # v2 confirmed，未生成题库

    model = _q(
        "SELECT model_id, version, model_json FROM competency_model"
        " WHERE model_id=(SELECT model_id FROM competency_model WHERE position_id=?"
        " AND version=2 AND status='confirmed')",
        (pid,),
    )[0]
    result = check_session_readiness(pid, model=model)
    assert result is not None, "v2 无题库应被 readiness 阻止开考"
    assert result["error_code"] == "QUESTION_BANK_INCOMPLETE", result


def test_selection_only_takes_matching_version():
    """REF-3.4 消费侧：selection 只取 model_version 匹配行（v2 无题库 → 无候选）。"""
    pid = _seed_position()
    mid1, _ = _seed_model(pid, 1)
    generate_question_bank(pid, mid1)
    mid2, _ = _seed_model(pid, 2)  # v2 confirmed，未生成题库

    conn = get_conn()
    sid = new_id("s")
    conn.execute(
        "INSERT INTO user(user_id, username, password_hash, role, created_at) VALUES(?,?,?,?,?)",
        (new_id("u"), "p4_bind_sel", "x", "candidate", now_iso()),
    )
    uid = conn.execute(
        "SELECT user_id FROM user WHERE username='p4_bind_sel'").fetchone()["user_id"]
    conn.execute(
        "INSERT INTO assessment_session(session_id, user_id, position_id, model_id,"
        " model_version, status, started_at, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (sid, uid, pid, mid2, 2, "in_progress", now_iso(), now_iso()),
    )
    conn.commit()
    conn.close()

    picked = select_next_question(sid)
    assert picked is None, f"v2 无版本匹配题库，selection 应无候选，实得 {picked}"
