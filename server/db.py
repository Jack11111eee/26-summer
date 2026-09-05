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
  created_at    TEXT NOT NULL,
  -- ============ Phase 3 计时新列（SSOT §12.1/D-39~D-42；无 DB CHECK——N11）============
  -- phase 状态机 PENDING_START→ACTIVE→SCORING→COMPLETED/ABANDONED 与 status 双轨并存
  -- （status CHECK 不动——Anti-pattern 4：PENDING_START/SCORING 落 phase 列）
  phase                     TEXT,
  active_elapsed_seconds    INTEGER,
  last_activity_at          TEXT,
  abandoned_at              TEXT,
  policy_version            TEXT,
  session_time_intervals_json TEXT
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
  created_at  TEXT NOT NULL,
  -- ============ Phase 2 v2 新列（D-14，SSOT §9.2；无 DB CHECK——N11 枚举代码校验）============
  model_id             TEXT,
  model_version       INTEGER,
  item_id             TEXT,
  question_type       TEXT NOT NULL DEFAULT 'ordinary',
  measurement_stage   TEXT NOT NULL DEFAULT 'ordinary',
  measurement_target  TEXT,
  evidence_requirement TEXT,
  observable_level_max INTEGER,
  observable_level_min INTEGER,
  rubric_version      TEXT
);

CREATE TABLE IF NOT EXISTS assessment_question (
  question_id      TEXT PRIMARY KEY,
  session_id       TEXT NOT NULL REFERENCES assessment_session,
  bank_question_id TEXT NOT NULL REFERENCES question_bank,
  seq              INTEGER NOT NULL,
  asked_at         TEXT,
  answered_at      TEXT,
  created_at       TEXT NOT NULL,
  -- ============ Phase 2 v2 新列（D-15，SSOT §12.2；无 DB CHECK——N11）============
  question_type           TEXT NOT NULL DEFAULT 'legacy',  -- 旧行='legacy' 不参与新选题路径
  measurement_stage       TEXT,
  item_id                 TEXT,
  difficulty              TEXT,
  status                  TEXT,   -- 旧行 NULL = legacy；新实例 'active'/'sealed'
  activated_at            TEXT,
  closed_at               TEXT,
  followup_count          INTEGER NOT NULL DEFAULT 0,
  seal_reason             TEXT,   -- answered/refused/timeout 枚举位，代码校验
  selection_reason        TEXT,   -- D-18 结构化 JSON
  selection_policy_version TEXT,
  path_state_snapshot     TEXT,
  -- ============ Phase 3 幂等/并发新列（D-37，SSOT §13.4——03-03 乐观锁版本号）============
  revision                INTEGER NOT NULL DEFAULT 1  -- 乐观锁版本号（expected_revision 校验）
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_aq_session_seq ON assessment_question(session_id, seq);

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
  created_at        TEXT NOT NULL,
  -- ============ Phase 3 消息分列三列（D-43，SSOT §12.1；全可空）============
  refined_content   TEXT,
  client_request_id TEXT,
  sequence_no       INTEGER
);

-- ============ 计时区间表（SSOT §15/D-39~D-42——03-04 服务端权威区间）============
-- interval_type ∈ {active, paused} 代码校验（N11 无 DB CHECK）；reason 敏感不进评分 prompt（D-40）；
-- 部分唯一索引 uq_sti_open（session_id WHERE ended_at IS NULL）保证同 session 至多一个 open 区间（实验 6）。
CREATE TABLE IF NOT EXISTS session_time_intervals (
  interval_id   TEXT PRIMARY KEY,
  session_id    TEXT NOT NULL REFERENCES assessment_session,
  interval_type TEXT NOT NULL,
  reason        TEXT,
  started_at    TEXT NOT NULL,
  ended_at      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_sti_open ON session_time_intervals(session_id) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_sti_session ON session_time_intervals(session_id);

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
  question_id    TEXT REFERENCES assessment_question,
  item_id        TEXT NOT NULL REFERENCES competency_item,
  score_live     INTEGER,
  score_final    INTEGER,
  evidence_quote TEXT,
  reason         TEXT,
  created_at     TEXT NOT NULL,
  -- ============ Phase 2 v2 新列（SSOT §12.4——02-05 消费点切换后 final_score 旧列已 DROP）============
  score_state    TEXT,
  -- ============ Phase 3 表单链新列（SSOT §16.1——03-01 gate 结构化结果 + 人工覆盖）============
  -- question_id/score_state 去 NOT NULL（gate 行这两列 NULL——A2 四步放宽法 [03-008]）；
  -- gate 五列 + 覆盖四列：gate 行才填，普通评分行 NULL（N11 无 DB CHECK）
  gate_result              TEXT,
  gate_status              TEXT,
  gate_reason              TEXT,
  evaluated_schema_version TEXT,
  evaluated_at             TEXT,
  automated_gate_result    TEXT,
  human_override           TEXT,
  override_reason          TEXT,
  reviewer_id              TEXT,
  -- ============ Phase 5 审计快照列（SSOT §12.4——05-01 evidence_spans + scorer/rubric 版本）============
  evidence_spans_json      TEXT,
  measurement_target       TEXT,
  rubric_version           TEXT,
  scorer_version           TEXT
);

-- ============ 表单实例表（SSOT §16.1——03-01 form_instance 不可变 schema 快照）============
-- status 三态 rendered/submitted/superseded 代码校验（N11 无 DB CHECK）；
-- revision 不可变：修订 = INSERT 新行 revision+1（同 form_instance_id），旧行 UPDATE status='superseded'；
-- render 触发（assessment 池耗尽未采集 gate）→ GET /forms/{id} 白名单 → submit-v2 六维校验消费。
CREATE TABLE IF NOT EXISTS form_instance (
  form_instance_id TEXT NOT NULL,
  session_id       TEXT NOT NULL REFERENCES assessment_session,
  form_type        TEXT NOT NULL,
  schema_version   TEXT NOT NULL,
  schema_snapshot  TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'rendered',
  revision         INTEGER NOT NULL DEFAULT 1,
  payload_json     TEXT,
  created_at       TEXT NOT NULL,
  submitted_at     TEXT,
  PRIMARY KEY (form_instance_id, revision)
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

-- ============ 幂等记录表（SSOT §13.4/D-36~D-38——03-03 三键作用域 + 两阶段）============
-- 三键 UNIQUE(session_id, endpoint, idempotency_key) 拦并发双发（IntegrityError）；
-- status PENDING/COMMITTED 代码校验（N11 无 DB CHECK）；response_snapshot = 决策结果 dict JSON
-- （COMMITTED 后填——白名单键，不含候选人输入原文——A1）；created_at 索引为
-- D-38 Phase 6 数据治理预留（清理策略不实现——演示期数据量级接受）。

CREATE TABLE IF NOT EXISTS idempotency_record (
  id               TEXT PRIMARY KEY,
  session_id       TEXT NOT NULL,
  endpoint         TEXT NOT NULL,           -- 'answer' | 'form_submit'
  idempotency_key  TEXT NOT NULL,
  request_hash     TEXT,                    -- sha256 规范化 JSON（Claude 裁量）
  status           TEXT NOT NULL,           -- PENDING/COMMITTED 代码校验（N11）
  response_snapshot TEXT,                   -- COMMITTED 后填——决策结果 dict JSON
  created_at       TEXT NOT NULL,
  UNIQUE(session_id, endpoint, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency_record(created_at);

-- ============ trace_link 统一审计链（SSOT §13.3/D-56——05-01）============
-- link_role 枚举（input/output/caused_by/scored/reported/source）代码校验、无 DB CHECK（N11）；
-- entity_type/entity_id 弱关联（业务表不加 FK——D-020）；UNIQUE 兜底幂等。
CREATE TABLE IF NOT EXISTS trace_link (
  id          TEXT PRIMARY KEY,
  trace_id    TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id   TEXT NOT NULL,
  link_role   TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE(trace_id, entity_type, entity_id, link_role)
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


def _migrate_question_bank_v2(conn: sqlite3.Connection) -> None:
    """Phase 2（D-14，SSOT §9.2）：question_bank 加 v2 新列 + §9.4 锚点回填。

    - 老库嗅探（PRAGMA table_info 取列名集合）逐列 ALTER；新库表已含新列自然跳过（幂等）。
    - NOT NULL 新列必须带常量 DEFAULT（SQLite ADD COLUMN 限制）；锚点两列裸 ADD 后
      用 UPDATE ... CASE difficulty 两步法回填（非常量 DEFAULT 被 SQLite 拒绝，实测路径见
      02-RESEARCH Pattern 1）；difficulty NULL 的行无锚点，保持 NULL。
    - 新列一律无 DB CHECK（N11，枚举代码校验）；question_type/measurement_stage
      旧行回填 'ordinary'。锚点回填幂等条件 WHERE observable_level_max IS NULL。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(question_bank)").fetchall()}
    if not cols:
        return  # 表不存在（新建走 _DDL）
    new_cols = [
        ("model_id", "TEXT"),
        ("model_version", "INTEGER"),
        ("item_id", "TEXT"),
        ("question_type", "TEXT NOT NULL DEFAULT 'ordinary'"),
        ("measurement_stage", "TEXT NOT NULL DEFAULT 'ordinary'"),
        ("measurement_target", "TEXT"),
        ("evidence_requirement", "TEXT"),
        ("observable_level_max", "INTEGER"),
        ("observable_level_min", "INTEGER"),
        ("rubric_version", "TEXT"),
    ]
    for name, decl in new_cols:
        if name not in cols:
            conn.execute(f"ALTER TABLE question_bank ADD COLUMN {name} {decl}")
    # 锚点回填（SSOT §9.4）：easy[2,3] / medium[3,4] / hard[4,5]；NULL 保持 NULL
    conn.execute("""UPDATE question_bank SET
        observable_level_max = CASE difficulty
            WHEN 'easy' THEN 3 WHEN 'medium' THEN 4 WHEN 'hard' THEN 5 ELSE observable_level_max END,
        observable_level_min = CASE difficulty
            WHEN 'easy' THEN 2 WHEN 'medium' THEN 3 WHEN 'hard' THEN 4 ELSE observable_level_min END
        WHERE observable_level_max IS NULL AND difficulty IS NOT NULL""")


def _migrate_assessment_question_v2(conn: sqlite3.Connection) -> None:
    """Phase 2（D-15，SSOT §12.2）：assessment_question 加 v2 新列 + (session_id, seq) 唯一索引。

    - 旧行 question_type 默认 'legacy'（不参与新选题路径）、status NULL = legacy；
      新实例才写 'active'/'sealed'（枚举代码校验，N11 无 DB CHECK）。
    - (session_id, seq) 唯一（Q2 决议：沿用 seq 列承载 §12.2 sequence_no 语义，不加新列）；
      建索引前先做重复检测，发现重复 raise RuntimeError 附行明细——演示库允许重跑生成，
      不做静默去重（T-02-01 唯一性不得被静默破坏）。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(assessment_question)").fetchall()}
    if not cols:
        return  # 表不存在（新建走 _DDL）
    new_cols = [
        ("question_type", "TEXT NOT NULL DEFAULT 'legacy'"),
        ("measurement_stage", "TEXT"),
        ("item_id", "TEXT"),
        ("difficulty", "TEXT"),
        ("status", "TEXT"),
        ("activated_at", "TEXT"),
        ("closed_at", "TEXT"),
        ("followup_count", "INTEGER NOT NULL DEFAULT 0"),
        ("seal_reason", "TEXT"),
        ("selection_reason", "TEXT"),
        ("selection_policy_version", "TEXT"),
        ("path_state_snapshot", "TEXT"),
        ("revision", "INTEGER NOT NULL DEFAULT 1"),
    ]
    for name, decl in new_cols:
        if name not in cols:
            conn.execute(f"ALTER TABLE assessment_question ADD COLUMN {name} {decl}")
    dup_rows = conn.execute(
        "SELECT session_id, seq, COUNT(*) c FROM assessment_question"
        " GROUP BY session_id, seq HAVING COUNT(*) > 1"
    ).fetchall()
    if dup_rows:
        detail = "; ".join(f"session={r[0]} seq={r[1]} count={r[2]}" for r in dup_rows)
        raise RuntimeError(
            f"assessment_question 存在 (session_id, seq) 重复行，无法创建唯一索引 uq_aq_session_seq：{detail}"
            "（演示库请重跑生成，本迁移不做静默去重）"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_aq_session_seq ON assessment_question(session_id, seq)"
    )


def _migrate_question_score_v2(conn: sqlite3.Connection) -> None:
    """Phase 2（SSOT §12.4）：question_score 加 score_state + final_score→score_final 合并 + DROP。

    - score_state 存量行回填 'SCORED'（语义正确：旧行均为正常评分）。
    - final_score 旧列值合并进 score_final（COALESCE 保序：final_score 优先）；
    - 合并后 DROP final_score 列——A8 次序合同收尾（02-05 消费点全切换后才
      DROP + _DDL 去列；scoring/aggregation/report 三消费面与测试断言已切
      score_final 口径）；幂等嗅探：列存在才 DROP。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(question_score)").fetchall()}
    if not cols:
        return  # 表不存在（新建走 _DDL）
    if "score_state" not in cols:
        conn.execute(
            "ALTER TABLE question_score ADD COLUMN score_state TEXT NOT NULL DEFAULT 'SCORED'"
        )
    if "final_score" in cols:
        # 合并语义：final_score 有值优先（终局评分历史事实）——DROP 之前完成
        conn.execute(
            "UPDATE question_score SET score_final=COALESCE(final_score, score_final)"
        )
        # A8 次序合同（02-01 锁定 → 02-05 收尾）：消费点切换完成后才 DROP——
        # 幂等嗅探：上方 "in cols" 即列存在才执行（二次 init_db 直接跳过）
        conn.execute("ALTER TABLE question_score DROP COLUMN final_score")


def _migrate_question_score_phase3(conn: sqlite3.Connection) -> None:
    """Phase 3（SSOT §16.1）：question_score 加 gate 五列 + 覆盖四列，并放宽 question_id/
    score_state 的 NOT NULL（gate 行这两列 NULL——结构化 gate 结果复用评分表）。

    - gate 五列（gate_result/gate_status/gate_reason/evaluated_schema_version/evaluated_at）
      与覆盖四列（automated_gate_result/human_override/override_reason/reviewer_id）
      全部可空、无 DB CHECK（N11）——gate 行才填，普通评分行 NULL。
    - NOT NULL 放宽采用 A2 四步放宽法（ADD *_v2 → UPDATE 拷值 → DROP 原列 → RENAME COLUMN）：
      A2 四步放宽法——02-RESEARCH 实验 9/10 验证 + 关口包裁决 [03-008]（2026-09-05）；
      gate 行 question_id NULL 与 D-31 字面 'question_score gate 项行' 的兼容取舍已裁决。
      旧行值保留（放宽不丢数据）：question_id_v2 拷原值、score_state_v2 回填 COALESCE 原值。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(question_score)").fetchall()}
    if not cols:
        return  # 表不存在（新建走 _DDL，已含新列）
    for name, decl in (
        ("gate_result", "TEXT"),
        ("gate_status", "TEXT"),
        ("gate_reason", "TEXT"),
        ("evaluated_schema_version", "TEXT"),
        ("evaluated_at", "TEXT"),
        ("automated_gate_result", "TEXT"),
        ("human_override", "TEXT"),
        ("override_reason", "TEXT"),
        ("reviewer_id", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE question_score ADD COLUMN {name} {decl}")

    def _relax(column: str, copy_expr: str) -> None:
        """A2 四步放宽法：目标列若仍 NOT NULL 则 ADD v2 → UPDATE 拷 → DROP → RENAME。

        init_db 的 conn 为裸 sqlite3.connect（无 row_factory），PRAGMA table_info 返回元组
        (cid, name, type, notnull, dflt_value, pk)——notnull 取下标 3。
        """
        info = {r[1]: r for r in conn.execute("PRAGMA table_info(question_score)").fetchall()}
        if info[column][3] == 0:
            return  # 已放宽（幂等嗅探：二次 init_db 直接跳过）
        conn.execute(f"ALTER TABLE question_score ADD COLUMN {column}_v2 TEXT")
        conn.execute(f"UPDATE question_score SET {column}_v2 = {copy_expr}")
        conn.execute(f"ALTER TABLE question_score DROP COLUMN {column}")
        conn.execute(f"ALTER TABLE question_score RENAME COLUMN {column}_v2 TO {column}")

    _relax("question_id", "question_id")
    _relax("score_state", "COALESCE(score_state, 'SCORED')")


def _migrate_form_instance(conn: sqlite3.Connection) -> None:
    """Phase 3（SSOT §16.1）：补建 form_instance（老库无此表；CREATE IF NOT EXISTS 幂等）。

    新表走 _DDL 直建；存量库走本函数（与 _migrate_question_bank_v2 双轨纪律同形态）。
    """
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS form_instance (
      form_instance_id TEXT NOT NULL,
      session_id       TEXT NOT NULL REFERENCES assessment_session,
      form_type        TEXT NOT NULL,
      schema_version   TEXT NOT NULL,
      schema_snapshot  TEXT NOT NULL,
      status           TEXT NOT NULL DEFAULT 'rendered',
      revision         INTEGER NOT NULL DEFAULT 1,
      payload_json     TEXT,
      created_at       TEXT NOT NULL,
      submitted_at     TEXT,
      PRIMARY KEY (form_instance_id, revision)
    );
    """)


def _migrate_idempotency_record(conn: sqlite3.Connection) -> None:
    """Phase 3（SSOT §13.4）：补建 idempotency_record（老库无此表；CREATE IF NOT EXISTS 幂等）。

    新表走 _DDL 直建；存量库走本函数（三键 UNIQUE + created_at 索引与 _DDL 双轨同形态）。
    """
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS idempotency_record (
      id               TEXT PRIMARY KEY,
      session_id       TEXT NOT NULL,
      endpoint         TEXT NOT NULL,
      idempotency_key  TEXT NOT NULL,
      request_hash     TEXT,
      status           TEXT NOT NULL,
      response_snapshot TEXT,
      created_at       TEXT NOT NULL,
      UNIQUE(session_id, endpoint, idempotency_key)
    );
    CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency_record(created_at);
    """)


def _migrate_session_phase3(conn: sqlite3.Connection) -> None:
    """Phase 3（SSOT §12.1/§15/D-39~D-43）：assessment_session 加 6 计时列 + assessment_message
    加 3 分列 + 补建 session_time_intervals 与 uq_sti_open 部分唯一索引。

    - 新列 PRAGMA 嗅探 if-not-in-ADD（幂等）；旧行 phase 回填 'PENDING_START'（WHERE phase IS NULL）。
    - session_time_intervals 表与索引走 CREATE IF NOT EXISTS（与 _DDL 双轨同语句——
      02-01 双轨纪律；部分索引 WHERE ended_at IS NULL 子句与 _DDL 同串——W4 sqlite_master 断言口径）。
    - status CHECK 不动（Anti-pattern 4：PENDING_START/SCORING 落 phase 列，status 存量语义不动）。
    """
    sess_cols = {r[1] for r in conn.execute("PRAGMA table_info(assessment_session)").fetchall()}
    if sess_cols:
        for name, decl in (
            ("phase", "TEXT"),
            ("active_elapsed_seconds", "INTEGER"),
            ("last_activity_at", "TEXT"),
            ("abandoned_at", "TEXT"),
            ("policy_version", "TEXT"),
            ("session_time_intervals_json", "TEXT"),
        ):
            if name not in sess_cols:
                conn.execute(f"ALTER TABLE assessment_session ADD COLUMN {name} {decl}")
        conn.execute(
            "UPDATE assessment_session SET phase='PENDING_START' WHERE phase IS NULL"
        )

    msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(assessment_message)").fetchall()}
    if msg_cols:
        for name, decl in (
            ("refined_content", "TEXT"),
            ("client_request_id", "TEXT"),
            ("sequence_no", "INTEGER"),
        ):
            if name not in msg_cols:
                conn.execute(f"ALTER TABLE assessment_message ADD COLUMN {name} {decl}")

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS session_time_intervals (
      interval_id   TEXT PRIMARY KEY,
      session_id    TEXT NOT NULL REFERENCES assessment_session,
      interval_type TEXT NOT NULL,
      reason        TEXT,
      started_at    TEXT NOT NULL,
      ended_at      TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_sti_open ON session_time_intervals(session_id) WHERE ended_at IS NULL;
    CREATE INDEX IF NOT EXISTS idx_sti_session ON session_time_intervals(session_id);
    """)


def _migrate_trace_link(conn: sqlite3.Connection) -> None:
    """Phase 5（SSOT §13.3/D-56/D-57）：补建 trace_link + 旧 ref_id 导入。

    建表走 CREATE IF NOT EXISTS（与 _DDL 双轨同串）；旧 llm_trace.ref_id 按 call_type
    逐候选实体表 SELECT 1 命中探测，命中即拆 entity_type/entity_id 导成 link_role='source'
    行（INSERT OR IGNORE 幂等）；命不中保留 ref_id 原值不拆（弱关联不强造，T-05-02）。
    """
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS trace_link (
      id          TEXT PRIMARY KEY,
      trace_id    TEXT NOT NULL,
      entity_type TEXT NOT NULL,
      entity_id   TEXT NOT NULL,
      link_role   TEXT NOT NULL,
      created_at  TEXT NOT NULL,
      UNIQUE(trace_id, entity_type, entity_id, link_role)
    );
    """)
    # 新库此时 llm_trace 尚未建（走 _DDL 尾部），无旧行可导——跳过
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_trace'"
    ).fetchone() is None:
        return

    # call_type → 候选实体表（D-57 语义域映射；interviewer/refine/score 的 ref_id 可能指向
    # question_id 或 session_id——以「能命中实体表」为准，逐表探测取首个命中）
    tables_by_call = {
        "extract": ("jd_record", "position", "competency_model"),
        "disambiguate": ("jd_record", "position", "competency_model"),
        "aggregate_level": ("jd_record", "position", "competency_model"),
        "question_gen": ("assessment_question", "assessment_session"),
        "interviewer": ("assessment_question", "assessment_session"),
        "refine": ("assessment_question", "assessment_session"),
        "score": ("assessment_question", "assessment_session"),
        "report": ("report",),
    }
    pk_by_table = {
        "jd_record": "jd_id",
        "position": "position_id",
        "competency_model": "model_id",
        "assessment_question": "question_id",
        "assessment_session": "session_id",
        "report": "report_id",
    }
    from .services.pipeline import new_id

    rows = conn.execute(
        "SELECT trace_id, call_type, ref_id, created_at FROM llm_trace"
    ).fetchall()
    for trace_id, call_type, ref_id, created_at in rows:
        for table in tables_by_call.get(call_type, ()):
            pk = pk_by_table[table]
            hit = conn.execute(
                f"SELECT 1 FROM {table} WHERE {pk}=?", (ref_id,)
            ).fetchone()
            if hit is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO trace_link(id, trace_id, entity_type, entity_id,"
                    " link_role, created_at) VALUES(?,?,?,?,?,?)",
                    (new_id("tl"), trace_id, table, ref_id, "source", created_at),
                )
                break


def _migrate_question_score_phase5(conn: sqlite3.Connection) -> None:
    """Phase 5（SSOT §12.4/D-55）：question_score 加 4 审计快照列（全部可空、无 DB CHECK）。

    - PRAGMA 嗅探逐列 ALTER（幂等）；新库表已含新列自然跳过。
    - 全可空（evidence_spans_json/measurement_target/scorer_version 历史行 NULL 接受；
      rubric_version 由评分运行时写 'v1'——迁移不回填存量，避免臆造）。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(question_score)").fetchall()}
    if not cols:
        return  # 表不存在（新建走 _DDL，已含新列）
    for name, decl in (
        ("evidence_spans_json", "TEXT"),
        ("measurement_target", "TEXT"),
        ("rubric_version", "TEXT"),
        ("scorer_version", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE question_score ADD COLUMN {name} {decl}")


def init_db() -> None:
    """建表（幂等）+ 老库迁移，启动时调用一次。"""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        _migrate_llm_trace(conn)
        _migrate_feedback_status(conn)
        _migrate_question_bank_v2(conn)
        _migrate_assessment_question_v2(conn)
        _migrate_question_score_v2(conn)
        _migrate_question_score_phase3(conn)
        _migrate_form_instance(conn)
        _migrate_idempotency_record(conn)
        _migrate_session_phase3(conn)
        _migrate_trace_link(conn)
        _migrate_question_score_phase5(conn)
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
