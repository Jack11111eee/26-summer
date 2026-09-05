---
phase: 05-evidence-report-contract
plan: 04
subsystem: api
tags: [python, fastapi, sqlite, feedback, audit, review, state-events]

# Dependency graph
requires:
  - phase: 05-evidence-report-contract/03
    provides: report 版本化行（feedback FK 指向具体版本 report_id 不悬空）+ REVIEW_* 事件入口 append_event
provides:
  - feedback 表 user_id/review_note/reviewer_id/reviewed_at 四审计列（_migrate_feedback_phase5 幂等迁移）
  - submit_feedback 落 user_id + 同事务 REVIEW_FEEDBACK_RECEIVED 事件（actor_type=candidate）
  - admin review_feedback/mark_bad_case 持久化 note + reviewer_id + reviewed_at（废除 body.note 静默丢弃）
  - _load_question_reviews SELECT 补 qs.item_id（前端 itemReason 可锚定能力项）
affects:
  - 06-migration-regression (feedback 表 schema_version 收口)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "feedback 审计列全可空、无 DB CHECK（N11），存量行 NULL——迁移不虚构提交人/处理人"
    - "submit_feedback INSERT + append_event 同事务（append_event 不 commit，由调用者 conn.commit() 覆盖）"
    - "admin review/bad-case 留痕 review_note/reviewer_id/reviewed_at（废除 body.note 丢弃）"
    - "_load_question_reviews SELECT 补 qs.item_id（dict(r) 自动透出 item_id 键）"

key-files:
  created:
    - server/test_phase5_feedback.py
  modified:
    - server/db.py
    - server/api/assessment.py
    - server/api/admin/feedback.py
    - server/services/report.py

key-decisions:
  - "feedback 审计列命名 = user_id/review_note/reviewer_id/reviewed_at（plan 权威，D-66 的 note/reviewer 落为 review_note/reviewer_id）"
  - "存量 feedback 行 user_id/review_note/reviewer_id/reviewed_at 保持 NULL（D-66 只保证新行全字段）"
  - "REVIEW_FEEDBACK_RECEIVED 事件 actor_type='candidate' actor_id=user_id，与 feedback INSERT 同事务单 commit"

patterns-established:
  - "feedback 审计链闭环：user_id 溯源 + REVIEW_FEEDBACK_RECEIVED 事件 + admin 处理留痕 + 逐题回顾 item_id 锚定"

requirements-completed: [REF-7.3]

# Metrics
duration: 3min
completed: 2026-09-05
---

# Phase 05 Plan 04: feedback 审计链闭环 Summary

**feedback 审计链收口为可回溯闭环：四审计列迁移 + submit_feedback 落 user_id 且同事务写 REVIEW_FEEDBACK_RECEIVED 事件 + admin review/bad-case 持久化 note/reviewer/reviewed_at + question_reviews 补 item_id**

## Performance

- **Duration:** 3 min
- **Started:** 2026-09-05T10:52:47Z
- **Completed:** 2026-09-05T10:56:11Z
- **Tasks:** 3
- **Files modified:** 5 (1 created + 4 modified)

## Accomplishments
- feedback 表新增 user_id/review_note/reviewer_id/reviewed_at 四审计列（`_migrate_feedback_phase5` PRAGMA 幂等迁移 + `_DDL` 同步补列）
- submit_feedback 捕获 load_owned_report 返回值拿 session_id，INSERT 补 user_id，commit 前同事务 append_event REVIEW_FEEDBACK_RECEIVED（actor_type=candidate）
- admin review_feedback/mark_bad_case 注入 admin 依赖，持久化 review_note + reviewer_id + reviewed_at（废除现状「body.note 丢弃」）
- _load_question_reviews SELECT 补 qs.item_id，前端 itemReason 可锚定能力项

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave 0 测试脚手架（三条 REF-7.3 断言 RED）** - `518cf17` (test)
2. **Task 2: feedback 四列迁移 + submit_feedback 落 user_id + REVIEW_FEEDBACK_RECEIVED 事件** - `1687fb3` (feat)
3. **Task 3: admin review/bad-case note 持久化 + question_reviews 补 item_id** - `b81aede` (feat)

## Files Created/Modified
- `server/test_phase5_feedback.py` - 三条 REF-7.3 断言（test_feedback_audit_fields / test_admin_note_persisted / test_question_reviews_has_item_id）
- `server/db.py` - feedback DDL 补四审计列 + `_migrate_feedback_phase5` 迁移 + init_db 注册
- `server/api/assessment.py` - submit_feedback 捕获 rpt + INSERT 补 user_id + REVIEW_FEEDBACK_RECEIVED 事件
- `server/api/admin/feedback.py` - review_feedback/mark_bad_case 留痕 note/reviewer_id/reviewed_at
- `server/services/report.py` - _load_question_reviews SELECT 补 qs.item_id

## Decisions Made
- feedback 审计列命名采用 plan 权威口径 user_id/review_note/reviewer_id/reviewed_at（D-66 简写 note/reviewer 落到 review_note/reviewer_id）
- 存量 feedback 行四审计列保持 NULL（迁移不虚构提交人/处理人，D-66 只保证新行全字段）
- REVIEW_FEEDBACK_RECEIVED 事件 actor_type='candidate'、actor_id=user_id，与 feedback INSERT 同事务单 commit（D-067 一切留痕）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Critical functionality] feedback DDL 同步补四审计列**
- **Found during:** Task 2
- **Issue:** 计划 `<action>` 只描述新增 `_migrate_feedback_phase5` 迁移函数，未提 `_DDL` 中 feedback 表定义更新。新测试库（tempfile 全新 DB）走 init_db 时 feedback 表由 `_DDL` 直建，迁移函数因「表不存在」提前返回——若不补 DDL，全新库 feedback 无 user_id/review_note 列，test_feedback_audit_fields 必然 OperationalError
- **Fix:** `_DDL` feedback 表追加 user_id/review_note/reviewer_id/reviewed_at 四列（与 report/question_score 的「DDL + 迁移」双轨既定模式一致）
- **Files modified:** server/db.py
- **Verification:** 全新临时库 init_db 后 PRAGMA table_info(feedback) 含四列；test_feedback_audit_fields 绿
- **Committed in:** 1687fb3

---

**Total deviations:** 1 auto-fixed（1 Rule 2 critical functionality）
**Impact on plan:** Auto-fix 为 feedback 审计链正确性必需（否则全新库无列）。无 scope creep。

## Issues Encountered
- append_event 已由 assessment.py 顶部既有 import（request_report 使用），Task 2 无需新增 import（plan 中「补 append_event import」为过度指定，实际无需改动）

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 05-evidence-report-contract 四计划（05-01 证据链 / 05-02 裁决与补算 / 05-03 状态机与发布 / 05-04 feedback）全部落地
- feedback.report_id FK 已指向具体版本 report 行（05-03 版本化），不悬空；REVIEW_FEEDBACK_RECEIVED / REVIEW_REPORT_PUBLISH_CONFIRMED 事件均已落库
- 06-migration-regression 可启动：feedback 表 schema_version 收口 + 全套回归

---

*Phase: 05-evidence-report-contract*
*Completed: 2026-09-05*

## Self-Check: PASSED

- 5 files verified present (test_phase5_feedback.py, db.py, api/assessment.py, api/admin/feedback.py, services/report.py)
- 3 task commits verified present: 518cf17, 1687fb3, b81aede
