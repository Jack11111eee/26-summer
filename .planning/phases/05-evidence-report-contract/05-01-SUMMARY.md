---
phase: 05-evidence-report-contract
plan: 01
subsystem: database
tags: [sqlite, trace_link, evidence-span, audit-chain, llm-trace, scoring]

# Dependency graph
requires:
  - phase: 02-dynamic-selection
    provides: question_score score_state 三态、score_question/score_session 落库路径、llm_trace 调用留痕
  - phase: 04-assessment
    provides: question_bank model_id/model_version 绑定、competency_item、assessment_session 链路
provides:
  - trace_link 统一审计链实体表 + link_entity 枚举校验服务（LINK_ROLES 六态）
  - 旧 llm_trace.ref_id 导入迁移（_migrate_trace_link，sqlite_master 守卫 + 懒导入防循环依赖）
  - _locate_span code-point 语义 evidence_span 定位 + quote_hash 降级路径
  - question_score 审计快照列（evidence_spans_json/rubric_version/scorer_version/measurement_target）
  - score→trace 运行时写点（主观题 trace_id → link_entity scored/source）
  - llm._record_trace 返回 trace_id + call_llm_json trace_out 透传
affects: [05-evidence-report-contract (05-02 报告聚合, 05-03 report→session 审计腿)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - N11 枚举代码校验（link_role 校验，无 DB CHECK，raise ValueError 中文报错）
    - D-003「LLM 不碰数字」——offset/quote_hash 全代码计算，LLM 只产 evidence_quote 文本
    - D-020 trace_link 统一审计链（report→session→model/version→question→message→score→trace）
    - Unicode code-point 语义（Python str.find/len，非 UTF-16 码元）
    - SQLite 单写者模式 B「内存算完单事务落库」（含 LLM 调用，一次写库避免 database is locked）
    - 迁移双轨（_DDL 字符串 + _migrate_* 函数注册进 init_db）
    - 懒导入防循环依赖（db._migrate_trace_link 内 from .services.pipeline import new_id）

key-files:
  created:
    - server/test_phase5_evidence.py
    - server/services/trace_link.py
  modified:
    - server/db.py
    - server/services/scoring.py
    - server/services/llm.py
    - server/api/admin/trace.py

key-decisions:
  - "_locate_span 定位失败返回 None，调用方降级为 quote_hash-only span（source_message_id/offset 全 None）"
  - "旧 llm_trace.ref_id 经 _migrate_trace_link 按 call_type→候选表 probe 命中才拆 trace_link('source')，未命中保留原 ref_id"
  - "score→trace 运行时写点仅主观题（客观/INVALIDATED 无 LLM trace，trace_id=None 不写 link）"
  - "test 文件懒导入 _locate_span（Task 2 子集先可收集，Task 3 落地后三 span 测试可用）"

patterns-established:
  - "evidence_span 三态：定位命中（source_message_id/start_offset/end_offset/quote_hash）/ 降级（quote_hash only）/ 无 quote（None）"
  - "trace_link 合并去重消费（trace.py get_session_traces ref_id IN 并集 + trace_link 反查 dedup）"

requirements-completed: [REF-2.10, REF-2.3, REF-8.7]

# Metrics
duration: 9min
completed: 2026-09-05
---

# Phase 05 Plan 01: 证据链 span 定位与统一审计链 trace_link 基础设施

**evidence_span 定位（code-point 语义 + quote_hash 降级）、trace_link 统一审计链实体表与旧 ref_id 导入迁移、question_score 审计快照列与 score→trace 运行时写点**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-05T09:42:23Z
- **Completed:** 2026-09-05T09:51:09Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- trace_link 统一审计链实体表（DDL）+ link_entity 枚举校验服务（LINK_ROLES 六态，N11 惯例无 DB CHECK）
- 旧 llm_trace.ref_id 导入迁移 `_migrate_trace_link`（call_type→候选表 probe 命中拆 link，未命中保留原 ref_id；sqlite_master 守卫兼容 fresh DB）
- `_locate_span` 结构化 span 定位（code-point 语义，quote_hash=sha256 全代码计算）+ 定位失败降级为 quote_hash-only
- question_score 审计快照列（evidence_spans_json/rubric_version/scorer_version/measurement_target）经 `_migrate_question_score_phase5` ALTER 补列
- score→trace 运行时写点：主观题成功 trace 经 link_entity(scored/source) 关联 question_score 与 assessment_question
- llm `_record_trace` 返回 trace_id，`call_llm_json` 新增 `trace_out` 透传（仅成功路径 append，失败重试不追加）

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 测试脚手架（三件套 header + 6 RED 断言）** - `bd10529` (test)
2. **Task 2: trace_link 服务 + 表 DDL + 旧 ref_id 导入迁移 + llm trace_id 透传** - `35460c2` (feat)
3. **Task 3: _locate_span + evidence_spans_json + 审计快照列 + score→trace 运行时写点** - `586348c` (feat)

**Plan metadata:** final `docs(05-01)` commit follows this summary.

_Note: TDD RED/GREEN——Task 1 为 RED，Task 2/3 各为 GREEN 子集。_

## Files Created/Modified

- `server/test_phase5_evidence.py` - 6 测试（span 定位/降级/Unicode/枚举校验/迁移/审计链闭合）+ 三件套 header
- `server/services/trace_link.py` - LINK_ROLES 枚举 + link_entity 校验写点
- `server/db.py` - trace_link 表 DDL + `_migrate_trace_link` + `_migrate_question_score_phase5`（4 列）+ init_db 注册
- `server/services/scoring.py` - `_locate_span`/`_build_evidence_spans`/`_latest_user_message_id` + score_question/score_session 返回 evidence_spans_json/trace_id + 运行时 link 写点
- `server/services/llm.py` - `_record_trace` 返回 trace_id + `call_llm_json` trace_out 透传
- `server/api/admin/trace.py` - get_session_traces 加 trace_link 反查合并去重

## Decisions Made

- `_locate_span` 定位失败返回 None（不抛错），调用方 `_build_evidence_spans` 降级为 quote_hash-only span —— mock "mock quote" 与 LLM 改写非原文场景不阻断评分落库
- 旧 ref_id 导入采用 probe 命中判定（`SELECT 1 FROM {table} WHERE {pk}=?`），未命中保留原 ref_id 而非硬删
- score→trace 运行时写点仅主观题：客观题/INVALIDATED 无 LLM 调用故 trace_id=None 不写 link
- 测试文件懒导入 `_locate_span`，使 Task 2 子集（枚举校验/迁移）可在 Task 3 落地前独立收集验证（增量 TDD）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 修正 `_migrate_trace_link` 内 pipeline 导入路径（防循环依赖）**
- **Found during:** Task 2 (trace_link 迁移落地)
- **Issue:** 顶层 `from .pipeline import new_id` 在 db.py 会触发 `ModuleNotFoundError: No module named 'server.pipeline'`（pipeline.py 位于 `server/services/pipeline.py`），且顶层导入会与 pipeline 的 `from ..db import get_conn` 形成循环依赖
- **Fix:** 改为 `_migrate_trace_link` 函数内懒导入 `from .services.pipeline import new_id`
- **Files modified:** server/db.py
- **Verification:** test_ref_id_import_migration 通过（迁移正常执行，trace_link 拆分正确）
- **Committed in:** 35460c2 (Task 2 commit)

**2. [Rule 1 - Bug] 测试模块懒导入 `_locate_span` 以避免 Task 2 子集收集失败**
- **Found during:** Task 2 验证（增量 TDD 分阶段收集）
- **Issue:** 模块顶层导入 `_locate_span`（Task 3 才落地）会导致 Task 2 的 test_trace_link_role_validation/test_ref_id_import_migration 无法收集（ImportError）
- **Fix:** 将 `_locate_span` 改为在 3 个 span 测试函数内懒导入
- **Files modified:** server/test_phase5_evidence.py
- **Verification:** Task 2 后 `-k "role_validation or ref_id_import"` 收集通过；Task 3 后全量 5 通过
- **Committed in:** bd10529 (Task 1 commit，后续 Task 2 修正)

**3. [Rule 1 - Bug] 迁移测试改用裸 sqlite3.connect 播种（绕 FK）**
- **Found during:** Task 2 验证（test_ref_id_import_migration 播种失败）
- **Issue:** assessment_session 外键链（user_id/position_id/model_id）不齐备时经 get_conn()（FK=ON）直插会被拒绝，无法构造「parentless session + llm_trace」迁移种子
- **Fix:** 播种改用裸 `sqlite3.connect(_tmp_db)`（无 FK 强制），迁移本体仍走 get_conn()
- **Files modified:** server/test_phase5_evidence.py
- **Verification:** test_ref_id_import_migration 通过
- **Committed in:** bd10529 (Task 1 commit，后续 Task 2 修正)

---

**Total deviations:** 3 auto-fixed (2 bug, 1 blocking)
**Impact on plan:** 均为正确性/可收集性必需修正，无范围蔓延。

## Issues Encountered

- 循环依赖（db.py ↔ pipeline）经懒导入规避，未改模块依赖结构
- test_audit_chain_closure 在 "session" 步断言失败 —— **这是预期 RED**：report→session 腿（trace_link `reported`→report / `source`→assessment_session）由 05-03 落地，05-01 只交付 score→trace 腿（scored→question_score / source→assessment_question）。测试如实报告，未尝试在此强行转绿。

## Test State

- **5 passed**: test_span_located_in_original / test_span_degrade_on_mock_quote / test_span_unicode_code_point / test_trace_link_role_validation / test_ref_id_import_migration
- **1 expected RED**: test_audit_chain_closure —— 断言 `_resolve(report_id, "session")` 为 None（report→session 腿待 05-03 闭合）

## User Setup Required

None - no external service configuration required（全程 LLM_PROVIDER=mock 离线，DB 用 tempfile）。

## Next Phase Readiness

- 05-02（报告聚合）可直接消费 evidence_spans_json 与 question_score 审计快照列
- 05-03（report→session 审计腿）落地后 test_audit_chain_closure 应转绿，届时重跑确认
- 无阻塞项

---

## Self-Check: PASSED

- All 6 created/modified files exist (server/test_phase5_evidence.py, server/services/trace_link.py, server/db.py, server/services/scoring.py, server/services/llm.py, server/api/admin/trace.py)
- All 3 task commits verified: bd10529 (test) / 35460c2 (feat) / 586348c (feat)
- Test state confirmed: 5 passed, 1 expected RED (test_audit_chain_closure @ "session" — report→session leg lands in 05-03)

---
*Phase: 05-evidence-report-contract*
*Completed: 2026-09-05*
