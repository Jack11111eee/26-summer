---
phase: 05-evidence-report-contract
plan: 03
subsystem: api
tags: [python, fastapi, sqlite, report, state-machine, audit, trace-link]

# Dependency graph
requires:
  - phase: 05-evidence-report-contract/02
    provides: aggregate_session_scores 新增 review_status/observation_status/provisional/coverage 字段（状态机推进依据）
  - phase: 05-evidence-report-contract/01
    provides: trace_link.link_entity + LINK_ROLES 枚举 + llm.call_llm_json trace_out 透出（report→trace 写点调用对象）
provides:
  - report 表 report_status/review_status/version + 发布/人工复核字段（_migrate_report_phase5 存量回填）
  - 报告状态机 GENERATING→PROVISIONAL|READY→PUBLISHED|FAILED（REPORT_STATUSES/REVIEW_STATUSES + _assert_report_transition）
  - 七项一致性校验 _run_consistency_checks + HIRING_REDLINE_WORDS 录用红线词表
  - 版本化 INSERT（废除 DELETE 覆盖，feedback FK 不悬空）
  - POST /api/admin/reports/{report_id}/publish 管理员显式发布端点
  - 后台任务异常 → FAILED 行 + TASK_FAILED 事件，前端确定性区分生成中/失败
  - report→session→…→trace 运行时 trace_link 写点（闭合 D-56 五要素）
affects:
  - 05-evidence-report-contract/04 (feedback/review 闭环依赖 report 版本行 FK)
  - 06-migration-regression (report 表 schema_version 收口)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "状态机迁移由代码校验（_assert_report_transition raise ValueError），无 DB CHECK（N11 惯例）"
    - "版本化报告行：version = 1 + MAX(version)，get_report_by_session 取 ORDER BY created_at DESC, version DESC LIMIT 1"
    - "七项一致性校验在聚合后、版本化 INSERT 前运行，任一失败 → FAILED 行（report_json 含 error 摘要）"
    - "后台任务异常独立小事务写 FAILED 行 + TASK_FAILED 事件（先 commit 再调 LLM 模式）"

key-files:
  created:
    - server/services/report_checks.py
    - server/api/admin/reports.py
  modified:
    - server/db.py
    - server/services/report.py
    - server/api/assessment.py
    - server/main.py
    - web/src/views/assessment/Report.vue
    - web/src/views/admin/TestCenter.vue
    - server/test_phase5_report.py
    - server/test_m6_backend.py

key-decisions:
  - "存量回填 = PUBLISHED + NONE + version=1（关口 A 裁决）"
  - "REVIEW_STATUSES 六值并集含 HUMAN_REVIEW_REQUIRED（关口 A 裁决）"
  - "HIRING_REDLINE_WORDS = (建议录用,不予录用,排名第,推荐淘汰,拟录用,建议淘汰)（D-002 集中一处）"
  - "校验②改 agg-vs-DB weight 一致性（m6 种子权重 Σ=0.40 非 1.0，绝对值 Σ≈1.0 口径不适用）"
  - "report→trace 写点：link_entity reported(report) + source(assessment_session)，与 score→trace 共享 trace_id"

patterns-established:
  - "版本化报告：废除 DELETE 覆盖，同 session 多版本行保留，旧行反馈 FK 不悬空"
  - "FAILED 显式可见：后台异常写 FAILED 行 + TASK_FAILED 事件，前端 poll 确定性分支"

requirements-completed: [REF-5.9, REF-8.3]

# Metrics
duration: 9min
completed: 2026-09-05
---

# Phase 05 Plan 03: 报告发布状态机与审计契约 Summary

**报告发布收口为可审计状态机：七项一致性校验 + 版本化 INSERT（废除 DELETE 覆盖）+ 管理员显式 publish 端点 + report→trace 运行时 trace_link 写点（闭合 D-56 五要素）**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-05T18:33:35+08:00
- **Completed:** 2026-09-05T18:41:16+08:00
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- report 表新增 10 列（report_status/review_status/version + 发布/人工复核字段），存量回填 PUBLISHED+NONE+version=1
- 报告状态机 GENERATING→PROVISIONAL|READY→PUBLISHED|FAILED，非法迁移代码拒绝
- 七项一致性校验 `_run_consistency_checks`，任一失败 → FAILED 行（不生成正常报告）
- 版本化 INSERT 替换 DELETE 覆盖——同 session 多版本行保留，feedback FK 不悬空
- POST /api/admin/reports/{report_id}/publish 管理员显式发布端点（候选人 403）
- 后台任务异常 → FAILED 行 + TASK_FAILED 事件，前端 poll 确定性区分生成中/失败
- report→session→…→trace 运行时 trace_link 写点闭合审计链（test_audit_chain_closure GREEN）

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 测试脚手架（5 条新断言 RED）** - `34f310b` (test)
2. **Task 2: 状态机列 + 七项校验 + 版本化 INSERT + report→trace 写点** - `291405c` (feat)
3. **Task 3: request_report 409 + publish 端点 + 前端最小化 + test_m6 重写** - `014d8b2` (feat)

## Files Created/Modified
- `server/services/report_checks.py` - 七项一致性校验 + HIRING_REDLINE_WORDS 常量
- `server/api/admin/reports.py` - POST /reports/{report_id}/publish 端点（require_admin）
- `server/db.py` - report 表 10 新列 + _migrate_report_phase5 + 存量回填
- `server/services/report.py` - REPORT_STATUSES/REVIEW_STATUSES 常量 + 状态机 + 版本化 INSERT + trace_link 写点
- `server/api/assessment.py` - request_report 409 边界 + _write_failed_report + TASK_FAILED
- `server/main.py` - 注册 admin.reports router
- `web/src/views/assessment/Report.vue` - poll 读 report_status 确定性区分 failed/generating
- `web/src/views/admin/TestCenter.vue` - 「发布报告」按钮 + onPublish handler
- `server/test_phase5_report.py` - 新增 5 条测试（9 条全绿）
- `server/test_m6_backend.py` - 7 条 stale 断言重写为版本化新值（44 通过/0 失败）
- `server/test_phase5_evidence.py` - _seed_audit_chain 补 report→session trace 腿（deviation）
- `web/src/api/index.js` - admin.reports.publish API 封装（deviation）

## Decisions Made
- 存量回填默认值 PUBLISHED+NONE+version=1（关口 A 硬裁决，锁定）
- REVIEW_STATUSES 六值并集含 HUMAN_REVIEW_REQUIRED（关口 A 硬裁决，锁定）
- HIRING_REDLINE_WORDS 六词表集中 report_checks.py（D-002）
- 校验②权重一致性改为 agg-vs-DB 比对（m6 种子 Σ=0.40，绝对值 Σ≈1.0 口径失真）
- 校验⑦需报告全文，签名加可选 `report_text=""` 参数

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Critical functionality] 校验②权重口径改为 agg-vs-DB 一致性**
- **Found during:** Task 2
- **Issue:** 计划校验②写「Σ item.weight ≈ 1.0 容差 0.005」，但 m6 种子模型权重 Σ=0.40（硬技能/软技能/经验/资格分权），绝对值 Σ≈1.0 会永久误判
- **Fix:** 改为比对聚合侧 item_scores 权重和 vs DB competency_item 权重和（<0.005 容差）
- **Files modified:** server/services/report_checks.py
- **Verification:** test_consistency_check_fails_to_failed + test_m6_backend.py 全绿
- **Committed in:** 291405c

**2. [Rule 2 - Critical functionality] 校验⑦签名补 report_text 参数**
- **Found during:** Task 2
- **Issue:** 校验⑦需对 report_data 全文扫描红线词，但计划签名 `_run_consistency_checks(agg, session_id)` 无报告文本入参
- **Fix:** 加可选第三参 `report_text=""`，调用处传 `json.dumps(report_data)`
- **Files modified:** server/services/report.py, server/services/report_checks.py
- **Verification:** 7 项校验完整运行，红线词检测生效
- **Committed in:** 291405c

**3. [Rule 1 - Bug] test_version_immutability 用 generate_report 直调而非 request_report**
- **Found during:** Task 1
- **Issue:** request_report 有 409 REPORT_GENERATING 边界，第二次触发会被拦；且 TestClient 后台任务执行非确定性，无法可靠制造 2 版本行
- **Fix:** 直接调 generate_report 两次制造 version 1/2，断言 2 行 + MAX(version)=2 + 旧行保留
- **Files modified:** server/test_phase5_report.py
- **Verification:** test_version_immutability 绿
- **Committed in:** 34f310b (测试), 291405c (实现后转绿)

**4. [Rule 2 - Critical functionality] test_phase5_evidence.py 补 report→session trace 腿**
- **Found during:** Task 2
- **Issue:** 审计链闭合测试 test_audit_chain_closure 需 report→session 腿（05-03 落地写点），但原 _seed_audit_chain 未造该腿
- **Fix:** _seed_audit_chain 追加 report→session trace_link（reported→report / source→assessment_session）
- **Files modified:** server/test_phase5_evidence.py
- **Verification:** test_audit_chain_closure 6 步遍历全绿
- **Committed in:** 291405c

**5. [Rule 2 - Critical functionality] web/src/api/index.js 补 admin.reports.publish 封装**
- **Found during:** Task 3
- **Issue:** 计划 files_modified 列 TestCenter.vue 但未列 api/index.js，前端按钮无 API 封装无法调用 publish 端点
- **Fix:** admin 对象补 `reports: { publish: (report_id, review_outcome, review_note) => api.post(...) }`
- **Files modified:** web/src/api/index.js
- **Verification:** TestCenter.vue onPublish 引用 admin.reports.publish 成功
- **Committed in:** 014d8b2

**6. [Rule 1 - Bug] test_m6_backend.py 7 条 stale 断言重写**
- **Found during:** Task 3
- **Issue:** 05-02 归一化（_normalize_score = (score−1)/4 + adjudicate 取低）改变了聚合/报告值，7 条旧断言（Python 5.0→3.0、total 30→24.5、幂等 n==1→版本化 n==2 等）失效
- **Fix:** 重写为正确值：Python actual=3.0/gap=1.0/score=9.5、沟通 score=6.0、total=24.5、radar actual=[3.0,3.0]、版本化 n==2/maxv==2
- **Files modified:** server/test_m6_backend.py
- **Verification:** `python test_m6_backend.py` → 44 通过/0 失败
- **Committed in:** 014d8b2

---

**Total deviations:** 6 auto-fixed（1 Rule 1 bug + 5 Rule 2 critical functionality）
**Impact on plan:** All auto-fixes necessary for correctness/audit-contract integrity. No scope creep.

## Issues Encountered
- test_m6_backend.py 7 条 stale 断言在任务执行前即存在（05-02 归一化遗留），属用户明确要求重写范围，非意外问题
- SQLite 单写者约束下，后台任务失败注入需 monkeypatch generate_report + admin 读豁免（_seed_session 造不可登录用户）

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 05-04（feedback/review 闭环）可启动：report 版本行 FK 已就位，feedback 提异议不再悬空
- publish 端点 + REVIEW_REPORT_PUBLISH_CONFIRMED 事件已就位，供 05-04 review 状态流转复用

---
*Phase: 05-evidence-report-contract*
*Completed: 2026-09-05*

## Self-Check: PASSED

- 12 files verified present (report_checks.py, admin/reports.py, db.py, report.py, assessment.py, main.py, Report.vue, TestCenter.vue, test_phase5_report.py, test_m6_backend.py, test_phase5_evidence.py, api/index.js)
- 3 task commits verified present: 34f310b, 291405c, 014d8b2
