# Phase 2: 动态选题与有界循环 - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

把测评运行时按 SSOT §10/§11 落地：废除 create_session 一次性预选，改为每 `action=next` 由代码按四层顺序动态选题（合法性过滤 → required 硬约束 → 配额 → 排序），selection_reason 落库可审计；难度路径状态机（升/降/滞回恢复/跳级禁止）由代码执行并写 DIFFICULTY_* 事件；interviewer 拆为两层（LLM 结构化观察 answer_state 11 态 + 证据维度，代码裁决下一步与 score_value分级）；拒答经一次确认后跳过且记 REFUSED（score_value=0 不进能力等级分母）；followup ≤2 代码硬约束；评分链废除 score_live/score_final 50/50 合成、客观题 answer_key 为空判题库无效、权重口径修正 7:3（config 旧 55/20/20/5 作废）；表结构演进内嵌本阶段（assessment_question 动态实例列 / question_score 统一 score_final / question_bank observable_level 锚点列 + measurement_mode 区分）。

对应 REQUIREMENTS.md：REF-1.3, REF-1.6, REF-1.7, REF-2.7, REF-2.9, REF-3.1, REF-3.2, REF-3.6, REF-3.7, REF-4.1, REF-4.2, REF-4.3, REF-4.4, REF-4.5, REF-5.1, REF-5.2, REF-5.3, REF-5.7, REF-8.1（19 项，支撑 REQ-dynamic-question-generation / REQ-interactive-multiturn-assessment）。

**不在本阶段**：表单/SSE/幂等/计时（Phase 3，SCORING 中间态随 REF-2.6 状态机 Phase 3 落）；题库 model/version 绑定主体与生成失败可见（Phase 4）；证据 span/trace_link/item_measurement 裁决/报告状态机（REF-2.9 的 human_override 列随 Phase 5；item_measurement 表 Phase 5）；迁移体系收口 schema_version（Phase 6）；综合题槽位与等值组（REF-3.8/3.9 登记不排期）。

</domain>

<decisions>
## Implementation Decisions

> 以下 D-14~D-2x 为 Phase 2 编号（接续 Phase 1 的 D-01~D-13）。逐项产生于 2026-09-03 灰区分析（auto 模式推荐项选取，留痕见 02-DISCUSSION-LOG.md），每条依据为 SSOT 条款/已决事项/代码现状三者之一，无臆造项。

### 表结构演进与迁移（计划 02-01）
- **D-14: 迁移形态 = ALTER ADD COLUMN + 代码校验，不重建表。** question_bank 补齐 v2.0 列（model_id/model_version/item_id/question_type/measurement_stage/measurement_target/evidence_requirement/observable_level_max/min/rubric_version）、assessment_question 补动态实例列（question_type/measurement_stage/item_id/difficulty/status/activated_at/closed_at/followup_count/seal_reason/selection_reason/selection_policy_version/path_state_snapshot）、question_score 统一 score_final——全部 ALTER ADD COLUMN，新列不带 DB CHECK（N11 枚举代码校验）；旧列已有 CHECK（category 三态、qtype 两态）不改不删。理由：现有 SQLite 业务库须平滑直升；schema_version 登记簿属 Phase 6（各阶段内嵌迁移随阶段走，届时只登记）。
- **D-15: 旧数据不回头迁移。** question_score 旧 `final_score` 列迁移合并（本质是数据搬运一次，在 02-01 DDL 迁移函数内完成）；旧会话/旧 assessment_question 行保持可读（新列默认 NULL/‘legacy’ 语义不参与新选选题路径）；业务库 data/app.db 的任何写入只在正式运行时发生（红线 2：测试永用 /tmp/ 临时库）。演示数据允许重跑生成。
- **D-16: 权重 7:3 修正的落点 = config.CATEGORY_RATIO 更新 + aggregate.py `_compute_weights` 跟随 + aggregation.py 确认不二次乘大类比例（现状已如此，加回归断言锁死）。** 存量 confirmed 模型**不自动重算** weight——分数是历史事实（D-003）、confirmed 模型不被静默覆盖（§8.3）；02-01 后新聚合产出的模型自动用 7:3。旧口径模型经 Phase 4 题库升版重建自然退役。

### 动态选题（计划 02-02）
- **D-17: 四层选题的执行体 = services/question_selection.py 全量重写为新函数 select_next_question(session_id)，create_session 不再预选。** 每层顺序严格按 §10.6：①合法性过滤（题库 status='active'、模型版本匹配 [Phase 4 前用 position 归属近似]、未用实例、路径合法）→ ②required 硬约束（未覆盖 required 优先）→ ③配额（7:3 大类 + tier 公式实时计算剩余）→ ④排序（chain 后继 → item.weight → 稳定随机种子）。**「题目质量」分项本期显式禁用**（SSOT 无质量指标定义，臆造违反 §31 开放参数红线；三键排序已确定性可审计）——DECISIONS 记录该禁用，属计划层裁量非 SSOT 变更。
- **D-18: selection_reason = 结构化 JSON 落 assessment_question.selection_reason。** 四层命中记录 {layer, predicate, category, tier, chain_followed, weight, seed} 形态，机器可解析（Phase 5 证据链/报告、Phase 6 E2E 断言消费）；中文可读描述留给报告展示层生成。SC-1 「可审计」以 JSON 结构为准。
- **D-19: 配额计算从 CATEGORY_QUOTA{hard:6,soft:2,exp:2} 换为岗位级 N + 7:3 + tier 公式（§10.1–10.3 全公式落地）。** N 默认值 = SSOT §31 开放参数：**code 内落 config.ORDINARY_PLAN_N 常量但具体数值交关口包呈现用户裁决**（不臆造）。experience/qualification 从普通选题剔除（readiness 配额检查同步换公式，D-11 no-op 位填充）。required 刚性例外（§10.5：每 item 最多一次、仅 medium/hard）实现在普通计划耗尽后的补选题分支。

### 难度状态机（计划 02-03）
- **D-20: 路径状态载体 = assessment_question.path_state_snapshot JSON 列（§12.2 列名即承载意图）。** item 级难度状态（当前难度、连续未达锚点计数、恢复滞回计数、是否已用例外）持久在 session 运行上下文；DIFFICULTY_RAISED/LOWERED/RESTORED 事件与快照同事务写入（复用 append_event helper，D-06）。不建新表、不做实时派生查询（跨实例聚合不可审计）。
- **D-21: 升降级判据 = §11.2 原文逐条代码化。** easy→medium 一次充分证据；medium→hard 充分且稳定 + 仅 target_level>4 的 item；降级仅统计有效候选人证据失败（同 item 同难度连续两道有效题未达最低锚点/followup 后仍模糊）；恢复滞回（连续两次充分或一次稳定）；一次实例内不升降级；跳级默认禁止（PATH_UNAVAILABLE → 标记不静默）。「不计入普通失败」七类清单（技术/无障碍/题目无效/模型不确定/合理质疑/明确拒答/攻击性事件）由 answer_state 分类驱动排除，与 D-22 联动。

### 回答状态分类两层化（计划 02-04）
- **D-22: interviewer 两层化 = 观察层 LLM 输出结构化 JSON（answer_state 11 态之一 + 证据观察维度 relevance/specificity/attribution/span 等），裁决层代码按 §11.3/§11.4 固定规则计算 evidence_sufficient/stable_evidence 布尔并决定 action。** LLM 输出走严格 Pydantic schema 校验（schemas.py 新增 InterviewObservation），非法输出降级 NEED-model-uncertain 路径不卡死会话（§11.5 精神，错误处理 Phase 3 补全）。decide_next_action 单函数签名保留（API 面 downstream 不动），内部拆两步。
- **D-23: mock 双轨制。** _mock_interview 重写为规则分类器（回答长度 <20 字→NEED_CLARIFICATION、含拒答关键词→DECLINED、含「举例/项目/具体」实义词→VALID_EVIDENCE rough 判定），其与真实模式共用同一 Pydantic 输出契约与裁决层——即 **mock 模拟的是「观察输出」而非「绕过裁决」**，离线全流程可跑（D-005）且分类语义可测试。真实模式 prompt 重构属 Prompt 模块周期（D-030 接口保留），本 phase 只改 schema 与裁决层结构。
- **D-24: 拒答处理 = 一次确认后跳过且记 REFUSED。** answer_state=DECLINED 时代码触发确认话术（SUPPORT/control 类文案，一次性），二次仍 DECLINED → 封存当前实例（seal_reason='refused'）+ score_state=REFUSED + score_value=0（特殊状态值不进能力等级分母 D-013）+ 事件留痕。不再提供末尾补答。
- **D-25: followup ≤2 维持 config.FOLLOWUP_MAX 硬约束（现状已合规），计数迁移到实例内 followup_count 列。** 实例封存语义（closed_at + seal_reason）覆盖 next/finish/refused/timeout 四路，单题超时封存属 Phase 3 计时（本期只留 seal_reason 枚举位）。

### 评分链修正（计划 02-05）
- **D-26: 50/50 合成废除 = scoring.py 删 final = round(score_live*0.5 + score_final*0.5) 路径，score_final 独立落库。** score_live 列保留（导航与偏差分析用途，D-12），question_score 统一 score_final 列后 `_latest_score_live` 只作参考值写 score_live 列不参与任何 final 计算。聚合 aggregation.py 的 actual 取数从 final_score 切到 score_final。
- **D-27: answer_key 为空客观题判题库无效。** _score_objective 现行「缺失→按最低分记 1 分」（Phase 1 WR-14 已改）升级为 score_state=INVALIDATED 语义（该题不进正常分母、产生缺失警告，走 Phase 5 IMPUTED 补算链路的前置条件）；题库生成侧的 CR-01 降级（objective 无 key 转 subjective）保持。
- **D-28: score_state 分母规则 = §12.4 原文。** SCORED 进正常观察；REFUSED 不进能力等级分母（只进行为/完整度聚合）；INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED/INVALIDATED/INCOMPLETE 不进正常分母产生缺失/警告。系统错误与题目无效不转普通低分。

### 开放参数（呈报项，非本 phase 决定）
- **N 默认值（ORDINARY_PLAN_N）**：SSOT §31-1 开放参数「实施期结合 40 分钟体验测定」——**关口包呈现，用户裁决**（影响 02-02 的 config 落值与测试种子）。

### Claude's Discretion
- 02-01 各新列的默认值填充与迁移函数具体形态（对齐 _migrate_* 既有手写嗅探式惯例——注意 N11 原则下新列避免 CHECK）
- 路径状态 snapshot 的 JSON 内部结构（字段命名自由，承载 §11.2 判据所需计数器即可）
- 测试文件组织（沿用 M5 的 pytest+TestClient 风格 + mock 双模式断言；新增文件须 pytest 可收集且不与既有模块同进程共库）
- 7:3 与 tier 公式的单元测试边界用例选择（覆盖 §10.2 表格四行 + 单类目岗位退化情形）

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 设计权威（SSOT）
- `design/final-design/总设计文档.md` §8.2 — 7:3 权重口径（两层结构 + tier 语义 + 现有大类归一原则）
- `design/final-design/总设计文档.md` §9.1–9.4 — 题库分类树（普通题仅 hard/soft 两类三层 tier）/ question_bank 演进后 DDL / 等值组边界 / 难度-等级锚点映射 [2,3]/[3,4]/[4,5]
- `design/final-design/总设计文档.md` §10.1–10.6 — 题量计数（N/E/I/followup）/ 7:3 最大余数 / tier 0.8/0.6/1.7 公式 / 开考检查 / required 刚性例外 / 四层选题执行顺序
- `design/final-design/总设计文档.md` §11.1–11.5 — 实例模型（动态实例化 + followup 子轮次）/ 难度路径状态机全文 / 证据判定（evidence_sufficient/stable_evidence）/ answer_state 11 态 + score_state 8 态 / SSE 契约（SSE 属 Phase 3，但两层化输出契约此处定义）
- `design/final-design/总设计文档.md` §12.1–12.5 — assessment_session/assessment_question/assessment_message/question_score 演进列清单 / 分母规则 / 原文 hash 单 session 限制
- `design/final-design/总设计文档.md` §13.2 — 事件枚举（QUESTION_*/OBSERVATION_* 为本 phase 激活组）
- `design/final-design/总设计文档.md` §17–18 — 评分链（score_live 仅导航 50/50 作废）/ 拒答 REFUSED=0
- `design/final-design/总设计文档.md` §31 — 开放参数清单（N 默认值 = 关口包呈报项）

### 证据基线（gap matrix 与已决事项）
- `research/ssot-code-gap-matrix.md` — 68 行契约核对（Phase 2 相关行：矩阵 §1/§2/§3/§4/§5 对应 REF-1.3~8.1）
- `.planning/intel/decisions.md` D-006~D-016 — 权重/配额/选题/难度/评分链/拒答/例外全部锁定级决策全文
- `.planning/phases/01-p0/01-CONTEXT.md` — Phase 1 已决（D-05/06/07 事件体系、D-09 测试断言面、D-11 readiness no-op 位、D-13 409 契约）

### 代码现状（改造对象与既有约定）
- `server/services/question_selection.py` — 一次性预选现行实现（全量重写对象；CATEGORY_QUOTA 废除）
- `server/services/interview.py` — 单层决策现行实现（两层化对象；FOLLOWUP_MAX 护栏保留）
- `server/services/scoring.py` — 50/50 合成现行实现（删除对象；WR-14/CR-01 防护保留）
- `server/services/readiness.py` — 开考检查（第 5 步配额公式换新 + 第 6 步综合题 no-op 留空 [Phase 4] + 第 7 步表单 no-op 留空 [Phase 3]）
- `server/api/assessment.py` — create_session/submit_answer 主链（选题调用点迁移 + 决策消费面）
- `server/services/state_events.py` — append_event helper（DIFFICULTY_*/QUESTION_* 事件复用入口）
- `server/config.py` — CATEGORY_RATIO 旧口径（作废对象）+ 新增 ORDINARY_PLAN_N 落点（N 默认值）
- `server/db.py` — _DDL 与手写迁移惯例（ALTER 路径参照 _migrate_* 系）
- `.planning/codebase/ARCHITECTURE.md` — 分层/SQLite 单写者两模式/反模式清单
- `.planning/codebase/TESTING.md` — 测试纪律（单文件单进程/mock 约定/新测试 checklist）

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/state_events.py:14` append_event — DIFFICULTY_*/QUESTION_SELECTED/ACTIVATED/SEALED 事件单点入口（调用者持事务、不 commit 的契约不变）
- `server/services/pipeline.py:14-19` new_id/now_iso — 新实例/新行复用
- `server/schemas.py` — Pydantic v2 LLM 输出模型惯例（ExtractResult/DisambiguateResult 先例，InterviewObservation 照此加）
- `server/services/scoring.py:107-154` — 「内存算完单事务落库」模式（新分类/裁决逻辑涉及 LLM 观察调用时遵守）
- `server/api/assessment.py:167` — 「先 commit 再调 LLM」模式（submit_answer 改造遵守）
- `server/services/readiness.py` — D-11 骨架与 no-op 位（第 5 步填新公式）

### Established Patterns
- raw SQL + get_conn() per-call + 显式 commit（无 ORM）——新选题/状态机服务同风格
- 状态机 TEXT 列 + 代码驱动迁移（assessment_question.status/seal_reason 沿用）
- mock 模式：每服务 _mock_* 相邻定义、解析 user prompt 产确定性输出（D-23 重写 _mock_interview 仍遵守此签名惯例）
- DDL 迁移：手写字符串嗅探式（_migrate_llm_trace 先例）——02-01 的 ALTER 路径照此（但避免 3rd DDL 拷贝膨胀，新列 ALTER 不重建表）

### Integration Points
- `server/api/assessment.py` create_session — 删一次性预选 INSERT 循环，改 readiness 检查后直建 session（首题在首次 get/answer 时由 select_next_question 派发）
- `server/api/assessment.py` submit_answer — decision 消费面切两层化输出；next 时调 select_next_question（替代 ORDER BY seq LIMIT 1）
- `server/services/interview.py` decide_next_action — 签名保留内部两层化；_mock_interview 重写
- `server/services/scoring.py` score_session/score_question — 合成路径删除、score_state 写入、item 匹配跳过语义改（通用题 std_name 无 item 不再静默跳过——按 v2.0 题库 item_id 绑定后天然消失）
- `server/services/aggregation.py` — actual 取数切 score_final 列
- `server/config.py` — CATEGORY_RATIO 改 0.7/0.3/0/0 + 新增 ORDINARY_PLAN_N（值待关口包）
- `server/api/admin/eval.py` + `eval/*` — mock 分类器改动影响 virtual_candidates 的行为种子（断言联动改）

</code_context>

<specifics>
## Specific Ideas

- 旧版中「commpleted 护栏」与状态机演进无冲突，不重开（Phase 1 D-09/D-10）。
- 一切新枚举（answer_state/score_state/seal_reason/question_type/measurement_stage）在代码层校验（N11），不引 DB CHECK——旧表已有 CHECK 不动。
- 提交留痕的事件行含 phase2 新枚举时，payload 里带判据摘要（如 DIFFICULTY_LOWERED 的 evidence_counts），报告/审计可解释。
- Phase 1 已写 QUESTION_ANSWERED 语义稳定，本 phase 保持（不改为 ANSWER_RECEIVED——枚举语义变更属 SSOT 层面动作，无必要不动）。

</specifics>

<deferred>
## Deferred Ideas

- ** RESEARCH 若发现 question_bank 列改造量超大 → 可评估一次性重建该表 vs 纯 ALTER**——属 plan 层裁量（D-001 无 SSOT 冲突），plan 阶段定。
- 综合题/等值组实现（REF-3.8/3.9）——登记不排期，待用户恢复排期。
- 「题目质量」排序分项的真实指标 —— 若未来 SSOT 校准后定义，可作为独立小改动回来补第四层排序键。
- 真实模式 interviewer prompt 重构 —— Prompt 模块周期（D-030），本 phase 只动 schema 与裁决层。

</deferred>

---

*Phase: 2-动态选题与有界循环*
*Context gathered: 2026-09-03*
