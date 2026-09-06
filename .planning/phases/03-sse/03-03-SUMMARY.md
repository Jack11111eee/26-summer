---
phase: 03-sse
plan: 03
subsystem: api
tags: [sqlite, idempotency, optimistic-lock, sse, sha256]

# Dependency graph
requires:
  - phase: 03-sse
    plan: 02
    provides: submit_answer SSE 化 + AnswerRequest Pydantic（idempotency_key/expected_revision/client_attempt_id 字段预留位）
  - phase: 03-sse
    plan: 01
    provides: form_instance/submit-v2 端点 + FormSubmitRequest（idempotency_key 字段）+ gate 行结构化五列
provides:
  - idempotency_record 表（UNIQUE(session_id, endpoint, idempotency_key) 三键 + created_at 索引）
  - server/services/idempotency.py（check_idempotency 两阶段 + request_hash_of + finalize_idempotency）
  - assessment_question.revision 乐观锁列（迁移 + _DDL 双轨 + _instantiate 补列）
  - answer/submit-v2 两端点幂等接入（快照回放 200 JSON + 409 三态 + 乐观锁 409）
affects:
  - 03-04（单题超时点检——A4 时序注释已预留幂等最先）
  - Phase 6（数据治理——D-38 idempotency_record 清理策略锁定不实现）

# Tech tracking
tech-stack:
  added: []  # 仅 stdlib sqlite3 + hashlib + json
  patterns:
    - 两阶段幂等（INSERT PENDING 占位 → 业务链 commit 后 UPDATE COMMITTED + response_snapshot）
    - 乐观锁（UPDATE ... SET revision=revision+1 WHERE question_id=? AND revision=? → rowcount==0 判冲突）
    - 响应快照白名单键（决策结果 dict——不含候选人输入原文）

key-files:
  created:
    - server/services/idempotency.py
    - server/test_phase3_idempotency.py
  modified:
    - server/db.py
    - server/services/question_selection.py
    - server/api/assessment.py
    - server/test_phase3_forms.py

key-decisions:
  - "COMMITTED 命中先比 request_hash（W1）：同 key 异 payload → 409 IDEMPOTENCY_KEY_REUSED，永不回放首次快照"
  - "幂等前置在 StreamingResponse 之前且先于 answered_at 状态维检查（A4 时序——否则重放撞 QUESTION_ALREADY_ANSWERED）"
  - "finalize_idempotency 自取新连接（主链已 commit，新事务干净——answer 返回 StreamingResponse 前的最后写点）"
  - "快照白名单七键（action/reply/question_id/next_question_id/score_live/answer_state/evidence_sufficient）不含候选人输入原文（A1）"

patterns-established:
  - "两阶段幂等：INSERT PENDING → UPDATE COMMITTED（三键 UNIQUE 拦并发双发 IntegrityError）"
  - "乐观锁原子判：UPDATE WHERE revision=? + rowcount==0 判冲突（避免 TOCTOU 窗口）"

requirements-completed: [REF-4.9]

# Metrics
duration: 15min
completed: 2026-09-05
---

# Phase 03 Plan 03: 幂等与并发防护 Summary

**SQLite 三键幂等（INSERT PENDING → UPDATE COMMITTED + sha256 request_hash 比对）与 revision 乐观锁接入 answer/submit-v2 两端点**

## Performance

- **Duration:** ~15 min（commit 10:42 → 10:54）
- **Started:** 2026-09-05T10:40:00+08:00
- **Completed:** 2026-09-05T10:55:00+08:00
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments
- idempotency_record 表落地（UNIQUE 三键 + created_at 索引），assessment_question 加 revision 列（迁移 + _DDL 双轨 + _instantiate 补列）
- 两阶段幂等服务 check_idempotency/finalize_idempotency/request_hash_of（sha256 sort_keys 规范化；COMMITTED 命中先比 hash——异 payload 409 IDEMPOTENCY_KEY_REUSED）
- answer/submit-v2 两端点接入：快照回放 200 application/json（sse.js 形态 B）+ 乐观锁 409 QUESTION_REVISION_CONFLICT + PENDING 409 REQUEST_IN_PROGRESS
- 快照白名单七键不含候选人输入原文（A1 断言 test_snapshot_schema）
- 无 key 面零行为变化（A/B 兼容——缺省不启用，test_no_key_no_records / test_revision_absent_no_lock 断言）

## Task Commits

Each task was committed atomically:

1. **Task 1: test_phase3_idempotency.py 幂等全断言（先红）** - `89dc213` (test)
2. **Task 2: db.py DDL + idempotency.py 服务 + question_selection.py 补列** - `bd391ff` (feat)
3. **Task 3: assessment.py 两端点接入 + test_phase3_forms.py 追加** - `a71e8f3` (feat)

**Plan metadata:** 本 summary 提交（docs: complete 03-03 plan）

## Files Created/Modified
- `server/db.py` - idempotency_record DDL（UNIQUE 三键 + idx_idem_created）+ _migrate_idempotency_record + revision 列双轨
- `server/services/idempotency.py` - check_idempotency（两阶段）/ request_hash_of / finalize_idempotency
- `server/services/question_selection.py` - _instantiate INSERT 补 revision=1 列
- `server/api/assessment.py` - submit_answer 前置幂等检查 + 乐观锁 + 快照 finalize；submit_form_v2 同构接入；_answer_snapshot 白名单
- `server/test_phase3_idempotency.py` - 11 条幂等/乐观锁/兼容断言
- `server/test_phase3_forms.py` - 追加 test_form_submit_idempotent

## Decisions Made
- COMMITTED 命中先比 request_hash（W1 定谳）：同 key 异 payload 409 IDEMPOTENCY_KEY_REUSED，绝不回放首次快照
- 幂等检查置于 load_owned_session 后、status/answered_at 检查前（A4——否则重放撞 QUESTION_ALREADY_ANSWERED）
- finalize_idempotency 自取新连接 + 自身 commit（主链已 commit，answer 返回 StreamingResponse 前最后写点，避免 generator 启动前残留写锁）
- 无 key 零路径（缺省不启用），乐观锁仅带 expected_revision 才走——A/B 兼容

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 乐观锁 write-then-raise 泄漏 SQLite RESERVED 写锁**
- **Found during:** Task 3（assessment.py 两端点接入）
- **Issue:** 乐观锁 `UPDATE ... SET revision=revision+1 WHERE ... AND revision=?` 即使 rowcount==0 也开启写事务（RESERVED 锁）；原实现直接 raise 409 而不 rollback，连接泄漏持锁 >5s，导致紧随其后的测试/请求 INSERT 报 `database is locked`（test_revision_absent_no_lock 稳定复现）
- **Fix:** 在 409 raise 前加 `conn.rollback()` 释放写锁
- **Files modified:** `server/api/assessment.py`
- **Verification:** test_phase3_idempotency.py 11 条全绿（原 1 failed 11 passed → 11 passed）
- **Committed in:** `a71e8f3`（Task 3 提交）

---

**Total deviations:** 1 auto-fixed（Rule 1 - bug）
**Impact on plan:** 必要正确性修复，无范围蔓延。乐观锁并发语义与计划一致，仅补释放锁的收尾。

## Issues Encountered
- 测试文件为「单文件单进程」设计（各文件 import 时 `os.environ["DB_PATH"]` 设临时库，但 `config.DB_PATH` 仅 import 时读取一次——同 pytest 进程跑多文件会共享首文件 DB）。计划的 verify 用 `&&` 逐文件执行，已按此逐文件验证（idempotency 11 / forms 16 / sse 11 / m5 7 / p0 11 全绿）。

## Next Phase Readiness
- 幂等与并发防护闭合，ready for 03-04 单题超时点检（A4 时序注释已预留幂等最先位置）
- 无阻塞项

---
*Phase: 03-sse*
*Completed: 2026-09-05*

## Self-Check: PASSED

- FOUND: server/services/idempotency.py
- FOUND: server/test_phase3_idempotency.py
- FOUND: server/api/assessment.py
- FOUND: .planning/phases/03-sse/03-03-SUMMARY.md
- FOUND commits: 89dc213 (test), bd391ff (feat), a71e8f3 (feat)
