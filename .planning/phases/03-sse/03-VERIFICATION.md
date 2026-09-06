---
phase: 03-sse
verified: 2026-09-05T04:07:50Z
status: passed
score: 46/46  # 5 roadmap success criteria + 41 plan truths
overrides_applied: 0
overrides: []
gaps: []
deferred:
  - truth: "A6 前端「开始测评」按钮接线（POST /sessions/{id}/start 由前端调用）"
    addressed_in: "Phase 6"
    evidence: "ROADMAP Phase 6 SC-4『候选人端完整 E2E（含刷新恢复/断线重试/越权/超时）』；DECISIONS [03-010] 用户批准：后端 start 契约测试全绿即达 Phase 3 边界，web 零改动约束下前端接线延后 Phase 6"
  - truth: "技术/无障碍/管理三种暂停来源的专属触发端点"
    addressed_in: "运维面（无里程碑 phase）"
    evidence: "03-05-PLAN truth 3 明确『候选人端点本期交付 reason=candidate_request；技术/无障碍/管理暂停触发路径经 timer helper open_interval(reason=...) 写区间，专属端点延期至运维面』——数据层 reason 四源能力已就位，仅端点面分批"
---

# Phase 3: 表单/SSE/幂等/计时 Verification Report

**Phase Goal:** 资格核验表单成为真实可用链路（schema 版本化实例 + gate 结构化结果），对话话术真实流式推送，重复请求幂等返回首次结果，全场/单题计时按服务端权威区间运转
**Verified:** 2026-09-05T04:07:50Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths — Roadmap Success Criteria (契约)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 表单链：form_instance 生命周期实体（不可变 schema 快照、GET 只读白名单不暴露阈值）、提交六维校验、重复提交返回第一次结果 | ✓ VERIFIED | `services/forms.py` render_form_instance/whitelist_form/validate_and_submit；`api/assessment.py:887` GET /forms/{id} + `:905` submit-v2；`db.py:258` form_instance 表（PRIMARY KEY(form_instance_id,revision)）；16 tests green |
| 2 | gate 由代码计算并输出独立结构化结果（gate_result/gate_status/gate_reason），判定不再从自由 payload 猜测；人工覆盖字段就位且需二次确认 | ✓ VERIFIED | `services/forms.py:173-186` gate 行 INSERT（question_id/score_state NULL 五列落值）；`api/admin/forms.py` GateOverrideBody.override_reason min_length=1 强制；`aggregation.py:48` _gate_row 新链优先 |
| 3 | 答题话术真实 SSE 逐 token 推送（决策先落库再展示；finish 仅代码触发）；sse.js 双形态自适应走流式；非法 LLM 输出进失败/人工状态不卡死 | ✓ VERIFIED | `api/assessment.py:313-347` _sse_event/_event_stream（decision→reply×N→done）；`interview.py:248-262` RuntimeError/ValidationError → MODEL_UNCERTAIN 降级；`web/src/utils/sse.js` 形态 A/B（web 零改动）；11 tests green |
| 4 | 携 idempotency_key 的重复请求返回第一次持久化结果，不重复写消息/计 followup/扣题量；并发双写由事务 + 乐观版本号防护 | ✓ VERIFIED | `services/idempotency.py` 两阶段 PENDING/COMMITTED + request_hash 比对；`api/assessment.py:411-419` 前置 + `:757` finalize；`db.py:358` idempotency_record 三键 UNIQUE；`assessment.py:530-543` revision 乐观锁；11 tests green |
| 5 | 计时服务端权威：全场 40min / 单题 20min / 暂停不计入写事件 / 单题超时封存续题 / 全场超时收尾 / 6h ABANDONED | ✓ VERIFIED | `config.py:54-56` 40/20/6；`services/timer.py` merge_spans 纯函数 + seal_if_question_timed_out + maybe_abandon_session；`api/assessment.py` start/pause/resume + 409 SESSION_PAUSED；18+10 tests green |

**Score:** 5/5 roadmap success criteria verified

### Observable Truths — Plan must_haves (41)

All 41 plan-level truths verified against code + green tests. Grouped by plan (evidence = authoritative file:line + test file):

| Plan | Truths | Verdict | Key evidence |
|------|--------|---------|--------------|
| 03-01 表单链 | 9 | ✓ 9/9 | `forms.py` 幂等 render(:63)/六维(:114)/gate 行(:168)/revise(:194)；`assessment.py:365` _render_form_branch + `:905` submit-v2 finish/next 触发；`scoring.py:247` DELETE WHERE gate_result IS NULL；`aggregation.py:48` 双源；test_phase3_forms 16 pass |
| 03-02 SSE | 9 | ✓ 9/9 | `assessment.py:390` submit_answer→StreamingResponse；`_event_stream` 零 DB generator(:319)；`schemas.py:100` AnswerRequest strip validator；`interview.py` MODEL_UNCERTAIN 降级；test_phase3_sse 11 pass（content-type/事件序/reply 拼接/abort 落库断言） |
| 03-03 幂等 | 7 | ✓ 7/7 | `idempotency.py` request_hash_of(:25)/check_idempotency(:36 两阶段)/finalize(:85)；`db.py:358` 三键 + `:176` revision 列；`assessment.py:530` UPDATE revision=revision+1；test_phase3_idempotency 11 pass |
| 03-04 计时/上下文 | 10 | ✓ 10/10 | `timer.py` merge_spans(:30)/overlap_seconds(:48)/seal(:128)/maybe_abandon(:163)；`config.py` 40/20/6/8000；`interview.py:77` _truncate_history；`db.py:201` session_time_intervals + uq_sti_open；`assessment.py` 闭旧开新/超时/全场收尾/6h；test_phase3_timer 18 pass |
| 03-05 收口 | 6 | ✓ 6/6 | `assessment.py:208` start / `:242` pause / `:279` resume 三端点 + `:598` INJECTION_DETECTED + `:157` phase=='ACTIVE' 派发门；`interview.py:29` _INJECTION_WORDS + `:135` 分类；test_phase3_misc 10 pass |

**Plan truth score:** 41/41 verified

### Deferred Items

Items not yet met but explicitly addressed in later phases or documented plan scope boundaries (informational — do not affect status):

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | A6 前端「开始测评」按钮接线 | Phase 6 | ROADMAP Phase 6 SC-4 E2E；DECISIONS [03-010] 用户批准 |
| 2 | 技术/无障碍/管理暂停专属端点 | 运维面 | 03-05-PLAN truth 3 计划内范围裁量；数据层 reason 能力已就位 |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `server/db.py` | form_instance + gate 五列/覆盖四列 + idempotency_record + session_time_intervals + revision + message 三列 + session 六列 | ✓ VERIFIED | L1 存在 700 行；L2 实质性（9 迁移函数）；L3 由 init_db 串行调用 |
| `server/services/forms.py` | render_form_instance + 六维 validate + gate 判定 | ✓ VERIFIED | L1/L2/L3 全过；assessment.py 导入 render_form_instance/validate_and_submit/_all_gate_items_collected |
| `server/services/idempotency.py` | check_idempotency 两阶段 + request_hash_of + finalize | ✓ VERIFIED | assessment.py:21 导入并在 submit_answer/submit-v2 调用 |
| `server/services/timer.py` | interval 闭开 + merge 纯函数 + seal + abandon | ✓ VERIFIED | assessment.py:29-37 导入；start/pause/resume/answer 四处调用 |
| `server/api/assessment.py` | 表单/SSE/幂等/计时/三端点全挂载 | ✓ VERIFIED | L1 1122 行；L2 无 stub；L3 main.py:82 include_router |
| `server/api/admin/forms.py` | gate 人工覆盖（require_admin + override_reason 强制 + rowcount 404） | ✓ VERIFIED | main.py:42 注册；test_phase3_forms 覆盖 |
| `server/services/aggregation.py` | _gate_check 双源读 | ✓ VERIFIED | :48 _gate_row 新链优先 → :136 回退 _gate_check |
| `server/services/scoring.py` | score_session DELETE 保留 gate 行 | ✓ VERIFIED | :247 `WHERE gate_result IS NULL` |
| `server/services/interview.py` | _truncate_history + _INJECTION_WORDS | ✓ VERIFIED | :77 纯函数；:29 词表；:135 注入分类 |
| `server/config.py` | 40/20/6/8000 常量 | ✓ VERIFIED | :54-59 |
| `server/schemas.py` | AnswerRequest + FormSubmitRequest Pydantic | ✓ VERIFIED | :100/:118 |
| `server/test_phase3_forms.py` | 表单全链断言 | ✓ VERIFIED | 16 tests pass |
| `server/test_phase3_sse.py` | 流式消费断言 | ✓ VERIFIED | 11 tests pass；client.stream 4 处 |
| `server/test_phase3_idempotency.py` | 三键/revision/并发断言 | ✓ VERIFIED | 11 tests pass |
| `server/test_phase3_timer.py` | 区间/merge/超时/6h 断言 | ✓ VERIFIED | 18 tests pass |
| `server/test_phase3_misc.py` | start/pause/resume/injection 断言 | ✓ VERIFIED | 10 tests pass |

**Artifacts:** 16 unique files, all VERIFIED at L1/L2/L3 (exists + substantive + wired). No MISSING, no STUB, no ORPHANED.

### Key Link Verification

| From | To | Via | Status |
| ---- | --- | --- | ------- |
| assessment.py 池耗尽分支 | forms.render_form_instance | gate 未采集判定后同事务调用 | ✓ WIRED (:371) |
| assessment.py submit-v2 | 主链 finish 段 | _all_gate_items_collected + select_next_question None → SESSION_COMPLETED | ✓ WIRED (:948-961) |
| assessment.py submit-v2 | forms 校验+gate | GATE_EVALUATED 事件 | ✓ WIRED (forms.py:183) |
| scoring.score_session DELETE | gate 行 | WHERE gate_result IS NULL | ✓ WIRED (:247) |
| aggregation._gate_check | gate 行/payload 双源 | _gate_row 优先 + _load_form_payload 兜底 | ✓ WIRED (:48/:136) |
| submit_answer 尾 commit | StreamingResponse(_event_stream) | generator 只消费局部变量 | ✓ WIRED (:761) |
| _event_stream | sse.js 双形态 | data: {json}\n\n + type 三分发 | ✓ WIRED (:316) |
| AnswerRequest | FastAPI 422 | strip validator | ✓ WIRED (schemas.py:107) |
| submit_answer 前置 | check_idempotency | 带 key 入口先查 | ✓ WIRED (:412) |
| submit_answer 尾段 | finalize_idempotency | COMMITTED + 快照 | ✓ WIRED (:758) |
| answer 封存 UPDATE | revision 乐观锁 | UPDATE WHERE revision=? | ✓ WIRED (:532) |
| submit_answer 前区 | timer | maybe_abandon/SESSION_PAUSED/seal 时序 | ✓ WIRED (:407/:428/:449) |
| pause/answer 路径 | session_time_intervals | uq_sti_open 部分唯一索引 | ✓ WIRED (db.py:209) |
| _build_user_prompt | _truncate_history | history 加载后、prompt 前 | ✓ WIRED (interview.py:236) |
| 消息 INSERT | message 三新列 | refined/client_request_id/sequence_no | ✓ WIRED (assessment.py:551-557) |
| POST start | open_interval(active) | 第一个 active 区间同事务 | ✓ WIRED (:234) |
| OBSERVATION_CLASSIFIED 相邻 | append_event INJECTION_DETECTED | answer_state==PROMPT_INJECTION | ✓ WIRED (:598) |
| get_session 派发 | phase 列 | phase=='ACTIVE' 条件 | ✓ WIRED (:157) |

**Key links:** 18/18 WIRED. No broken or partial links.

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| submit_answer SSE | decision | decide_next_action (LLM/mock → Pydantic 校验 → 裁决层) | ✓ real | ✓ FLOWING |
| form render | fi (form_instance) | render_form_instance → _gate_items 动态展开 | ✓ real | ✓ FLOWING |
| gate 判定 | gate_results | _gate_check (years/qualification 真值) | ✓ real | ✓ FLOWING |
| idempotency replay | response_snapshot | finalize 时 decision dict 白名单 | ✓ real | ✓ FLOWING |
| timer 判定 | active/paused spans | session_time_intervals 表读 | ✓ real | ✓ FLOWING |

No HOLLOW / DISCONNECTED / STATIC data paths found.

### Behavioral Spot-Checks

Per-file single-process test discipline (env DB_PATH/LLM_PROVIDER=mock/JWT_SECRET set per test file before import):

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 表单全链（render→GET→submit→gate→revision→admin 覆盖→finish 触发） | `python -m pytest test_phase3_forms.py -q` | 16 passed | ✓ PASS |
| SSE 流式（content-type/事件序/reply 拼接/abort 落库） | `python -m pytest test_phase3_sse.py -q` | 11 passed | ✓ PASS |
| 幂等/并发（三键回放/revision 冲突/PENDING/hash 复用） | `python -m pytest test_phase3_idempotency.py -q` | 11 passed | ✓ PASS |
| 计时（merge 纯函数/超时三路/6h ABANDONED/暂停 409） | `python -m pytest test_phase3_timer.py -q` | 18 passed | ✓ PASS |
| 收口（start/pause/resume 状态机/injection 白名单） | `python -m pytest test_phase3_misc.py -q` | 10 passed | ✓ PASS |
| 回归（m5/p0_chain/p0_security/phase2 四组 + migration/weights） | 9 文件各自 `python -m pytest` | 7+11+10+13+13+9+7+8+5=83 passed | ✓ PASS |
| 脚本式回归 | `python test_m6_backend.py` / `python test_question_bank.py` / `python -m pytest test_m7_backend.py` | 43 / 25 / 5 passed | ✓ PASS |

**Total: 222 tests green across 16 test files** (66 phase-3 + 83 pytest 回归 + 73 脚本式). Matches SUMMARY claim exactly.

Per-file isolation notes (pre-existing, NOT phase-3 regressions — logged in `deferred-items.md`): test_phase2_migration full-suite IndexError and test_question_bank init_db gap are test-harness issues; both pass under the prescribed per-file/script discipline.

### Requirements Coverage

Phase 3 REF set: REF-2.4, REF-2.6, REF-2.8, REF-3.3, REF-4.6, REF-4.7, REF-4.8, REF-4.9, REF-4.10, REF-4.12, REF-6.4 (11 items).

| Requirement | Plan | Description | Status | Evidence |
| ----------- | ---- | ----------- | ------ | -------- |
| REF-2.4 | 03-01 | form_instance 新表（schema 快照/生命周期） | ✓ SATISFIED | db.py:258 + forms.py |
| REF-2.6 | 03-04/05 | assessment_session phase/计时区间/abandoned/状态机 | ✓ SATISFIED | db.py:114-123 + timer.py + start/pause/resume |
| REF-2.8 | 03-04 | assessment_message 分列三列 | ✓ SATISFIED | db.py:192-195 + assessment.py:551 |
| REF-3.3 | 03-01 | experience/qualification 走表单 | ✓ SATISFIED | forms.py:77-83 动态展开 + _gate_items |
| REF-4.6 | 03-02 | 真实 SSE（决策先落库、话术逐 token） | ✓ SATISFIED | assessment.py:_event_stream |
| REF-4.7 | 03-01/02/05 | Pydantic 请求/输出 schema | ✓ SATISFIED | schemas.py AnswerRequest/FormSubmitRequest/GateOverrideBody |
| REF-4.8 | 03-04 | 计时区间 40/20/6h/暂停写事件 | ✓ SATISFIED | config.py + timer.py |
| REF-4.9 | 03-03 | 幂等三键 + 乐观锁 | ✓ SATISFIED | idempotency.py + db.py |
| REF-4.10 | 03-01 | 表单链（render/GET 白名单/gate 结构化/覆盖二次确认） | ✓ SATISFIED | forms.py + admin/forms.py |
| REF-4.12 | 03-04 | 上下文三层（滑窗/导航摘要/refine 分列） | ✓ SATISFIED | interview.py:_truncate_history + message 分列 |
| REF-6.4 | 03-05 | Prompt injection + INJECTION_DETECTED 留痕 | ✓ SATISFIED | assessment.py:598 + interview.py:_INJECTION_WORDS |

**11/11 REFs satisfied.** No orphaned requirements (REQUIREMENTS.md maps exactly these 11 REFs to Phase 3; no unclaimed Phase-3 REFs).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | - | - | - | - |

Scan of all phase-3 modified files (services/forms.py, idempotency.py, timer.py, interview.py, aggregation.py, scoring.py, api/assessment.py, api/admin/forms.py, config.py, schemas.py, db.py): zero TBD/FIXME/XXX/TODO markers, zero placeholder stubs, zero empty `return null/{}/[]` stubs (the two grep hits — `_FIELD_WHITELIST_KEYS`'s `"placeholder"` field key and `merge_spans`'s `return []` empty-input guard — are both legitimate, non-stub code). No debt markers.

### Human Verification Required

N/A — Phase 3 is a backend/service-layer infrastructure phase with no user-facing UI changes (`web/` intentionally zero-changed: `git diff 7e5f89f..808e7cd -- web/` = 0 files). All observable truths are verified at the code + contract-test level. Visual appearance / user-flow / real-time behavior checks apply only to UI phases.

### Gaps Summary

No gaps. Phase goal fully achieved:

- Form chain is a real, usable link (immutable schema snapshot + structured gate result + six-dim validation + finish/next terminal trigger).
- SSE streaming is real (decision→reply×N→done, commit-before-stream, generator zero-DB).
- Idempotency returns first persisted result (3-key + request_hash + optimistic revision lock).
- Server-authoritative timing runs end-to-end (40/20min, pause with events, 6h ABANDONED).
- All 222 tests green under the documented per-file discipline; zero debt markers; zero stub/anti-patterns.

Two informational deferred items (frontend start wiring → Phase 6; non-candidate pause endpoints → operations surface) are documented plan scope boundaries, not execution gaps — they do not block the phase goal.

---

_Verified: 2026-09-05T04:07:50Z_
_Verifier: Claude (gsd-verifier)_
