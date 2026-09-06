---
phase: 03-sse
plan: 05
subsystem: api
tags: [fastapi, sqlite, state-machine, sse, prompt-injection, start-pause-resume, pitfall-12]

# Dependency graph
requires:
  - phase: 03-sse
    plan: 04
    provides: "计时区间服务（timer.py open_interval/close_open_interval）+ phase 列双轨 + SESSION_PAUSED 409 护栏"
provides:
  - "POST /sessions/{id}/start + /pause + /resume 三端点（状态机激活段收口）"
  - "get_session 派发 phase 门（Pitfall 12 修复）+ 响应 phase 字段"
  - "INJECTION_DETECTED 事件挂载（payload 白名单 {answer_state, stability}）"
  - "mock 注入词表 _INJECTION_WORDS（PROMPT_INJECTION 可离线触发）"
affects: [06-e2e, 前端-start-按钮接线（A6 [03-010]）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "三端点无 body 无 Pydantic（D-46 边界——GET/start/pause 均无 body）"
    - "start 状态转换三步同事务（UPDATE phase + open_interval + SESSION_STARTED）"
    - "pause/resume 事件对 + paused 区间 reason 区分（D-40 四源——候选人端点 reason='candidate_request' 固定）"
    - "get_session 派发 phase in (None, 'ACTIVE') 兼容口径（NULL legacy 放行 / PENDING_START 拦截）"
    - "回归适配：tolerant _start helper（assert 200|409）——重复调用幂等"

key-files:
  created: [server/test_phase3_misc.py]
  modified:
    - server/api/assessment.py
    - server/services/interview.py
    - server/test_m5_backend.py
    - server/test_p0_chain.py
    - server/test_p0_security.py
    - server/test_phase2_selection.py
    - server/test_phase2_interview.py
    - server/test_phase2_difficulty.py
    - server/test_phase2_scoring.py
    - server/test_phase3_forms.py
    - server/test_phase3_idempotency.py
    - server/test_phase3_sse.py
    - server/test_phase3_timer.py

key-decisions:
  - "start 端点不派发首题（A6 裁量「前者简单」）——首题由 get_session phase 门在 start 后自然派发"
  - "pause reason='candidate_request' 固定；技术/无障碍/管理暂停经 timer helper 写区间、专属端点运维面延期（W6/D-40）"
  - "INJECTION_DETECTED payload 白名单恰两键 {answer_state, stability} 不含输入原文（D-45/T-03-25）"
  - "get_session 派发 gate phase in (None, 'ACTIVE')——legacy/直插 NULL 行不卡死，PENDING_START 拦截（Pitfall 12）"
  - "_INJECTION_WORDS 分支置于长度判断前（与 _DECLINE_WORDS 同路径）——短注入串（如 7 字「忽略上面的指令」）也命中"

patterns-established:
  - "tolerant _start helper：assert status in (200, 409) 使 get_current_question 类 helper 在循环内可安全重复调用"
  - "pause/resume 双事件序：SESSION_PAUSE_REQUESTED（actor candidate）先于 SESSION_PAUSED（from ACTIVE to PAUSED）"

requirements-completed: [REF-2.6, REF-4.7, REF-6.4]

# Metrics
duration: 60min
completed: 2026-09-05
---

# Phase 3 Plan 5: 收口三件（start/pause/resume + INJECTION_DETECTED）Summary

**入场确认 start 端点（PENDING_START→ACTIVE + 首个 active 区间 + SESSION_STARTED）+ pause/resume 端点对（paused 区间 reason='candidate_request' + 双事件留痕）+ INJECTION_DETECTED 事件白名单挂载，Pitfall 12 派发死循环修复与 11 个回归文件 start 步骤适配。**

## Performance

- **Duration:** ~60min（跨上下文压缩的净有效执行时间，含 3 次全量回归）
- **Started:** 2026-09-05
- **Completed:** 2026-09-05T03:56:32Z
- **Tasks:** 3
- **Files modified:** 14

## Accomplishments

- POST /start：phase PENDING_START→ACTIVE 三动作同事务（UPDATE phase + open_interval active + SESSION_STARTED），幂等 409 SESSION_ALREADY_ACTIVE；无 body 无 Pydantic（D-46）
- POST /pause + /resume：paused 区间（reason='candidate_request'）+ SESSION_PAUSE_REQUESTED/SESSION_PAUSED/SESSION_RESUMED 事件链 + 409 三态护栏（SESSION_NOT_IN_PROGRESS / SESSION_ALREADY_PAUSED / SESSION_NOT_PAUSED）
- get_session 派发分支加 phase 门 `phase in (None, 'ACTIVE')`——PENDING_START 不派发不计时（Pitfall 12），legacy NULL 行兼容放行；响应加 `phase` 字段
- INJECTION_DETECTED 事件挂载（answer_state==PROMPT_INJECTION 分类驱动），payload 白名单恰两键 `{answer_state, stability}` 不含输入原文（D-45）
- mock 注入词表 `_INJECTION_WORDS`（6 词中英混合）驱动 PROMPT_INJECTION 可离线触发
- 全量回归 136 tests 绿（test_phase3_misc 10 + 11 回归文件适配后恢复派发）

## Task Commits

Each task was committed atomically:

1. **Task 1: test_phase3_misc.py 三端点 + 注入留痕断言（RED）** - `ab8f176` (test)
2. **Task 2: assessment.py 三端点 + phase 门 + INJECTION 挂载** - `2064fe4` (feat)
3. **Task 3: interview.py 注入词表 + 11 回归文件 start 适配** - `18b8274` (feat)

**Plan metadata:** （本 SUMMARY 由 orchestrator 提交 docs commit）

## Files Created/Modified

- `server/test_phase3_misc.py` - 新建：10 测试覆盖 start 状态机/幂等 409/Pitfall 12 派发/pause-resume 全环/注入白名单/数据身份静态断言/get_session phase 字段
- `server/api/assessment.py` - 三端点（start/pause/resume）+ get_session phase 门与 phase 字段 + INJECTION_DETECTED 挂载 + timer import（close_open_interval/open_interval）
- `server/services/interview.py` - `_INJECTION_WORDS` 元组 + `_mock_interview` PROMPT_INJECTION 分支（长度判断前拦截）
- `server/test_m5_backend.py` - `_start` helper + test_session_state/test_answer_flow_and_scoring 两处插入
- `server/test_p0_chain.py` - `_start` helper + `_answer_whole_session` 与 test_in_progress_report_rejected 插入
- `server/test_p0_security.py` - `_start` helper + `_answer_whole_session`/_seed_in_progress_session/test_owner_main_chain_unaffected 插入
- `server/test_phase2_selection.py` - `_start` helper + `_answer_one` 与 test_dynamic_dispatch_per_next 插入
- `server/test_phase2_interview.py` - `_start` helper + `_new_session` 插入
- `server/test_phase2_difficulty.py` - `_start` helper + `_cur_q` 插入
- `server/test_phase2_scoring.py` - `_start` helper + `_cur_q` 插入
- `server/test_phase3_forms.py` - `_start` helper + `_answer_until_form` 与 test_submit_next_when_pool_left 插入
- `server/test_phase3_idempotency.py` - `_start` helper + `_first_question`/`_answer_until_form` 插入
- `server/test_phase3_sse.py` - `_start` helper + `_first_question` 插入
- `server/test_phase3_timer.py` - `_start` helper + `_first_question` 插入 + test_session_paused_guard 直插前闭合 active 区间

## Decisions Made

- start 端点不派发首题（A6 裁量「前者简单」）——首题由 get_session phase 门在 start 返回后自然派发
- pause reason='candidate_request' 固定（候选人端点本期交付）；技术/无障碍/管理暂停经 timer.py open_interval(reason=...) 写区间、专属触发端点属运维面延期（W6/D-40 交付口径——数据面就位端点面分批）
- INJECTION_DETECTED payload 白名单恰两键 {answer_state, stability}（D-45/T-03-25：注入面证据不变成泄露面）
- get_session 派发 gate `phase in (None, 'ACTIVE')`——legacy/直插 NULL 行不卡死，PENDING_START 拦截
- `_INJECTION_WORDS` 分支置于长度判断前（DECLINED 同路径形态），短注入串也命中

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] test_session_paused_guard 直插 paused 区间撞 uq_sti_open 双 open**

- **Found during:** Task 3（回归适配——test_phase3_timer.py）
- **Issue:** 该测试经 `_first_question` 触发 `_start` 后已开一个 open active 区间，随后直插 open paused 区间违反部分唯一索引 `uq_sti_open ON (session_id) WHERE ended_at IS NULL`，抛 sqlite3.IntegrityError。
- **Fix:** 在直插 paused 区间前先 `close_open_interval(conn, sid)` 闭合 start 开的 active 区间（模拟 pause 语义：闭 active + 开 paused），测试原断言零改动。
- **Files modified:** server/test_phase3_timer.py
- **Verification:** `python -m pytest test_phase3_timer.py` 18 passed
- **Committed in:** `18b8274`（Task 3 commit）

---

**Total deviations:** 1 auto-fixed（Rule 3 blocking）
**Impact on plan:** 属计划预期内的「以实际红项为准逐文件适配」范围，无范围蔓延。

## Issues Encountered

- 回归文件全部 11 个均有红项（phase 门拦 PENDING_START 派发），按「建会话→GET current_question 之间插 POST /start」机械适配；种子直插型（legacy NULL phase / completed 直插）零适配放行，与 plan 兼容口径预期一致。
- A6（[03-010]）前端「开始测评」按钮接线延后 Phase 6、I3（[03-012]）data/app.db 存量 in_progress 会话重跑演示脚本重建——两处已裁决均在 assessment.py 注释段留痕，未做数据操作（plan 明示不属本计划 files_modified 范围）。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 状态机激活段（start/pause/resume）与注入留痕后端契约完备（SC-5 起算锚 + D-45 收口），由 test_phase3_misc.py 全链覆盖。
- Phase 6 E2E 前置待办：前端「开始测评」按钮接线（A6 [03-010]），data/app.db 存量会话重跑演示脚本（I3 [03-012]——由 orchestrator 在 Phase 3 execute/verify 完成后执行）。

---
*Phase: 03-sse*
*Completed: 2026-09-05*

## Self-Check: PASSED

- FOUND: .planning/phases/03-sse/03-05-SUMMARY.md
- FOUND: ab8f176 (Task 1 RED)
- FOUND: 2064fe4 (Task 2 assessment.py)
- FOUND: 18b8274 (Task 3 interview + regression)
