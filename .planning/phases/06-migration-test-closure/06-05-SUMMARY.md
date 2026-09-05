---
phase: 06-migration-test-closure
plan: "06-05"
subsystem: testing
tags: [eval, sqlite, pytest, bad-case, secret-gate, input-limits, jwt]

# Dependency graph
requires:
  - phase: 06-migration-test-closure
    provides: [set_db_path/_DB_PATH_OVERRIDE (06-01), conftest.py mock 三件套 + session 临时库 (06-01)]
provides:
  - eval 隔离（业务库只读快照到临时库 + 结果写回 eval_results）
  - bad_case_candidate 表 + 双分背离检测（永不改分）
  - 输入限额/开放参数占位常量 + secret fail-closed 测试锁定
affects: [06-migration-test-closure (06-03 M1 回归), eval harness, admin TestCenter]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "eval 隔离 = sqlite3 backup 业务库只读快照 → 临时库 → set_db_path 运行 → finally 复位 → 独立业务库连接写回"
    - "开放参数占位 = config.py 常量 None + '# 实施期校准 — 待用户裁决' 注释（不臆造数值）"
    - "bad case 检测 = 双分背离 INSERT 候选，永不 UPDATE score（D-031）"

key-files:
  created: [server/test_eval_isolation.py, server/test_bad_case.py, server/test_secret_gate.py, server/test_input_limits.py, server/services/input_limits.py]
  modified: [eval/consistency_test.py, eval/virtual_candidates.py, server/api/admin/eval.py, server/db.py, server/services/report.py, server/config.py]

key-decisions:
  - "D-76 JWT 方向 = jwt-cookie-migrate（本期仅锁方向，实际迁移为 Phase 6 外后续计划，本计划零改 security/auth/sse/index.js）[06-009]"
  - "REF-6.2 secret = secret-failclosed-keep（锁定 main.py:59-67 现 fail-closed-always 现状，零生产改动 main.py）[06-009]"
  - "eval 隔离采用 sqlite3 backup 全量业务库只读快照到临时库（RESEARCH Pattern 4），比逐表播种更简且业务库零写入"
  - "bad_case 幂等 guard 用 NULL-safe 'question_id IS ?'（报告版本化重复生成不重复建候选）"

patterns-established:
  - "eval 三脚本 _run_isolated：业务库快照 → set_db_path(temp) → fn → set_db_path(None)"
  - "config.py append-only：限额/开放参数占位常量追加在常量区块末尾，勿重写区块"

requirements-completed: [REF-5.11, REF-6.1, REF-6.2, REF-6.3, REF-8.8, REQ-data-compliance, REQ-iterative-loop]

# Metrics
duration: 9min
completed: 2026-09-05
---

# Phase 6 Plan 05: eval 隔离 + bad case 候选 + 安全收尾 Summary

**eval 三脚本隔离临时库运行并写回 eval_results；bad_case_candidate 双分背离检测永不改分；输入限额/开放参数 config.py 占位 + secret fail-closed 测试锁定**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-05T15:22:27Z
- **Completed:** 2026-09-05T15:31:16Z
- **Tasks:** 3 (Task 0 checkpoint 已由用户裁决 [06-009]，免停车)
- **Files modified:** 11 (6 new + 5 modified)

## Accomplishments
- eval 三脚本（consistency/virtual_candidates + admin eval `_run`）改用 `set_db_path(temp)` 隔离临时库运行，业务库 `data/app.db` 零写入（REF-8.8）
- 评测结果经独立业务库连接写回 `eval_results`（status='completed'），admin 轮询可见
- `bad_case_candidate` 表（status pending/reviewed/dismissed CHECK + FK）+ `_detect_bad_case_divergence` 双分背离检测，背离≥阈值建候选、永不改分（REF-5.11/D-031）
- config.py 追加 `BAD_CASE_DIVERGENCE_THRESHOLD` + 6 个输入限额/开放参数占位常量（均 None + 实施期校准注释），已决值沿用 MAX_ANSWER_LEN/MAX_CONTEXT_TOKENS
- secret fail-closed 现状测试锁定（test_secret_gate.py），输入限额结构校验纯函数 + 测试（input_limits）

## Task Commits

Each task was committed atomically:

1. **Task 1: eval 隔离——临时库运行 + 写回 eval_results（REF-8.8）** - `d92bc43` (feat)
2. **Task 2: bad case 候选——双分背离检测 + bad_case_candidate 表（REF-5.11）** - `6d5e289` (feat)
3. **Task 3: 安全收尾——输入限额 + secret fail-closed 锁定 + 开放参数占位** - `8475d02` (feat)

## Files Created/Modified
- `eval/consistency_test.py` - 新增 `_run_isolated`（业务库快照→临时库→set_db_path→复位），CLI main 走隔离
- `eval/virtual_candidates.py` - 新增 `_run_isolated`（同上）
- `server/api/admin/eval.py` - `_build_temp_db` 快照 + `_run` 隔离运行 + 复位后 `_save_result` 写回业务库
- `server/test_eval_isolation.py` - 锁定业务库 session 行数不变 + eval_results 增 + status='completed'
- `server/db.py` - 追加 `bad_case_candidate` 表 DDL（trace_link 后）
- `server/services/report.py` - `_detect_bad_case_divergence` + generate_report 聚合后调用
- `server/config.py` - 追加 BAD_CASE_DIVERGENCE_THRESHOLD + 6 占位常量
- `server/test_bad_case.py` - 锁定建候选 + 不改分 + 阈值未裁决跳过
- `server/services/input_limits.py` - validate_jd_length / clamp_pagination_limit 就近纯函数
- `server/test_secret_gate.py` - 锁定默认 secret fail-closed + test-secret 放行
- `server/test_input_limits.py` - monkeypatch 断言超限拒绝/钳制

## Decisions Made
- **D-76 JWT 方向 = jwt-cookie-migrate**（用户裁决 [06-009]）：本期仅「锁方向」，实际迁移为 Phase 6 外后续计划，本计划不改 security.py/auth.py/sse.js/index.js
- **REF-6.2 secret = secret-failclosed-keep**：锁定 main.py 现 fail-closed-always 现状，零生产改动 main.py
- **eval 隔离 = sqlite3 backup 全量业务库只读快照**：比逐表播种更简，天然覆盖 consistency 需会话数据 / virtual 需岗位模型两类输入，业务库零写入
- **bad_case 幂等 guard**：`question_id IS ?` NULL-safe 比较，报告版本化重复生成不重复建 pending 候选

## Deviations from Plan

None — plan executed as written, with two Claude's-Discretion choices the plan explicitly sanctioned:

1. **eval 隔离机制**：plan 写「init_db() 建表 + 播种」，实际用 `sqlite3 backup` 全量业务库只读快照到临时库（RESEARCH Pattern 4 明确「copies/re-seeds the target session/position data」），免逐表播种且覆盖两类 eval 输入。
2. **`server/services/input_limits.py` 为新增文件**（plan files_modified 未列）：plan 的 Task 3 action 明确「校验落点若需新增小型纯函数则放 server/services/」，属计划内裁量。
3. **`server/main.py` 未改动**（plan files_modified 列了 main.py）：Task 0 裁决 secret-failclosed-keep → 「零生产改动 main.py 逻辑」，仅测试锁定现状。

**Total deviations:** 0 auto-fixed. All choices were plan-sanctioned discretion.

## Issues Encountered
- **全量回归 `pytest .` 现 98 failed / 117 passed**，但失败全部集中在 13 个会话类测试文件（test_m5/p0_chain/p0_security/phase2_*/phase3_*/phase4_binding/phase5_evidence），根因 = 直插 `question_bank` 不写 `model_id/model_version`（Phase 4 消费侧收紧后 readiness 判 QUESTION_BANK_INCOMPLETE），为 STATE.md/CONTEXT.md 已登记 deferred 项（D-71），**由 Wave 3 计划 06-03 补齐**，非本计划引入。本计划 4 新测试（10 用例）+ test_migration 全绿；全量收集 215 tests collected 无 fixture error。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 06-05 收口完成：eval 隔离 + bad case + 安全收尾三项落地，4 新测试全绿
- 后续 Wave 3 计划 06-03（M1 回归 + mock 恒 3 分记档 + 13 文件 model_id/model_version 补齐）将把全量回归收口到全绿
- 开放参数（BAD_CASE_DIVERGENCE_THRESHOLD / MAX_JD_LENGTH / MAX_JD_FILE_LINES / MAX_PAGINATION_LIMIT / TRACE_RETENTION_DAYS / TRACE_DESENSITIZE / IDEMPOTENCY_CLEANUP_THRESHOLD）均 None 占位待用户裁决

---
*Phase: 06-migration-test-closure*
*Completed: 2026-09-05*

## Self-Check: PASSED
- All 11 created/modified files verified present (6 new + 5 modified)
- All 3 task commits verified in git history (d92bc43, 6d5e289, 8475d02)
