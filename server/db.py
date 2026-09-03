"""SQLite 连接与建表（DDL 严格按 05 文档 §5，8 张表）。"""

import os
import sqlite3

from .config import DB_PATH

# 05 文档 §5 DDL，字段名与 CHECK 约束不增删
_DDL = """
CREATE TABLE IF NOT EXISTS user (
  user_id       TEXT PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN ('admin','candidate')),
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position (
  position_id TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  status      TEXT NOT NULL CHECK(status IN ('pending_review','active')),
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_alias (
  alias_id    TEXT PRIMARY KEY,
  position_id TEXT NOT NULL REFERENCES position,
  alias       TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS jd_record (
  jd_id          TEXT PRIMARY KEY,
  position_id    TEXT REFERENCES position,
  job_title      TEXT,
  company        TEXT,
  source_type    TEXT NOT NULL CHECK(source_type IN ('paste','file','plugin')),
  raw_text       TEXT NOT NULL,
  cleaned_text   TEXT,
  raw_items_json TEXT,
  std_items_json TEXT,
  low_confidence INTEGER NOT NULL DEFAULT 0,
  status         TEXT NOT NULL CHECK(status IN ('imported','parsing','parsed','failed')),
  error_msg      TEXT,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competency_model (
  model_id     TEXT PRIMARY KEY,
  position_id  TEXT NOT NULL REFERENCES position,
  version      INTEGER NOT NULL,
  status       TEXT NOT NULL CHECK(status IN ('draft','confirmed','stalled')),
  model_json   TEXT NOT NULL,
  confirmed_by TEXT REFERENCES user,
  confirmed_at TEXT,
  created_at   TEXT NOT NULL,
  UNIQUE(position_id, version)
);

CREATE TABLE IF NOT EXISTS competency_item (
  item_id         TEXT PRIMARY KEY,
  model_id        TEXT NOT NULL REFERENCES competency_model,
  std_name        TEXT NOT NULL,
  category        TEXT NOT NULL CHECK(category IN ('hard_skill','soft_skill','experience','qualification')),
  required_level  INTEGER,
  importance      TEXT CHECK(importance IN ('required','preferred','plus')),
  weight          REAL,
  years           REAL,
  gate            INTEGER NOT NULL DEFAULT 0,
  level_reason    TEXT,
  occurrence_json TEXT,
  evidence_json   TEXT
);

CREATE TABLE IF NOT EXISTS competency_dict (
  std_name        TEXT NOT NULL,
  category        TEXT NOT NULL,
  definition      TEXT,
  exclusions_json TEXT,
  aliases_json    TEXT,
  created_by      TEXT NOT NULL CHECK(created_by IN ('llm_pending','human')),
  status          TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  PRIMARY KEY(std_name, category)
);

CREATE TABLE IF NOT EXISTS llm_trace (
  trace_id  TEXT PRIMARY KEY,
  -- 模块二扩展：question_gen / interviewer / refine / score；模块三扩展：report（07 文档 §11 llm_trace 扩 5 类型）
  call_type TEXT NOT NULL CHECK(call_type IN ('extract','disambiguate','aggregate_level',
                                              'question_gen','interviewer','refine','score','report')),
  ref_id    TEXT NOT NULL,
  attempt   INTEGER NOT NULL,
  prompt    TEXT NOT NULL,
  response  TEXT,
  success   INTEGER NOT NULL,
  error     TEXT,
  created_at TEXT NOT NULL
);

-- ============ 模块二/三新增（07 文档 §7.2，7 张表）============

CREATE TABLE IF NOT EXISTS assessment_session (
  session_id    TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL REFERENCES user,
  position_id   TEXT NOT NULL REFERENCES position,
  model_id      TEXT NOT NULL REFERENCES competency_model,
  model_version INTEGER NOT NULL,
  status        TEXT NOT NULL CHECK(status IN ('in_progress','completed','abandoned')),
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS question_bank (
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

CREATE TABLE IF NOT EXISTS assessment_question (
  question_id      TEXT PRIMARY KEY,
  session_id       TEXT NOT NULL REFERENCES assessment_session,
  bank_question_id TEXT NOT NULL REFERENCES question_bank,
  seq              INTEGER NOT NULL,
  asked_at         TEXT,
  answered_at      TEXT,
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessment_message (
  message_id        TEXT PRIMARY KEY,
  session_id        TEXT NOT NULL REFERENCES assessment_session,
  question_id       TEXT REFERENCES assessment_question,
  role              TEXT NOT NULL CHECK(role IN ('system','user','assistant')),
  content           TEXT NOT NULL,
  raw_hash          TEXT,
  action            TEXT,
  reason            TEXT,
  score_live        INTEGER,
  score_live_reason TEXT,
  created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS context_raw (
  raw_id     TEXT PRIMARY KEY,
  hash       TEXT UNIQUE NOT NULL,
  full_text  TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS form_submission (
  form_id      TEXT PRIMARY KEY,
  session_id   TEXT NOT NULL REFERENCES assessment_session,
  user_id      TEXT NOT NULL REFERENCES user,
  form_type    TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS question_score (
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

-- ============ 模块三新增（07 文档 §10.5，2 张表）============

CREATE TABLE IF NOT EXISTS report (
  report_id   TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES assessment_session,
  total_score REAL NOT NULL,
  gate_passed INTEGER NOT NULL,
  report_json TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  feedback_id   TEXT PRIMARY KEY,
  report_id     TEXT NOT NULL REFERENCES report,
  item_id       TEXT NOT NULL REFERENCES competency_item,
  feedback_text TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','reviewed','bad_case')),
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_results (
  task_id      TEXT PRIMARY KEY,
  test_name    TEXT NOT NULL,
  status       TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
  result_json  TEXT,
  created_at   TEXT NOT NULL,
  completed_at TEXT
);

-- ============ 状态事件表（SSOT §13.1，v2.0 新增契约）============
-- append-only：禁止 UPDATE/DELETE（触发器 ase_no_update/ase_no_delete 强制，D-06）；
-- actor_type 枚举（candidate/system/admin）代码校验、无 DB CHECK（N11）；
-- 快照列与事件同事务更新，LLM 调用不持有长事务（§13.1）。

CREATE TABLE IF NOT EXISTS assessment_state_event (
  id                      TEXT PRIMARY KEY,
  session_id              TEXT NOT NULL,
  sequence_no             INTEGER NOT NULL,
  assessment_question_id  TEXT NULL,
  assessment_message_id   TEXT NULL,
  event_type              TEXT NOT NULL,
  from_state              TEXT NULL,
  to_state                TEXT NULL,
  actor_type              TEXT NOT NULL,
  actor_id                TEXT NULL,
  request_id              TEXT NULL,
  idempotency_key         TEXT NULL,
  policy_version          TEXT NULL,
  model_version           INTEGER NULL,
  question_bank_version   TEXT NULL,
  correlation_id           TEXT NULL,
  causation_event_id      TEXT NULL,
  payload_json           TEXT,
  created_at              TEXT NOT NULL,
  UNIQUE(session_id, sequence_no)
);

CREATE TRIGGER IF NOT EXISTS ase_no_update BEFORE UPDATE ON assessment_state_event
BEGIN SELECT RAISE(ABORT, 'assessment_state_event 为 append-only：禁止 UPDATE'); END;

CREATE TRIGGER IF NOT EXISTS ase_no_delete BEFORE DELETE ON assessment_state_event
BEGIN SELECT RAISE(ABORT, 'assessment_state_event 为 append-only：禁止 DELETE'); END;

-- ============ 题库生成任务表（SSOT §10.4/D-12 题库 readiness 载体）============
-- 状态枚举 QUEUED/RUNNING/SUCCEEDED/FAILED 代码校验、无 DB CHECK（N11）；
-- confirm 触发生成时插 QUEUED，generate_question_bank 开始/结束更新自身行；
-- 开考检查（services/readiness.py）按最新行判定生成中/不完整/就绪。

CREATE TABLE IF NOT EXISTS question_bank_task (
  task_id      TEXT PRIMARY KEY,
  position_id  TEXT NOT NULL REFERENCES position,
  model_id     TEXT NOT NULL REFERENCES competency_model,
  model_version INTEGER NOT NULL,
  status       TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  started_at   TEXT,
  finished_at  TEXT,
  error_msg    TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    """返回开启外键、Row 工厂的数据库连接。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_llm_trace(conn: sqlite3.Connection) -> None:
    """老库 llm_trace.call_type CHECK 类型不全时，重建表放宽到 _DDL 最新口径（含 report）。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='llm_trace'"
    ).fetchone()
    if row is None or "'report'" in (row[0] or ""):
        return  # 表不存在（新建走 _DDL）或已是最新约束
    conn.executescript("""
    BEGIN;
    CREATE TABLE llm_trace_new (
      trace_id  TEXT PRIMARY KEY,
      call_type TEXT NOT NULL CHECK(call_type IN ('extract','disambiguate','aggregate_level',
                                                  'question_gen','interviewer','refine','score','report')),
      ref_id    TEXT NOT NULL,
      attempt   INTEGER NOT NULL,
      prompt    TEXT NOT NULL,
      response  TEXT,
      success   INTEGER NOT NULL,
      error     TEXT,
      created_at TEXT NOT NULL
    );
    INSERT INTO llm_trace_new SELECT * FROM llm_trace;
    DROP TABLE llm_trace;
    ALTER TABLE llm_trace_new RENAME TO llm_trace;
    COMMIT;
    """)


def _migrate_feedback_status(conn: sqlite3.Connection) -> None:
    """老库 feedback.status CHECK 无 'bad_case' 时，重建表加入该值（同 llm_trace 迁移思路）。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='feedback'"
    ).fetchone()
    if row is None or "'bad_case'" in (row[0] or ""):
        return  # 表不存在（新建走 _DDL）或已是含 bad_case 的约束
    conn.executescript("""
    BEGIN;
    CREATE TABLE feedback_new (
      feedback_id   TEXT PRIMARY KEY,
      report_id     TEXT NOT NULL REFERENCES report,
      item_id       TEXT NOT NULL REFERENCES competency_item,
      feedback_text TEXT NOT NULL,
      status        TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','reviewed','bad_case')),
      created_at    TEXT NOT NULL
    );
    INSERT INTO feedback_new SELECT * FROM feedback;
    DROP TABLE feedback;
    ALTER TABLE feedback_new RENAME TO feedback;
    COMMIT;
    """)


def init_db() -> None:
    """建表（幂等）+ 老库迁移，启动时调用一次。"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        _migrate_llm_trace(conn)
        _migrate_feedback_status(conn)
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
