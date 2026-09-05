---
phase: 06-migration-test-closure
plan: "06-03"
subsystem: testing
tags: [regression, pytest, mock, model_id, model_version, config, migration]

# Dependency graph
requires:
  - phase: 06-migration-test-closure
    provides: [conftest.py mock 三件套 + session 临时库 (06-01), test 文件 _test_*→test_* 改名 (06-02), §31-5/§31-6 开放参数占位常量 (06-05)]
provides:
  - M1 八项回归锁（清洗/抽取/消歧/权重尾差/冲突/confirmed 覆盖/版本 diff/权限）
  - mock interviewer 固定 3 分已知局限的 docstring 记档（D-72）
  - config.py §31-4 占位常量（DICT_MATCH_THRESHOLD=None / TITLE_CLEAN_WORDS=[]，待用户裁决）
  - 13 个会话类测试文件 question_bank INSERT 补齐 model_id/model_version（对齐 Phase 4 双列消费侧收紧 D-50）
affects: [06-migration-test-closure 收口, verifier, §31-4 消费侧后续接入]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "M1 回归锁 = 测试函数体内懒导入被测纯函数（RESEARCH Pattern 2，避免 import 期副作用）"
    - "config.py append-only = §31-4 占位常量追加在 06-05 已落常量之后，值 None/[] + '# 实施期校准 — 待用户裁决'（不臆造数值）"
    - "question_bank 测试直插双列对齐 = INSERT 列清单补 model_id/model_version + VALUES 写 mid/1，seed helper 由 _seed_question_bank(pid) 改 (pid,mid)"

key-files:
  created: [server/test_m1_regression.py]
  modified: [server/config.py, server/test_m5_backend.py, server/test_m6_backend.py, server/test_m7_backend.py, server/test_p0_chain.py, server/test_p0_security.py, server/test_phase2_difficulty.py, server/test_phase2_interview.py, server/test_phase2_scoring.py, server/test_phase3_forms.py, server/test_phase3_sse.py, server/test_phase3_timer.py, server/test_phase3_idempotency.py, server/test_phase3_misc.py]

key-decisions:
  - "mock=3 确定性局限以 docstring 记档，不改 _mock_score（D-72/REF-8.6）"
  - "§31-4 两占位常量 DICT_MATCH_THRESHOLD=None / TITLE_CLEAN_WORDS=[] 只落占位不接线消费，待用户裁决（红线：不臆造阈值数值）"
  - "13 文件 question_bank 直插统一走 model_id/model_version 补齐 + mid 线程化（对齐 test_phase2_selection.py 既有样例），非 lookup 方案"

patterns-established:
  - "测试懒导入：八条 test_* 一律在函数体内 from server.services.X import func"
  - "seed helper 签名升级：_seed_question_bank(pid) → _seed_question_bank(pid, mid)，调用点 _mid 统一改 mid"

requirements-completed: [REF-7.5, REF-8.6, REQ-iterative-loop, REQ-jd-parse-model]

# Metrics
duration: 25min
completed: 2026-09-06
---

# Phase 6 Plan 03: M1 回归 + §31-4 占位 + 13 文件双列补齐 Summary

**M1 八项回归锁（test_m1_regression.py）+ mock=3 已知局限 docstring 记档；config.py §31-4 词典阈值/清洗词表占位常量（待用户裁决）；13 个会话类测试文件 question_bank INSERT 补齐 model_id/model_version**

## Performance

- **Duration:** 25 min（估算，跨多 session 含源码核验 + 83 处调用点映射）
- **Started:** 2026-09-05T15:55:23Z
- **Completed:** 2026-09-05T16:14:07Z
- **Tasks:** 3
- **Files modified:** 15 (1 new + 14 modified)

## Accomplishments
- `server/test_m1_regression.py`：八条 `test_*` 锁死模块一脆弱点——清洗边界（clean_jd）/抽取异常（normalize_title）/消歧降级（disambiguate_items）/权重尾差 Σ=1（生成器精确 + 编辑器 ±0.005 容差）/冲突 stalled（_gate_check 阈值=2）/confirmed 不可静默覆盖（adjudicate）/版本 diff（diff_models）/管理员权限（require_admin）
- mock interviewer 固定 3 分的确定性局限以模块 docstring 记档（D-72，不增强 `_mock_score`）
- `server/config.py` append-only 追加 §31-4 两占位常量 `DICT_MATCH_THRESHOLD=None` / `TITLE_CLEAN_WORDS=[]`，均标 `# 实施期校准 — 待用户裁决`，只落占位不接线消费
- 13 个会话类测试文件所有 `INSERT INTO question_bank` 列清单补齐 `model_id`/`model_version` 两列 + VALUES 写 `mid`/`1`，seed helper 由 `_seed_question_bank(pid)` 升级为 `(pid, mid)`

## Task Commits

Each task was committed atomically:

1. **Task 1: test_m1_regression.py 八项回归锁 + mock=3 记档** - `91a3cf3` (test)
2. **Task 2: §31-4 占位常量（config.py append-only）** - `0aef437` (chore)
3. **Task 3: 13 文件 question_bank INSERT 补齐 model_id/model_version** - `20f5d5d` (test)

## Files Created/Modified
- `server/test_m1_regression.py` - 八项 M1 回归锁 + mock=3 已知局限 docstring（懒导入被测纯函数）
- `server/config.py` - append-only 追加 DICT_MATCH_THRESHOLD=None / TITLE_CLEAN_WORDS=[] 占位常量（待用户裁决）
- `server/test_m5_backend.py` / `test_m6_backend.py` / `test_m7_backend.py` - question_bank INSERT 补双列 + mid 线程化
- `server/test_p0_chain.py` / `test_p0_security.py` - 同上（含 _seed_question_bank 签名升级）
- `server/test_phase2_difficulty.py` / `test_phase2_interview.py` / `test_phase2_scoring.py` - 同上
- `server/test_phase3_forms.py` / `test_phase3_sse.py` / `test_phase3_timer.py` / `test_phase3_idempotency.py` / `test_phase3_misc.py` - 同上

## Decisions Made
- **mock=3 记档（不增强）**：`_mock_score` 恒返回 `{"score": 3}` 作为已知局限写入 docstring，不改 `server/services/scoring.py`（D-72/REF-8.6）
- **§31-4 占位 = None/[]**：词典候选 top10 匹配阈值与清洗标题词表仅落占位 + 注释，禁止臆造数值，消费侧在用户裁决后由后续计划接入
- **13 文件双列补齐走 mid 线程化**：对齐 `test_phase2_selection.py` 既有 `_seed_question_bank(pid, mid)` 样例，逐文件 grep 定位 INSERT + 补列 + 写值，不改断言数值/测试语义

## Deviations from Plan

None — plan executed as written. 所有改动严格遵循「只补两列、不改断言、不改测试语义、config.py append-only」约束。

**Out-of-scope discoveries（按 scope boundary 记录至 deferred-items.md，非 auto-fix）：**

1. **`test_p0_chain.py::test_completed_session_guardrail` 二次 POST /report 返回 202 而非 409** — `request_report` 护栏只拒 `report_status=='GENERATING'`（分支 b），终态行（READY/PUBLISHED/FAILED）落入分支 c → 新 GENERATING 行 + 202。属 D-08 端点语义与 P0「成功标准 5」冲突的设计层问题，非双列补齐 bug。
2. **`test_phase3_timer.py::test_phase_column_defaults` 重跑 init_db 后 phase 仍 NULL** — phase 回填迁移已登记进 schema_version 登记簿（D-68），重跑 init_db 幂等、不回填手动置 NULL 的行。与 question_bank 无关。

**Total deviations:** 0 auto-fixed. 两项失败均为「双列补齐前更早失败被掩盖」的既有问题，非本计划引入，已 defer 待设计裁决。

## Issues Encountered
- **两项预存失败被双列补齐「揭盖」**：补齐 model_id/model_version 后，11/13 文件转绿，但 `test_completed_session_guardrail` 与 `test_phase_column_defaults` 在更深步骤撞上与本计划无关的既有缺口（报告重触发护栏 / phase 迁移幂等）。经核实两处均不在 Task 3 的 `files_modified` 且不涉及 question_bank 列，按 scope boundary 记录 deferred-items.md，未越权修复（Rule 4 架构层，须用户裁决）。
- 本计划 3 验收文件 `test_m5_backend.py`/`test_m6_backend.py`/`test_m7_backend.py` 全绿（16 passed）；grep 验收（13 文件每个 INSERT 列清单均含 model_id/model_version）空输出通过。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 06-03 收口完成：M1 八项回归锁 + mock=3 记档 + §31-4 占位常量 + 13 文件双列补齐全部落地
- Phase 6 五计划（06-01~06-05）全部完成，里程碑 v2.0 待验证收口
- 遗留两项 deferred（报告重触发护栏 / phase 回填幂等）需设计裁决，见 `.planning/phases/06-migration-test-closure/deferred-items.md`
- §31-4 两开放参数（DICT_MATCH_THRESHOLD / TITLE_CLEAN_WORDS）None/[] 待用户裁决后接入消费侧

---
*Phase: 06-migration-test-closure*
*Completed: 2026-09-06*
