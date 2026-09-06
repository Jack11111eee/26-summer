---
phase: 05-evidence-report-contract
plan: 02
subsystem: api
tags: [aggregation, adjudicate, impute, report, scoring, sqlite, item-measurement]

# Dependency graph
requires:
  - phase: 05-evidence-report-contract (05-01)
    provides: question_score 审计快照列（evidence_spans_json 等）、trace_link 基础设施、score_state 三态落库
  - phase: 02-dynamic-selection
    provides: question_score score_state 分母规则、_EXCLUDED_STATES 三路分流先例
provides:
  - item_measurement 统一裁决（adjudicate 替换按题数均分；冲突取低留人工标记，阈值常量一处定义）
  - IMPUTED r 比例补算（_impute_r + _observed_items question→item 归约 + 覆盖率展示）
  - required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED；O=∅ → NO_VALID_OBSERVATION
  - _normalize_score 统一 (score−1)/4 归一化（关口 A 裁决，隔离 §20.1/§20.3 张力）
  - report.py 透传 agg 新增字段（review_status/observation_status/provisional/coverage）
affects: [05-evidence-report-contract (05-03 报告状态机落库消费这些字段, 05-04 feedback)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - D-058 item_measurement 内存统一测量记录（非新表），普通题 measurement_source="ordinary"，综合题列位预留
    - D-059 IMPUTED r = Σ w_i·s_i / Σ w_i（s_i=(score−1)/4），den==0 不除零返回 None
    - D-060 required 缺失 → provisional + HUMAN_REVIEW_REQUIRED（不触发补测）
    - 归一化张力隔离进 _normalize_score 单一函数（observed/imputed 两分支同尺度 (score−1)/4）
    - 覆盖率 coverage{observed_count, imputed_count, total_measureable, coverage_ratio, missing_reasons}
    - 测试纯函数懒导入（adjudicate/_impute_r/_normalize_score），增量 TDD 分阶段可收集

key-files:
  created:
    - server/test_phase5_report.py
  modified:
    - server/services/aggregation.py
    - server/services/report.py

key-decisions:
  - "adjudicate 冲突阈值 ADJUDICATE_CONFLICT_THRESHOLD=2：观测等级极差 ≥2 视为重大冲突取低留人工标记"
  - "_normalize_score observed/imputed 两分支统一 (score−1)/4（关口 A 裁决，作废 score/5 两尺度混用）"
  - "IMPUTE_RATIO_THRESHOLD=0.2：IMPUTED 覆盖率超阈值 → human_review=True（关口 A 裁决）"
  - "可测量普通 item = 非 gate、importance≠required、category≠qualification；qualification 缺失仅记 missing_warnings 不标 PROVISIONAL"
  - "测试纯函数懒导入：Task 2 先落地 adjudicate/_normalize_score，Task 3 落地 _impute_r（同 05-01 _locate_span 懒导入先例）"

patterns-established:
  - "item_measurement 裁决：question-level 收成统一测量记录 → adjudicate 产出 item_final_level → _normalize_score 进总分"
  - "IMPUTED display level = r×4+1 映射回 1–5 级参与总分/雷达；实际贡献 = weight × (display_level−1)/4 × 100 ≈ weight × r × 100"

requirements-completed: [REF-5.4, REF-5.5, REF-5.6]

# Metrics
duration: 5min
completed: 2026-09-05
---

# Phase 05 Plan 02: item_measurement 统一裁决 + IMPUTED 补算 + required 缺失 PROVISIONAL

**废弃按题数均分，改由 item_measurement 统一裁决（adjudicate 冲突取低留人工标记）；缺失普通 item 走 r 比例补算 IMPUTED + 覆盖率展示；required 缺失 → PROVISIONAL；O=∅ → NO_VALID_OBSERVATION；归一化张力隔离进 _normalize_score 统一 (score−1)/4**

## Performance

- **Duration:** 5 min
- **Started:** 2026-09-05T10:01:34Z
- **Completed:** 2026-09-05T10:06:57Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- `adjudicate` 纯函数替换 `actual = sum(finals)/len(finals)`：重大冲突（极差 ≥2）取低 + human_review 标记，一致场景取 round(mean,2)
- `_normalize_score(score, source)` 统一 observed/imputed 两分支为 `(score−1)/4`，作废旧实现 `score/5` 两尺度混用（关口 A 裁决）
- `_impute_r`（r = Σ w_i·s_i / Σ w_i，den==0 不除零）+ `_observed_items`（question-level item_measurement 归约为 per-item {item_id, weight, score}）
- `_load_model_items` 补 `ci.importance` 列（required 缺失判定依赖）
- aggregate 主循环三路分流收成内存 item_measurement 记录，缺失项按 importance/category 分流：required→PROVISIONAL、qualification→仅警告、preferred/plus→IMPUTED、O=∅→NO_VALID_OBSERVATION
- 聚合返回新增 coverage/review_status/observation_status/provisional；report.py 透传进 report_data（状态机落库属 05-03）

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 测试脚手架（test_phase5_report.py 4 断言 RED）** - `bd22014` (test)
2. **Task 2: adjudicate + _normalize_score 纯函数（归一化张力隔离）** - `f8e2c6e` (feat)
3. **Task 3: _impute_r + _observed_items 归约 + 主循环接入 + report.py 透传** - `f5ddfad` (feat)

**Plan metadata:** final `docs(05-02)` commit follows this summary.

_Note: TDD RED/GREEN——Task 1 为 RED（ImportError/KeyError），Task 2/3 各为 GREEN 子集。_

## Files Created/Modified

- `server/test_phase5_report.py` - 4 测试（adjudicate 冲突取低 / IMPUTED r 数学 / O=∅ NO_VALID_OBSERVATION / required 缺失 PROVISIONAL）+ 三件套 header + _seed_session 直插外键全链
- `server/services/aggregation.py` - 常量（ADJUDICATE_CONFLICT_THRESHOLD/NORMALIZE_*/IMPUTE_RATIO_THRESHOLD）+ adjudicate/_normalize_score/_impute_r/_observed_items 纯函数 + _load_model_items 补 importance + aggregate_session_scores 主循环改写
- `server/services/report.py` - report_data 透传 review_status/observation_status/provisional/coverage

## Decisions Made

- 冲突量化阈值 `ADJUDICATE_CONFLICT_THRESHOLD = 2` 一处定义（§19 重大冲突取低，实施期可调）
- `_normalize_score` 两分支统一 `(score−1)/4`，归一化张力隔离进单一函数（关口 A 已裁决，SSOT §20.3 已同步补公式）
- `IMPUTE_RATIO_THRESHOLD = 0.2`（§31-3 补算复核阈值，关口 A 已裁决）
- 可测量普通 item 定义 = 非 gate 且 importance≠required 且 category≠qualification（§20.1 required/qualification 不补算）
- 测试纯函数懒导入，使 Task 2 子集（adjudicate）可在 _impute_r 落地前独立转绿（同 05-01 懒导入先例）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 测试 _seed_session 硬编码 username 触发 UNIQUE 冲突**
- **Found during:** Task 3 全量回归（test_required_missing_provisional 与 test_impute_no_valid_observation 同进程）
- **Issue:** `_seed_session` 以固定 username "cand_report" 插 user 行，两个集成测试各自播种时第二次 INSERT 触发 `sqlite3.IntegrityError: UNIQUE constraint failed: user.username`
- **Fix:** username 改用唯一 uid（`(uid, uid, ...)`），user_id 本就唯一
- **Files modified:** server/test_phase5_report.py
- **Verification:** test_phase5_report.py 4 条全绿
- **Committed in:** f5ddfad (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (bug)
**Impact on plan:** 测试隔离性正确性修正，无范围蔓延。

## Issues Encountered

- Task 2 的 `<verify>` 命令同时列出 test_impute_r_math，但 `_impute_r` 按计划在 Task 3 才落地——Task 2 后该测试仍 RED（懒导入 ImportError），Task 2 验收仅要求 test_adjudicate_conflict_lower 绿；如实报告，Task 3 后转绿。
- `evidence_refs: []` 为 item_measurement 记录的列位预留占位（综合题 integrated 来源 REF-3.9 延后，D-58 明确列位预留），非阻断性 stub。

## Test State

- **4 passed**: test_adjudicate_conflict_lower / test_impute_r_math / test_impute_no_valid_observation / test_required_missing_provisional
- **test_m6_backend.py 预期 RED（deferred）**: 总分数值断言（31.4）与「Python actual_level=(5+3)/2=4.0」断言因 (score−1)/4 归一化 + adjudicate 冲突取低（[5,3]→3.0）而 RED。该文件由 05-03 改写断言，本计划**未修改**，如实报告。

## User Setup Required

None - no external service configuration required（全程 LLM_PROVIDER=mock 离线，DB 用 tempfile）。

## Next Phase Readiness

- 05-03（报告状态机与发布）可消费聚合新增字段 review_status/observation_status/provisional/coverage 落库 report_status/review_status
- 05-03 需同步改写 test_m6_backend.py 总分数值与 actual_level 断言（版本化 + 状态机）
- 无阻塞项

---

## Self-Check: PASSED

- All 3 created/modified files exist (server/test_phase5_report.py, server/services/aggregation.py, server/services/report.py)
- All 3 task commits verified: bd22014 (test) / f8e2c6e (feat) / f5ddfad (feat)
- Test state confirmed: test_phase5_report.py 4 passed

---
*Phase: 05-evidence-report-contract*
*Completed: 2026-09-05*
