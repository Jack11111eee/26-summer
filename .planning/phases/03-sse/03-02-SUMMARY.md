---
phase: 03-sse
plan: 02
subsystem: api
tags: [fastapi, sse, streaming, streamingresponse, pydantic]

# Dependency graph
requires:
  - phase: 03-01
    provides: form 分支（_render_form_branch / action='form' 语义），本计划将其返回值一并改造为 StreamingResponse
provides:
  - submit_answer 三处 return 统一为 StreamingResponse（text/event-stream），事件序 decision → reply×N → done
  - _sse_event / _event_stream generator（零 DB、先落库再推流）
  - AnswerRequest Pydantic（question_id/answer min_length=1 + strip validator + 3 个幂等 Optional 键）
  - 8 个回归文件的 _answer helper 统一改为流式消费 + data: 行解析 + 组回旧 JSON 同构 dict
affects: [web (sse.js 双形态 A/B 分支——本计划零改动，仅对齐其 onDecision/onReply/onDone 语义), 04-report]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "先落库再推流：decide_next_action + assistant 消息 + 选题/封存全部在首个 yield 前 commit；generator 函数体零 get_conn（Pitfall 1 SQLite threadpool worker 锁）"
    - "SSE 帧格式：`data: {json.dumps(payload, ensure_ascii=False)}\\n\\n`；mock 模式 reply 按 ceil(len/4) 分 4 块假流"
    - "Pydantic v2 field_validator 实现 WR-02 strip 语义（纯空格串 422）"

key-files:
  created:
    - server/test_phase3_sse.py
  modified:
    - server/api/assessment.py
    - server/schemas.py
    - server/test_m5_backend.py
    - server/test_p0_chain.py
    - server/test_p0_security.py
    - server/test_phase2_interview.py
    - server/test_phase2_difficulty.py
    - server/test_phase2_selection.py
    - server/test_phase2_scoring.py
    - server/test_phase3_forms.py

key-decisions:
  - "三处 return（主 finish / legacy finish / 主 next + form 分支）统一改 StreamingResponse，form 分支 decision 帧 action='form' 透传（DRAFT 池耗尽三路统一）"
  - "decision 帧携带 answer_state/evidence_sufficient 扩展键透传（D-34），一律 .get 防 MODEL_UNCERTAIN 降级 dict 缺键面"
  - "mock 4 块假流：size=max(1, ceil(len/4)) 分块，前端 onReply 逐块拼接 == 决策 reply 全文"

patterns-established:
  - "流式消费测试 helper：client.stream + iter_lines → 过滤 data: 前缀 → json.loads(ln[6:]) → 组回 action/reply/next_question_id/score_live dict，上层断言零改动"

requirements-completed: [REF-4.6, REF-4.7]

# Metrics
duration: 35min
completed: 2026-09-05
---

# Phase 3 Plan 2: SSE 化 submit_answer Summary

**submit_answer 端点改造为 text/event-stream 流式响应（decision → reply×N → done 事件序），请求体 Pydantic 化（AnswerRequest），8 个回归文件统一改为流式消费 helper——mock 模式 reply 分 4 块假流可断言**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-09-05T01:55:00Z (approx)
- **Completed:** 2026-09-05T02:30:13Z
- **Tasks:** 3
- **Files modified:** 11

## Accomplishments
- submit_answer 三处 return 统一为 StreamingResponse（`media_type="text/event-stream"` + `Cache-Control: no-cache` / `X-Accel-Buffering: no`），事件序 decision → reply×N → done
- `_event_stream` generator 零 DB 访问（先落库再推流），decide_next_action 留在 endpoint body 内（LLM 失败降级 MODEL_UNCERTAIN 不走 500 不卡死）
- AnswerRequest Pydantic：question_id/answer Field(min_length=1) + strip validator（纯空格串 422）+ 3 个幂等 Optional 键；缺字段走 FastAPI 422
- 8 个回归文件 _answer helper 统一改流式消费 + data: 行解析 + 组回旧 JSON 同构 dict，上层断言零改动
- mock 模式 reply 按 ceil(len/4) 分 4 块假流，前端 onReply 逐块拼接 == 决策 reply 全文（中文 ensure_ascii=False 原样）

## Task Commits

1. **Task 1: test_phase3_sse.py RED 测试** - `331da23` (test) — 11 个流式消费断言测试
2. **Task 2: assessment.py SSE 化 + AnswerRequest Pydantic** - `7eca5cf` (feat)
3. **Task 3: 8 个回归文件流式解析适配** - `93a4155` (test)

## Files Created/Modified
- `server/api/assessment.py` - submit_answer 三处 return 改 StreamingResponse + `_sse_event`/`_event_stream` generator + `_render_form_branch` 同改
- `server/schemas.py` - 新增 `AnswerRequest` Pydantic（field_validator strip 语义）
- `server/test_phase3_sse.py` - 11 个流式消费断言测试（新增）
- `server/test_m5_backend.py` - `_answer` helper 改流式消费
- `server/test_p0_chain.py` - `_stream_answer` helper + `_answer_whole_session` 内 answer POST 改流式
- `server/test_p0_security.py` - `_stream_answer` helper + `_answer_whole_session`/`_seed_in_progress_session` 改流式
- `server/test_phase2_interview.py` - `_answer` helper 改流式
- `server/test_phase2_difficulty.py` - `_answer` helper 改流式
- `server/test_phase2_selection.py` - `_stream_answer` helper + 内联 answer 改流式
- `server/test_phase2_scoring.py` - `_answer` helper 改流式
- `server/test_phase3_forms.py` - `_stream_answer` helper + `_answer_until_form`/内联 answer 改流式

## Decisions Made
- 三处 return 统一改 StreamingResponse（主 finish / legacy finish / 主 next + form 分支）
- decision 帧携带 answer_state/evidence_sufficient 扩展键（D-34），一律 `.get` 防缺键
- mock 4 块假流分块策略 size=max(1, ceil(len/4))

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- `test_p0_chain.py::test_in_progress_report_rejected` 在 Task 3 首轮 8 文件跑批中失败（JSON decode）：该测试内联 `client.post + r.json()["action"]` 消费 answer，被遗漏于首轮适配。修复：改 `_stream_answer`，8 文件全绿。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- SSE 化 answer 端点 + 8 回归全绿，web/ 零改动、sse.js 双形态 untouched（SC-3）
- 前端 sse.js 形态 A 分支可接管本端点；无需额外环境变量或配置

---
*Phase: 03-sse*
*Completed: 2026-09-05*
