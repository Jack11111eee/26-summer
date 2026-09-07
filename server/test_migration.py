"""迁移体系测试（REF-2.11/REF-2.1）：登记簿重放 parity / 幂等 / 旧库迁移。

per-test 独立临时库（autouse _fresh_db 只设路径不 init_db——test_old_db_migration 需
手造旧 schema），不与 conftest session 库共享。运行：cd server && python -m pytest test_migration.py -q
"""
import re

import pytest

from server.db import set_db_path, init_db, get_conn, _DDL


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path):
    set_db_path(str(tmp_path / "test.db"))
    yield
    set_db_path(None)


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """只读查询：开连接→读→关，避免持锁（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def test_fresh_replay():
    init_db()
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 15))
    # REF-2.1 parity：用户表名集合 == 从 _DDL 动态提取的 CREATE TABLE 集合（不硬编码数量）
    ddl_tables = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _DDL))
    actual = {
        r["name"]
        for r in _q(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%' AND name != 'schema_version'"
        )
    }
    assert actual == ddl_tables
    assert len(actual) == len(ddl_tables)


def test_idempotent():
    init_db()
    init_db()  # 二次 init_db 应 no-op：登记簿行数不变
    rows = _q("SELECT COUNT(*) c FROM schema_version")
    assert rows[0]["c"] == 14


def test_old_db_migration():
    conn = get_conn()
    try:
        # 手造旧 schema（call_type 无 'report'、feedback 无 'bad_case'、question_bank 无 v2 列）
        conn.execute(
            "CREATE TABLE llm_trace(trace_id TEXT PRIMARY KEY,"
            " call_type TEXT NOT NULL CHECK(call_type IN ('extract','disambiguate',"
            "'aggregate_level','question_gen','interviewer','refine','score')),"
            " ref_id TEXT NOT NULL, attempt INTEGER NOT NULL, prompt TEXT NOT NULL,"
            " response TEXT, success INTEGER NOT NULL, error TEXT, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE feedback(feedback_id TEXT PRIMARY KEY, report_id TEXT NOT NULL,"
            " item_id TEXT NOT NULL, feedback_text TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','reviewed')),"
            " created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE question_bank(question_id TEXT PRIMARY KEY,"
            " scope TEXT NOT NULL, position_id TEXT, std_name TEXT NOT NULL,"
            " category TEXT NOT NULL, difficulty TEXT, qtype TEXT NOT NULL,"
            " stem TEXT NOT NULL, answer_key TEXT, rubric TEXT, source TEXT NOT NULL,"
            " status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()

    init_db()

    llm_sql = _q("SELECT sql FROM sqlite_master WHERE name='llm_trace'")[0]["sql"]
    assert "'report'" in llm_sql
    fb_sql = _q("SELECT sql FROM sqlite_master WHERE name='feedback'")[0]["sql"]
    assert "'bad_case'" in fb_sql
    qb_cols = {r["name"] for r in _q("PRAGMA table_info(question_bank)")}
    assert {"model_id", "model_version"} <= qb_cols
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 15))


def test_position_inactive_migration():
    """migration 14 岗位审核轮：老 position CHECK 无 'inactive' 时重建放宽，存量行原样保留。"""
    conn = get_conn()
    try:
        # 手造旧 schema（两态 CHECK）+ 双岗存量行
        conn.execute(
            "CREATE TABLE position(position_id TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " status TEXT NOT NULL CHECK(status IN ('pending_review','active')),"
            " created_at TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO position VALUES(?,?,?,?)",
            [("pos_a1", "算法", "active", "2026-01-01"),
             ("pos_p1", "算法专家", "pending_review", "2026-01-02")],
        )
        conn.commit()
    finally:
        conn.close()

    init_db()

    pos_sql = _q("SELECT sql FROM sqlite_master WHERE name='position'")[0]["sql"]
    assert "'inactive'" in pos_sql
    # 存量行的 status 与 PK 迁移后原样保留
    rows = _q("SELECT position_id, name, status FROM position ORDER BY position_id")
    assert rows == [
        {"position_id": "pos_a1", "name": "算法", "status": "active"},
        {"position_id": "pos_p1", "name": "算法专家", "status": "pending_review"},
    ]
    # 放宽后 inactive 可写（下架语义载体）
    conn = get_conn()
    try:
        conn.execute("UPDATE position SET status='inactive' WHERE position_id='pos_a1'")
        conn.commit()
    finally:
        conn.close()
    assert _q("SELECT status FROM position WHERE position_id='pos_a1'")[0]["status"] == "inactive"
