"""Phase 2 wave 0：三表结构演进迁移双路径测试（02-01，REF-2.7/REF-2.9/REF-3.7）。

老库路径：模块级先用【旧版 DDL】直连临时库建旧结构三表 + 插旧行（init_db 的
executescript(_DDL) 是 CREATE IF NOT EXISTS 不动已有表，迁移函数才会 ALTER），
再各测试内调 init_db() 断言新列全在、锚点回填、score_final 合并、唯一索引。
新库路径：换临时库直跑 init_db()（PRAGMA 断言 _DDL 直建含新列——Pitfall 2 双轨纪律）。

全程仅 sqlite3/PRAGMA 断言，无 API 调用；测试库全部在 tempfile.mkdtemp()，
不碰 data/app.db；不 import 其他测试模块（单文件单进程纪律）。
运行：cd server && python -m pytest test_phase2_migration.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_dir = tempfile.mkdtemp()
_tmp_db = os.path.join(_tmp_dir, "test_phase2_migration.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- 旧版三表 DDL（Phase 2 之前结构：question_bank 15 列 / assessment_question 现有列 /
# question_score 含 final_score+score_final 双列），模拟老业务库 ----
_OLD_DDL = """
CREATE TABLE question_bank (
  question_id TEXT PRIMARY KEY,
  scope       TEXT NOT NULL CHECK(scope IN ('position','general')),
  position_id TEXT REFERENCES position,
  std_name    TEXT NOT NULL,
  category    TEXT NOT NULL CHECK(category IN ('hard_skill','soft_skill','experience','qualification')),
  difficulty  TEXT CHECK(difficulty IN ('easy','medium','hard')),
  qtype       TEXT NOT NULL CHECK(qtype IN ('objective','subjective')),
  stem        TEXT NOT NULL,
  answer_key  TEXT,
  rubric      TEXT,
  chain_key   TEXT,
  chain_seq   INTEGER,
  source      TEXT NOT NULL CHECK(source IN ('llm_seed','imported','human')),
  status      TEXT NOT NULL DEFAULT 'active',
  created_at  TEXT NOT NULL
);

CREATE TABLE assessment_question (
  question_id      TEXT PRIMARY KEY,
  session_id       TEXT NOT NULL REFERENCES assessment_session,
  bank_question_id TEXT NOT NULL REFERENCES question_bank,
  seq              INTEGER NOT NULL,
  asked_at         TEXT,
  answered_at      TEXT,
  created_at       TEXT NOT NULL
);

CREATE TABLE question_score (
  score_id       TEXT PRIMARY KEY,
  session_id     TEXT NOT NULL REFERENCES assessment_session,
  question_id    TEXT NOT NULL REFERENCES assessment_question,
  item_id        TEXT NOT NULL REFERENCES competency_item,
  score_live     INTEGER,
  score_final    INTEGER,
  final_score    INTEGER,
  evidence_quote TEXT,
  reason         TEXT,
  created_at     TEXT NOT NULL
);
"""

_NOW = "2026-01-01T00:00:00"


def _build_old_db(db_path: str, with_duplicate_seq: bool = False) -> None:
    """直连临时库用旧版 DDL 建三表并插旧行（模拟 Phase 2 之前的业务库）。

    with_duplicate_seq=True 时追加同 (session_id, seq) 旧行，用于断言迁移重复检测。
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_OLD_DDL)
        for qid, cat, diff, qtype in (
            ("qb_old_easy", "hard_skill", "easy", "objective"),
            ("qb_old_medium", "hard_skill", "medium", "objective"),
            ("qb_old_hard", "hard_skill", "hard", "subjective"),
            ("qb_old_null", "experience", None, "subjective"),
        ):
            conn.execute(
                "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
                " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source,"
                " status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (qid, "general", None, qid.split("_", 2)[-1], cat, diff, qtype, f"{qid} 题面",
                 None, None, None, None, "human", "active", _NOW),
            )
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
            " asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
            ("aq_old_1", "sess_old_1", "qb_old_easy", 1, _NOW, _NOW, _NOW),
        )
        if with_duplicate_seq:
            conn.execute(
                "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq,"
                " asked_at, answered_at, created_at) VALUES(?,?,?,?,?,?,?)",
                ("aq_old_2", "sess_old_1", "qb_old_medium", 1, _NOW, _NOW, _NOW),
            )
        conn.execute(
            "INSERT INTO question_score(score_id, session_id, question_id, item_id, score_live,"
            " score_final, final_score, evidence_quote, reason, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("sc_old_1", "sess_old_1", "aq_old_1", "ci_old_1", 2, 2, 3, None, None, _NOW),
        )
        conn.commit()
    finally:
        conn.close()


_build_old_db(_tmp_db)

from server.db import init_db, get_conn  # noqa: E402
import server.db as db_module  # noqa: E402


def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _cols(table: str) -> set[str]:
    """PRAGMA table_info 取列名集合（表名为测试内字面量，无用户输入）。"""
    return {r["name"] for r in _q(f"PRAGMA table_info({table})")}


# Phase 2 新列清单（D-14：全部 ALTER ADD COLUMN，无 DB CHECK——N11）
_QB_NEW_COLS = {
    "model_id", "model_version", "item_id", "question_type", "measurement_stage",
    "measurement_target", "evidence_requirement", "observable_level_max",
    "observable_level_min", "rubric_version",
}
_AQ_NEW_COLS = {
    "question_type", "measurement_stage", "item_id", "difficulty", "status",
    "activated_at", "closed_at", "followup_count", "seal_reason", "selection_reason",
    "selection_policy_version", "path_state_snapshot",
}
_QS_NEW_COLS = {"score_state"}


def test_old_db_migration_adds_columns():
    """老库路径：手工旧结构建库插旧行 → init_db() → 三表新列全在（ALTER 路径）。"""
    init_db()
    assert _QB_NEW_COLS <= _cols("question_bank"), \
        f"question_bank 缺列: {_QB_NEW_COLS - _cols('question_bank')}"
    assert _AQ_NEW_COLS <= _cols("assessment_question"), \
        f"assessment_question 缺列: {_AQ_NEW_COLS - _cols('assessment_question')}"
    assert _QS_NEW_COLS <= _cols("question_score"), \
        f"question_score 缺列: {_QS_NEW_COLS - _cols('question_score')}"
    # D-15 旧行语义：question_type 旧行='legacy' 不参与新选题路径；status 旧行 NULL
    aq = _q("SELECT question_type, followup_count, status FROM assessment_question"
            " WHERE question_id='aq_old_1'")[0]
    assert aq["question_type"] == "legacy"
    assert aq["followup_count"] == 0
    assert aq["status"] is None  # 旧行 NULL = legacy；新实例才 'active'/'sealed'
    qb = _q("SELECT question_type, measurement_stage FROM question_bank"
            " WHERE question_id='qb_old_easy'")[0]
    assert qb["question_type"] == "ordinary"
    assert qb["measurement_stage"] == "ordinary"
    # 存量评分行回填 'SCORED'（旧行均为正常评分）
    sc = _q("SELECT score_state FROM question_score WHERE score_id='sc_old_1'")[0]
    assert sc["score_state"] == "SCORED"


def test_anchor_backfill():
    """老库路径：§9.4 锚点回填 easy[2,3]/medium[3,4]/hard[4,5]；difficulty NULL 行保持 NULL。"""
    init_db()
    for qid, want_max, want_min in (
        ("qb_old_easy", 3, 2),
        ("qb_old_medium", 4, 3),
        ("qb_old_hard", 5, 4),
    ):
        row = _q("SELECT observable_level_max, observable_level_min FROM question_bank"
                 " WHERE question_id=?", (qid,))[0]
        assert row["observable_level_max"] == want_max, qid
        assert row["observable_level_min"] == want_min, qid
    null_row = _q("SELECT observable_level_max, observable_level_min FROM question_bank"
                  " WHERE question_id='qb_old_null'")[0]
    assert null_row["observable_level_max"] is None
    assert null_row["observable_level_min"] is None


def test_score_final_merge():
    """老库路径：COALESCE(final_score, score_final) 合并——final_score=3 覆盖 score_final=2；
    合并完成后列 DROP（02-05 A8 次序合同收尾——断言翻转归 02-05 任务 3 所有权）。"""
    init_db()
    sc = _q("SELECT score_final FROM question_score WHERE score_id='sc_old_1'")[0]
    assert sc["score_final"] == 3  # COALESCE 合并在 DROP 段之前执行（老库行值先并入）
    assert "final_score" not in _cols("question_score")  # 02-05：消费点切换完成后 DROP


def test_unique_index_created():
    """老库路径：uq_aq_session_seq 唯一索引存在（Q2 决议：沿用 seq 列承载 sequence_no 语义）。"""
    init_db()
    assert _q("SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_aq_session_seq'")


def test_unique_index_is_unique():
    """双路径：uq_aq_session_seq 必须为 UNIQUE 索引（老库 ALTER 路径与 _DDL 直建路径一致）。"""
    init_db()
    for row in _q("PRAGMA index_list(assessment_question)"):
        if row["name"] == "uq_aq_session_seq":
            assert row["unique"] == 1, "uq_aq_session_seq 必须为 UNIQUE 索引（Q2 决议）"
            break
    else:
        raise AssertionError("uq_aq_session_seq 不存在于老库路径")

    fresh_db = os.path.join(tempfile.mkdtemp(), "new_unique.db")
    original = db_module.DB_PATH
    db_module.DB_PATH = fresh_db
    try:
        init_db()
    finally:
        db_module.DB_PATH = original
    conn = sqlite3.connect(fresh_db)
    try:
        indexes = conn.execute("PRAGMA index_list(assessment_question)").fetchall()
        row = next((r for r in indexes if r[1] == "uq_aq_session_seq"), None)
        assert row is not None, "_DDL 直建路径缺 uq_aq_session_seq"
        assert row[2] == 1, "_DDL 直建路径的 uq_aq_session_seq 必须为 UNIQUE（与迁移路径一致）"
    finally:
        conn.close()


def test_new_db_direct_path():
    """新库路径：_DDL 直建含全部新列（Pitfall 2 双轨）；二次 init_db 幂等。"""
    fresh_db = os.path.join(tempfile.mkdtemp(), "new_direct.db")
    original = db_module.DB_PATH
    db_module.DB_PATH = fresh_db
    try:
        init_db()
        init_db()  # 幂等：嗅探早退，二次运行不抛
    finally:
        db_module.DB_PATH = original
    conn = sqlite3.connect(fresh_db)  # 直查新库（不复用 _q——它指向模块主库）
    try:
        for table, new_cols in (
            ("question_bank", _QB_NEW_COLS),
            ("assessment_question", _AQ_NEW_COLS),
            ("question_score", _QS_NEW_COLS),
        ):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert new_cols <= cols, f"{table} 缺列: {new_cols - cols}"
        qs_cols = {r[1] for r in conn.execute("PRAGMA table_info(question_score)")}
        assert "final_score" not in qs_cols  # 02-05：_DDL 直建已去列（新库不含旧列）
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_aq_session_seq'"
        ).fetchall()
    finally:
        conn.close()


def test_legacy_columns_not_touched():
    """老库路径：迁移后 question_bank 旧 CHECK（category/qtype/scope 三态）仍在（不重建表）。"""
    init_db()
    create_sql = _q("SELECT sql FROM sqlite_master WHERE type='table'"
                    " AND name='question_bank'")[0]["sql"]
    assert "CHECK(category IN ('hard_skill','soft_skill','experience','qualification'))" in create_sql
    assert "CHECK(scope IN ('position','general'))" in create_sql
    assert "CHECK(qtype IN ('objective','subjective'))" in create_sql


def test_duplicate_seq_blocks_migration():
    """老库路径：(session_id, seq) 重复时迁移 raise RuntimeError（不静默去重，T-02-01）。"""
    dup_db = os.path.join(tempfile.mkdtemp(), "old_dup.db")
    _build_old_db(dup_db, with_duplicate_seq=True)
    original = db_module.DB_PATH
    db_module.DB_PATH = dup_db
    try:
        with pytest.raises(RuntimeError, match="sess_old_1"):  # 异常附行明细
            init_db()
    finally:
        db_module.DB_PATH = original
