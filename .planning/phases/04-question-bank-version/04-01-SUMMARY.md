---
phase: 04-question-bank-version
plan: 01
subsystem: database
tags: [sqlite, fastapi, pytest, question-bank, version-binding, fail-visibility, model-version]

# Dependency graph
requires:
  - phase: 03-forms-sse-idempotency-timing
    provides: question_bank_task 表（D-12 生命周期：QUEUED/RUNNING/SUCCEEDED/FAILED + error_msg），check_session_readiness 三态 409
  - phase: 02-dynamic-selection
    provides: 四层选题 _load_candidate_rows + plan_quotas 同源口径（WR-15），test_phase2_selection.py 三件套种子
provides:
  - question_bank 行真正落库 model_id/model_version/item_id/rubric_version='v1'（D-47/D-54）
  - 消费侧（readiness + selection）强制 model_id+model_version 匹配，去除 NULL 放行（D-50）
  - 生成失败可见：readiness FAILED 分支返回 error_msg[:200] + get_todos 新增 question_bank_failed 明细（REF-8.4/D-51）
affects: [05-evidence-report-contract, 06-migration-test-closeout]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "版本绑定口径统一：question_bank 行的「有效题目 = status='active' 且 model_id+model_version 匹配」在落库侧（_insert_question）与消费侧（readiness/selection）三处同源"
    - "幂等判重键升级：(model_id, model_version, std_name, category, difficulty) 取代 (position_id, std_name, category, difficulty)，模型升版后旧题库不被误判跳过"

key-files:
  created:
    - server/test_phase4_binding.py
    - server/test_phase4_fail_visible.py
  modified:
    - server/services/question_bank.py
    - server/services/readiness.py
    - server/services/question_selection.py
    - server/api/admin/positions.py
    - server/test_phase2_selection.py

key-decisions:
  - "D-47 落库绑定：_insert_question 新增 model_id/model_version/item_id 三 keyword-only 参，rubric_version 落常量 'v1'，measurement_target/evidence_requirement 留 NULL"
  - "D-50 消费侧强制双列匹配：readiness 三处 count/tier WHERE 与 selection _load_candidate_rows 均加 model_id+model_version 谓词，去 NULL 放行"
  - "D-51 失败可见：readiness FAILED 分支返回 QUESTION_BANK_INCOMPLETE + error_msg[:200]；get_todos 保留 question_bank_not_ready(int) 并新增 question_bank_failed 明细"
  - "D-48 旧题保持 active 靠过滤失效：不改旧题 status 实现升版失效"

patterns-established:
  - "单文件单进程测试纪律：test_phase4_binding.py / test_phase4_fail_visible.py 各自独立三件套（tempfile DB_PATH + LLM_PROVIDER=mock + JWT_SECRET + init_db() before import server）"
  - "先 commit 再调 LLM 模式：question_bank 逐 item commit 点保持不动"

requirements-completed: [REF-2.5, REF-3.4, REF-8.4]

# Metrics
duration: 50min
completed: 2026-09-05
---

# Phase 04 Plan 01: 题库版本绑定 + 失败可见 Summary

**题库落库绑定 confirmed 模型版本（model_id/model_version/item_id/rubric_version='v1'），消费侧强制双列匹配阻断升版旧题误用，生成失败经 readiness error_msg 与管理员待办明细可见**

## Performance

- **Duration:** 50 min
- **Started:** 2026-09-05T05:25:00Z
- **Completed:** 2026-09-05T06:15:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- generate_question_bank 落库的每一行 question_bank 现在携带 model_id/model_version/item_id/rubric_version='v1'（measurement_target/evidence_requirement 留 NULL），兑现 D-47/D-54
- 4 处 exists 判重键升级为 (model_id, model_version, std_name, category, difficulty)，模型升版（v2）后旧题库（v1）不再被误判跳过（D-49）
- 消费侧收紧：readiness 三处 count/tier WHERE 与 selection _load_candidate_rows 均强制 model_id+model_version 匹配，去除 NULL 放行；v2 题库未生成时开考被 QUESTION_BANK_INCOMPLETE 阻止（D-50/REF-3.4）
- 生成失败可见：readiness FAILED 分支返回 QUESTION_BANK_INCOMPLETE + detail 附 error_msg[:200]；get_todos 新增 question_bank_failed 明细列表（position_id/model_id/model_version/error_msg），question_bank_not_ready 保持 int（REF-8.4/D-51）

## Task Commits

Each task was committed atomically (TDD 红→绿):

1. **Task 1: 新建 test_phase4_binding.py + test_phase4_fail_visible.py（先红）** - `f40aaac` (test)
2. **Task 2: question_bank.py 落库填充 + 判重键升级** - `b28cef9` (feat)
3. **Task 3: 消费侧收紧 + 失败明细 + test_phase2_selection.py 种子绑定** - `935bce7` (feat)

**Plan metadata:** final docs commit (SUMMARY.md + STATE.md + ROADMAP.md + REQUIREMENTS.md)

## Files Created/Modified
- `server/test_phase4_binding.py` - 4 tests：落库绑定列 / v2 判重键不跳过 / readiness 阻断 v2 无题库 / selection 只取匹配版本
- `server/test_phase4_fail_visible.py` - 2 tests：readiness FAILED 带 error_msg / get_todos 返回 question_bank_failed 明细
- `server/services/question_bank.py` - _insert_question 落库 model_id/model_version/item_id/rubric_version + 4 处判重键升级 + generate_question_bank 取 model_version
- `server/services/readiness.py` - 两 count helper + tier LEFT JOIN 加双列过滤 + task 查询取 error_msg + FAILED 分支
- `server/services/question_selection.py` - _load_candidate_rows 加 model_version 并收紧为 b.model_id=? AND b.model_version=?
- `server/api/admin/positions.py` - get_todos 新增 question_bank_failed 明细
- `server/test_phase2_selection.py` - _seed_question_bank/_add 种子写 model_id+model_version 绑定

## Decisions Made
- 落库绑定列顺序照 DDL（model_id, model_version, item_id, rubric_version 紧随 scope, position_id）
- 版本过滤口径统一为「双列都要」（D-50），消费侧与落库侧同源，防 Phase 2 口径漂移（WR-15 教训）复发
- get_todos 的 question_bank_failed 不额外截断/不去重/不滤空——error_msg 入库时已 str(e)[:200] 截断，前端 Positions.vue 对未知键安全（零改动）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_required_exception_after_exhaustion 的「cm_other 排除案例」指令缺陷**
- **Found during:** Task 3（test_phase2_selection.py 种子绑定）
- **Issue:** 计划指令「cm_other 排除案例改传 model_version 为另一值保持『他人版本候选排除』语义」导致 409「必备能力项缺题：沟通能力」——Phase 4 之后 readiness 的 _covered_std_names 也按 model_id+model_version 过滤，与 selection 口径一致（WR-15），因此「cm_other」medium 题（model_id="cm_other"）不再被 readiness 计入覆盖，阻断会话创建。
- **Fix:** 重构 soft 侧种子构造：沟通能力只留 easy 题（readiness 计入覆盖，但 _pick_exception_question 只取 medium/hard → 无候选）；新增两个更高权重必备软技能项（协作能力A 0.30、协作能力B 0.28）填满 2 个 soft 必备槽位，使沟通能力（0.25）在正常计划中保持 uncovered。保留全部原断言语义（MySQL medium 例外、REQUIRED_EXCEPTION_GRANTED、PATH_UNAVAILABLE、completed）。
- **Files modified:** server/test_phase2_selection.py
- **Verification:** `python -m pytest test_phase2_selection.py -v` 9 passed
- **Committed in:** 935bce7（Task 3 commit）

**2. [Rule 3 - 计划 grep 规格不精确] question_selection.py 的验证 grep 字面量不匹配**
- **Found during:** Task 3 验收（grep 断言）
- **Issue:** 计划 `<verification>` 期望 `grep -c "model_id=? AND model_version=?" question_selection.py == 1`，但正确 SQL 使用限定列名 `b.model_id=? AND b.model_version=?`（"b." 别名前缀打断连续字面匹配 → 计数 0）。readiness 的 grep 计数 3 满足，但经两 count helper + task 查询行达成，tier JOIN 使用 `qb.` 前缀同样不匹配字面量。
- **Fix:** 无代码改动——这是计划 grep 规格的字面量不精确，非功能缺陷。功能正确性（所有消费侧 WHERE 均含 model_id+model_version、无 IS NULL 放行）由 4 个测试文件的绿态证明。
- **Files modified:** 无
- **Verification:** test_phase4_binding.py / test_phase4_fail_visible.py / test_phase2_selection.py 全绿
- **Committed in:** 935bce7（Task 3 commit）

---

**Total deviations:** 2 auto-fixed（1 计划缺陷修复、1 grep 规格不精确）
**Impact on plan:** 缺陷修复必要（保证回归测试绿态与 WR-15 口径一致），grep 不精确无范围蔓延。无 scope creep。

## Issues Encountered
- 无。4 个测试文件均需单文件单进程运行（DB_PATH import 时读取冲突），最终串行验证全部绿态。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 04-01 完成：题库版本绑定 + 失败可见落地，为 04-02（orphan 路由 + 模型编辑校验）提供「版本绑定口径」与「FAILED 明细」基座
- 无阻断项。Phase 4 剩余 1 plan（04-02）。

---
*Phase: 04-question-bank-version*
*Completed: 2026-09-05*

## Self-Check: PASSED

- SUMMARY.md exists at `.planning/phases/04-question-bank-version/04-01-SUMMARY.md`
- Task commits verified: `f40aaac` (test), `b28cef9` (feat), `935bce7` (feat)
- Plan metadata commit present (SUMMARY.md + STATE.md + ROADMAP.md + REQUIREMENTS.md)
