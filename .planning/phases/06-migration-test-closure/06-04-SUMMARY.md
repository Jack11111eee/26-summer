---
phase: 06-migration-test-closure
plan: 06-04
subsystem: testing
tags: [pytest, testclient, e2e, fastapi, vue, submit-v2]

# Dependency graph
requires:
  - phase: 06-migration-test-closure
    provides: server/conftest.py mock 三件套 + session 级临时 DB fixture（Wave 0 linchpin）
provides:
  - server/test_e2e_full_chain.py（候选人端全链主链 + 四场景脚本化 E2E，无 Playwright，D-73）
  - server/api/assessment.py get_session 补 position_name + messages（D-79 契约修复）
  - web 前端 submit-v2 接线 + missing_reasons 中文映射（api/index.js + FormCard.vue + Report.vue）
affects: [06-migration-test-closure]

# Tech tracking
tech-stack:
  added: []
  patterns: [脚本化 API 层 E2E（TestClient + 直接函数调用）, question_bank 直插种子绑 model_id/model_version]

key-files:
  created: [server/test_e2e_full_chain.py]
  modified: [server/api/assessment.py, web/src/api/index.js, web/src/components/FormCard.vue, web/src/views/assessment/Report.vue]

key-decisions:
  - "E2E question_bank 直插种子必须写 model_id/model_version（Phase 4 消费侧收紧 D-50，readiness/选题按双列过滤）"
  - "submit-v2 body 必须带 schema_version:'v1'（FormSubmitRequest.schema_version 必填，计划 body 规格遗漏）"
  - "missing_reasons 渲染在 Report.vue 而非 Chat.vue（计划 target 文件错误）；报告失败重试 UI 已存在"
  - "FormCard 新增 expectedRevision prop 默认 1（get_form 白名单不含 revision，前端取默认值）"

patterns-established:
  - "question_bank 直插种子写 model_id/model_version + item 绑 confirmed 模型（readiness/selection 双列过滤 D-50）"
  - "E2E 脚本化 API 层：TestClient + 直接函数调用，不跨测试模块 import helper（本文件内复制）"

requirements-completed: [REF-7.6, REQ-e2e-demo-deliverables]

# Metrics
duration: 15min
completed: 2026-09-05
---

# Phase 6 Plan 04: 候选人端全链 E2E + 前端契约修复 Summary

**候选人端完整 E2E 脚本化测试（注册→登录→建岗→session→start→逐题作答/追问→表单 submit-v2→完成→评分→报告→异议）+ 四场景（刷新恢复/断线重试/越权拒绝/超时封存）落地，并补齐 get_session 的 position_name/messages 与前端 submit-v2 契约（D-73/D-79）。**

## Performance

- **Duration:** 15 min (approx)
- **Started:** 2026-09-05T22:50:00+08:00 (approx)
- **Completed:** 2026-09-05T23:03:42+08:00
- **Tasks:** 3
- **Files modified:** 5（1 created + 4 modified）

## Accomplishments

- `server/test_e2e_full_chain.py`：5 条 `test_*`（主链 + 四场景）全部通过，全程 TestClient + 直接函数调用，不引 Playwright（D-73）
- 四场景契约全覆盖：刷新恢复 `get_session.messages` 非空 + `position_name`；断线重试同 `idempotency_key` 直返快照且消息零重复写；越权 B 读 A 会话 404 / 非管理员访问 admin 路由 403；超时封存 `seal_reason='timeout'` + `QUESTION_TIMEOUT` 事件
- `get_session` 补 `position_name`（JOIN position，缺失返回 None 不抛异常）+ `messages`（`ORDER BY sequence_no, created_at`），纯增量两键不动其余字段
- 前端 submit-v2 接线：`submitForm` 切 `POST /forms/submit-v2`（body 带 `schema_version:'v1'`）；FormCard `onSubmit` 新签名；Report.vue missing_reasons 的 score_state→中文映射

## Task Commits

Each task was committed atomically:

1. **Task 1: test_e2e_full_chain.py 全链主链 + 四场景（tdd RED）** - `2b2c054` (test)
2. **Task 2: get_session 补 position_name + messages（GREEN）** - `182a8c8` (feat)
3. **Task 3: 前端契约修复 submit-v2 + missing_reasons 中文映射** - `690db51` (feat)

**Plan metadata:** see final `docs` commit (SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `server/test_e2e_full_chain.py` - 新建：主链 + 四场景脚本化 E2E（helper 复刻 test_m5 模式，不跨测试模块 import）
- `server/api/assessment.py` - `get_session` 返回体补 `position_name` + `messages`（13 行增量）
- `web/src/api/index.js` - `submitForm` 切 submit-v2，body 带 form_instance_id/payload/expected_revision/schema_version
- `web/src/components/FormCard.vue` - `onSubmit` 新签名 + 新增 `expectedRevision` prop（默认 1）
- `web/src/views/assessment/Report.vue` - missing_reasons.reason → 中文映射（reasonLabel）

## Decisions Made

- E2E question_bank 直插种子写 `model_id`/`model_version`（bind confirmed 模型版本）—— Phase 4 消费侧收紧（readiness 三处 count/tier WHERE 与 selection `_load_candidate_rows` 均加双列谓词，D-50）后，不写版本会 409 `QUESTION_BANK_INCOMPLETE`
- submit-v2 body 带 `schema_version:'v1'`—— `FormSubmitRequest.schema_version` 为 `Field(min_length=1)` 必填，计划 body 规格漏列，漏了会 422
- missing_reasons 中文映射落在 `Report.vue`（真实渲染处）而非计划所列 `Chat.vue`；报告失败重试 UI 已在 Report.vue 49-55 存在，无需新增
- FormCard 新增 `expectedRevision` prop 默认 1—— `get_form` 白名单（form_type/title/fields）不含 revision，前端无从 schema 取，默认值对齐后端 `expected_revision=1`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 复刻的 question_bank 种子未写 model_id/model_version，5 条 E2E 全 409**

- **Found during:** Task 1（RED 阶段）
- **Issue:** 计划要求「复用 test_m5_backend.py 的 helper 模式」，但该 helper（及 test_p0_chain.py 源头）属 13 个 stale 测试文件之一（STATE.md deferred items），直插 question_bank 不写 `model_id`/`model_version`。Phase 4 消费侧收紧后（D-50），readiness 与选题均按 `model_id+model_version` 过滤，导致 5 条 E2E 全部 `409 QUESTION_BANK_INCOMPLETE: 必备能力项缺题`。
- **Fix:** `_seed_question_bank` 改签名为 `(pid, mid)`，每条 INSERT 补 `model_id=mid, model_version=1`；5 处调用点同步改传 `mid`。
- **Files modified:** server/test_e2e_full_chain.py
- **Verification:** `python -m pytest test_e2e_full_chain.py -q` → 刷新恢复场景如期 RED（缺 position_name），其余 4 条 passed
- **Committed in:** 2b2c054（Task 1 RED commit）

**2. [Rule 2 - Missing Critical Functionality] submit-v2 body 缺 schema_version 必填字段**

- **Found during:** Task 3（api/index.js submitForm 改造）
- **Issue:** 计划 body 规格只写 `{ form_instance_id, payload, expected_revision }`，但 `FormSubmitRequest.schema_version` 为 `Field(min_length=1)` 必填（无默认值），漏列会导致 422。
- **Fix:** body 补 `schema_version: 'v1'`（对齐 `forms.py: FORM_SCHEMA_VERSION = "v1"`）。
- **Files modified:** web/src/api/index.js
- **Verification:** `npm run build` 成功；后端 `submit_form_v2` 契约核对通过
- **Committed in:** 690db51（Task 3 commit）

### Plan File-Reference Discrepancies

**3. [Plan target 文件错误] missing_reasons 渲染与报告失败重试 UI 在 Report.vue，不在 Chat.vue**

- **Found during:** Task 3（read_first 核实）
- **Issue:** 计划 Task 3 第③点要求「Chat.vue 补 missing_reasons 映射 + 报告失败重试 UI」。实测：`Chat.vue` 只消费 `data.messages` 与 `session.position_name`（`load()` 172-195），不含 missing_reasons 或报告渲染；missing_reasons 渲染在 `Report.vue`（99-102 行 `{{ m.reason }}` 原始 code），报告失败重试 UI（49-55 行「重新生成」→ `bootstrap`）已存在。
- **Fix:** missing_reasons 中文映射落在 `Report.vue`（真实渲染处）；报告失败重试 UI 已存在，无需新增（不制造死代码）。
- **Files modified:** web/src/views/assessment/Report.vue（计划列 Chat.vue 未改动，符合「外科手术式改动」）
- **Verification:** `npm run build` 成功；Report.vue 模板 `{{ reasonLabel(m.reason) }}` 接线
- **Committed in:** 690db51（Task 3 commit）

---

**Total deviations:** 2 auto-fixed（1 bug + 1 missing critical）+ 1 plan file-reference discrepancy
**Impact on plan:** 均为正确性/可运行性必要修正，无范围蔓延；file-reference 修正使映射落在真实渲染处而非制造 Chat.vue 死代码。

## Issues Encountered

- E2E RED 阶段刷新恢复场景如预期先挂在 `position_name` 为 None（Task 2 缺口），Task 2 补字段后 GREEN——标准 TDD RED→GREEN 闭环。
- 全量收集 `cd server && python -m pytest . --collect-only -q` → 205 tests collected，无 fixture 错误，新增 e2e 可收集。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 候选人端完整 E2E（REF-7.6）与前端契约（D-79）已闭环，06-05（eval 隔离/安全）可在统一收集 + CI 入口上继续
- `server/conftest.py` mock 三件套 + session 临时 DB fixture 持续复用（本计划未设 env、未跨测试模块 import）

## Self-Check: PASSED

- `.planning/phases/06-migration-test-closure/06-04-SUMMARY.md` 已创建
- `server/test_e2e_full_chain.py` 存在于磁盘
- Task 提交 `2b2c054`（Task 1）、`182a8c8`（Task 2）、`690db51`（Task 3）均存在于 git 历史

---
*Phase: 06-migration-test-closure*
*Completed: 2026-09-05*
