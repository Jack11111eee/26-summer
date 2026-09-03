# Phase 2: 动态选题与有界循环 - Research

**Researched:** 2026-09-04
**Domain:** SQLite 内嵌迁移（ALTER ADD COLUMN）/ 四层动态选题（7:3 最大余数 + tier 0.8/0.6/1.7 公式）/ 难度路径状态机 / interviewer 两层化（Pydantic 结构化观察 + 代码裁决）/ 评分链契约修正（50/50 废除、score_state 分母）
**Confidence:** HIGH

## Summary

Phase 2 是 SSOT v2.0 差距矩阵中最重的结构性阶段（19 项 REF），但**零新增框架/零新增包**——全部工作落在现有分层（router → service → raw SQL → 纯 Python 状态机）内。研究逐文件核对了四个改造对象的现状：`question_selection.py`（67 行，一次性预选 + `CATEGORY_QUOTA{hard:6,soft:2,exp:2}` 硬编码，全量重写对象）、`interview.py`（116 行，单层 LLM 决策 + 规则护栏，两层化对象但**签名保留**）、`scoring.py:172-177`（三行 50/50 合成路径 + `_latest_score_live`，删除对象）、`config.py:25-30`（`CATEGORY_RATIO 5.5/2.0/2.0/0.5` 旧口径，作废对象）。SSOT §8.2/§9/§10/§11/§12/§13/§17/§18 的公式与判据已逐条摘录为可代码化规格（见 Code Examples），无遗留灰色条款——**唯一开放参数是 N 默认值（SSOT §31-1），已在 CONTEXT.md 明确"关口包呈现用户裁决"，研究不做任何数值假设**。

关键技术机制已在本地实测验证（Python 3.13.2 / SQLite 3.45.3 / FastAPI 0.141.1 / pytest 9.1.1 / pydantic 2.10.3）：①`ALTER TABLE ADD COLUMN` 支持常量 DEFAULT（含 `NOT NULL DEFAULT 'legacy'`），拒绝非常量表达式默认——锚点回填必须走 `UPDATE ... SET CASE difficulty ...` 两步；②SQLite 3.45（≥3.35）支持 `DROP COLUMN`，`question_score.final_score` 迁移合并（`UPDATE SET score_final=COALESCE(final_score,score_final)` → `DROP COLUMN final_score`）本机实测可行且不影响其余列；③老库重建路径完全不必要——question_bank 现有 15 列 + 演进 12 新列 = 27 列全 ALTER 可达（对照 deferred idea"重建 vs ALTER"：ALTER 无争议胜出）；④Pydantic v2 `Literal[...]` 对 answer_state 11 态校验实测可靠（非法值抛 `ValidationError` 带 `literal_error` 类型，loc 可定位字段）；⑤`(session_id, sequence_no)` 唯一性只能用 `CREATE UNIQUE INDEX`（§12.2 唯一约束不在新列上，实测 ADD COLUMN 不能带 UNIQUE）；⑥业务库 data/app.db 现存 16 条 assessment_question / 8 条 question_score（含 final_score=score_final 同值），迁移量微小且演示数据允许重跑。

**Primary recommendation:** 严格按 5 个 plan 的既定切分落地：02-01 全 ALTER 迁移（三表 _migrate_* 嗅探式 + DEFAULT 填充 + score_final 合并一次完成）+ 7:3 三落点（config/aggregate/aggregation）；02-02 `select_next_question(session_id)` 全量重写按 §10.6 严格四层 + selection_reason 结构化 JSON；02-03 `path_state_snapshot` JSON 载体 + 纯函数状态机 + DIFFICULTY_* 事件同事务；02-04 `InterviewObservation` Pydantic schema + 裁决层纯函数 + `_mock_interview` 重写为规则分类器（共享契约）；02-05 three-line 合成路径删除 + INVALIDATED 语义 + 分母规则落 `aggregate_session_scores`。全程不改 `decide_next_action` 签名、不改既有 409 契约、不动 Phase 3+ 的 no-op 占位。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### 表结构演进与迁移（计划 02-01）
- **D-14: 迁移形态 = ALTER ADD COLUMN + 代码校验，不重建表。** question_bank 补齐 v2.0 列（model_id/model_version/item_id/question_type/measurement_stage/measurement_target/evidence_requirement/observable_level_max/min/rubric_version）、assessment_question 补动态实例列（question_type/measurement_stage/item_id/difficulty/status/activated_at/closed_at/followup_count/seal_reason/selection_reason/selection_policy_version/path_state_snapshot）、question_score 统一 score_final——全部 ALTER ADD COLUMN，新列不带 DB CHECK（N11 枚举代码校验）；旧列已有 CHECK（category 三态、qtype 两态）不改不删。理由：现有 SQLite 业务库须平滑直升；schema_version 登记簿属 Phase 6（各阶段内嵌迁移随阶段走，届时只登记）。
- **D-15: 旧数据不回头迁移。** question_score 旧 `final_score` 列迁移合并（本质是数据搬运一次，在 02-01 DDL 迁移函数内完成）；旧会话/旧 assessment_question 行保持可读（新列默认 NULL/'legacy' 语义不参与新选选题路径）；业务库 data/app.db 的任何写入只在正式运行时发生（红线 2：测试永用 /tmp/ 临时库）。演示数据允许重跑生成。
- **D-16: 权重 7:3 修正的落点 = config.CATEGORY_RATIO 更新 + aggregate.py `_compute_weights` 跟随 + aggregation.py 确认不二次乘大类比例（现状已如此，加回归断言锁死）。** 存量 confirmed 模型**不自动重算** weight——分数是历史事实（D-003）、confirmed 模型不被静默覆盖（§8.3）；02-01 后新聚合产出的模型自动用 7:3。旧口径模型经 Phase 4 题库升版重建自然退役。

### 动态选题（计划 02-02）
- **D-17: 四层选题的执行体 = services/question_selection.py 全量重写为新函数 select_next_question(session_id)，create_session 不再预选。** 每层顺序严格按 §10.6：①合法性过滤（题库 status='active'、模型版本匹配 [Phase 4 前用 position 归属近似]、未用实例、路径合法）→ ②required 硬约束（未覆盖 required 优先）→ ③配额（7:3 大类 + tier 公式实时计算剩余）→ ④排序（chain 后继 → item.weight → 稳定随机种子）。**「题目质量」分项本期显式禁用**（SSOT 无质量指标定义，臆造违反 §31 开放参数红线；三键排序已确定性可审计）——DECISIONS 记录该禁用，属计划层裁量非 SSOT 变更。
- **D-18: selection_reason = 结构化 JSON 落 assessment_question.selection_reason。** 四层命中记录 {layer, predicate, category, tier, chain_followed, weight, seed} 形态，机器可解析（Phase 5 证据链/报告、Phase 6 E2E 断言消费）；中文可读描述留给报告展示层生成。SC-1 「可审计」以 JSON 结构为准。
- **D-19: 配额计算从 CATEGORY_QUOTA{hard:6,soft:2,exp:2} 换为岗位级 N + 7:3 + tier 公式（§10.1–10.3 全公式落地）。** N 默认值 = SSOT §31 开放参数：**code 内落 config.ORDINARY_PLAN_N 常量但具体数值交关口包呈现用户裁决**（不臆造）。experience/qualification 从普通选题剔除（readiness 配额检查同步换公式，D-11 no-op 位填充）。required 刚性例外（§10.5：每 item 最多一次、仅 medium/hard）实现在普通计划耗尽后的补选题分支。

### 难度状态机（计划 02-03）
- **D-20: 路径状态载体 = assessment_question.path_state_snapshot JSON 列（§12.2 列名即承载意图）。** item 级难度状态（当前难度、连续未达锚点计数、恢复滞回计数、是否已用例外）持久在 session 运行上下文；DIFFICULTY_RAISED/LOWERED/RESTORED 事件与快照同事务写入（复用 append_event helper，D-06）。不建新表、不做实时派生查询（跨实例聚合不可审计）。
- **D-21: 升降级判据 = §11.2 原文逐条代码化。** easy→medium 一次充分证据；medium→hard 充分且稳定 + 仅 target_level>4 的 item；降级仅统计有效候选人证据失败（同 item 同难度连续两道有效题未达最低锚点/followup 后仍模糊）；恢复滞回（连续两次充分或一次稳定）；一次实例内不升降级；跳级默认禁止（PATH_UNAVAILABLE → 标记不静默）。「不计入普通失败」七类清单（技术/无障碍/题目无效/模型不确定/合理质疑/明确拒答/攻击性事件）由 answer_state 分类驱动排除，与 D-22 联动。

### 回答状态分类两层化（计划 02-04）
- **D-22: interviewer 两层化 = 观察层 LLM 输出结构化 JSON（answer_state 11 态之一 + 证据观察维度 relevance/specificity/attribution/span 等），裁决层代码按 §11.3/§11.4 固定规则计算 evidence_sufficient/stable_evidence 布尔并决定 action。** LLM 输出走严格 Pydantic schema 校验（schemas.py 新增 InterviewObservation），非法输出降级 NEED-model-uncertain 路径不卡死会话（§11.5 精神，错误处理 Phase 3 补全），decide_next_action 单函数签名保留（API 面 downstream 不动），内部拆两步。
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

### Deferred Ideas (OUT OF SCOPE)
- ** RESEARCH 若发现 question_bank 列改造量超大 → 可评估一次性重建该表 vs 纯 ALTER**——属 plan 层裁量（D-001 无 SSOT 冲突），plan 阶段定。**[本研究已核：15 现有列 + 12 新列均可 ALTER，量不超大——见 Common Pitfalls #1 的实测结论，无需重建]**
- 综合题/等值组实现（REF-3.8/3.9）——登记不排期，待用户恢复排期。
- 「题目质量」排序分项的真实指标 —— 若未来 SSOT 校准后定义，可作为独立小改动回来补第四层排序键。
- 真实模式 interviewer prompt 重构 —— Prompt 模块周期（D-030），本 phase 只动 schema 与裁决层。

## Project Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REF-1.3 | score_live 由 LLM 直产 1-5 分 → 随 §17 重构（见 REF-5.1） | score_live 生产点在 `decide_next_action` 返回值（interview.py:113）+ mock 给 2/3；重构后归入两层化的观察层、仅导航消费；§17 修正见 D-26 |
| REF-1.6 | 单步"LLM 直接决定 action"重构为观察/裁决两层（§11.3/§11.4） | interview.py 现单层结构逐行核对；`InterviewObservation` Pydantic 模型设计（Code Examples #4）；decide_next_action 签名保留（D-22） |
| REF-1.7 | LLM 不决定难度迁移/finish | finish 护栏现状合规（is_last 强制）；难度迁移全新实现为代码状态机（D-20/21），LLM 输出仅观察维度不输出 action |
| REF-2.7 | assessment_question 演进（动态实例列/封存/selection_reason/路径快照；(session_id,sequence_no) 唯一） | 12.2 新列清单全文核对；现有表 6 列 + 新 13 列 ALTER 可达；`seq`→`sequence_no` 命名决策（见 Open Questions Q2）；唯一索引 CREATE UNIQUE INDEX 实测路径 |
| REF-2.9 | question_score 演进（统一 score_final 废弃 final_score、score_state、override 列） | 现有 final_score/score_final 双列实测确认；合并迁移两步法实测（UPDATE COALESCE + DROP COLUMN ≥3.35）；human_override 列随 Phase 5（CONTEXT 明确） |
| REF-3.1 | 岗位级 N + 7:3 最大余数 + tier 0.8/0.6/1.7 公式 | §10.2/§10.3 全公式 + 四行样例表转入 Code Examples #1#2；ceil 边界规则（不超过大类总量、小数相等归 hard）有 SSOT 原文 |
| REF-3.2 | 四层动态选题替换 create_session 一次性预选 | create_session:104-110 INSERT 循环为删除对象；select_next_question 新函数设计 + 消费点（get_session 首题派发 / submit_answer next 分支）逐一核对 |
| REF-3.6 | required 刚性例外（每 item 最多一次、仅 medium/hard） | §10.5 全文核对；实现位置 = 普通计划耗尽后补选题分支（D-19）；REQUIRED_EXCEPTION_GRANTED 事件枚举在 §13.2 |
| REF-3.7 | 难度→1-5 等级锚点映射（observable_level 列） | §9.4 三行锚点表（easy[2,3]/medium[3,4]/hard[4,5]）；question_bank 新列 observable_level_max/min 的 CASE UPDATE 回填已实测（Pitfall #1） |
| REF-4.1 | 动态实例化（每呈现题面新实例；followup 为实例内子轮次） | followup_count 新列计迁移（D-25）；现 `_count_followups` 按消息表 COUNT 的实现为替换对象；followup question_id 不变已在现流程天然成立 |
| REF-4.2 | 难度路径状态机（升/降/滞回恢复；不计普通失败；跳级禁止） | §11.2 全判据逐条分解为状态机输入/转移/事件（Code Examples #3）；path_state_snapshot JSON 结构（Claude 裁量）已给出建议形态 |
| REF-4.3 | evidence_sufficient/stable_evidence 结构化观察维度 + 代码布尔裁决 | §11.3 七个观察维度 + 排除清单全文核对；裁决条件代码化设计（D-22）；stable_evidence 依赖跨实例聚合（见 Pitfall #6 跨实例语义） |
| REF-4.4 | answer_state 11 态 + score_state 8 态两层分离 | §11.4 枚举清单全文核对；Pydantic Literal 校验实测；score_state 8 态中 IMPUTED/HUMAN_REVIEW_REQUIRED 属 Phase 5（CONTEXT D-27 限定 SCORED/REFUSED/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED/INVALIDATED/INCOMPLETE） |
| REF-4.5 | 各状态处理原则（拒答一次确认/技术暂停计时/边界设定等） | §11.4 处理原则清单引用；Phase 2 落地项 = 拒答 confirm-then-skip（D-24）+ 模型不确定降级（D-22）；计时/暂停属 Phase 3 |
| REF-5.1 | score_live 仅导航；废弃 50/50 合成 | scoring.py:172-177 合成路径 + aggregation.py:74/79/118 final_score 消费点 + test_m5:290 断言三处确认；删除后报告链（report.py:39 final_score SELECT）同步切列 |
| REF-5.2 | 客观题 answer_key 空属题库缺陷 → 判题库无效 | _score_objective WR-14 防护现状（1 分兜底）确认；升级为 INVALIDATED 语义后 score_session 跳过方向 + 且该题不写 5 分也不写 1 分（脱离普通评分通道） |
| REF-5.3 | 拒答 REFUSED=0 特殊状态值，不进能力等级分母 | D-24 + D-28 联动设计；aggregation.py 分母切 score_state 过滤的实现点（aggregate_session_scores:73-79） |
| REF-5.7 | 7:3 权重口径修正 + 模块三直接复用 item.weight 不二次乘 | config.py:25-30 旧口径 + aggregate.py:81-98 _compute_weights 消费点 + aggregation.py:121 （actual/5 无二次乘，合规确认）；新模型 7:3 自动生效 + 存量不重算（D-16） |
| REF-8.1 | 空 answer_key 客观题恒满分漏洞（并入 REF-5.2） | Phase 1 WR-14 已堵（低分），Phase 2 语义升级 INVALIDATED；测试需覆盖「无效题不进分母」的新断言 |
</user_constraints>

## Project Constraints (from CLAUDE.md)

- **Think Before Coding**：不臆测；不确定就问；多种解释并存时列出不默选——**N 默认值是本 phase 最典型的"不臆造"红线**（SSOT §31-1）。
- **Simplicity First**：最小代码解决问题。四个新服务函数（select_next_question / 裁决层 / 状态机 / 分母过滤）均为 CONTEXT 已锁定职责，不属 speculative；selection_reason 字段按 D-18 最小集 {layer, predicate, category, tier, chain_followed, weight, seed}。
- **Surgical Changes**：只改必须改的；匹配既有风格（中文 docstring、raw SQL `?` 参数化、`status.HTTP_*`、`# noqa: E402`、mock _mock_* 相邻定义）。旧测试只改断言不重构（D-09 前例）。
- **Goal-Driven Execution**：成功标准 1–5 即现成验收口径，每条映射到 Validation Architecture 的测试行。
- **Git**：commit every working-tree change；当前分支 `feature/m5-assessment` 直接推进（charter 锁定不建分支）。
- **SSOT 治理（本仓库 CLAUDE.md）**：本 phase 全部规格来自 SSOT 既有条款（§8.2/§9/§10/§11/§12/§13/§17/§18），**不需修改 SSOT**——「题目质量」禁用属计划层裁量已在 DECISIONS 留痕。任何研究发现与 SSOT 冲突时以 SSOT 为准。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 表结构演进（ALTER 迁移） | 数据库层（db.py `_migrate_*` + `_DDL` 同步更新） | — | D-14 锁定内嵌迁移；`_DDL` 需同步加新列（IF NOT EXISTS 建新库直含新列，老库走迁移嗅探） |
| 7:3 权重口径 | 配置层（config.CATEGORY_RATIO）→ 模块一聚合（aggregate._compute_weights） | aggregation.py（不二次乘的回归断言） | D-16 三落点；模块三复用 item.weight 是消费侧断言 |
| 四层动态选题 | Service 层（question_selection.select_next_question） | API 层（create_session 删预选 / submit_answer next 分支 / get_session 首题派发） | §10.6 代码执行可审计；API 层只做调用点编排 |
| 配额公式（N + 7:3 + tier） | Service 层（question_selection 内纯函数） | readiness.py 第 5 步（同公式复检） | 同一公式两处消费（recommend 提取共享函数防漂移，见 Pitfall #4） |
| required 刚性例外 | Service 层（普通计划耗尽后的补选分支） | — | §10.5；事件 REQUIRED_EXCEPTION_GRANTED |
| 难度路径状态机 | Service 层（纯函数判据 + path_state_snapshot 读写） | db.py（列 DDL）+ state_events（DIFFICULTY_* 事件） | 代码唯一状态机（D-003）；事件与快照同事务（§13.1） |
| 结构化观察（answer_state 分类） | Service 层 + LLM 层（interviewer 观察层经 call_llm_json） | schemas.py（InterviewObservation Pydantic） | REF-1.6 两层化；LLM 只出观察不决定 action |
| 代码裁决（evidence_sufficient/stable_evidence 布尔） | Service 层（纯函数） | — | §11.3 代码按固定条件计算；不进 LLM |
| 拒答处理（confirm→skip） | Service 层（裁决层分支）+ 封存（closed_at/seal_reason） | scoring（REFUSED=0）+ aggregation（分母排除） | D-24 跨三处但语义单一；score_state 写入属 02-05 |
| 评分链修正（50/50 废除） | Service 层（scoring.py 删合成 + score_state 写入） | aggregation.py（取数切列 + 分母规则）+ report.py（final_score SELECT 切换） | D-26/D-27/D-28；报告链是隐藏消费面（Pitfall #5） |
| followup 硬约束 | Service 层（现有 ação 护栏保留）+ 新 followup_count 列 | — | D-25；现状已合规只迁计数位置 |
| 事件留痕（DIFFICULTY_*/QUESTION_*/OBSERVATION_*） | state_events.append_event（复用） | 各调用点（持事务不 commit） | D-06 Phase 1 既有契约不变 |
| 测试证明 | 测试层（server/test_*.py pytest+TestClient） | — | 成功标准 1-5 要求可测试证明；单文件单进程纪律 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlite3（stdlib） | SQLite 3.45.3 | ALTER ADD COLUMN / DROP COLUMN 迁移 / UNIQUE INDEX / 全部查询 | 既有栈；ALTER 行为已本机实测（见 Pitfall #1） [VERIFIED: 本机运行验证 + SQLite 官方文档] |
| FastAPI | 0.141.1（已装） | API 层、BackgroundTasks、HTTPException | 既有栈；零新依赖 [VERIFIED: 本机 `import fastapi`] |
| pydantic | 2.10.3（已装） | `InterviewObservation` LLM 输出强 Schema（Literal 11 态 + 观察维度） | schemas.py 既有惯例（ExtractResult 等先例）；Literal 校验实测 [VERIFIED: 本机运行验证] |
| pytest | 9.1.1（已装） | 新测试 + 既有断言重写 | M5/M7 既有风格；单文件单进程 [VERIFIED: 本机 `pytest --version`] |
| fastapi.testclient（httpx 传递） | — | API 级集成测试 | 既有模式（同一 client 全流程） |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json（stdlib） | — | selection_reason / path_state_snapshot 序列化 | D-18/D-20 结构化 JSON 落库（`json.dumps(ensure_ascii=False)` 惯例） |
| math.ceil（stdlib） | — | tier 公式取整 | `required_target = ceil(category_quota × 0.8 / 1.7)` |
| random.Random（stdlib） | — | 稳定随机种子排序 | 第四层 tie-break；`random.Random(seed)` 单实例多次调用可复现 [ASSUMED：seed 来源待 plan 定——建议 session_id hash，见 Open Questions Q3] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ALTER ADD COLUMN 迁移 | 表重建（_migrate_llm_trace 12 步法） | 实测证明不必要（新列全部可 ALTER、不触碰旧 CHECK）；重建反而要复制旧 CHECK 有膨胀风险——CONTEXT deferred idea 已由研究关闭 |
| path_state_snapshot JSON 列 | item_difficulty_state 新表 / 实时派生查询 | CONTEXT D-20 已锁定 JSON 列（跨实例聚合不可审计、不建新表）——SSOT §12.2 列名即承载 |
| Pydantic 校验 LLM 观察 | 手写 dict 校验 | schemas.py 全部既有 LLM 输出走 Pydantic（Extract/Disambiguate/AggregateLevel 先例）；D-22 明确严格 schema |
| 纯函数状态机 | 状态机框架（transitions 库等） | 三态 + 计数器逻辑极小（<200 行）；引包违反 Simplicity First + D-005 技术栈锁定 |

**Installation:**
```bash
# 无需安装任何新包。本机已实测：Python 3.13.2 / SQLite 3.45.3 / FastAPI 0.141.1 / pydantic 2.10.3 / pytest 9.1.1
```

**Version verification:** 本阶段**零新增包**——全部依赖为既有 requirements.txt 内的已在用包（pydantic 随 FastAPI 传递），无需 registry 检查。已装版本见上表（均本机实测）。

## Package Legitimacy Audit

> 本阶段不安装任何外部包（零新增依赖），此表不适用——无新包引入即无供应链风险面。

**Packages removed due to slopcheck [SLOP] verdict:** none（未运行——无新包）
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

Phase 2 改造后的测评主链（有界循环 Observation→Policy→Act→Evaluation→Persist 的运行时形态）：

```
候选人浏览器 (Chat.vue)
   │  POST /sessions  ──────────────► create_session
   │                                    │ readiness 检查(§10.4, 公式换新)
   │                                    ▼
   │                               INSERT session（无预选题！D-17）
   │
   │  GET /sessions/{id} ────────► get_session
   │                                    │ 当前实例不存在 → select_next_question(session_id)
   │                                    ▼
   │ ←── current_question（实例 INSERT + QUESTION_SELECTED/ACTIVATED 事件）
   │
   │  POST /sessions/{id}/answer  ►  submit_answer
   │                                    │ 1) user 消息 + refine（原文 hash 归档）
   │                                    │ 2) conn.commit()  ←── 先 commit 再调 LLM（单写者纪律）
   │                                    ▼
   │                          ┌── 观察层（LLM via call_llm_json）──────┐
   │                          │ InterviewObservation（Pydantic 校验）    │
   │                          │  answer_state ∈ 11 态 + 观察维度         │
   │                          └───────────────┬─────────────────────────┘
   │                                          ▼
   │                          ┌── 裁决层（代码纯函数）─────────────────┐
   │                          │ evidence_sufficient / stable_evidence  │
   │                          │ 拒答首次 → confirm 分支（二次 DECLINED   │
   │                          │   → 封存 refused + REFUSED）           │
   │                          │ followup ≤2 硬约束（followup_count 列） │
   │                          └───────────────┬─────────────────────────┘
   │                                          ▼
   │                          ┌── 难度状态机（代码，实例封存后）────────┐
   │                          │ §11.2 判据 × path_state_snapshot        │
   │                          │ DIFFICULTY_RAISED/LOWERED/RESTORED 事件 │
   │                          │ （与快照同事务写入）                     │
   │                          └───────────────┬─────────────────────────┘
   │                                          ▼
   │                    action = followup? （同实例，question_id 不变）
   │                    action = next?    → select_next_question(session_id)
   │                                      → 四层：①合法过滤 ②required 硬约束
   │                                              ③配额(7:3+tier 剩余) ④排序三键
   │                                      → selection_reason JSON 落库
   │                    action = finish?  （规则触发：N+E 耗尽；LLM 不自主结束）
   │                                          ▼
   │ ←── reply/next_question_id        session status=completed
   │
   │  POST /report ──► 后台串行链: score_session → generate_report
   │                          │ score_final 独立落库（50/50 已废除）
   │                          │ 客观题 answer_key 空 → score_state=INVALIDATED
   │                          │ 拒答 → score_state=REFUSED, score_value=0
   │                          ▼
   │                    aggregate_session_scores
   │                          │ actual 取 score_final 列（非 final_score）
   │                          │ 分母过滤：仅 score_state=SCORED 进能力等级
   │                          │ 总分 = Σ(item.weight × normalized) × 100
   │                          │ （item.weight 已含 7:3，不二次乘大类比例）
```

### Recommended Project Structure
```
server/
├── db.py                      # [改] _DDL 三表加列（新库直建全列）+ _migrate_* 加 ALTER 嗅探式迁移
├── config.py                  # [改] CATEGORY_RATIO 7:3 + 新增 ORDINARY_PLAN_N（值待关口包）
├── schemas.py                 # [改] 新增 InterviewObservation（answer_state Literal 11 态 + 观察维度）
├── services/
│   ├── question_selection.py  # [重写] select_next_question(session_id) 四层 + 配额纯函数（7:3/tier 公式）
│   ├── interview.py           # [重构内部] decide_next_action 签名不变；观察/裁决两层化；_mock_interview 规则分类器
│   ├── difficulty.py          # [新，名可 plan 定] 难度路径状态机纯函数（§11.2 判据 + snapshot 更新 + 事件）
│   ├── scoring.py             # [改] 删 50/50 合成；answer_key 空 → INVALIDATED 语义；score_state 写入
│   ├── aggregation.py         # [改] actual 取数切 score_final；分母按 score_state 过滤（REF-5.3）
│   ├── aggregate.py            # [改] _compute_weights 跟随 7:3（CATEGORY_RATIO 更新后自动生效，加注释/断言）
│   ├── readiness.py           # [改] 第 5 步配额公式换新（D-11 no-op 位填充）
│   └── state_events.py        # [不动] append_event 复用（DIFFICULTY_*/QUESTION_* 事件）
├── api/assessment.py           # [改] create_session 删预选；get_session 首题派发；submit_answer 消费两层化输出
└── prompts/interviewer.py      # [轻触] INTERVIEWER_SYSTEM 输出契约描述对齐新 schema（真实 prompt 重构留 D-030）

server/test_phase2_*.py         # [新] pytest+TestClient，单文件单进程（沿用 M5 模板）
server/test_m5_backend.py       # [改断言] 选题/合成/score_live 断言重写（不重构风格）
server/test_m6_backend.py      # [改断言] 50/50 与 final_score 断言重写（脚本式风格保持）
server/test_question_bank.py   # [改断言] test_selection 按 CATEGORY_QUOTA 断言重写（脚本式保持）
eval/virtual_candidates.py      # [核] 直插链是否受新断言影响（辅助链不经 decide/select，预计仅列名核对）
```

### Pattern 1: 嗅探式迁移（_migrate_* 惯例扩展至 ALTER）
**What:** db.py init_db() 迁移序列追加新函数：查 `sqlite_master` 判断列是否存在，缺则 `ALTER TABLE ... ADD COLUMN`，之后按需 `UPDATE` 回填条件值。
**When to use:** 02-01 表结构演进（question_bank / assessment_question / question_score 三表）。
**Example:**
```python
# 依据：本机实测（SQLite 3.45.3）+ SQLite 官方 ALTER TABLE 文档
# https://www.sqlite.org/lang_altertable.html
def _migrate_question_bank_v2(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(question_bank)").fetchall()}
    # ① NOT NULL 新列必须带常量 DEFAULT（实测：无默认被拒绝）
    #    [CITED: sqlite.org/lang_altertable.html — "cannot add a NOT NULL column with default value NULL"]
    if "question_type" not in cols:
        conn.execute("ALTER TABLE question_bank ADD COLUMN question_type TEXT NOT NULL DEFAULT 'ordinary'")
    # ② 非 NOT NULL 列可裸 ADD（存量行读出 NULL，代码层 'legacy' 语义兜底，D-15）
    if "item_id" not in cols:
        conn.execute("ALTER TABLE question_bank ADD COLUMN item_id TEXT")
    # ③ 锚点回填：非常量默认不能用 ADD COLUMN DEFAULT（实测拒绝）
    #    必须 UPDATE CASE 两步——按现有 difficulty 列回填 §9.4 锚点
    conn.execute("""UPDATE question_bank SET
        observable_level_max = CASE difficulty
            WHEN 'easy' THEN 3 WHEN 'medium' THEN 4 WHEN 'hard' THEN 5 ELSE observable_level_max END,
        observable_level_min = CASE difficulty
            WHEN 'easy' THEN 2 WHEN 'medium' THEN 3 WHEN 'hard' THEN 4 ELSE observable_level_min END
        WHERE observable_level_max IS NULL AND difficulty IS NOT NULL""")
```

### Pattern 2: 先 commit 再调 LLM / 内存算完单事务落库（单写者纪律的两条既有模式）
**What:** 混 DB 写与 LLM 调用必选其一，Phase 2 的选题主链（submit_answer 内 select_next_question）与评分链都命中。
**When to use:** select_next_question 若在裁决 LLM 调用之后执行——**必须**确认外层 conn 已 commit（assessment.py:191-192 现状即"先 commit 再决策"，两层化后决策内含 LLM 调用，选题 INSERT 在其后新事务——天然合规，但 plan 需显式验证提交次序）；scoring.py 改造保持既有"内存算完单事务落库"不动（只在 pending_rows 组装处删合成、加 score_state）。

### Pattern 3: 事件与快照同事务（append_event 契约）
**What:** QUESTION_SELECTED/DIFFICULTY_* 等新事件在调用者持事务内 append（不 commit），与实例 INSERT / path_state_snapshot UPDATE 同事务。
**When to use:** select_next_question 落新实例 + QUESTION_SELECTED/ACTIVATED；难度状态机封存点 + DIFFICULTY_*。
**Example:**
```python
# 依据：state_events.py:14 既有契约 + SSOT §13.1
append_event(conn, session_id=session_id, event_type="QUESTION_SELECTED",
             actor_type="system",
             assessment_question_id=new_aq_id,
             payload={"selection_reason": reason_json})  # 判据摘要进 payload（CONTEXT specifics 条款）
```

### Pattern 4: mock 双轨制（观察层 mock，裁决层共用）
**What:** `_mock_interview` 重写为规则分类器，输出与真实 LLM 同构的 InterviewObservation dict（含 answer_state + 观察维度），传给同一裁决层。
**When to use:** 02-04 + 全部离线测试。
**Example:**
```python
# 依据：CONTEXT D-23 + 现有 _mock_* 惯例（签名 (system_prompt, user_prompt)->dict）
_DECLINE_WORDS = ("不方便回答", "不想说", "隐私", "无可奉告")
_EVIDENCE_WORDS = ("项目", "举例", "具体", "结果", "数据")

def _mock_interview(system_prompt: str, user_prompt: str) -> dict:
    """规则分类器：模拟「观察输出」而非「绕过裁决」——与真实模式共用裁决层。"""
    last_user = ...  # 现有解析惯例
    if any(w in last_user for w in _DECLINE_WORDS):
        state = "DECLINED"
        dims = {"relevance": False, "specificity": 0, "attribution": False}
    elif len(last_user) < MIN_ANSWER_CHARS:
        state = "NEED_CLARIFICATION"
        dims = {"relevance": True, "specificity": 0, "attribution": False}
    elif any(w in last_user for w in _EVIDENCE_WORDS):
        state = "VALID_EVIDENCE"
        dims = {"relevance": True, "specificity": 2, "attribution": True}
    else:
        state = "VALID_EVIDENCE"
        dims = {"relevance": True, "specificity": 1, "attribution": False}
    # 返回的是观察 → 裁决层（与真实模式共享）计算 evidence_sufficient 并决定 action
    return {"answer_state": state, "observation": dims, "reply_reason": "mock 分类器"}
```

### Pattern 5: 7:3 权重三层落点（config 常量驱动，无散布数字）
**What:** `config.CATEGORY_RATIO` 改 `{"hard_skill": 0.7, "soft_skill": 0.3, "experience": 0.0, "qualification": 0.0}` 后，`aggregate._compute_weights` 的 `total_ratio = sum(...)` 归一逻辑**自动**产出 7:3（experience/qualification 中保留 0.0 系数，gate 项权重自然趋 0，但 gate 项 present 时仍走"仅出现类目参与配比"——gate item 的 weight 由 coef 分摊在 0 池中归 0，与 §8.2"gate 走事实核验不占权重池"一致）。
**When to use:** 02-01 D-16。注意 aggregate.py:165 `category_weights` 摘要（`CATEGORY_RATIO[c]/sum(values)`）同步自动更新——无需改逻辑，只需回归断言新值。
**Warning:** experience/qualification 若保留字面 0.0，`_compute_weights` 的 `total_ratio` 包含它们没问题（sum 不变），但 **plan 必须断言 gate item 的最终权重与 Phase 2 语义一致**（现状 gate=1 的 item 参与 weight 计算且 report 中按 gate 二值计分不乘 weight×actual —— aggregation.py:88-102 已豁免 gate 项不进 actual 计算，只需确认 weight 值不影响该路径）。

### Pattern 6: 配额公式纯函数（selection 与 readiness 共享）
**What:** `plan_quotas(n, categories_present, tier_counts) -> {category: {tier: target}}` 纯函数一处实现，select_next_question 与 readiness 第 5 步同源调用，防两处口径漂移（WR-15 同类教训）。
**When to use:** 02-02 + readiness 改造。

### Anti-Patterns to Avoid
- **Anti-pattern 1 — 选题在决策 LLM 调用同事务内 INSERT：** SQLite 单写者（llm_trace 独立连接写库）→ database is locked。选题必须位于 conn.commit() 之后的新事务，或决策前预选（但会损失"裁决后才知难度"的信息——按 §10.6 选题每轮 action=next 时执行，天然在 LLM 之后，走 commit-then-select 次序）。
- **Anti-pattern 2 — 把 answer_state 直接映射为分数：** §11.4 明文"代码不把 answer_state 直接映射为分数"；answer_state 只驱动处理原则（followup/转向/封存），分数只来自 P-score 或 answer_key 匹配。
- **Anti-pattern 3 — selection_reason 拼中文串：** D-18 锁定结构化 JSON；中文可在报告层生成，选题落库只存机器可解析结构。
- **Anti-pattern 4 — N 默认值拍脑袋：** SSOT §31-1 明文"默认值实施期结合 40 分钟体验测定"。code 写常量但数值空缺/占位由关口包裁决——任何测试种子中的 N 数值均须标注"测试用值，非生产默认"。
- **Anti-pattern 5 — 在 Phase 2 顺手做 Phase 3/5 的事：**计时封存（seal_reason=timeout 写入逻辑）、item-level IMPUTED 补算、HUMAN_REVIEW_REQUIRED 完整态——本期只留枚举位/no-op，写了就是范围蔓延。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|------|
| LLM 输出校验（answer_state 11 态 + 观察维度） | 手写 if/raise 逐字段校验 dict | `schemas.py` 既有 Pydantic 模式（`Literal` + `Field`） | 实测 ValidationError 带 loc/type 可测试断言；schemas.py 全部 LLM 输出先例统一走此模式 |
| 迁移框架/版本登记 | 引 schema_version 表或迁移 runner | `_migrate_*` 手写嗅探式（D-14） | schema_version 属 Phase 6 REF-2.11；Phase 2 内嵌迁移随阶段走 |
| 随机性 | `random.random()`（不可复现） | `random.Random(seed)` 实例（seed = 确定性派生） | 第四层排序稳定种子的可审计性（同一会话同一次选题可重放） |
| 幂等迁移判断 | 自算列哈希对比 | `PRAGMA table_info` 列名嗅探（既有惯例） | `_migrate_llm_trace` 用 `sqlite_master.sql` 字符串嗅探——列存在性用 PRAGMA 更直接、既有 question_bank_task 先例（db.py:255 无 CHECK 保守面） |
| 事件写入 | 手拼 INSERT 事件行 | `state_events.append_event`（D-06 既有） | 取号/校验/列宽单点封装；跳过 helper 直接 INSERT 会绕过 actor_type 校验与 sequence_no 取号 |

**Key insight:** Phase 2 的"不值得手搓"全部是**既有项目资产**——append_event、call_llm_json gateway、schemas.py Pydantic 惯例、_migrate_* 约定、两种 SQLite 写锁规避模式。新技术内容只有三个纯函数（配额公式、裁决布尔、状态机判据），它们是业务规格的直接代码化，没有轮子可引。

## Runtime State Inventory

> 本阶段为 schema 演进 + 代码重构混合，含 ALTER 迁移——但**不涉任何 rename/字符串替换**类改造，5 项核查如下：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 业务库 data/app.db：16 条 assessment_question（answered_at 多为非 NULL）、8 条 question_score（final_score=score_final 同值，实测确认）、6 条 question_bank、若干 assessment_message 含 score_live 列值 | code edit —— ALTER 迁移函数自动兼容旧行（D-15：默认 NULL/'legacy'，不回头迁移）；INVALIDATED 语义只作用于新评分。**无 data migration**（final_score→score_final 合并在迁移函数内一次完成即全部存量动作） |
| Live service config | 无外部服务配置（单进程 uvicorn、无 n8n/PM2/launchd/云配置） | None — verified：sqlite_master 18 表全本地、无 .plist/cron 注册（find . 无 pm2 config、无 launchd 脚本入仓库） |
| OS-registered state | None — verified：`git ls-files | grep -iE "launchd|plist|systemd|pm2"` 无命中；启动方式为手动 uvicorn | 无 |
| Secrets/env vars | `.env`（不入库）含 DB_PATH/LLM_API_KEY/JWT_SECRET；`FOLLOWUP_MAX`（config.py:45 env 可覆盖）——**无新 env 名引入**（ORDINARY_PLAN_N 建议 code 常量而非 env，CONTEXT D-19 字面是 config 常量） | 无（除非 plan 决定 ORDINARY_PLAN_N 可 env 覆盖——留 plan 裁量，非必须） |
| Build artifacts | `web/dist`（若存在）不涉后端列名；无 egg-info/编译产物依赖 question_bank 列名 | 无 |

**结论：** 唯一 runtime 状态动作 = 02-01 迁移函数对 data/app.db 的 ALTER + 一次 UPDATE 合并（正式运行时发生，D-15）。演示数据允许重跑生成，无阻塞性迁移。

## Common Pitfalls

### Pitfall 1: ALTER ADD COLUMN 的三个实测限制（02-01 核心）
**What goes wrong:** ①`ADD COLUMN x TEXT NOT NULL`（无默认）被拒绝——存量行立即违反约束；②`ADD COLUMN ... DEFAULT (CASE ...)` 非常数默认被拒绝——锚点无法在 DDL 一行完成；③`ADD COLUMN ... UNIQUE` 不允许——`(session_id, sequence_no)` 唯一约束不能随列加。
**Why it happens:** SQLite ADD COLUMN 不重写表——存量行读时隐式取默认；非常量/UNIQUE/PK 违反该机制。[CITED: SQLite 官方 ALTER TABLE 文档 — ADD COLUMN 限制清单]
**How to avoid:** ①NOT NULL 新列一律带常量默认（`DEFAULT 'ordinary'` / `DEFAULT 0`），枚举完备性代码校验（N11 本就禁 CHECK）；②锚点列先裸 ADD（NULL 允许）再 `UPDATE ... CASE difficulty` 回填（本机实测路径，见 Pattern 1）；③`(session_id, sequence_no)` 用 `CREATE UNIQUE INDEX IF NOT EXISTS`——**注意**：现有表已有 `seq` 列（存量行有值），若重命名 `seq`（B）则新旧列并存或需 UPDATE 拷贝——plan 阶段需定夺（推荐：加 `sequence_no` 不改名，seq 保留兼容读，或直接沿用 `seq` 列不加新列——**这是 Claude's Discretion 范围，建议沿用 seq 并建 UNIQUE(session_id, seq) 索引，避免无谓双列**，前提是 plan 认定 §12.2 "sequence_no" 的到列名映射 `seq` 可接受）。
**Warning signs:** 迁移函数在老库上抛 `OperationalError: Cannot add a NOT NULL column with default value NULL`。

### Pitfall 2: `_DDL` 与 `_migrate_*` 双轨不同步
**What goes wrong:** 只改 `_DDL`（新库直建含新列）不改迁移 → 老库 init_db 后仍缺列，代码 SELECT 新列抛 `OperationalError: no such column`；只改迁移不改 `_DDL` → 新建库（如执行中删除 DB 重建）走 CREATE IF NOT EXISTS 已有表则不触发迁移嗅探。
**Why it happens:** `_DDL` 是 `CREATE TABLE IF NOT EXISTS`（幂等但不动已有表）；迁移函数独立跑。两者必须**同步加列**——_DDL 的 CREATE 语句中加新列 + 迁移函数对已有表 ALTER（新建库因为表已含新列，迁移嗅探自然跳过）。
**How to avoid:** 每个 plan 的 DDL 改动 checklist：改 `_DDL` 的 CREATE 语句 **和** 加对应 `_migrate_*`。测试断言两路径：全新临时库 + init_db；模拟老库（手工建旧版表后 init_db）→ 新列存在。
**Warning signs:** 测试只跑全新库路径漏老库路径——业务库直升断裂只在正式启动暴露。

### Pitfall 3: readiness 与 select_next_question 的配额口径漂移
**What goes wrong:** 02-02 重写 selection 用新公式，02-01~02-05 中间态 readiness 第 5 步仍按 CATEGORY_QUOTA 检查 → 开考检查拒绝合法库（hard<6 即 INCOMPLETE），或反之放过实际不可行的库。WR-15（列表/会话两处口径漂移）的前科。
**Why it happens:** 两处独立实现同一公式。
**How to avoid:** quota 公式实现为共享纯函数（Pattern 6），readiness 第 5 步与 selection 同源 import；测试用 §10.2 四行样例（N=9/10/11/15）作共享对拍断言。**依赖顺序注意：若 readiness 在 02-02 前先被修（02-01 批次），它与尚未重写的 selection 间的关系应在同 plan 内闭合**——建议 read+selection 同批（02-02 内)。
**Warning signs:** test_m5 旧断言 `question_count == 10` 失败后的重写中两处数字不一致。

### Pitfall 4: 50/50 废除的隐藏消费面（4 处，不止 scoring.py）
**What goes wrong:** 只删 scoring.py:172-177 合成三行，漏掉其余消费点——聚合取数、报告 SELECT、测试断言。
**Why it happens:** final_score 是被 4 处引用的散布列。
**How to avoid:** 全部 4 个消费点一次清完：
1. `scoring.py:172-177` → 删合成 + `_latest_score_live` 降为纯 score_live 列参考值
2. `aggregation.py:74+79+118` → `final_score` → `score_final`（增值税：分母加 `score_state` 过滤）
3. `report.py:39`（`_load_question_reviews` SELECT `qs.final_score`）→ 切 `score_final`
4. 测试：`test_m5_backend.py:290`（`final_score == 3` 断言）、`test_m6_backend.py:177-182`（`final=round(3*0.5+3*0.5)=3`）→ 重写断言（只改断言不改风格 D-09 前例）
**Warning signs:** grep `final_score` 在 02-05 完成后仅余迁移函数与 DROP 后残留零命中（或保留 D-15 legacy 读兼容不读处）。

### Pitfall 5: 事件 payload 的判据摘要（DIFFICULTY_* 必带）
**What goes wrong:** 事件写 from/to 但 payload 空——报告/审计不可解释"为什么降级"。
**Why it happens:** append_event 的 payload 默认 None；判断逻辑分散在状态机内部。
**How to avoid:** CONTEXT specifics 明文"提交留痕的事件行含 phase2 新枚举时，payload 里带判据摘要（如 DIFFICULTY_LOWERED 的 evidence_counts）"——plan 的状态机任务验收标准即包含 payload 结构断言：
```python
payload={"criterion": "followup_still_ambiguous", "evidence_counts": {"sufficient": 0, "insufficient": 2}, "from_difficulty": "medium", "to_difficulty": "easy"}
```
**Warning signs:** 测试只断言 event_type 存在不断言 payload 内容。

### Pitfall 6: stable_evidence 的跨实例语义（§11.3 易错点）
**What goes wrong:** 把 stable_evidence 当作"单次回答的属性"计算（单实例内 evidence_sufficient 累加即判 stable）——实际规格是"两个**不同**普通题实例的独立有效观察"（跨实例聚合计数，同回答两句不算）。
**Why it happens:** 它与 evidence_sufficient（单次观察可算）粒度不同——第二次实现容易混淆。
**How to avoid:** 设计三个不同函数，签名分开：`is_evidence_sufficient(obs) -> bool`（单观察维度）、`is_stable_evidence(item_id, session_id, current_obs) -> bool`（查历史 snapshot 计数：sufficient_in_row ≥ 2 或 hard_strong == 1）、`update_path_state(...)`（持久化）。状态机判据"medium→hard 充分且稳定"依赖后者——其判定在 item 级而非实例级。
**Warning signs:** 状态机测试若只造一个实例就断言 RAISED，是编写错误。
（注 [ASSUMED]：**stable_evidence 计算 Phase 5 裁决是终局消费（item_measurement），Phase 2 只需做难度导航用的轻量版**——SSOT §11.2"medium→hard 充分且稳定的证据"需在 plan 阶段定义其轻量实现边界（如"两个不同实例 sufficient 观察即轻量 stable"），本研究建议按此落地，需 plan 检查与 CONTEXT D-22 的字面契合度。）

### Pitfall 7: score_state 枚举的 Phase 2 子集
**What goes wrong:** 全量实现 8 态（含 IMPUTED/HUMAN_REVIEW_REQUIRED）——但 §12.4 完整分母规则依赖 item_measurement 裁决（REF-5.4 Phase 5）；提前铺写会与 Phase 5 冲突。CONTEXT D-28 字面排除 IMPUTED/HUMAN_REVIEW_REQUIRED。
**Why it happens:** §11.4 枚举清单是全量的。
**How to avoid:** Phase 2 落 6 态：SCORED/REFUSED/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED/INVALIDATED/INCOMPLETE；IMPUTED/HUMAN_REVIEW_REQUIRED 只作为代码层枚举值预留（枚举常量映射），不写评分链产生路径。分母过滤现阶段口径=「排除人工审核/补算候选」= 聚合侧**只按 REFUSED 和 INVALIDATED 两个明确语义过滤**（INSUFFICIENT_EVIDENCE 的生产者在 Phase 5 —— [ASSUMED]：Phase 2 聚合仅数据状态过滤，不写完整度聚合新表，留 CONTEXT D-28 六态分母口径）。plan 必须尽早定 INSUFFICIENT_EVIDENCE 的 Phase 2 生产与否（见 Open Questions Q1）。
**Warning signs:** 计划中出现 item_measurement 表或 IMPUTED 补算——属 Phase 5 越界。

### Pitfall 8: `decide_next_action` 下游契约破坏面（回复结构不可变）
**What goes wrong:** 两层化时改变返回 dict 的键（删 score_live、改 reason 字段名）→ submit_answer 及前端 Chat.vue 的 SSE adapter / 决策·话术断言破裂。
**Why it happens:** 现有返回 5 键 {action, reason, reply, score_live, score_live_reason}，两层化后命名字段重构冲动。
**How to avoid:** 明确保留 5 键（含 score_live —— 它来自观察层/裁决层此时可保留为 LLM 直产 1-5 分（REF-1.3 将其改造为观察层输出的一部分；D-22 字面允许——CONTEXT 未禁），仍写 assessment_message.score_live）。selection 事件和新增内容**只加不减**：can 加 answer_state/observation 等新增键供测试与日志。
**Warning signs:** 前端 streamAnswer (`web/src/utils/sse.js`) 的 onDecision 处理 d.action——新增 answer_state 字段前端无需感知，但**不得**删 action。

### Pitfall 9: create_session 删预选后的响应结构
**What goes wrong:** 返回 `question_count` 消失/变化 → Chat.vue 无碍（不消费 question_count，见 grep 核查）但 test_m5 断言 `body["question_count"] == 10` 失败。
**Why it happens:** 旧断言基于一次性预选。
**How to avoid:** 按 Phase 1 D-09 前例只改断言——新断言如 `question_count == None`（或字段删除后去掉断言）并加调度性断言（第三次 answer 后 assessment_question 行数 = 3 而非 N）；`estimated_duration_minutes` 可按 40 分钟口径预估（[ASSUMED] SS 全场 40 分钟 → 估算值含义由 plan 定，建议保留字段形式）。
**Warning signs:** Chat.vue 只用 total_count/answered_count（get_session 返回），路径无恙——但 get_session 的 total_count 必须同步改为 N+E 口径（分母不再是题目行数）。

### Pitfall 10: mock 分类器与 eval 链的耦合（virtual_candidates）
**What goes wrong:** `_mock_interview` 重写后 answer>20 字不再恒 next——eval/virtual_candidates.py 绕过 decide_next_action 直接落库（核查确认：不走 interview 服务），但它依赖 `score_session` / `aggregate_session_scores` / question_score 列名。02-05 删合成/改列后其 tier 逻辑不受影响（总分来源 objective 命中率）——但 02-04 若扩出 answer_state 相关的 DB 写（如 assistant 消息 action 字段），virtual 不写则缺失。
**Why it happens:** eval 是服务层直调，不走 API 面。
**How to avoid:** 02-04 plan 必须为 eval 增量兼容做核对（virtual_candidates 所有 INSERT 语句列表核对：assessment_message 只写 role/content —— 与新 answer_state 无关，实际风险低）；test_m7_backend 的 eval runner 测试若涉及 feedback/trace 不到评分列。
**Warning signs:** grep `virtual_candidates` 内 `INSERT INTO assessment_message` 无 action 列——新代码若 NOT NULL 需默认（勿加 NOT NULL）。

## Code Examples

以下三段为 SSOT 原文的可代码化转写（摘自 design/final-design/总设计文档.md，均已逐字核对）：

### 1. 大类 7:3 最大余数分配（§10.2）
```python
# Source: design/final-design/总设计文档.md §10.2（原文）
def largest_remainder_73(n: int) -> tuple[int, int]:
    """hard = floor(0.7n) 起步，余下名额按小数部分大小分；小数相等归 hard。"""
    raw_hard, raw_soft = 0.70 * n, 0.30 * n
    hard, soft = int(raw_hard), int(raw_soft)          # 先取整数部分
    rem = n - hard - soft                              # 余下名额
    if raw_soft - soft > raw_hard - hard:              # soft 小数更大
        soft += rem
    else:                                              # 含相等：归 hard
        hard += rem
    return hard, soft

# §10.2 样例（测试断言直接用）：
# N=9 → (6,3)  N=10 → (7,3)  N=11 → (8,3)  N=15 → (11,4)
```

### 2. 类内 tier 配额（§10.3，和 1.7）
```python
# Source: design/final-design/总设计文档.md §10.3（原文）
from math import ceil

TIER_COEF = {"required": 0.8, "preferred": 0.6, "plus": 0.3}  # 和 1.7

def tier_targets(category_quota: int) -> dict[str, int]:
    required_target = ceil(category_quota * 0.8 / 1.7)
    preferred_target = ceil(category_quota * 0.6 / 1.7)
    plus_target = category_quota - required_target - preferred_target
    return {"required": required_target, "preferred": preferred_target, "plus": plus_target}
    # §10.3 边界：向上取整不得使目标超过该大类总量（如 soft 仅 2 题：required=1、preferred=1、plus=0）
    # → 需 clamp：required = min(required, total_in_category)... 题量不足先保 required 再保 preferred
```

### 3. 难度状态机判据（§11.2，状态转移纯函数骨架）
```python
# Source: design/final-design/总设计文档.md §11.2（原文判据清单）
# path_state_snapshot 建议结构（Claude's Discretion 范围，CONTEXT D-20）：
SNAPSHOT = {
    "item_id": "c_xxx",
    "current_difficulty": "easy",       # 下一实例难度
    "sufficient_in_row": 1,             # 连续充分证据计数（升/恢复滞回共用）
    "stable_ever": False,               # 是否已出现过稳定证据（一次即算）
    "fail_same_difficulty": 0,          # 同难度连续未达锚点计数（降级判据）
    "followup_ambiguous": False,        # followup 后仍模糊（降级判据 2）
    "exception_used": False,            # required 刚性例外已用（§10.5）
}

def next_difficulty(snap: dict, *, evidence_sufficient: bool, stable: bool,
                    is_valid_failure: bool) -> tuple[str | None, str | None]:
    """返回 (new_difficulty, event_type)。None = 无迁移。
    判据（§11.2 逐条）：
      easy→medium：一次充分证据（sufficient_in_row ≥ 1）
      medium→hard：充分且稳定 + 仅 required_level > 4 的 item
      降级：仅统计有效候选人证据失败（fail_same_difficulty ≥ 2 或 followup_ambiguous）；
            非最低难度才可降（easy 不降）
      恢复：连续两次充分（sufficient_in_row ≥ 2）或一次稳定（stable_ever=True 一旦出现）
      跳级：默认禁止——next_difficulty 跳档（如 easy→hard 直接）不可返回，
            无合法迁移即 PATH_UNAVAILABLE 事件（标记不静默）
    注意：一次实例内不升降级——本函数只在实例封存后由下一实例承载（调用点约束）。
    """
```

### 4. InterviewObservation Pydantic 模型（D-22；schemas.py 惯例）
```python
# 模式依据：schemas.py 既有 ExtractResult/DisambiguateResult 先例（Pydantic v2 Literal）
# 本机实测 Literal 非法值抛 ValidationError（literal_error, loc 可定位）
from typing import Literal, Optional
from pydantic import BaseModel, Field

ANSWER_STATES = Literal[
    "VALID_EVIDENCE", "NEED_CLARIFICATION", "OFF_TOPIC", "NO_RECALL",
    "DECLINED", "PROCESS_CHALLENGE", "CONDUCT_EVENT",
    "TECHNICAL_OR_ACCESS_BARRIER", "PROMPT_INJECTION",
    "MODEL_UNCERTAIN", "ITEM_INVALID",  # §11.4 11 态
]

class ObservationDims(BaseModel):
    relevance: bool = Field(description="与测量目标相关")
    specificity: int = Field(ge=0, le=3, description="具体度 0-3")
    attribution: bool = Field(description="有可归因事实（项目/数据/角色）")
    required_points_covered: Optional[bool] = None
    source_span_available: Optional[bool] = None
    contradiction_detected: Optional[bool] = None
    uncertainty: Optional[bool] = None

class InterviewObservation(BaseModel):
    """观察层输出——LLM 只出观察，不出 action（D-22 / §11.3）。"""
    answer_state: ANSWER_STATES
    observation: ObservationDims
    reply_suggestion: Optional[str] = Field(None, description="可选话术建议，代码可弃用")
    reason: str = ""
```

### 5. score_state 分母过滤（§12.4 → aggregation 集成点）
```python
# Source: design/final-design/总设计文档.md §12.4（原文）+ aggregation.py:73-79 现行取数
# 现行（旧）：
rows = conn.execute("SELECT item_id, final_score FROM question_score WHERE session_id=?", ...)
# 新（Phase 2 六态口径，D-28）：
rows = conn.execute(
    "SELECT item_id, score_final, score_state FROM question_score"
    " WHERE session_id=? AND score_state IN ('SCORED')",   # REFUSED 不进能力等级分母
    (session_id,),
)
# REFUSED → 只进行为/完整度聚合（聚合函数需额外算 refusals 单独列表）
# INVALIDATED / INCOMPLETE → 排除 + 产生缺失/警告列表（不隐式转 0）
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `CATEGORY_QUOTA{hard:6,soft:2,exp:2}` 硬编码 + experience 进普通题 | 岗位级 N + 7:3 最大余数 + tier 0.8/0.6/1.7（SSOT v2.0） | 2026-09-02（SSOT §30 N4） | question_selection 全量重写；readiness 第 5 步公式换新；经验/资格题改走表单（表单链本体 Phase 3，Phase 2 只剔出选题） |
| `final = round(score_live*0.5 + score_final*0.5)` | score_final 独立落库，score_live 仅导航（SSOT §30 N2） | 2026-09-02 | scoring.py 三行删除 + 4 消费点切列（Pitfall 4） |
| LLM 单步出 action（interviewer function call） | 观察层 + 裁决层两层化（SSOT §30 N5 / §11.3） | 2026-09-02 | interview.py 内部重构（签名不变），schemas.py 新增 |
| 单 `difficulty` 类目递进（easy→hard 按类） | item 级难度路径状态机（§11.2 升/降/滞回） | 2026-09-02 | path_state_snapshot 列 + DIFFICULTY_* 事件 + §9.4 锚点 |
| `answer_key` 缺 → 按最低分 1 分（Phase 1 WR-14） | 判题库无效 INVALIDATED（不走 Phase 5 IMPUTED 链前置条件） | 本 phase（REF-5.2/8.1） | score_session 跳过 + 缺失警告列表 |

**Deprecated/outdated:**
- `CATEGORY_QUOTA`（question_selection.py:9）：02-02 重写时**全库 grep 确认消费点**——readiness.py:11 import 是唯一外部引用（test_question_bank.py:38 经 select 间接）；重写时两处一起换。
- `final_score` 列：02-01 迁移合并后 DROP（实测可行）；**注意 `report.py:39` 与 `eval` 的 SELECT 更新先于 DROP**（DDL 迁移先跑一步、代码 SELECT 随 02-05 批次切的次序风险——建议 02-01 只合并不 DROP，**DROP 推迟到 02-05 所有消费点切完后**，见次序表）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `seq` 列可继续承载 §12.2 `sequence_no` 语义（不加新列、建 UNIQUE(session_id,seq) 索引） | Pitfall 1 / REF-2.7 | 若 plan 坚持 §12.2 字面列名，需加 `sequence_no` 新列 + 回填 UPDATE（同为 ALTER 可达，成本小幅上升） |
| A2 | stable_evidence 的 Phase 2 轻量版 = "两个不同实例 sufficient 观察"，完整裁决（rubric/覆盖一致性/矛盾）留 Phase 5 | Pitfall 6 / REF-4.3 | 若严格按 §11.3 全判据提前做，工作量越 Phase 5 界；若过轻，medium→hard 升级语义测试可能不足以证合规 |
| A3 | INSUFFICIENT_EVIDENCE 态 Phase 2 只在代码枚举层预留、不写完整生产路径（生产者=Phase 5 裁决） | Pitfall 7 / REF-4.4 | 若 CONTEXT 期望 Phase 2 产出该态（如 evidence_sufficient=False 时写入），聚合分母行为要同步多排一态 |
| A4 | `decide_next_action` 返回 5 键保持（含 score_live 从观察层产出），submit_answer 输出结构不变 | Pitfall 8 / REF-1.3 | 若 score_live 移出 interview 决策（如并入 scorer），前端 m5 断言 score_live==3 需另改 |
| A5 | ORDINARY_PLAN_N 为 config 常量（不可 env 覆盖），数值留关口包 | Project Constraints | 若期望 env 可覆盖，config 读取逻辑加一行 `os.environ.get` 之差（小） |
| A6 | 事件 `REQUIRED_EXCEPTION_GRANTED` 属 §13.2 QUESTION_\* 组、Phase 2 写入（required 例外激活时） | REF-3.6 | 若按 SC 最小事件集字面（未列）不写，则审计链缺例外记录；建议写（§13.2 已有枚举且 SC-1 可审计精神覆盖） |
| A7 | create_session 响应去掉 question_count 或置 None，前端无消费（grep 已核 Chat.vue 只用 get_session 的 total_count） | Pitfall 9 | PositionAssess.vue 只取 session_id（实测核过 :134），无风险；唯 test_m5 断言要改 |
| A8 | 迁移次序：02-01 合并 final_score→score_final 但不 DROP，DROP 延后至 02-05 | State of the Art | 若 02-01 即 DROP，report.py/eval SELECT 在 02-01 与 02-05 之间运行会断裂（业务库直升窗口内） |

## Open Questions (RESOLVED)

1. **INSUFFICIENT_EVIDENCE 态的 Phase 2 生产边界（A3）**
   - What we know: SSOT §11.4 枚举含该态；D-28 列它于"不进正常分母"组；生产场景=evidence_sufficient=False 且非拒答/无效。
   - What's unclear: Phase 2 的 score_question/score_session 是否在评分时依据观察层 evidence_sufficient 写该态，还是留空（默认 SCORED）待 Phase 5。
   - Recommendation: 按 A3 兜底（枚举预留不生产）；plan 对 02-05 验收标准明确"REFUSED/INVALIDATED 有生产路径、INSUFFICIENT_EVIDENCE 至少出现在代码枚举常量"。若计划要求生产，其判据轻微（evidence_sufficient=False 时 score_session 标记），加一个 if 的成本可控。
   - **Resolution:** Q1 → 02-05 interfaces（score_state 6 态口径：INSUFFICIENT_EVIDENCE 保持枚举常量存在、本 phase 不生产；见 02-05-PLAN.md「score_state 6 态（D-28 / Pitfall 7）」）。

2. **`sequence_no` 新列 vs 沿用 `seq`（A1）**
   - What we know: §12.2 字面列名 sequence_no；现有列 seq；现有代码（selection→INSERT）多处用 seq；UNIQUE 可用索引实现。
   - What's unclear: SSOT 对内部列名的字面约束力（§12.2 是"演进后"描述而非 DDL 级强制）。
   - Recommendation: 沿用 `seq` + `CREATE UNIQUE INDEX uq_aq_session_seq ON assessment_question(session_id, seq)`——避免双列冗余；在 selection_reason JSON 或 DDL 注释中说明 seq = sequence_no 语义载体。若 plan 检查器判定必须字面对齐，加 `sequence_no` 列的 ALTER 成本约 3 行 + 索引。
   - **Resolution:** Q2 → 02-01（沿用 seq 列承载 §12.2 sequence_no 语义、不加新列；CREATE UNIQUE INDEX IF NOT EXISTS uq_aq_session_seq ON assessment_question(session_id, seq)；见 02-01-PLAN.md 新列清单）。

3. **「稳定随机种子」的 seed 来源（排序第四键）**
   - What we know: D-17 要求"chain 后继 → item.weight → 稳定随机种子"三键；seed 未定义来源。
   - What's unclear: seed = session_id 派生（同一会话重放同序）vs question_id 派生（跨会话同库同序）。
   - Recommendation: `random.Random(int(hashlib.sha256(session_id.encode()).hexdigest()[:8], 16))` 会话级派生——可审计（selection_reason 记 seed 值）且同会话幂等。plan 阶段一句话定死。
   - **Resolution:** Q3 → 02-02（排序第四键 seed = int(sha256(session_id).hexdigest()[:8], 16) 会话级派生，selection_reason 记 seed 值；见 02-02-PLAN.md「§10.6 四层选题」第④层）。

4. **readiness 第 5 步与 02-02 的同批闭合**
   - What we know: Pitfall 3 指出两处口径需共享；readiness 属 02-01 计划清单还是 02-02（CONTEXT 原文 readiness 改造写在 02-01 权重批次的代码现状引用里，但 02-02 选题才是公式主体）。
   - What's unclear: plan 拆分时 readiness 公式更新归 02-01 还是 02-02。
   - Recommendation: 归 02-02（与 select_next_question 同 plan 闭合共享函数），02-01 只做表结构 + 7:3 权重三落点——readiness 不依赖权重口径只依赖配额公式，跟选题走语义最顺。
   - **Resolution:** Q4 → 02-02 Task 3（readiness 第 5 步改 from .question_selection import plan_quotas 同源预检，与 select_next_question 共享同一公式；见 02-02-PLAN.md Task 3）。

5. **旧会话（无 path_state_snapshot/dynamic columns）的兼容读行为（D-15 边界确认）**
   - What we know: 业务库有 16 条旧 assessment_question/8 条旧 score 行；D-15 说"保持可读、不参与新选选题路径"。旧会话 status=in_progress 的（若有）在 02-02 后 submit_answer 会不会走新 select_next_question？
   - What's unclear: 旧 in_progress 会话的续答语义（新代码面对无 selection_reason/无 path snapshot 的存量实例）。
   - Recommendation: select_next_question 入口对"旧会话"的可识别兜底：查询到的已封存实例若无 selection_reason（legacy NULL）→ 可续用旧路径或最小改动（兼容读+首 next 即走新选题）；建议 plan 加一个 migration smoke test——造旧结构 session（手工插行模拟）→ submit_answer next → 断言不 500。实测业务库现状：16 行全有 seq 且会话状态混合（in_progress 存在），不能假设零存量。
   - **Resolution:** Q5 → 02-02 legacy 兜底（会话既有实例 selection_reason 全 NULL → 走旧 ORDER BY seq 派发、不进新四层选题）+ test_legacy_session_continues 迁移冒烟测试（见 02-02-PLAN.md「旧会话兼容」）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | 全部 | ✓ | 3.13.2 | — |
| SQLite (sqlite3 stdlib) | 02-01 ALTER/DROP/UNIQUE INDEX | ✓ | 3.45.3（≥3.35 DROP COLUMN 门槛建议满足） | — |
| FastAPI / TestClient / httpx | 集成测试 | ✓ | 0.141.1 / httpx 传递 | — |
| pydantic | InterviewObservation schema | ✓ | 2.10.3 | — |
| pytest | 测试运行 | ✓ | 9.1.1 | — |
| uvicorn | 手动冒烟（可选） | ✓ | 0.52.4 | — |
| 业务库 data/app.db | 迁移直升目标 | ✓ | 18 表（无 assessment_state_event——Phase 1 表只在新 init_db 后建） | 演示数据允许重跑（D-15） |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

> 注：data/app.db 目前缺 assessment_state_event 表与触发器——这**不影响** Phase 2 迁移（该表部署随下次正式启动 init_db 自动补齐）；但 02-05 若依赖 Phase 1 事件的回归测试注入旧库，测试一律用临时库（红线 2），无实际阻塞。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + FastAPI TestClient（httpx） |
| Config file | none — 单文件单进程纪律（约定，Phase 6 REF-7.4 统一 pytest 收集） |
| Quick run command | `cd server && python -m pytest test_phase2_<area>.py -v`（单文件） |
| Full suite command | 逐文件：`python -m pytest server/test_phase2_*.py -v` → `test_m5_backend.py` → `test_m7_backend.py` → `test_p0_security.py` → `test_p0_chain.py`；脚本式：`python server/test_m6_backend.py`、`python server/test_question_bank.py`（**一次 pytest 不得收多文件**） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REF-2.7/2.9 (02-01) | 老库模拟（旧建表→init_db）→ 新列全在、锚点 CASE 回填正确、final_score 合并值=COALESCE 语义、新库直建路径同样全列 | unit（迁移函数直测） | `python -m pytest test_phase2_migration.py -v` | ❌ Wave 0 |
| REF-5.7 (02-01) | 7:3 公式单断言：items=hard+soft 时 Σhard weight=0.7±尾差、Σsoft=0.3；纯 soft 岗位归一 1.0；aggregation 总分不二次乘（回归断言） | unit | `python -m pytest test_phase2_weights.py -v` | ❌ Wave 0 |
| REF-3.1 (02-02) | N=9/10/11/15 四行样例逐行断言 + tier 样例（soft=2 → req1/pref1/plus0）+ 单类目退化（纯 hard 岗 Direct N 全 hard） | unit | `python -m pytest test_phase2_selection.py -v` | ❌ Wave 0 |
| REF-3.2/4.1 (02-02) | API 级：create_session 后 aq 行=0；第 k 次 answer next 后 aq 行=k；selection_reason JSON 含四层记录；followup 不增行 | integration | `python -m pytest test_phase2_selection.py -v` | ❌ Wave 0 |
| REF-3.6 (02-02) | required 例外：普通计划耗尽后未覆盖 required → 补选 medium（无 medium → hard）；同 item 第二次例外不出现；事件 REQUIRED_EXCEPTION_GRANTED（A6 若采纳） | integration + unit | 同上 | ❌ |
| REF-4.2 (02-03) | 状态机纯函数判据表驱动测试：每条 §11.2 判据一行（升/降/滞回/跳级拒绝/单实例不升降）；DIFFICULTY_* 事件 + payload 判据摘要断言；快照与事件同事务 | unit + integration | `python -m pytest test_phase2_difficulty.py -v` | ❌ Wave 0 |
| REF-1.6/1.7/4.3/4.4 (02-04) | mock 分类器语义测试（短/拒答关键词/实义词三向）+ Pydantic 非法 answer_state 拒绝 + 裁决层 followup≤2 硬约束 + 旧测试断言重写后通过 | unit + integration | `python -m pytest test_phase2_interview.py -v` | ❌ Wave 0 |
| REF-4.5 (02-04) | 拒答确认流：首次 DECLINED → action=confirm 类回复；二次 DECLINED → 实例封存 seal_reason=refused + score_state=REFUSED + score_value=0 | integration | 同上 | ❌ |
| REF-5.1/5.2/5.3/8.1 (02-05) | score_final 独立（mock 3 分直落）；answer_key 空客观题 → INVALIDATED 不进分母含警告；拒答 → REFUSED 分母排除（聚合 actual 不含它但 refusals 列表有）；grep 无 50/50 合成残留 | integration + regression | `python -m pytest test_phase2_scoring.py -v` | ❌ Wave 0 |
| 回归（全 SC） | 既有套件断言重写后全绿：m5（question_count/final_score/ score_live==3 断言）+ m6（final=round(...) 断言）+ question_bank（test_selection 配额断言） | regression | 逐文件跑三套 | ⚠️ 存在，需逐条重写（D-09 前例：**只改断言不重构风格**） |

### Sampling Rate
- **Per task commit:** 该任务撞到的单测试文件（<30s，全 mock 离线）
- **Per wave merge:** 全 8 文件逐个跑（5 个新建 + 3 个重写）+ `python eval/virtual_candidates.py --position-id <seed>` 冒烟（临时库）
- **Phase gate:** 全绿 → `/gsd:verify-work`；成功标准 1–5 逐条核（SC-1 selection_reason 落库审计、SC-2 四行公式、SC-3 升降级事件、SC-4 两层化+拒答、SC-5 评分链）

### Wave 0 Gaps
- [ ] `server/test_phase2_migration.py` — 老库模拟迁移 + 锚点回填 + score_final 合并（REF-2.7/2.9）
- [ ] `server/test_phase2_weights.py` — 7:3 三落点回归断言（REF-5.7）
- [ ] `server/test_phase2_selection.py` — 配额公式四样例 + API 级动态选题 + required 例外（REF-3.1/3.2/3.6/4.1）
- [ ] `server/test_phase2_difficulty.py` — 表驱动判据 + 事件/快照同事务（REF-4.2）
- [ ] `server/test_phase2_interview.py` — mock 分类器 + Pydantic 拒绝 + 拒答确认流（REF-1.6/1.7/4.3/4.4/4.5）
- [ ] `server/test_phase2_scoring.py` — score_final 独立/INVALIDATED/REFUSED 分母（REF-5.1/5.2/5.3/8.1）
- [ ] `server/test_m5_backend.py` — 修改：question_count/final_score/score_live 断言（D-09 前例风格）
- [ ] `server/test_m6_backend.py` — 修改：50/50 三断言重写（脚本式 check 保持）
- [ ] `server/test_question_bank.py` — 修改：test_selection 断言按新配额（脚本式保持）
- [ ] 无框架安装需求（pytest 已在环境）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（不改认证） | 既有 python-jose HS256 + require_login |
| V3 Session Management | no（session 状态机演化属 Phase 3 REF-2.6） | 既有 in_progress→completed |
| V4 Access Control | no（Phase 1 已落所有权校验；Phase 2 无新候选人资源路由） | 既有 load_owned_* helper 覆盖旧路由；submit_answer/get_session 消费面改动不新增路由 |
| V5 Input Validation | **yes（LLM 输出强 Schema = 本 phase 核心）** | `InterviewObservation` Pydantic Literal 11 态 + 观察维度约束（ge/le）；非法输出降级 MODEL_UNCERTAIN 不卡死（D-22）——**LLM 输出不直接进 SQL/控制流** |
| V6 Cryptography | no | 既有 bcrypt/JWT 不动 |

### Known Threat Patterns for FastAPI + SQLite + LLM-in-loop

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM 输出注入控制流（假 action/难度指令） | Tampering / Elevation | 两层化（D-22）：LLM 只出观察枚举 + 维度；action/难度/finish 全代码裁决（§11.5 + REF-1.7）；Pydantic Literal 白名单拒绝未知值（实测 literal_error） |
| Prompt injection 经候选人回答进 interviewer | Tampering | answer_state 11 态含 PROMPT_INJECTION 分类（§11.4）；候选回答永远是数据不是指令（CONTEXT §11.4 处理原则）；完整 INJECTION_DETECTED 事件留 Phase 3 REF-6.4 |
| selection_reason JSON 注入（伪造结构） | Tampering | selection_reason 由**代码构造**（非 LLM 输出直存）；json.dumps 落 TEXT 列，读侧 json.loads 容错 |
| 事务竞态：事件与快照不同事务 | Tampering / Repudiation | append_event 复用 Phase 1 契约（调用者持事务、不 commit）——DIFFICULTY_* 与 snapshot UPDATE 同事务（§13.1） |
| SQL 注入 | Tampering | 沿用全库 `?` 参数化；新 select_next_question 动态拼 WHERE 列名时只拼列名字面量，值走参数 |
| LLM trace 缺失（新 LLM 调用绕过 gateway） | Repudiation | 观察 LLM 仍走 call_llm_json（llm_trace 落库）——两层化不新增旁路 |

## Sources

### Primary (HIGH confidence)
- `design/final-design/总设计文档.md` §8.2/§9.1-9.4/§10.1-10.6/§11.1-11.5/§12.1-12.4/§13.1-13.2/§17/§18/§30/§31 — 全部公式、判据、枚举、DDL 逐字核对（本 phase 的规格权威）
- `server/services/question_selection.py`（67 行全文）— 现行一次性预选、CATEGORY_QUOTA、chain 逻辑、scope 过滤口径
- `server/services/interview.py`（116 行全文）— decide_next_action 签名、_mock_interview 现状、FOLLOWUP_MAX 护栏、返回 5 键
- `server/services/scoring.py`（197 行全文）— 50/50 合成三行、_latest_score_live、内存算完单事务模式、WR-14 客观题防护
- `server/db.py`（342 行全文）— _DDL 18 表、_migrate_llm_trace/_migrate_feedback_status 嗅探式先例、get_conn
- `server/api/assessment.py`（407 行全文）— create_session 预选循环、submit_answer 主链 commit 点、get_session 当前题查询
- `server/config.py` / `server/services/aggregate.py` / `server/services/aggregation.py` / `server/services/report.py` / `server/services/readiness.py` / `server/services/state_events.py` / `server/services/llm.py` / `server/services/question_bank.py` / `server/schemas.py` — 全文核读
- 既有测试四文件（test_m5_backend/test_m6_backend/test_question_bank 全文 + test_p0_chain grep）— 断言重写面清单
- 本机实测（2026-09-03/04，Python 3.13.2 + SQLite 3.45.3 + pydantic 2.10.3）：ALTER ADD COLUMN 三限制、DROP COLUMN 成功路径、UNIQUE INDEX 执行、非 CONSTANT DEFAULT 拒绝、Pydantic Literal ValidationError、CASE UPDATE 锚点回填

### Secondary (MEDIUM confidence)
- SQLite 官方文档 [ALTER TABLE](https://www.sqlite.org/lang_altertable.html) — ADD COLUMN 限制清单与 DROP COLUMN 条件（WebFetch 受限，经 WebSearch 摘要交叉核对；与本地实测完全一致）
- `server/services/prompts/interviewer.py` + `prompts/score.py` — 现行 prompt 输出契约（双层化改造的对照基线）
- `eval/virtual_candidates.py` + `eval/consistency_test.py` + `eval/assertions.py`（全文）— eval 直调链消费面核对
- `web/src/views/assessment/Chat.vue` + `PositionAssess.vue` + `web/src/utils/sse.js`（grep 定向核对）— 前端消费面（total_count/question_count/score_live/d.action）
- `.planning/codebase/ARCHITECTURE.md` + `TESTING.md` — 分层/反模式/测试纪律（两模式两纪律全文）
- `.planning/intel/decisions.md` D-006~D-016 全文 — 锁定决策原文
- `data/app.db` 直查（sqlite3）— 存量 16 aq/8 qs/6 qb 行、18 表无 state_event、final_score=score_final 同值

### Tertiary (LOW confidence)
- 无（本 phase 全部规格来自仓库内 SSOT + 代码；无外部技术选型问题）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新增包，全部依赖本机实测在位
- Architecture: HIGH — 四个改造对象全文直读 + 5 plan 切分与 CONTEXT 一一对应 + 消费面逐 grep 核对（含 report.py 隐藏消费点）
- Pitfalls: HIGH — 10 项中 8 项有实测/逐行证据；Pitfall 6（stable_evidence 边界）与 Pitfall 7（INSUFFICIENT_EVIDENCE 生产边界）各有 [ASSUMED] 标注待 plan 检查

**Research date:** 2026-09-04
**Valid until:** 2026-10-04（规格来自仓库内 SSOT 静态文件，无外部时效风险；30 天为惯例窗口）
