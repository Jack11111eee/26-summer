---
phase: 05-evidence-report-contract
verified: 2026-09-05T11:36:54Z
status: gaps_found
score: 4/5 must-haves verified
overrides_applied: 0
gaps:
  - truth: "缺失 item 按观察加权比例 r 补算并标 IMPUTED（特殊视觉标记 + 覆盖率展示）"
    status: partial
    reason: "后端已完整落地：adjudicate 统一裁决（废弃按题数均分）、_impute_r 按 r=Σ w_i·s_i/Σ w_i 补算并标 imputed=True、coverage 字典（observed_count/imputed_count/total_measureable/coverage_ratio/missing_reasons）透传进 report_data。但前端 web/src/views/assessment/Report.vue 未渲染 IMPUTED 特殊视觉标记，也未展示观察覆盖率/真实观察数/缺失原因——grep web/src 全目录对 imputed/coverage/覆盖率/补算/observation_status/provisional 均无渲染引用。SSOT §20.1「IMPUTED…必须特殊视觉标记 + 展示观察覆盖率/真实观察数/缺失原因」、§21.1「雷达图…IMPUTED 特殊标记」为硬性契约，前端展示缺口未闭合。"
    artifacts:
      - path: "web/src/views/assessment/Report.vue"
        issue: "item_details 明细表仅渲染 no_data（「未出题/未作答」），imputed==true 的 item 与真实观察项无视觉区分；无观察覆盖率/真实观察数/缺失原因展示；雷达图未标记 IMPUTED"
    missing:
      - "Report.vue item_details 明细表/雷达图对 imputed==true 的 item 渲染特殊视觉标记（如「补算」徽标或颜色区分，区别于真实观察）"
      - "报告页展示 coverage 字典（观察覆盖率/真实观察数/缺失原因）"
---

# Phase 5: 证据链与报告契约 (evidence-report-contract) Verification Report

**Phase Goal:** 全链审计链通过 trace_link 闭合、证据引用结构化可定位；报告发布走完整状态机（人工明确点击发布 + 七项一致性校验 + 版本化），反馈异议带完整审计字段
**Verified:** 2026-09-05T11:36:54Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Success Criteria)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | 每个证据引用结构化可定位（source_message_id / start_offset / end_offset Unicode code point / quote_hash）；终局评分回捞原文；trace_link 闭合 report→session→model/version→question→message→score→trace，旧 ref_id 关联导入 | ✓ VERIFIED | `scoring.py:_locate_span` 返回完整 span dict（code-point 语义 str.find/len），定位失败降级 quote_hash-only；`_fetch_answer_text` 经 raw_hash 回捞 context_raw.full_text；`score_session` 运行时写 trace_link（scored→question_score / source→assessment_question），`generate_report` 写（reported→report / source→assessment_session）；`db._migrate_trace_link` 按 call_type→实体表 probe 导入旧 ref_id。`test_audit_chain_closure`（6 步贯通）与 `test_ref_id_import_migration` 全绿。 |
| 2   | item 最终等级由统一测量记录裁决（adjudicate 不按题数均分、冲突取低留人工标记）；缺失 item 按 r 补算并标 IMPUTED（特殊视觉标记 + 覆盖率展示）；O=∅ → NO_VALID_OBSERVATION/HUMAN_REVIEW_REQUIRED；required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | ✗ PARTIAL | 裁决/补算/语义后端全绿：`adjudicate` 替换 sum/len（grep 确认无 `sum(finals)/len(finals)`），冲突极差≥2 取低 + human_review 并传导 PROVISIONAL/HUMAN_REVIEW_REQUIRED（CR-01 已修）；`_impute_r` + `_observed_items` 归约，`imputed=True` 标记 + `coverage` 字典；O=∅ 与 required 缺失分支正确。**缺口**：前端 Report.vue 未渲染 IMPUTED 特殊视觉标记，也未展示观察覆盖率/真实观察数/缺失原因（SSOT §20.1/§21.1 硬性契约）。详见 Gaps Summary。 |
| 3   | 报告发布契约完整运转：GENERATING → PROVISIONAL\|READY → PUBLISHED\|FAILED 状态机；发布前七项一致性校验由代码执行；管理员必须明确点击发布才 PUBLISHED；重复生成不再 DELETE 覆盖（报告不可变版本化） | ✓ VERIFIED | `report.py` REPORT_STATUSES/REVIEW_STATUSES + `_assert_report_transition`（非法迁移 raise）；`report_checks.py:_run_consistency_checks` 七项校验，任一失败写 FAILED 行；`api/admin/reports.py:publish_report` 路由级 `Depends(require_admin)`，候选人 403，HUMAN_REVIEW_REQUIRED 未 CONFIRMED → 409；`generate_report` 无 `DELETE FROM report`（grep 确认），`_insert_report_row` 复用 GENERATING 占位行或版本化 INSERT。`test_status_transition_legality`/`test_consistency_check_fails_to_failed`/`test_version_immutability`/`test_publish_flow` 全绿。 |
| 4   | 报告生成失败显式可见（FAILED 状态 + 前端可区分"生成中/失败"，不再静默 pass） | ✓ VERIFIED | `api/assessment.py:_write_failed_report` 异常写 FAILED 行 + `_generate_report_task` 发 TASK_FAILED 事件；`get_report_by_session` 返回 report_status；前端 Report.vue bootstrap/poll 读 `report_status` 确定性分支 FAILED/GENERATING/ready。`test_generate_failed_visible` 绿。 |
| 5   | 候选人异议带完整字段（user_id/note/reviewer/时间戳），submit_feedback 校验 item 属于该报告对应模型，admin review note 不再被丢弃 | ✓ VERIFIED | `submit_feedback` INSERT 补 user_id + 同事务 REVIEW_FEEDBACK_RECEIVED（actor_type=candidate）；item 归属经 JOIN report→session→competency_item 校验（无关 model → 404）；`api/admin/feedback.py` review/bad-case 持久化 review_note/reviewer_id/reviewed_at（废除 note 丢弃）；`_load_question_reviews` 补 qs.item_id。`test_feedback_audit_fields`/`test_admin_note_persisted`/`test_question_reviews_has_item_id` 全绿。 |

**Score:** 4/5 truths fully verified (1 partial — success criterion 2 has a frontend presentation gap)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/trace_link.py` | link_entity + LINK_ROLES 六值 + link_role 代码校验 | ✓ VERIFIED | LINK_ROLES 六值、非法值 raise ValueError、不 commit |
| `server/services/scoring.py` | `_locate_span` + evidence_spans_json 落库 + score→trace 运行时写点 | ✓ VERIFIED | `_locate_span`/`_build_evidence_spans`/`_latest_user_message_id`；score_session INSERT 含 evidence_spans_json/rubric_version/scorer_version/measurement_target；主观题 link_entity(scored/source) |
| `server/services/aggregation.py` | item_measurement + adjudicate + _impute_r + _observed_items + _normalize_score + required 判定 | ✓ VERIFIED | 全部纯函数落地，主循环已接 adjudicate/IMPUTED/O=∅/required 分流 |
| `server/services/report.py` | 状态机 + 版本化 INSERT + FAILED 行 + report→trace 写点 + question_reviews item_id | ✓ VERIFIED | REPORT_STATUSES/REVIEW_STATUSES/_assert_report_transition；无 DELETE 覆盖；link_entity(reported/source)；_load_question_reviews 补 qs.item_id |
| `server/services/report_checks.py` | 七项一致性校验 + HIRING_REDLINE_WORDS | ✓ VERIFIED | 七项校验完整，红线词表集中一处 |
| `server/api/admin/reports.py` | POST /reports/{id}/publish (require_admin) | ✓ VERIFIED | 路由级 require_admin + 状态机校验 + REVIEW_REPORT_PUBLISH_CONFIRMED 事件 |
| `server/api/admin/feedback.py` | review/bad-case 持久化 note/reviewer/reviewed_at | ✓ VERIFIED | review_note/reviewer_id/reviewed_at 三列 UPDATE |
| `server/db.py` | trace_link DDL + 4 迁移函数 + report/feedback/question_score 新列 | ✓ VERIFIED | `_migrate_trace_link`/`_migrate_question_score_phase5`/`_migrate_report_phase5`/`_migrate_feedback_phase5` 注册 init_db；report→assessment_session 回退映射（WR-04 已修） |
| `server/services/llm.py` | `_record_trace` 返回 trace_id + `call_llm_json` trace_out | ✓ VERIFIED | trace_id 返回、trace_out 仅成功路径 append |
| `server/api/assessment.py` | request_report 三分支 + 失败可见 + submit_feedback 留痕 | ✓ VERIFIED | 409 REPORT_GENERATING（无 REPORT_ALREADY_EXISTS）、_write_failed_report、REVIEW_FEEDBACK_RECEIVED |
| `web/src/views/assessment/Report.vue` | poll 读 report_status 区分失败/生成中 | ⚠️ PARTIAL | FAILED/GENERATING/ready 分支已实现；但 IMPUTED 特殊标记 + 覆盖率展示缺失（见 gap） |
| `web/src/views/admin/TestCenter.vue` | 「发布报告」按钮 + onPublish | ✓ VERIFIED | onPublish 调 admin.reports.publish，二次确认弹窗 |
| `web/src/api/index.js` | admin.reports.publish API 封装 | ✓ VERIFIED | 第 76-77 行封装 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `scoring.score_question` | `_locate_span` | evidence_quote 文本定位 | ✓ WIRED | `_build_evidence_spans` 调 `_locate_span(answer_text, evidence_quote, source_message_id)` |
| `scoring.score_session` | `question_score.evidence_spans_json` | INSERT 列清单扩展 | ✓ WIRED | 14 列 INSERT 含 evidence_spans_json/rubric_version/scorer_version/measurement_target |
| `db._migrate_trace_link` | `llm_trace.ref_id` | 逐实体表 SELECT 1 探测 | ✓ WIRED | call_type→候选表，命中 INSERT OR IGNORE，未命中保留 ref_id |
| `scoring.score_session` | `trace_link` | 落 question_score 后 link_entity | ✓ WIRED | 主观题 trace_id → link_entity(scored/source) |
| `report.generate_report` | `_run_consistency_checks` | 聚合后、INSERT 前 | ✓ WIRED | 失败写 FAILED 行，通过才版本化 INSERT |
| `assessment.request_report` | `report_status='GENERATING'` | 入队前写占位行 | ✓ WIRED | 分支 (c) 写 GENERATING + TASK_QUEUED 事件 |
| `admin/reports.publish` | `REVIEW_REPORT_PUBLISH_CONFIRMED` | append_event 同事务 | ✓ WIRED | commit 前 append_event |
| `report.generate_report` | `trace_link` | 版本化 INSERT 后 link_entity | ✓ WIRED | link_entity(reported→report / source→assessment_session) |
| `assessment.submit_feedback` | `REVIEW_FEEDBACK_RECEIVED` | append_event 同事务 | ✓ WIRED | commit 前 append_event（actor_type=candidate） |
| `admin/feedback.review_feedback` | `feedback.reviewer_id` | admin["user_id"] | ✓ WIRED | review_note/reviewer_id/reviewed_at 持久化 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `aggregation.py` item_scores | `observed_level` (measurements) | question_score SCORED 行 | 真实 SQL 读取 | ✓ FLOWING |
| `aggregation.py` IMPUTED item | `r = _impute_r(observed_items)` | 已裁决 observed per-item | 真实加权计算 | ✓ FLOWING |
| `aggregation.py` coverage | observed/imputed/total_measureable | model_items + observed_items | 真实计算 | ✓ FLOWING |
| `report.py` report_data.item_details | `{**it, score: round(...)}` | agg.item_scores | 真实聚合结果 | ✓ FLOWING |
| `report.py` question_reviews | `_load_question_reviews` | question_score JOIN question_bank | 真实 SQL 读取 | ✓ FLOWING |
| `Report.vue` item_details 表 | `report.item_details` | getReportBySession report_json | 真实数据（但 imputed/coverage 未渲染） | ⚠️ HOLLOW (imputed/coverage 字段流入前端但未展示) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 证据 span/迁移/审计链 | `cd server && python -m pytest test_phase5_evidence.py -v` | 6 passed | ✓ PASS |
| 裁决/补算/状态机/发布/版本化 | `cd server && python -m pytest test_phase5_report.py -v` | 11 passed | ✓ PASS |
| feedback 审计链 | `cd server && python -m pytest test_phase5_feedback.py -v` | 3 passed | ✓ PASS |
| m6 端到端脚本回归 | `cd server && python test_m6_backend.py` | 44 通过 / 0 失败 | ✓ PASS |
| m7 feedback/trace 回归 | `cd server && python -m pytest test_m7_backend.py -v` | 5 passed | ✓ PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` or phase-declared probe scripts exist (this phase is pytest-based; spot-checks above are the runnable evidence).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| REF-2.3 | 05-01 | 新表 trace_link（统一审计链） | ✓ SATISFIED | trace_link DDL + LINK_ROLES + link_entity + test_trace_link_role_validation |
| REF-2.10 | 05-01 | 证据定位结构化（span/offset/quote_hash；hash 复用限单 session） | ✓ SATISFIED | `_locate_span` + evidence_spans_json + test_span_*/test_span_unicode_code_point |
| REF-5.4 | 05-02 | item_measurement 统一裁决（废弃按题数均分；冲突取低留人工标记） | ✓ SATISFIED | `adjudicate` + 主循环替换 + test_adjudicate_conflict_lower + CR-01 传导修复 |
| REF-5.5 | 05-02 | 缺失补算 IMPUTED（r 比例 + 特殊标记 + 覆盖率展示；O=∅ → NO_VALID_OBSERVATION） | ⚠️ PARTIAL | 后端补算/标记/O=∅ 完整；前端「特殊标记 + 覆盖率展示」缺失（见 gap） |
| REF-5.6 | 05-02 | required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | ✓ SATISFIED | aggregation required 分支 + test_required_missing_provisional |
| REF-5.9 | 05-03 | 报告状态机 + review_status + 七项校验 + 明确点击发布 + 版本化 | ✓ SATISFIED | 状态机/校验/publish/版本化全落地 + 4 条测试绿 |
| REF-7.3 | 05-04 | feedback 补 user_id/note/reviewer/时间戳；question_reviews 补 item_id；submit_feedback 校验 item 属于对应模型 | ✓ SATISFIED | feedback 四列 + REVIEW_FEEDBACK_RECEIVED + qs.item_id + JOIN 校验 + 3 条测试绿 |
| REF-8.3 | 05-03 | 报告后台任务异常静默 pass → FAILED 可见 | ✓ SATISFIED | _write_failed_report + TASK_FAILED + 前端确定性分支 + test_generate_failed_visible |
| REF-8.7 | 05-01 | llm_trace ref_id 单字段弱关联迁移导入 trace_link | ✓ SATISFIED | _migrate_trace_link + test_ref_id_import_migration |

**Orphaned requirements:** None — all 9 phase requirement IDs (REF-2.3, REF-2.10, REF-5.4, REF-5.5, REF-5.6, REF-5.9, REF-7.3, REF-8.3, REF-8.7) are claimed by at least one plan and mapped above. No additional Phase-5 IDs in REQUIREMENTS.md were left unclaimed.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | 无 TBD/FIXME/XXX/PLACEHOLDER debt marker | — | 关键文件扫描干净 |
| `web/src/views/assessment/Report.vue` | 316-322 | `itemReason` 仍用 `q.std_name === item.std_name` 匹配 + 陈旧注释「question_reviews 未携带 item_id」（实际已携带） | ℹ️ Info | 多题 item 时可能取错理由；后端 item_id 已就位但前端未消费（REVIEW IN-02，非阻断） |
| `server/api/admin/reports.py` | 19-21 | `_PublishBody.review_outcome` 未约束到允许枚举（str 任意值可持久化） | ℹ️ Info | 极端输入可污染 review_outcome 列（REVIEW IN-04，非阻断） |
| `server/services/scoring.py` | 321-333 | 重评分 DELETE 旧 question_score 行，遗留 trace_link 弱关联指向已删 score_id | ℹ️ Info | 弱关联设计接受（D-020，REVIEW IN-05，非阻断） |

### Human Verification Required

以下为 gap 闭合后仍建议人工目验的报告展示项（不影响当前 gaps_found 判定，作为后续验收参考）：

### 1. 报告 IMPUTED 特殊视觉标记与覆盖率展示

**Test:** 打开一份含补算 item 的候选人报告，确认 IMPUTED 项有特殊视觉标记、页面展示观察覆盖率/真实观察数/缺失原因。
**Expected:** IMPUTED 项与真实观察项视觉可区分；覆盖率数字与后端 coverage 字段一致。
**Why human:** 视觉呈现与 UX 布局无法 grep 判定；且该功能当前尚未实现（已记 gap）。

### 2. 管理员发布按钮流程

**Test:** 测试中心对 READY/PROVISIONAL 报告点击「发布报告」，确认二次确认后状态变 PUBLISHED 且不可再发。
**Expected:** 发布成功提示；HUMAN_REVIEW_REQUIRED 未 CONFIRMED 时被 409 拦截并提示。
**Why human:** 端到端交互流与权限 UX 需人工点验（后端 403/409 已由 test_publish_flow 覆盖）。

### Gaps Summary

1 项 partial gap（成功率 4/5）：

**前端 IMPUTED 特殊标记 + 覆盖率展示缺失。** 后端证据链、裁决、补算、状态机、发布、feedback 审计链全部落地且测试全绿（evidence 6 / report 11 / feedback 3 / m6 44 / m7 5 通过）。唯一未闭合的契约是 SSOT §20.1「IMPUTED 必须特殊视觉标记 + 展示观察覆盖率/真实观察数/缺失原因」与 §21.1「雷达图 IMPUTED 特殊标记」的前端展示——`Report.vue` 未渲染 `imputed` 标记，也未展示 `coverage` 字典。后端数据契约（`imputed=True` 标记 + `coverage{observed_count/imputed_count/total_measureable/coverage_ratio/missing_reasons}`）已完整透传进 `report_data`，属「数据已就位、前端未接线」的展示缺口，非后端计算缺口。

Grouped concern：该 gap 与 REVIEW.md 的 IN-02（itemReason std_name 匹配）同属「前端未消费 Phase 5 新增的后端字段」一类，可在同一前端收口任务中一并处理。

---

_Verified: 2026-09-05T11:36:54Z_
_Verifier: Claude (gsd-verifier)_
