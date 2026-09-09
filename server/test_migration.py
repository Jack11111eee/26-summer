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
    assert [r["version"] for r in rows] == list(range(1, 24))
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
    assert rows[0]["c"] == 23


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
    assert [r["version"] for r in rows] == list(range(1, 24))


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


def test_aggregate_task_migration():
    """migration 15（SSOT §8.4）：聚合任务表。存量库迁移建表 + 新库 _DDL 直接含表，
    两路径表结构一致、二次 init 幂等。"""
    from server.db import _DDL  # 旁证：新库路径 _DDL 直接含 aggregate_task

    assert "CREATE TABLE IF NOT EXISTS aggregate_task" in _DDL

    # 存量库路径：先建到最新（含登记簿 15 行），再把登记簿回拨到 14 模拟「migration 14
    # 时代的存量库」（aggregate_task 由尾部 _DDL IF NOT EXISTS 建过也无妨——迁移幂等）
    init_db()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM schema_version WHERE version >= 15")
        conn.commit()
    finally:
        conn.close()

    init_db()

    cols = {r["name"] for r in _q("PRAGMA table_info(aggregate_task)")}
    assert cols == {
        "task_id", "position_id", "status", "trigger_source", "total", "done",
        "llm_total", "llm_done", "current_item", "model_id", "error",
        "created_at", "started_at", "finished_at",
    }
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    # 回拨到 14 后重放会连 15/16/17/18（aggregate_task/jd_position_index/
    # evidence_exclusion/qbank_task_progress）一并补齐（登记簿始终到最新）
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：CREATE IF NOT EXISTS 幂等，表仍在、登记簿不重放
    assert len(_q("PRAGMA table_info(aggregate_task)")) == 14


def test_jd_position_index():
    """migration 16：存量库自动补建 idx_jd_position（无索引旧库 → 迁移后出现）。"""
    conn = get_conn()
    try:
        # 手造旧 schema（无 position_id 索引）+ 存量行
        conn.execute(
            "CREATE TABLE jd_record(jd_id TEXT PRIMARY KEY,"
            " position_id TEXT REFERENCES position, job_title TEXT, company TEXT,"
            " source_type TEXT NOT NULL, raw_text TEXT NOT NULL, cleaned_text TEXT,"
            " raw_items_json TEXT, std_items_json TEXT, low_confidence INTEGER NOT NULL DEFAULT 0,"
            " status TEXT NOT NULL, error_msg TEXT, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE position(position_id TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " status TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO position VALUES('pos_1', '算法', 'active', '2026-01-01')")
        conn.execute(
            "INSERT INTO jd_record VALUES('jd_1', 'pos_1', 't', 'c', 'paste', 'raw',"
            " NULL, NULL, NULL, 0, 'parsed', NULL, '2026-01-02')"
        )
        conn.commit()
    finally:
        conn.close()

    init_db()

    idx = _q(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jd_position'"
    )
    assert idx and idx[0]["name"] == "idx_jd_position"
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：CREATE IF NOT EXISTS 幂等，索引已存在不重复建
    assert len(_q("SELECT name FROM sqlite_master WHERE type='index' AND"
                " name='idx_jd_position'")) == 1


def test_evidence_exclusion_migration():
    """migration 17（SSOT §8.5）：证据排除表。存量库迁移建表 + 新库 _DDL 直接含表，
    两路径表结构一致、二次 init 幂等。注意 #17 为并入 m5 时的改号（原线曾占 #16，
    与主线 jd_position_index 冲突；登记簿无历史应用记录，改号无兼容性影响）。"""
    from server.db import _DDL  # 旁证：新库路径 _DDL 直接含 evidence_exclusion

    assert "CREATE TABLE IF NOT EXISTS evidence_exclusion" in _DDL

    # 存量库路径：先建到最新（含登记簿 17 行），再把登记簿回拨到 16 模拟「migration 17
    # 之前的存量库」（表由尾部 _DDL IF NOT EXISTS 建过也无妨——迁移幂等）
    init_db()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM schema_version WHERE version >= 17")
        conn.commit()
    finally:
        conn.close()

    init_db()

    cols = {r["name"] for r in _q("PRAGMA table_info(evidence_exclusion)")}
    assert cols == {
        "position_id", "jd_id", "std_name", "category", "text", "reason",
        "excluded_by", "excluded_at", "status", "lifted_by", "lifted_at",
    }
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：CREATE IF NOT EXISTS 幂等，表仍在、登记簿不重放
    assert len(_q("PRAGMA table_info(evidence_exclusion)")) == 11


def test_competency_item_facet_migration():
    """migration 19（SSOT §8.1/§16.1，2026-09-08）：competency_item 补 facet 打标两列。
    存量旧表（无两列）迁移补列 + 存量行值保留；新库 _DDL 直接含两列，两路径一致、二次 init 幂等。"""
    from server.db import _DDL  # 旁证：新库路径 _DDL 的 competency_item 已含两列

    assert "facet_params_json TEXT" in _DDL.split("CREATE TABLE IF NOT EXISTS competency_item")[1]

    # 存量库路径：手造 12 列旧表（migration 19 时代之前）+ 一行存量 gate item
    conn = get_conn()
    try:
        conn.execute(
            "CREATE TABLE competency_item("
            " item_id TEXT PRIMARY KEY, model_id TEXT NOT NULL,"
            " std_name TEXT NOT NULL, category TEXT NOT NULL, required_level INTEGER,"
            " importance TEXT, weight REAL, years REAL, gate INTEGER NOT NULL DEFAULT 0,"
            " level_reason TEXT, occurrence_json TEXT, evidence_json TEXT)"
        )
        conn.execute("CREATE TABLE competency_model(model_id TEXT PRIMARY KEY,"
                     " position_id TEXT, version INTEGER, status TEXT, model_json TEXT,"
                     " confirmed_by TEXT, confirmed_at TEXT, created_at TEXT)")
        conn.execute(
            "INSERT INTO competency_item VALUES('ci_1', 'm_1', '本科及以上学历',"
            " 'qualification', NULL, 'required', 0.0, NULL, 1, 'r', NULL, NULL)"
        )
        conn.commit()
    finally:
        conn.close()

    init_db()

    cols = {r["name"] for r in _q("PRAGMA table_info(competency_item)")}
    assert {"facet_key", "facet_params_json"} <= cols
    # 存量行值原样保留、facet 两列为 NULL（confirmed 模型不回填不重打标）
    row = _q("SELECT * FROM competency_item WHERE item_id='ci_1'")[0]
    assert row["std_name"] == "本科及以上学历" and row["gate"] == 1
    assert row["facet_key"] is None and row["facet_params_json"] is None
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：嗅探幂等，登记簿不重放、两列不重复 ALTER
    assert len(_q("PRAGMA table_info(competency_item)")) == 15


def test_qbank_task_progress_migration():
    """migration 18（SSOT §9.5）：question_bank_task 补进度三列。
    存量旧表（无三列）迁移补列 + 存量行值保留；新库 _DDL 直接含三列，两路径一致、二次 init 幂等。"""
    from server.db import _DDL  # 旁证：新库路径 _DDL 的 question_bank_task 已含三列

    assert "current_item TEXT" in _DDL.split("CREATE TABLE IF NOT EXISTS question_bank_task")[1]

    # 存量库路径：手造 17 列旧表（migration 18 时代之前）+ 一行存量任务
    conn = get_conn()
    try:
        conn.execute(
            "CREATE TABLE question_bank_task("
            " task_id TEXT PRIMARY KEY, position_id TEXT NOT NULL,"
            " model_id TEXT NOT NULL, model_version INTEGER NOT NULL,"
            " status TEXT NOT NULL, created_at TEXT NOT NULL,"
            " started_at TEXT, finished_at TEXT, error_msg TEXT)"
        )
        conn.execute("CREATE TABLE position(position_id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                     " status TEXT NOT NULL, created_at TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO question_bank_task VALUES('qbt_1', 'pos_1', 'm_1', 1,"
            " 'FAILED', '2026-01-01', '2026-01-01', '2026-01-01', '旧错误')"
        )
        conn.commit()
    finally:
        conn.close()

    init_db()

    cols = {r["name"] for r in _q("PRAGMA table_info(question_bank_task)")}
    assert cols == {
        "task_id", "position_id", "model_id", "model_version", "status",
        "created_at", "started_at", "finished_at", "error_msg",
        "total", "done", "current_item",
    }
    # 存量行值原样保留、新三列为 NULL（无可信进度值，不虚构）
    row = _q("SELECT * FROM question_bank_task WHERE task_id='qbt_1'")[0]
    assert row["status"] == "FAILED" and row["error_msg"] == "旧错误"
    assert row["total"] is None and row["done"] is None and row["current_item"] is None
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：嗅探幂等，登记簿不重放、三列不重复 ALTER
    assert len(_q("PRAGMA table_info(question_bank_task)")) == 12


def test_session_hidden_at_migration():
    """migration 21（SSOT §12.1，2026-09-08）：assessment_session 补候选端软隐藏列。
    存量旧表（无该列）迁移补列 + 存量行值保留（hidden_at=NULL 未删除语义）；
    新库 _DDL 直接含列，两路径一致、二次 init 幂等。"""
    from server.db import _DDL  # 旁证：新库路径 _DDL 的 assessment_session 已含该列

    assert "hidden_at" in _DDL.split("CREATE TABLE IF NOT EXISTS assessment_session")[1]

    # 存量库路径：手造旧表（migration 21 时代之前——v2 计时六列已并）+ 一行存量会话
    conn = get_conn()
    try:
        conn.execute(
            "CREATE TABLE assessment_session("
            " session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL,"
            " position_id TEXT NOT NULL, model_id TEXT NOT NULL,"
            " model_version INTEGER NOT NULL,"
            " status TEXT NOT NULL CHECK(status IN ('in_progress','completed','abandoned')),"
            " started_at TEXT NOT NULL, ended_at TEXT, created_at TEXT NOT NULL,"
            " phase TEXT, active_elapsed_seconds INTEGER, last_activity_at TEXT,"
            " abandoned_at TEXT, policy_version TEXT, session_time_intervals_json TEXT)"
        )
        conn.execute(
            "INSERT INTO assessment_session VALUES('sess_1', 'u_1', 'pos_1', 'm_1', 1,"
            " 'in_progress', '2026-01-01', NULL, '2026-01-01', 'ACTIVE', NULL, NULL,"
            " NULL, NULL, NULL)"
        )
        conn.commit()
    finally:
        conn.close()

    init_db()

    cols = {r["name"] for r in _q("PRAGMA table_info(assessment_session)")}
    assert "hidden_at" in cols
    # 存量行值原样保留、hidden_at 为 NULL（未删除语义——历史会话默认可见）
    row = _q("SELECT * FROM assessment_session WHERE session_id='sess_1'")[0]
    assert row["status"] == "in_progress" and row["phase"] == "ACTIVE"
    assert row["hidden_at"] is None
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：嗅探幂等，登记簿不重放、列不重复 ALTER
    assert len(_q("PRAGMA table_info(assessment_session)")) == 16


def test_competency_item_in_scope_migration():
    """migration 22（SSOT §20.1.A，U4 2026-09-09）：competency_item 补测评范围列 in_scope。
    存量旧表（无该列）迁移补列 + 存量行值保留（in_scope=NULL 视为 1 正式范围）；
    新库 _DDL 直接含列，两路径一致、二次 init 幂等。"""
    from server.db import _DDL  # 旁证：新库路径 _DDL 的 competency_item 已含该列

    assert "in_scope" in _DDL.split("CREATE TABLE IF NOT EXISTS competency_item")[1]

    # 存量库路径：手造 facet 时代旧表（migration 22 之前——facet 两列已并）+ 一行存量 item
    conn = get_conn()
    try:
        conn.execute(
            "CREATE TABLE competency_item("
            " item_id TEXT PRIMARY KEY, model_id TEXT NOT NULL,"
            " std_name TEXT NOT NULL, category TEXT NOT NULL, required_level INTEGER,"
            " importance TEXT, weight REAL, years REAL, gate INTEGER NOT NULL DEFAULT 0,"
            " level_reason TEXT, occurrence_json TEXT, evidence_json TEXT,"
            " facet_key TEXT, facet_params_json TEXT)"
        )
        conn.execute("CREATE TABLE competency_model(model_id TEXT PRIMARY KEY,"
                     " position_id TEXT, version INTEGER, status TEXT, model_json TEXT,"
                     " confirmed_by TEXT, confirmed_at TEXT, created_at TEXT)")
        conn.execute(
            "INSERT INTO competency_item VALUES('ci_1', 'm_1', 'Python',"
            " 'hard_skill', 3, 'required', 0.3, NULL, 0, NULL, NULL, NULL, NULL, NULL)"
        )
        conn.commit()
    finally:
        conn.close()

    init_db()

    cols = {r["name"] for r in _q("PRAGMA table_info(competency_item)")}
    assert "in_scope" in cols
    # 存量行值原样保留、in_scope 为 NULL（NULL 视为 1——§20.1.A 存量默认正式范围）
    row = _q("SELECT * FROM competency_item WHERE item_id='ci_1'")[0]
    assert row["std_name"] == "Python" and row["gate"] == 0
    assert row["in_scope"] is None
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：嗅探幂等，登记簿不重放、列不重复 ALTER
    assert len(_q("PRAGMA table_info(competency_item)")) == 15


def test_report_total_score_nullable_migration():
    """migration 23（SSOT §20.3，U4 2026-09-09）：report.total_score NOT NULL → 可空。

    手造 NOT NULL 旧表 + 有值存量行 → 迁移重建放宽 + 存量行 total_score 原样保留；
    迁移后 INSERT NULL 通过（无综合分不以 0 冒充）；二次 init 幂等。"""
    conn = get_conn()
    try:
        # FK 父行（迁移重建后的 report 带 REFERENCES assessment_session，_DDL 同款）
        conn.execute(
            "CREATE TABLE assessment_session(session_id TEXT PRIMARY KEY,"
            " user_id TEXT NOT NULL, position_id TEXT NOT NULL, model_id TEXT NOT NULL,"
            " model_version INTEGER NOT NULL, status TEXT NOT NULL,"
            " started_at TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO assessment_session VALUES('sess_1', 'u_1', 'pos_1', 'm_1', 1,"
            " 'completed', '2026-01-01', '2026-01-01')"
        )
        conn.execute(
            "CREATE TABLE report(report_id TEXT PRIMARY KEY,"
            " session_id TEXT NOT NULL REFERENCES assessment_session,"
            " total_score REAL NOT NULL,"
            " gate_passed INTEGER NOT NULL, report_json TEXT NOT NULL,"
            " created_at TEXT NOT NULL, report_status TEXT, review_status TEXT,"
            " version INTEGER, review_request_reason TEXT, reviewer_id TEXT,"
            " review_note TEXT, review_outcome TEXT, reviewed_at TEXT,"
            " publish_confirmed_by TEXT, published_at TEXT)"
        )
        conn.execute(
            "INSERT INTO report VALUES('rpt_1', 'sess_1', 60.24, 1, '{}',"
            " '2026-01-01', 'PUBLISHED', 'NONE', 1, NULL, NULL, NULL, NULL, NULL,"
            " NULL, NULL)"
        )
        # NOT NULL 旧行为自证：NULL 写入被旧约束拒绝
        try:
            conn.execute(
                "INSERT INTO report(report_id, session_id, total_score, gate_passed,"
                " report_json, created_at) VALUES('rpt_2', 'sess_1', NULL, 0, '{}',"
                " '2026-01-01')"
            )
            raise AssertionError("旧约束下 INSERT NULL 应被拒（实况自证）")
        except AssertionError:
            raise
        except Exception as e:
            assert "NOT NULL" in str(e)
        conn.commit()
    finally:
        conn.close()

    init_db()

    # 建表 SQL 已放宽（不含 total_score REAL NOT NULL）
    rpt_sql = _q("SELECT sql FROM sqlite_master WHERE name='report'")[0]["sql"]
    assert "total_score REAL NOT NULL" not in rpt_sql
    # 存量行值原样保留（有值不动，不重算不归零）
    row = _q("SELECT total_score FROM report WHERE report_id='rpt_1'")[0]
    assert row["total_score"] == 60.24
    # 迁移后 INSERT NULL 通过
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO report(report_id, session_id, total_score, gate_passed,"
            " report_json, created_at) VALUES('rpt_3', 'sess_1', NULL, 0, '{}',"
            " '2026-01-02')"
        )
        conn.commit()
    finally:
        conn.close()
    assert _q("SELECT total_score FROM report WHERE report_id='rpt_3'")[0]["total_score"] is None
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 24))

    init_db()  # 二次 init：嗅探幂等，登记簿不重放、表不重复重建
    assert len(_q("PRAGMA table_info(report)")) == 16
