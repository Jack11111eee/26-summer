---
phase: 03-sse
plan: 04
subsystem: api
tags: [sqlite, timer, interval, timeout, context-window, sse, phase-state-machine]

# Dependency graph
requires:
  - phase: 03-sse
    plan: 03
    provides: submit_answer 幂等前置 + 乐观锁 + AnswerRequest（idempotency_key/expected_revision/client_attempt_id）——本计划 A4 时序在其后插点
  - phase: 03-sse
    plan: 02
    provides: 决策链/封存链（answered/refused）与 SSE 化——单题超时封存复用封存链第四路 timeout
  - phase: 03-sse
    plan: 01
    provides: form_instance/submit-v2 + gate 行——超时后 finish 路径先查 gate 一致性
provides:
  - session_time_intervals 表（active|paused + reason + started_at/ended_at）+ uq_sti_open 部分唯一索引（session_id WHERE ended_at IS NULL）+ idx_sti_session
  - server/services/timer.py（merge_spans/overlap_seconds 纯函数 + close/open/advance/paused_overlap/session_active/seal_if_question_timed_out/maybe_abandon/touch_last_activity）
  - assessment_session 6 新列（phase/active_elapsed_seconds/last_activity_at/abandoned_at/policy_version/session_time_intervals_json）+ 旧行 phase 回填 PENDING_START
  - assessment_message 3 分列（refined_content/client_request_id/sequence_no）
  - interview.py _truncate_history 滑窗截断（MAX_CONTEXT_TOKENS=8000）
  - 单题超时第四路封存 + 全场超时收尾 + 6h ABANDONED 惰性 + 暂停 409 + estimated_duration_minutes 派生
affects:
  - 03-05（pause/resume 端点消费 SESSION_PAUSED 护栏 + start 端点 PENDING_START→ACTIVE 开首区间）
  - Phase 6（active_elapsed_seconds/policy_version/session_time_intervals_json 列生产——SSOT 完整 schema 预留）

# Tech tracking
tech-stack:
  added: []  # 仅 stdlib sqlite3 + datetime
  patterns:
    - Python merge 重叠区间（merge_spans/overlap_seconds——实验 5 反例 SQL SUM 跨行双计）
    - 部分唯一索引乐观环（open_interval IntegrityError → close 后重试一次）
    - 6h 惰性 ABANDONED（无后台线程 D-005——判定挂 answer 路径 load_owned_session 相邻）
    - 全场超时串行链复用（GLOBAL_TIMEOUT 独立小事务先落 → _generate_report_task → SESSION_COMPLETED）
    - 滑窗截断（reversed 累积 + len//2 近似 token，保尾部；mock 全量由调用方决定）

key-files:
  created:
    - server/services/timer.py
    - server/test_phase3_timer.py
  modified:
    - server/db.py
    - server/config.py
    - server/services/interview.py
    - server/api/assessment.py
    - server/test_m5_backend.py

key-decisions:
  - "全场超时事件序 = GLOBAL_TIMEOUT < ENTERED_SCORING < COMPLETED（以 Task 1 测试断言为权威——interfaces 段 COMPLETED-before-report 措辞与测试三行比较冲突，执行按测试序：_generate_report_task 同步调后落 SESSION_COMPLETED）"
  - "maybe_abandon_session MUTATE s['status']='abandoned' 使调用方现有 409 护栏自然接住；write-then-raise 前先 conn.commit() 持久化 abandoned"
  - "estimated_duration_minutes 由 config.SESSION_TOTAL_MINUTES 派生（IN-06 魔数 20 退役，[03-IN06]）"
  - "单题超时 decision 六键全集（action/reason/reply/score_live/answer_state/evidence_sufficient 写全不靠 .get——W5）"

patterns-established:
  - "计时区间闭旧开新：每次 answer/form 写操作前 advance_interval('active')（close→open 主事务内）"
  - "三超时路径：单题（activated_at 时间旅行）/ 全场（Σactive）/ 6h（last_activity_at）——均服务端权威时钟 now_iso()"
  - "分列落值：用户消息 refined_content=content 同值 + client_request_id=body 键 + sequence_no=COALESCE(MAX)+1"

requirements-completed: [REF-2.6, REF-2.8, REF-4.8, REF-4.12]

# Metrics
duration: ~45min
completed: 2026-09-05
---

# Phase 03 Plan 04: 计时区间与上下文三层侧带 Summary

**session_time_intervals 表 + Python merge 重叠区间 + phase 状态机双轨 + 三超时路径（单题/全场/6h）+ 消息分列三列 + _truncate_history 滑窗（MAX_CONTEXT_TOKENS=8000）**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-09-05
- **Completed:** 2026-09-05
- **Tasks:** 5（Task 5 为已裁决 verification-only——无代码变更）
- **Files modified:** 7 source + 03-DECISIONS.md

## Accomplishments
- session_time_intervals 表 + uq_sti_open 部分唯一索引（sqlite_master 双证 + WHERE ended_at IS NULL 子句断言）+ idx_sti_session；_DDL 与 _migrate_session_phase3 双轨同语句
- assessment_session 6 计时列（phase 状态机双轨 + last_activity_at + abandoned_at + active_elapsed_seconds/policy_version/session_time_intervals_json 预留）+ 旧行 phase 回填 PENDING_START；status CHECK 零触碰（Anti-pattern 4）
- assessment_message 3 分列（refined_content/client_request_id/sequence_no）分列落值
- timer.py 双形态服务：纯函数区（merge_spans/overlap_seconds 不持 conn）+ 接 conn 区（零 commit——D-06 契约）
- 三超时路径：单题超时（seal_reason='timeout' + QUESTION_SEALED/QUESTION_TIMEOUT 两事件 + 续题）→ 全场超时（GLOBAL_TIMEOUT→SCORING→报告链→SESSION_COMPLETED）→ 6h ABANDONED（惰性 + 不删证据）
- 暂停 409 SESSION_PAUSED 护栏 + last_activity_at 每写刷新
- _truncate_history 滑窗截断（保尾部 + mock 全量分支）+ config.MAX_CONTEXT_TOKENS=8000（[03-007]）
- estimated_duration_minutes 由 SESSION_TOTAL_MINUTES 派生（IN-06 魔数 20 退役，[03-IN06]）

## Task Commits

Each task was committed atomically:

1. **Task 1: test_phase3_timer.py 计时全断言（先红）** - `3533781` (test)
2. **Task 2: db.py 迁移 + timer.py 服务 + config 常量 + interview.py 截断** - `14dd51f` (feat)
3. **Task 3: assessment.py 五挂载点 + 全场超时收尾 + create_session 修正** - `3612107` (feat)
4. **Task 4: 回归适配（m5 estimated_duration）+ IN-06 处置登记 + MAX_CONTEXT_TOKENS 确认** - `5d2fd27` (test)
5. **Task 5: MAX_CONTEXT_TOKENS=8000 确认（非 blocking）** - 无代码变更（[03-007] 已裁决）
- **纯度收尾** - `eae695e` (refactor)：_truncate_history docstring 去 provider 字面（纯函数 grep 零命中）

**Plan metadata:** 本 summary 提交（docs: complete 03-04 plan）

## Files Created/Modified
- `server/db.py` - session_time_intervals 表 + uq_sti_open 部分唯一索引 + idx_sti_session；assessment_session 6 列 + assessment_message 3 列 + _migrate_session_phase3（PRAGMA 嗅探 + phase 回填）
- `server/services/timer.py` - 双形态计时服务（纯函数 merge/overlap + 接 conn 区闭开/三超时/6h/touch）
- `server/config.py` - SESSION_TOTAL_MINUTES=40 / QUESTION_TIMEOUT_MINUTES=20 / ABANDON_HOURS=6 / MAX_CONTEXT_TOKENS=8000
- `server/services/interview.py` - _truncate_history 纯函数 + decide_next_action 截断接入（mock 全量）
- `server/api/assessment.py` - 6h 惰性 + 暂停 409 + 单题/全场超时 + advance_interval/touch（followup/next/submit-v2）+ 消息分列 + create_session phase/estimated
- `server/test_phase3_timer.py` - 18 条计时/区间/截断/分列断言
- `server/test_m5_backend.py` - estimated_duration_minutes == config.SESSION_TOTAL_MINUTES（A5）
- `.planning/phases/03-sse/03-DECISIONS.md` - [03-IN06] IN-06 处置登记

## Decisions Made
- 全场超时事件序以测试三行断言（GLOBAL_TIMEOUT < ENTERED_SCORING < COMPLETED）为权威，interfaces 段「COMPLETED-before-report」措辞与之冲突，执行按测试序（_generate_report_task 同步调后落 SESSION_COMPLETED）
- maybe_abandon_session 变异 s['status'] 使现有 409 护栏自然接住 abandoned；write-then-raise 前先 commit 持久化
- 单题/全场超时 decision dict 均写全六键（W5 契约），不依赖 .get 容错
- estimated_duration_minutes 退役魔数 20，改 config.SESSION_TOTAL_MINUTES 派生

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_phase_column_defaults 直插 FK 违反（假红）**
- **Found during:** Task 3（全量跑测试）
- **Issue:** 测试直插 assessment_session 行用 `user_id='u_x'`，但 get_conn() 开 PRAGMA foreign_keys=ON，无 user 父行必 FK 违反（IntegrityError 假红——W4 同源）
- **Fix:** 直插前先落合法 user 父行（timer_phase_old）
- **Files modified:** `server/test_phase3_timer.py`
- **Verification:** test_phase_column_defaults 绿；18 条全绿
- **Committed in:** `3612107`（Task 3 提交）

**2. [Rule 1 - Bug] _truncate_history docstring 含 LLM_PROVIDER 字面（grep 零命中违反）**
- **Found during:** Task 2 验收 grep（_truncate_history 纯函数段零 provider 命中）
- **Issue:** docstring 注释「纯函数不看 LLM_PROVIDER」含 LLM_PROVIDER 字面，grep 命中 1（非代码引用，但验收要求零命中）
- **Fix:** 改写为「纯函数不读 provider 配置」，去除字面
- **Files modified:** `server/services/interview.py`
- **Verification:** grep 本函数段 LLM_PROVIDER 命中 0
- **Committed in:** `eae695e`（收尾 refactor）

---

**Total deviations:** 2 auto-fixed（Rule 1 - bug）
**Impact on plan:** 均为测试/注释级正确性收口，无范围蔓延。行为语义与计划一致。

## Issues Encountered
- 测试文件为「单文件单进程」设计（各文件 import 时设临时 DB_PATH，config 仅 import 时读一次）——按计划 verify 用 `&&` 逐文件执行验证（11 文件 126 断言全绿）。
- test_p0_chain.py 零改动（计划 Task 4 预期「主绿零改动」命中——advance_interval/phase 列不参与主链断言，GLOBAL_TIMEOUT 不触发该路径）。

## Threat Surface
- 无新网络端点/认证路径。新增 session_time_intervals 表为内部状态表（服务端权威写入，客户端只读展示——§15）。threat_model 七项 mitigate 全部落实：T-03-18（now_iso 服务端时钟）、T-03-19（reason 不进评分 prompt）、T-03-20（部分唯一索引）、T-03-21（last_activity 每写刷新）、T-03-22（Python merge）、T-03-23（GLOBAL_TIMEOUT 先落）、T-03-24（截断保尾部）。

## Known Stubs
- assessment_session 的 active_elapsed_seconds / policy_version / session_time_intervals_json 三列为 SSOT §12.1 schema 完整预留，本计划不生产（active_elapsed_seconds 由 03-05 pause/resume 端点落值；policy_version 随策略版本化落值；session_time_intervals_json 为快照冗余）。phase='ACTIVE' 迁移未在本计划触发（start 端点归 03-05）——均为计划明确的边界，非功能性 stub。

## Next Phase Readiness
- 计时区间/三超时/分列/滑窗闭合，ready for 03-05（pause/resume 端点 + start 端点 PENDING_START→ACTIVE 开首区间 + SESSION_PAUSED 消费）
- 无阻塞项

---
*Phase: 03-sse*
*Completed: 2026-09-05*

## Self-Check: PASSED

- FOUND: server/services/timer.py
- FOUND: server/test_phase3_timer.py
- FOUND: server/db.py
- FOUND: server/api/assessment.py
- FOUND: .planning/phases/03-sse/03-04-SUMMARY.md
- FOUND commits: 3533781 (test), 14dd51f (feat), 3612107 (feat), 5d2fd27 (test), eae695e (refactor)
