---
phase: 05-evidence-report-contract
verified: 2026-09-05T11:53:39Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 4/5
  gaps_closed:
    - "缺失 item 按观察加权比例 r 补算并标 IMPUTED（特殊视觉标记 + 覆盖率展示）——Report.vue 已渲染「补算」amber 徽标 + 覆盖率摘要 + 雷达轴「（补算）」后缀；itemReason 改 item_id 精确匹配；report.py 雷达 indicators 补 imputed 标志"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "打开一份含补算 item 的候选人报告，目验逐项明细中 imputed 项显示「补算 · 加权估算」amber 徽标、SECTION 3 下覆盖率摘要（观察覆盖率 % / 真实观察 / 可测量 / 补算数 / 缺失原因逐条）、雷达图 imputed 轴带「（补算）」后缀"
    expected: "IMPUTED 项与真实观察项视觉可区分；覆盖率数字与后端 coverage 字段一致；雷达轴后缀可见"
    why_human: "无前端单测基建，视觉呈现与 UX 布局无法 grep 判定；需人工点验"
  - test: "测试中心对 READY/PROVISIONAL 报告点击「发布报告」，确认二次确认后状态变 PUBLISHED 且不可再发；HUMAN_REVIEW_REQUIRED 未 CONFIRMED 时被 409 拦截"
    expected: "发布成功提示；未 CONFIRMED 被 409 拦截并提示；权限 403 拦截候选人"
    why_human: "端到端交互流与权限 UX 需人工点验（后端 403/409 已由 test_publish_flow 覆盖）"
---

# Phase 5: 证据链与报告契约 (evidence-report-contract) Verification Report

**Phase Goal:** 全链审计链通过 trace_link 闭合、证据引用结构化可定位；报告发布走完整状态机（人工明确点击发布 + 七项一致性校验 + 版本化），反馈异议带完整审计字段
**Verified:** 2026-09-05T11:53:39Z
**Status:** human_needed
**Re-verification:** Yes — gap-closure pass (previous: gaps_found 4/5)

## Goal Achievement

### Observable Truths (Success Criteria)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | 每个证据引用结构化可定位（source_message_id / start_offset / end_offset Unicode code point / quote_hash）；终局评分回捞原文；trace_link 闭合 report→session→model/version→question→message→score→trace，旧 ref_id 关联导入 | ✓ VERIFIED | `scoring.py:_locate_span` 返回完整 span dict（code-point 语义）；`_fetch_answer_text` 经 raw_hash 回捞原文；`score_session`/`generate_report` 运行时写 trace_link；`db._migrate_trace_link` 按 call_type→实体表 probe 导入旧 ref_id。`test_audit_chain_closure`/`test_ref_id_import_migration` 绿（evidence 6 passed）。 |
| 2   | item 最终等级由统一测量记录裁决（adjudicate 不按题数均分、冲突取低留人工标记）；缺失 item 按 r 补算并标 IMPUTED（特殊视觉标记 + 覆盖率展示）；O=∅ → NO_VALID_OBSERVATION/HUMAN_REVIEW_REQUIRED；required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | ✓ VERIFIED | 后端 `adjudicate`/`_impute_r`/`_observed_items` 完整；`item_scores[]` 携带 `imputed=True` + `coverage{observed_count/imputed_count/total_measureable/coverage_ratio/missing_reasons}` 透传进 `report_data.coverage`（report.py:223）。**前端 gap 已闭合**：`Report.vue` L118 渲染「补算 · 加权估算」amber 徽标（`v-else-if` 与 gate/no_data 互斥）；L95-103 覆盖率摘要（覆盖率 % / 真实观察 / 可测量 / 补算数 / 缺失原因逐条）；L346-348 雷达 imputed 轴「（补算）」后缀；L327-331 `itemReason` 改 `q.item_id === itemId` 精确匹配（后端 `_load_question_reviews` L110 已 SELECT qs.item_id）。前端 `npm run build` 通过。 |
| 3   | 报告发布契约完整运转：GENERATING → PROVISIONAL\|READY → PUBLISHED\|FAILED 状态机；发布前七项一致性校验由代码执行；管理员必须明确点击发布才 PUBLISHED；重复生成不再 DELETE 覆盖（报告不可变版本化） | ✓ VERIFIED | `report.py` 状态机 + `_assert_report_transition`；`report_checks.py:_run_consistency_checks` 七项校验；`api/admin/reports.py:publish_report` 路由级 require_admin；`generate_report` 无 `DELETE FROM report`，版本化 INSERT。`test_status_transition_legality`/`test_consistency_check_fails_to_failed`/`test_version_immutability`/`test_publish_flow` 绿（report 11 passed）。 |
| 4   | 报告生成失败显式可见（FAILED 状态 + 前端可区分"生成中/失败"，不再静默 pass） | ✓ VERIFIED | `api/assessment.py:_write_failed_report` + `_generate_report_task` 发 TASK_FAILED；前端 Report.vue bootstrap/poll 读 `report_status` 确定性分支 FAILED/GENERATING/ready。`test_generate_failed_visible` 绿。 |
| 5   | 候选人异议带完整字段（user_id/note/reviewer/时间戳），submit_feedback 校验 item 属于该报告对应模型，admin review note 不再被丢弃 | ✓ VERIFIED | `submit_feedback` INSERT 补 user_id + 同事务 REVIEW_FEEDBACK_RECEIVED；item 归属经 JOIN 校验；`api/admin/feedback.py` 持久化 review_note/reviewer_id/reviewed_at；`_load_question_reviews` 补 qs.item_id。`test_feedback_audit_fields`/`test_admin_note_persisted`/`test_question_reviews_has_item_id` 绿（feedback 3 passed）。 |

**Score:** 5/5 truths verified (gap from prior pass closed — SC #2 前端展示已落地)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/trace_link.py` | link_entity + LINK_ROLES 六值 + link_role 代码校验 | ✓ VERIFIED | LINK_ROLES 六值、非法值 raise、不 commit |
| `server/services/scoring.py` | `_locate_span` + evidence_spans_json 落库 + score→trace 写点 | ✓ VERIFIED | 14 列 INSERT 含 evidence_spans_json/rubric_version/scorer_version/measurement_target |
| `server/services/aggregation.py` | item_measurement + adjudicate + _impute_r + _observed_items + _normalize_score + required 判定 | ✓ VERIFIED | `adjudicate` 替换按题数均分；`item_scores[]` 带 imputed/no_data/gate 标志；coverage 字典完整 |
| `server/services/report.py` | 状态机 + 版本化 INSERT + FAILED 行 + trace 写点 + 雷达 indicators imputed 标志 | ✓ VERIFIED | L183 雷达 indicators 补 `imputed: bool(it.get("imputed"))`；L223 report_data 带 coverage |
| `server/services/report_checks.py` | 七项一致性校验 + HIRING_REDLINE_WORDS | ✓ VERIFIED | 七项校验完整 |
| `server/api/admin/reports.py` | POST /reports/{id}/publish (require_admin) | ✓ VERIFIED | require_admin + 状态机校验 + 事件 |
| `server/api/admin/feedback.py` | review/bad-case 持久化 note/reviewer/reviewed_at | ✓ VERIFIED | 三列 UPDATE |
| `server/db.py` | trace_link DDL + 4 迁移函数 + report/feedback/question_score 新列 | ✓ VERIFIED | 迁移函数注册 init_db |
| `server/services/llm.py` | `_record_trace` 返回 trace_id + `call_llm_json` trace_out | ✓ VERIFIED | trace_id 返回、trace_out 成功路径 append |
| `server/api/assessment.py` | request_report 三分支 + 失败可见 + submit_feedback 留痕 | ✓ VERIFIED | 409 REPORT_GENERATING、_write_failed_report、REVIEW_FEEDBACK_RECEIVED |
| `web/src/views/assessment/Report.vue` | poll 读 report_status + IMPUTED 标记 + coverage 展示 + 雷达轴标记 + itemReason item_id | ✓ VERIFIED | L118 补算徽标 / L95-103 coverage 摘要 / L346-348 雷达后缀 / L327-331 item_id 匹配；FAILED/GENERATING/ready 三分支保留 |
| `web/src/views/admin/TestCenter.vue` | 「发布报告」按钮 + onPublish | ✓ VERIFIED | onPublish 调 admin.reports.publish + 二次确认 |
| `web/src/api/index.js` | admin.reports.publish API 封装 | ✓ VERIFIED | API 封装在位 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `scoring.score_question` | `_locate_span` | evidence_quote 文本定位 | ✓ WIRED | `_build_evidence_spans` 调 `_locate_span` |
| `scoring.score_session` | `question_score.evidence_spans_json` | INSERT 列清单扩展 | ✓ WIRED | 14 列 INSERT |
| `db._migrate_trace_link` | `llm_trace.ref_id` | 逐实体表 SELECT 1 探测 | ✓ WIRED | call_type→候选表，命中 INSERT OR IGNORE |
| `report.generate_report` | `_run_consistency_checks` | 聚合后、INSERT 前 | ✓ WIRED | 失败写 FAILED 行，通过才版本化 INSERT |
| `report.generate_report` | `trace_link` | 版本化 INSERT 后 link_entity | ✓ WIRED | link_entity(reported→report / source→assessment_session) |
| `aggregation.item_scores` | `report_data.coverage` | report.py:223 透传 | ✓ WIRED | coverage 字典随 report_data 返回 |
| `report.radar_data.indicators` | `Report.vue renderRadar` | imputed 标志 → 轴「（补算）」后缀 | ✓ WIRED | L346-348 `ind.imputed ? ... name（补算）` |
| `_load_question_reviews.item_id` | `Report.vue itemReason` | `q.item_id === itemId` 精确匹配 | ✓ WIRED | L327-331 消费后端 L110 SELECT qs.item_id |
| `admin/reports.publish` | `REVIEW_REPORT_PUBLISH_CONFIRMED` | append_event 同事务 | ✓ WIRED | commit 前 append_event |
| `assessment.submit_feedback` | `REVIEW_FEEDBACK_RECEIVED` | append_event 同事务 | ✓ WIRED | actor_type=candidate |
| `admin/feedback.review_feedback` | `feedback.reviewer_id` | admin["user_id"] | ✓ WIRED | review_note/reviewer_id/reviewed_at 持久化 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `aggregation.py` item_scores | `observed_level` (measurements) | question_score SCORED 行 | 真实 SQL 读取 | ✓ FLOWING |
| `aggregation.py` IMPUTED item | `r = _impute_r(observed_items)` | 已裁决 observed per-item | 真实加权计算 | ✓ FLOWING |
| `aggregation.py` coverage | observed/imputed/total_measureable/missing_reasons | model_items + observed_items + missing_warnings | 真实计算 | ✓ FLOWING |
| `report.py` report_data.coverage | `agg.get("coverage", {})` | aggregation.coverage | 真实透传 | ✓ FLOWING |
| `report.py` radar_data.indicators.imputed | `bool(it.get("imputed"))` | aggregation.item_scores | 真实标志透传 | ✓ FLOWING |
| `report.py` question_reviews.item_id | `qs.item_id` (SELECT) | question_score JOIN question_bank | 真实 SQL 读取 | ✓ FLOWING |
| `Report.vue` 明细表 imputed 徽标 | `it.imputed` | report.item_details | 真实数据渲染（gap 已闭合） | ✓ FLOWING |
| `Report.vue` coverage 摘要 | `report.coverage` | getReportBySession report_json | 真实数据渲染（gap 已闭合） | ✓ FLOWING |
| `Report.vue` 雷达轴后缀 | `ind.imputed` | report.radar_data.indicators | 真实标志渲染（gap 已闭合） | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 证据 span/迁移/审计链 | `cd server && python -m pytest test_phase5_evidence.py -v` | 6 passed | ✓ PASS |
| 裁决/补算/状态机/发布/版本化 | `cd server && python -m pytest test_phase5_report.py -v` | 11 passed | ✓ PASS |
| feedback 审计链 | `cd server && python -m pytest test_phase5_feedback.py -v` | 3 passed | ✓ PASS |
| m6 端到端脚本回归 | `cd server && python test_m6_backend.py` | 44 通过 / 0 失败 | ✓ PASS |
| m7 feedback/trace 回归 | `cd server && python -m pytest test_m7_backend.py -v` | 5 passed | ✓ PASS |
| 前端生产构建 | `cd web && npm run build` | built in 5.33s（仅 chunk-size 提示，既有） | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` or phase-declared probe scripts exist (this phase is pytest-based; spot-checks above are the runnable evidence).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| REF-2.3 | 05-01 | 新表 trace_link（统一审计链） | ✓ SATISFIED | trace_link DDL + LINK_ROLES + link_entity + test_trace_link_role_validation |
| REF-2.10 | 05-01 | 证据定位结构化（span/offset/quote_hash；hash 复用限单 session） | ✓ SATISFIED | `_locate_span` + evidence_spans_json + test_span_unicode_code_point |
| REF-5.4 | 05-02 | item_measurement 统一裁决（废弃按题数均分；冲突取低留人工标记） | ✓ SATISFIED | `adjudicate` + 主循环替换 + test_adjudicate_conflict_lower |
| REF-5.5 | 05-02 | 缺失补算 IMPUTED（r 比例 + 特殊标记 + 覆盖率展示；O=∅ → NO_VALID_OBSERVATION） | ✓ SATISFIED | 后端补算/标记/O=∅ 完整；前端补算徽标 + 覆盖率摘要 + 雷达轴后缀已落地（05-05 gap closure，build 通过） |
| REF-5.6 | 05-02 | required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | ✓ SATISFIED | aggregation required 分支 + test_required_missing_provisional |
| REF-5.9 | 05-03 | 报告状态机 + review_status + 七项校验 + 明确点击发布 + 版本化 | ✓ SATISFIED | 状态机/校验/publish/版本化全落地 + 4 条测试绿 |
| REF-7.3 | 05-04 | feedback 补 user_id/note/reviewer/时间戳；question_reviews 补 item_id；submit_feedback 校验 item 属于对应模型 | ✓ SATISFIED | feedback 四列 + REVIEW_FEEDBACK_RECEIVED + qs.item_id + JOIN 校验 + 3 条测试绿 |
| REF-8.3 | 05-03 | 报告后台任务异常静默 pass → FAILED 可见 | ✓ SATISFIED | _write_failed_report + TASK_FAILED + 前端确定性分支 + test_generate_failed_visible |
| REF-8.7 | 05-01 | llm_trace ref_id 单字段弱关联迁移导入 trace_link | ✓ SATISFIED | _migrate_trace_link + test_ref_id_import_migration |

**Orphaned requirements:** None — all 9 phase requirement IDs (REF-2.3, REF-2.10, REF-5.4, REF-5.5, REF-5.6, REF-5.9, REF-7.3, REF-8.3, REF-8.7) are claimed by plans and mapped above. No additional Phase-5 IDs in REQUIREMENTS.md were left unclaimed.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | 无 TBD/FIXME/XXX/PLACEHOLDER debt marker | — | 关键文件扫描干净 |
| `server/services/report.py` | 58-70 | `placeholder` 变量名（GENERATING 占位行逻辑） | ℹ️ Info | 合法业务逻辑（复用 GENERATING 占位行，非 stub marker） |
| `server/services/report.py` | 148-151 | `placeholders`（SQL `?` 占位符） | ℹ️ Info | 合法 SQL 参数占位，非 stub |
| `server/services/report.py` | 146 | `return {}`（`_collect_evidence_quotes` 空 item_ids 守卫） | ℹ️ Info | 合法空值守卫，非 stub |
| `web/src/views/assessment/Report.vue` | 235 | `placeholder="请说明..."`（HTML input placeholder 属性） | ℹ️ Info | 合法表单属性，非 stub |

Note: the prior pass flagged `Report.vue` IN-02（itemReason std_name 匹配 + 陈旧注释）— now resolved（L326 注释已更新为「question_reviews 已携带 item_id」，L329 按 item_id 精确匹配）。

### Human Verification Required

以下为 gap 闭合后仍建议人工目验的报告展示项（无前端单测基建，视觉呈现需人工点验；不影响后端契约判定——后端数据已完整透传且测试全绿）。

### 1. IMPUTED 特殊视觉标记与覆盖率展示

**Test:** 打开一份含补算 item 的候选人报告，确认逐项明细中 imputed 项有「补算 · 加权估算」amber 徽标、SECTION 3 下覆盖率摘要（观察覆盖率 % / 真实观察 / 可测量 / 补算数 / 缺失原因逐条）、雷达图 imputed 轴带「（补算）」后缀。
**Expected:** IMPUTED 项与真实观察项视觉可区分；覆盖率数字与后端 coverage 字段一致；雷达轴后缀可见。
**Why human:** 视觉呈现与 UX 布局无法 grep 判定；代码与构建已通过，最终观感需人工点验。

### 2. 管理员发布按钮流程

**Test:** 测试中心对 READY/PROVISIONAL 报告点击「发布报告」，确认二次确认后状态变 PUBLISHED 且不可再发；HUMAN_REVIEW_REQUIRED 未 CONFIRMED 时被 409 拦截。
**Expected:** 发布成功提示；未 CONFIRMED 被 409 拦截并提示；候选人权限被 403 拦截。
**Why human:** 端到端交互流与权限 UX 需人工点验（后端 403/409 已由 test_publish_flow 覆盖）。

### Gaps Summary

无阻断缺口（成功率 5/5）。上一轮唯一 partial gap（SC #2 / REF-5.5 前端展示）已由 05-05 gap-closure（commit `fb4d139`）闭合：

- `web/src/views/assessment/Report.vue`：L118 补算 amber 徽标、L95-103 coverage 摘要、L346-348 雷达轴「（补算）」后缀、L327-331 itemReason 改 item_id 精确匹配、L524/525-536 样式。
- `server/services/report.py`：L183 雷达 indicators 补 `imputed` 标志；L223 report_data 已透传 coverage。
- 前端 `npm run build` 通过（5.33s，仅既有 chunk-size 提示）；后端 5 组测试全绿（evidence 6 / report 11 / feedback 3 / m6 44 / m7 5）。

遗留（非阻断，记档，来自 05-05-SUMMARY）：缺失原因 `reason` 为内部 score_state 码（INVALIDATED 等）或「qualification 缺失（不补算）」中文串，前端按原样展示未做码→中文映射。SSOT 仅要求「展示缺失原因」已满足，非 SC 契约缺口。

既有非 Phase 5 回归（记档，来自 04-011）：`test_p0_chain.py::test_completed_session_guardrail` 因 QUESTION_BANK_INCOMPLETE（缺种子题）失败，为 Phase 4 题库版本化涟漪，deferred 至 Phase 6，不计入 Phase 5 缺口。

---

_Verified: 2026-09-05T11:53:39Z_
_Verifier: Claude (gsd-verifier)_
