# Phase 5: 证据链与报告契约 - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning

<domain>
## Phase Boundary

把模块三的「评分→聚合→报告→反馈」链按 SSOT §12.4/§12.5/§13.3/§17/§19/§20/§21 收口为可审计、可回溯的契约：证据引用从「单字段 evidence_quote」升级为「结构化 span（source_message_id/start_offset/end_offset/quote_hash）+ trace_link 统一审计链」；item 最终等级从「按题数均分」改为「item_measurement 统一裁决」；缺失 item 走 r 比例补算 IMPUTED（特殊标记 + 覆盖率展示）；required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED；报告发布走完整状态机（GENERATING→PROVISIONAL|READY→PUBLISHED|FAILED + 七项一致性校验 + 管理员明确点击发布 + 不可变版本化）；报告生成失败显式可见（FAILED 态，不再静默）；反馈异议带完整审计字段。

对应 REQUIREMENTS.md：REF-2.3, REF-2.10, REF-5.4, REF-5.5, REF-5.6, REF-5.9, REF-7.3, REF-8.3, REF-8.7（9 项，支撑 REQ-talent-profile-report / REQ-iterative-loop）。

**不在本阶段**：schema_version 迁移登记簿收口（Phase 6）；测试统一 pytest + CI（Phase 6）；M1 回归（Phase 6）；候选人 E2E（Phase 6）；eval 隔离（Phase 6）；trace 保留期/脱敏策略（§31-5 数据治理，Phase 6）；综合题 item_measurement 的 integrated 来源（REF-3.9 延后，列位预留）；score_live/score_final 双分背离 bad case 自动候选（REF-5.11，Phase 6）。
</domain>

<decisions>
## Implementation Decisions

> D-55~D-67 为 Phase 5 编号（接续 04 的 D-47~D-54）。auto 模式（章程 §1）推荐项选取，逐条依据 = SSOT 条款/既定决策/代码现状三者之一，留痕见 05-DISCUSSION-LOG.md。

### 证据 span 结构化（REF-2.10，计划 05-01）

- **D-55: evidence_spans 结构化 = LLM 给 quote 文本、代码定位 offset/hash（D-003「LLM 不碰数字」）。** question_score 新增 `evidence_spans_json` 列（list of `{source_message_id, source_content_type(raw|refined), start_offset, end_offset, quote_hash}`）。P-score 继续输出 `evidence_quote`（文本），代码在 assessment_message 中定位该 quote 计算 start_offset/end_offset（Unicode code point，§12.5）与 quote_hash（确定性 hash）；定位失败（mock 占位 / LLM 改写非原文）→ 降级为 `quote_hash` only + `source_message_id=NULL`。`evidence_quote` 列保留（展示 + 后向兼容），`evidence_spans_json` 为结构化权威。客观题 evidence_quote = `answer_text[:60]`（answer_key 命中的回答片段），span 同理按定位填充。

### trace_link 统一审计链（REF-2.3/REF-8.7，计划 05-01）

- **D-56: trace_link 新表（§13.3 DDL 照抄）+ link_role 枚举代码校验（N11）。** `trace_link(id, trace_id, entity_type, entity_id, link_role, created_at, UNIQUE(trace_id, entity_type, entity_id, link_role))`，link_role ∈ `{input|output|caused_by|scored|reported|source}`。业务表不逐一加 trace 外键；审计链 report→session→model/version→question→message→score→trace 通过 trace_link 闭合。**trace_id 取值与各环节写点 = Claude's Discretion（planner 定）**，但五要素（report/session/model/version/question/score/trace）必须可达。

- **D-57: 旧 ref_id 导入 trace_link（REF-8.7）= 迁移函数把 llm_trace.ref_id 拆为 entity_type + entity_id 导成 trace_link 行。** llm_trace.ref_id 现状 = session_id / question_id / report 相关 id（call_type 决定语义）；迁移按 call_type 推断 entity_type（extract/disambiguate/aggregate_level → 模块一域；question_gen/interviewer/refine/score → session/question 域；report → report 域）。llm_trace.ref_id 列保留（trace 查看器 admin/trace.py 不破坏），trace_link 为新增统一关联层。

### item_measurement 统一裁决（REF-5.4，计划 05-02）

- **D-58: item_measurement = 内存统一测量记录（非新表——D-018「21 张表」清单无它）。** §19 pseudocode 落地为 aggregation.py 内中间结构 `(question_id, item_id, observed_level, evidence_refs, measurement_source: ordinary|integrated)`；普通题 → `ordinary`，综合题 `integrated`（本期无综合题，列位预留）。`item_final_level = adjudicate(...)` 替换现行 `actual = sum(finals)/len(finals)`（按题数均分，REF-5.4 明令废弃）：按 rubric/覆盖/稳定性/冲突裁决，**不按来源加权、不按题数重复乘 item.weight**；重大冲突取较低值 + 人工复核标记（human_review 列位）。

### IMPUTED 补算 + required 缺失（REF-5.5/REF-5.6，计划 05-02）

- **D-59: IMPUTED 补算 = §20.1 公式代码化 + 覆盖率展示 + O=∅ → NO_VALID_OBSERVATION。** `r = Σ(i∈O) w_i×s_i / Σ(i∈O) w_i`（s_i=(score−1)/4）；缺失普通 item 补算值 = r，标记 IMPUTED；IMPUTED 参与总分/雷达但特殊视觉标记 + 展示观察覆盖率/真实观察数/缺失原因；O=∅ → 不能补算 → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED；required 与 qualification 不补算（§20.1）。**补算比例超阈值 → 临时报告 + 人工复核，阈值 = §31-3 开放参数 → 关口包呈报项（不臆造）**。

- **D-60: required 缺失 → report_status=PROVISIONAL + review_status=HUMAN_REVIEW_REQUIRED（§20.2）。** 判定 = required item 在观察集合 O 中缺失（未 SCORED 且补算不适用）；不触发补测；人工确认后可发布为正式报告（必须明确点击发布）；系统不做录用判断。

### 报告状态机 + 发布 + 版本化（REF-5.9/REF-8.3，计划 05-03）

- **D-61: report 表演进 = 加 report_status/review_status/version + 发布与人工复核字段。** report_status: `GENERATING → PROVISIONAL|READY → PUBLISHED|FAILED`；review_status: `NONE|REQUIRED|IN_PROGRESS|CONFIRMED|CLOSED`；版本字段 `version`（session 内递增）+ 发布字段（review_request_reason/reviewer_id/review_note/review_outcome/reviewed_at/publish_confirmed_by/published_at，§21.1）。覆盖生成 `DELETE FROM report WHERE session_id=?` + INSERT → 改为不可变版本化（新版本 INSERT 新行，旧行保留）。

- **D-62: 报告版本化 key = report_id 每版本新行（session 内多版本），feedback FK → 具体版本 report_id 天然防外键断裂。** 现行 report PK=report_id，`get_report_by_session` 已 `ORDER BY created_at DESC LIMIT 1` 取最新——版本化后同 session 多行仍取最新；feedback.report_id 已 FK → report_id，指向具体版本不悬空（旧行保留故不 DELETE）。**重复生成语义**：现行 `request_report` 对「已存在 report 行」409 拒绝——版本化后改为「允许重生成创建新版本」（REF-5.9 SC-3「重复生成不再 DELETE 覆盖」），409 仅保留给 GENERATING 进行中（防并发重入），具体边界 planner 定。

- **D-63: 七项一致性校验 = 代码执行（§21.1），任一失败 → report_status=FAILED。** 七项：数字可重算 / weight 总和一致 / 引用 question·message 属于该 session / model·version 与快照一致 / 无效题·系统错误未进正常分母 / IMPUTED·REFUSED·required 警告与结构化状态一致 / 文案无录用判断表述。校验在聚合后、生成 PROVISIONAL|READY 前执行；失败不生成正常报告（与 §17「评分失败 → FAILED，不得生成 0 分正常报告」同源）。

- **D-64: 发布流程 = 管理员显式 POST publish 端点（明确点击）+ 前端最小化（零破坏优先，沿用 Phase 4 [04-010] 先例）。** 后端 `POST /api/admin/reports/{report_id}/publish`（require_admin），校验 review_status 满足（required 缺失需 CONFIRMED 人工复核完成）→ report_status=PUBLISHED + publish_confirmed_by + published_at + REVIEW_REPORT_PUBLISH_CONFIRMED 事件。前端：状态机/发布按钮走**后端优先 + 最小前端**——report_status 字段与端点落库后，仅在既有 Report.vue 轮询里区分 GENERATING/FAILED（真实 FAILED 态替代超时猜测）；发布按钮并入 admin（TestCenter.vue 反馈 review 界面既有）。具体 UI 范围 planner 裁量，倾向后端完整 + 前端最小。

- **D-65: 报告生成失败显式可见（REF-8.3）= `_generate_report_task` 异常捕获 → report_status=FAILED 行落库 + TASK_FAILED 事件（保留）。** 现状异常静默（前端轮询 report 表为空 + 超时猜测失败）；改 = 异常捕获写 FAILED 报告行（report_json 含 error 摘要，str(e)[:200] 截断同 Phase 4 T-04-01）+ TASK_FAILED 事件留痕。前端 Report.vue 轮询读 report_status 确定性区分「生成中/失败」。

### feedback 字段补全（REF-7.3，计划 05-04）

- **D-66: feedback 表补列 + admin note 持久化 + question_reviews 补 item_id。** feedback 加 `user_id`（submit 时从 require_login 取）/`note`/`reviewer`/`reviewed_at`；`review_feedback`/`mark_bad_case` 现有 `note` 入参被丢弃 → 补持久化 note + reviewer + reviewed_at；`submit_feedback` 校验 item 属于对应模型（现有 assessment.py:1124-1130 已做，保留不动）；question_reviews（report.json 逐题回顾，`_load_question_reviews`）补 `item_id` 列。

- **D-67: 审计字段 = REVIEW_* 事件（§13.2）落地。** feedback 提交 → `REVIEW_FEEDBACK_RECEIVED`；发布确认 → `REVIEW_REPORT_PUBLISH_CONFIRMED`。异议只进人工处理，永不触发改分（D-031）。

### 开放参数（关口包呈报项 SSOT §31 类）

- **补算复核阈值（§31-3）**：IMPUTED 补算比例超阈值 → 临时报告 + 人工复核。plan 落 config 占位 + 常量注释标注「实施期校准」，**数值不代决**（同 N=10 / MAX_CONTEXT_TOKENS 先例，关口包列呈报项；若用户不裁决则维持 plan 占位默认）。

### Claude's Discretion
- trace_link 具体写点与 trace_id 取值（session 级关联 vs llm_trace.trace_id）
- evidence_spans 定位算法（quote 在 raw/refined 中的子串定位 + 多命中策略 + hash 算法 sha256 规范化）
- item_measurement 中间结构字段命名与 adjudicate 裁决规则实现（§19 冲突取低 + 人工标记的具体代码形态）
- 报告版本号生成规则（session 内 MAX(version)+1 vs created_at 排序）
- 七项校验的代码实现形态与失败错误细分
- request_report 重复生成/409 的精确状态边界
- 测试组织（新 test_phase5_* 文件——沿用单文件单进程 + tempfile + mock 三件套纪律）

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 设计权威（SSOT）
- `design/final-design/总设计文档.md` §12.4 — question_score 演进（score_final 统一 / item_id / score_state / measurement_target / rubric_version / evidence_spans_json / scorer_version / human_override_score / human_override_state / override_reason / reviewer_id / reviewed_at；综合题 (question_id,item_id) 多记录；分母规则八态）
- `design/final-design/总设计文档.md` §12.5 — context_raw 与证据定位（hash 复用限单 session / source_message_id / source_content_type / start_offset / end_offset / quote_hash；终局评分回捞原文）
- `design/final-design/总设计文档.md` §13.3 — trace_link 统一关联表（DDL + link_role 枚举 + report→session→model/version→question→message→score→trace 审计链闭合）
- `design/final-design/总设计文档.md` §13.2 — REVIEW_* 事件组（REQUESTED/ACCESSED/DECIDED/REPORT_PUBLISH_CONFIRMED/FEEDBACK_RECEIVED）
- `design/final-design/总设计文档.md` §17 — 评分链（P-score temperature≈0 回捞原文 / score_live 仅导航 / 评分失败 → FAILED 不得 0 分正常报告）
- `design/final-design/总设计文档.md` §19 — item 内多题合并与综合题（item_measurement 统一测量记录 / adjudicate 裁决规则 / 不按来源加权不按题数重复乘 / 冲突取低留人工标记）
- `design/final-design/总设计文档.md` §20.1–20.3 — 缺失补算 IMPUTED（r 比例 / O=∅ NO_VALID_OBSERVATION / required·qualification 不补算 / 阈值实施期定）+ required 缺失 PROVISIONAL + 总分公式
- `design/final-design/总设计文档.md` §21.1 — 报告状态机与发布（report_status/review_status 状态机 / 七项一致性校验 / 管理员明确点击发布 / 人工复核字段 / 不可变版本化）
- `design/final-design/总设计文档.md` §28-5 — 修复待办第 5 步（证据 span/trace_link / 报告发布校验 / feedback 补字段 / 报告版本化防 feedback 外键断裂）
- `design/final-design/总设计文档.md` §31 — 开放参数（补算复核阈值「实施期定」——关口包呈报项）

### 证据基线
- `research/ssot-code-gap-matrix.md` — 68 行契约核对（Phase 5 相关：矩阵 §2 的 2.3/2.10、§5 的 5.4/5.5/5.6/5.9、§7 的 7.3、§8 的 8.3/8.7）
- `.planning/intel/decisions.md` D-020（trace_link 统一审计链）、D-025（报告五段式与发布契约）、D-031（异议只进人工不触发改分）、D-003（LLM 不碰数字）、D-018（21 张表清单）
- `.planning/phases/04-question-bank-version/04-CONTEXT.md` — Phase 4 已决（D-54 measurement_target/evidence_requirement 留 NULL 待本 phase、rubric_version "v1" 起步）
- `.planning/phases/02-dynamic-selection/02-CONTEXT.md` — Phase 2 已决（D-28 score_state 分母规则 / D-27 INVALIDATED 语义——IMPUTED 前置条件）

### 代码现状（改造对象）
- `server/db.py` — question_score DDL（gate 五列 + human_override/override_reason/reviewer_id 已落，evidence_spans_json/measurement_target/rubric_version/scorer_version 待加）、report DDL（report_id/session_id/total_score/gate_passed/report_json/created_at——无状态机字段）、feedback DDL（无 user_id/note/reviewer/reviewed_at）、llm_trace DDL（ref_id 单字段弱关联）、context_raw（hash UNIQUE → full_text 回捞）
- `server/services/scoring.py` — score_question（evidence_quote 单字段）/ score_session（DELETE+INSERT 覆盖 / item_id 匹配 / REFUSED·INVALIDATED 三态）
- `server/services/aggregation.py` — aggregate_session_scores（`actual=sum/len` 按题数均分——REF-5.4 废弃对象 / no_data 无 IMPUTED / _EXCLUDED_STATES 三路分流）
- `server/services/report.py` — generate_report（DELETE+INSERT 覆盖——版本化对象）/ _load_question_reviews（逐题回顾，无 item_id）/ _collect_evidence_quotes
- `server/services/prompts/score.py` — P-score 输出契约 {score, evidence_quote, reason}（evidence_quote 文本供代码定位 span）
- `server/api/assessment.py` — request_report（409 重复触发 / 后台链 _generate_report_task 异常静默）/ get_report_by_session / submit_feedback（item 归属校验已做）
- `server/api/admin/feedback.py` — review_feedback / mark_bad_case（note 入参丢弃——D-66 修复对象）
- `server/api/admin/trace.py` — get_session_traces（ref_id IN (...) 弱关联——trace_link 落地后的消费升级）
- `.planning/codebase/ARCHITECTURE.md` / `TESTING.md` — 分层纪律/SQLite 单写者两模式/测试纪律

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `context_raw`（hash UNIQUE → full_text）+ `assessment_message.raw_hash`——原文回捞链路已就绪（scoring `_fetch_answer_text` / report `_load_question_reviews` 已用），evidence_spans 的 source 定位直接复用
- `_load_question_reviews`（report.py:35）逐题回顾 + raw_hash 回捞——question_reviews 补 item_id 的既有载体
- `assessment_state_event` + `append_event`（state_events.py）——REVIEW_* 事件组走同一入口（§13.2 激活组）
- `_generate_report_task`（assessment.py:1031）——TASK_FAILED 事件已留痕，异常静默 → FAILED 报告行的改造点
- `submit_feedback`（assessment.py:1114）——item 归属校验（JOIN report→session→competency_item）已做，REF-7.3 该条已满足

### Established Patterns
- raw SQL + get_conn() per-call + 显式 commit；DDL 迁移幂等嗅探（PRAGMA table_info / 重建表放宽 CHECK——_migrate_llm_trace/_migrate_feedback_status 先例）
- N11 枚举代码校验（report_status/review_status/link_role 无 DB CHECK）
- 「先 commit 再调 LLM」/「内存算完单事务落库」（scoring score_session 已内存算完单事务写库——item_measurement 裁决层同一模式）
- 三路 score_state 分流（aggregation._EXCLUDED_STATES）——IMPUTED 补算在「缺 finals」分支插入，不破坏现有 SCORED/REFUSED/排除态逻辑
- 迁移函数 `_migrate_*` 注册于 init_db 收尾——trace_link 建表 + 旧 ref_id 导入 + report/feedback/question_score ALTER 照此

### Integration Points
- `server/services/scoring.py score_question` — evidence_quote 返回后代码定位 span（evidence_spans_json 生成点）
- `server/services/scoring.py score_session` — question_score INSERT 补 evidence_spans_json/rubric_version/scorer_version 列
- `server/services/aggregation.py aggregate_session_scores` — item_measurement 裁决替换按题数均分 + IMPUTED 补算 + required 缺失 PROVISIONAL 标记
- `server/services/report.py generate_report` — 七项校验 + 版本化 INSERT + report_status 状态机推进 + trace_link 写点
- `server/api/assessment.py request_report/_generate_report_task` — FAILED 捕获 + 重复生成语义
- `server/api/admin/` — 新增 publish 端点 + feedback review note 持久化
- `server/db.py` — trace_link 新表 + report/feedback/question_score ALTER + 旧 ref_id 导入迁移

</code_context>

<specifics>
## Specific Ideas

- 旧 ref_id 导入的 entity_type 推断须按 call_type 谨慎映射——interviewer/refine/score 的 ref_id 可能是 question_id 也可能是 session_id（`get_session_traces` 现状即「ref_id IN (session_id + question_ids)」并集——导入时以「能命中实体表」为准，命不中的保留 ref_id 原值不拆）。
- evidence_spans 定位多命中（quote 在多条消息重复出现）→ 取最早/最近一次（planner 定），但必须记录 source_message_id 消除歧义。
- mock 模式 `_mock_score` 返回 "mock quote" 不在原文中 → span 降级为 quote_hash only + source_message_id NULL（测试断言覆盖降级路径）。
- 报告版本化的「读最新」已由 `get_report_by_session ORDER BY created_at DESC LIMIT 1` 满足——版本化不破坏现有读路径，只改写路径（DELETE→INSERT 新版本）。
- 七项校验的「文案无录用判断表述」——现有报告文案由 LLM 生成（REPORT_SYSTEM），校验落在「报告 JSON 不含录用/排名类词表」；LLM 违规则 FAILED（与 D-002 范围红线一致）。
- 发布前 review_status 满足性：required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED → admin 复核 review_outcome=CONFIRMED 后方可 publish；无 required 缺失 → 生成即 READY → 可直接 publish。

</specifics>

<deferred>
## Deferred Ideas

- trace 保留期/脱敏细节（§31-5）——Phase 6 数据治理
- 补算复核阈值的真实校准（§31-3）——实施期校准，关口包呈报
- 综合题 integrated measurement_source 的 item_measurement 实现（REF-3.9 延后）
- score_live/score_final 双分背离 bad case 自动候选（REF-5.11）——Phase 6
- admin 报告发布/人工复核的完整前端 UI（若本 phase 仅最小前端，完整 UI 随 Phase 6 E2E 收口）
- 报告版本的历史浏览/对比 UI（VersionHistory.vue 已存在，报告版本对比是否并入该 UI 属 Phase 6 E2E 收口裁量）

</deferred>

---

*Phase: 5-证据链与报告契约*
*Context gathered: 2026-09-05*
