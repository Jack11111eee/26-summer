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
  call_type TEXT NOT NULL CHECK(call_type IN ('extract','disambiguate','aggregate_level')),
  ref_id    TEXT NOT NULL,
  attempt   INTEGER NOT NULL,
  prompt    TEXT NOT NULL,
  response  TEXT,
  success   INTEGER NOT NULL,
  error     TEXT,
  created_at TEXT NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    """返回开启外键、Row 工厂的数据库连接。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """按 §5 建 8 张表（幂等），启动时调用一次。"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
