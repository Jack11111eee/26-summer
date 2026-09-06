# 临时讨论稿·第十轮 — SSOT 修订稿（待授权写入）

> 状态：**修订草案（非权威，未写入）**。本文件是 `design/final-design/总设计文档.md`（SSOT）的本轮修订提案完整稿。
> 依据：2026-09-06 用户对「第十轮开放参数与未决事务收敛清单」的裁决（#1–#4 取值、#5–#8 不启用摘除、#9/#10 转正、#13–#15、#16 方案一、#17–#20、#22 授权回写、§4.1 维持/勾销）。
> 写入方式：**用户核查本稿并授权后**，按「正文各节 + §14 变更日志」一次原子 commit 写入 SSOT；各分模块摘录稿（模块一~四）在 SSOT 写入后同步。
> 每条修订 **只增注记/只关闭开放项，不改变任何已定设计语义**；登记数值均为代码已存在实现的事实（新接线项在 §14 中注明「代码接线随实施」）。

**修订范围（10 处正文修订 + §14 一条变更日志）**：

| # | SSOT 位置 | 修订类型 | 内容摘要 |
|---|---|---|---|
| R1 | §6 全局数据库清单 | 事实修正 + 注记 | 表数 21 → 26（25 业务表 + schema_version 注册表），附完整清单 |
| R2 | §31 开放问题 | 关闭 4 项 | 六条中关闭 3/4/5/6 四项；1（40min 体验校准）、2（deepseek 实测校准）保留开放 |
| R3 | §19 | 数值登记 | 重大冲突极差阈值 ADJUDICATE_CONFLICT_THRESHOLD=2 |
| R4 | §20.1 | 数值登记 | 补算复核阈值 0.2（2026-09-05 关口 A 转正） |
| R5 | §17 | 出处登记 | 客观题引文截断 60 字符 + 题库三档权重阈 0.10（非开放参数） |
| R6 | §10.4 | 注记 | 检查项 6/7 澄清为 by-design 恒过 |
| R7 | §11.3 | 注记 | stable_evidence 轻量口径 by-design |
| R8 | §12.1 | 注记 | 前端 start 接线方案（入场确认按钮） |
| R8b | §18 | 注记 | 三枚举位本期不产出（by-design） |
| R14 | §14 变更日志 | 新条目 | 上述全部 + 落点文件 |

---

## R1. §6 全局数据库清单

**现文**（§6:84）：

> 现有 18 张表 + 本轮新增 3 张（`assessment_state_event / trace_link / form_instance`），共 21 张：
> - 模块一（8）：`user / position / position_alias / jd_record / competency_model / competency_item / competency_dict / llm_trace`
> - 模块二（7+2）：`assessment_session / question_bank / assessment_question / assessment_message / context_raw / form_submission / question_score` + 新增 `assessment_state_event / form_instance`
> - 模块三（2）：`report / feedback`
> - 模块四（1）：`eval_results`
> - 公共新增（1）：`trace_link`
>
> 详细字段见 §7（模块一沿用现状）、§12（模块二三演进）、§13.4（事件与 trace）。

**修订为**（整段替换，以精确清单为准）：

> 全库 **26 张物理表 = 25 张业务表 + 1 张 schema_version 迁移注册表**（以 `server/db.py` 全部 CREATE TABLE 实测为准，2026-09-06 收口盘点；迁移事务内临时表 `llm_trace_new / feedback_new` 重命名后不残留，不计）：
>
> - 模块一（8）：`user / position / position_alias / jd_record / competency_model / competency_item / competency_dict / llm_trace`
> - 模块二（13）：`assessment_session / question_bank / question_bank_task / assessment_question / assessment_message / context_raw / form_submission / form_instance / assessment_state_event / question_score / session_time_intervals / idempotency_record / bad_case_candidate`
> - 模块三（2）：`report / feedback`
> - 模块四（1）：`eval_results`
> - 公共（1）：`trace_link`
> - 迁移注册表（1）：`schema_version`
>
> 合计 8+13+2+1+1+1 = 26。详细字段见 §7（模块一沿用现状）、§12（模块二三演进）、§13.4（事件与 trace）。

（自查记录：本节初稿曾误将 context_raw 重复列入模块二并将 schema_version 归属模块二，已上表修正。）

## R2. §31 开放问题（实施期定）

**现文**（§31:660-668）：

> 1. `N` 默认值与 40 分钟体验校准；
> 2. 滑窗 Token 参数、`REFINE_MIN_TOKENS` 校准；
> 3. 补算人工复核阈值；
> 4. 词典候选 top10 匹配阈值（已裁决 0.5：编辑距离+子串，2026-09-06）、清洗标题词表；
> 5. trace 保留期/脱敏细节与 LLM 供应商数据约束（实施期与合规确认）；
> 6. 幂等清理阈值与策略。

**修订为**：

> 1. `N` 默认值已裁决 10[02-007]；**余项：40 分钟体验校准（随真实 LLM 验收）**；
> 2. 滑窗 Token 已裁决 8000[03-007]；`REFINE_MIN_TOKENS=500` 已定默认；**余项：deepseek 接入后的实测校准**；
> 3. ~~补算人工复核阈值~~ **已裁决 0.2**（2026-09-05 关口 A；IMPUTED 覆盖率 > 0.2 → PROVISIONAL + 人工复核，`aggregation.py IMPUTE_RATIO_THRESHOLD`）；
> 4. ~~词典候选匹配阈值、清洗标题词表~~ 匹配阈值 **已裁决 0.5**（2026-09-06，`config.py DICT_MATCH_THRESHOLD`）；清洗走 pipeline 内置 NOISE_HEADERS/_SUFFIXES 硬编码表，**配置词表不启用（2026-09-06 演示期裁决，`TITLE_CLEAN_WORDS` 占位摘除）**；
> 5. ~~trace 保留期/脱敏~~ **演示期不启用**（2026-09-06 裁决：trace 全量保留利于验收审计，脱敏妨碍观察层验证；`TRACE_RETENTION_DAYS / TRACE_DESENSITIZE` 占位摘除）。生产 PII 治理（保留期/脱敏/供应商数据约束）随真实上线再开；
> 6. ~~幂等清理阈值与策略~~ **演示期不启用**（demo 量级永远到不了阈值，无清理任务/接口 by-design；`IDEMPOTENCY_CLEANUP_THRESHOLD` 占位摘除）。生产清理策略随真实上线再开。

同时 §13.4 幂等末行（`幂等记录长期保存，达阈值自动提醒清理，留管理员清理接口（策略实施期定）`）追加注记：**演示期阈值与清理接口均不启用（2026-09-06，见 §31-6）**。

## R3. §19 item 内多题合并与综合题

**现文**（§19:516 附近，裁决规则段）：

> 裁决规则：普通最低测量资格先检查（综合题不能替代）；按 rubric/覆盖/稳定性/冲突裁决，**不按来源加权、不按题数重复乘 item.weight**；共享 evidence span 只影响证据解释、不折扣不自动复制；**重大冲突取较低值并留人工复核标记**；……

**修订**（在"重大冲突取较低值并留人工复核标记"后追加括注）：

> **重大冲突取较低值并留人工复核标记（判据：观测等级极差 ≥ `ADJUDICATE_CONFLICT_THRESHOLD = 2`，2026-09-06 转正登记，集中 `config.py`）**；

代码侧同步（实施项，非本稿）：`services/aggregation.py:23` 模块级常量挪 `config.py`。

## R4. §20.1 观察集合与补算

**现文**（§20.1 末条）：

> 补算比例超阈值 → 临时报告 + 人工复核（阈值实施期定）。

**修订为**：

> 补算比例超阈值 → 临时报告 + 人工复核。**阈值已裁决 0.2**（`IMPUTE_RATIO_THRESHOLD`，2026-09-05 关口 A：IMPUTED 覆盖率 > 2 成 → PROVISIONAL + HUMAN_REVIEW_REQUIRED）。

## R5. §17 评分链

**现文**（§17 第一组列表）：

> - 客观题：代码匹配判分（answer_key 为空属于题库缺陷，判题库无效而非满分）；

**修订**（该条内追加括注 + 追加一条登记；仓位说明：题库三档权重阈出自 07 §6.2 与 question_bank.py 均已存在）：

> - 客观题：代码匹配判分（answer_key 为空属于题库缺陷，判题库无效而非满分）；**客观题 evidence_quote 取候选人回答前 60 字符（展示截断固定规则，现为 `scoring.py:192` 字面量，实施时常量化为 `_OBJECTIVE_QUOTE_LEN`；非开放参数）；命中=5 分 / 未命中=1 分，与 §20.3 `(score−1)/4` 归一化同口径**；
> - 题库生成结构规则（非运行期参数）：hard_skill 项 `weight>0.10` 生成 easy/medium/hard 三档，否则两档；soft_skill 两档；experience/qualification 无难度各 1 题（07 §6.2，`question_bank.py _question_plan`）。

## R6. §10.4 开考前可测量性检查

**现文**（§10.4:275 检查项段末）：

> ……hard/soft 配额可满足（**有 item 但题库不足 → 不允许转移名额，阻止开考**）；综合题槽位有合法题目（若策略 I>0）；qualification 表单 schema 可用。

**修订**（两句各追加括注）：

> ……hard/soft 配额可满足（**有 item 但题库不足 → 不允许转移名额，阻止开考**）；综合题槽位有合法题目（若策略 I>0。**本期 I=0 且综合题不排期 → 恒过，by-design，2026-09-06**）；qualification 表单 schema 可用（**现为模型 items 数据驱动生成（form_instance.schema_snapshot），其存在性已被"items 非空"检查隐式覆盖 → 恒过，by-design，2026-09-06**）。

代码侧同步（实施项）：`services/readiness.py:51,58-59,178-179` 注释改写为同一口径。

## R7. §11.3 证据判定

**现文**（§11.3 stable_evidence 段）：

> **`stable_evidence`**：两个不同普通题实例的独立有效观察，或一次 hard 强证据（仍须满足 rubric 与证据完整性）；依据观察独立性 + target 覆盖一致性 + 锚点一致性 + 无矛盾 + rubric/version 一致。同一回答的两个相似句子不算两次观察。**证据冲突 → 不平均，stable_evidence=false → 人工复核。**

**修订**（段末追加实施注记）：

> **实施注记（2026-09-06）**：现实现为轻量口径——同 item 充分观察计数 `sufficient_in_row ≥ 2`（`assessment.py _stable_evidence_light`，事件表布尔聚合），**by-design 转正**：其唯一消费者是难度状态机升档，漏判只导致保守不升档，不影响任何分数/报告/聚合；完整判据（观察独立性四要素、冲突不平均）依赖 P-interviewer 结构化输出重构（§26 登记项），重构时一并进行。

## R8. §12.1 assessment_session 状态机（前端 start 接线方案登记）

**现文**（§12.1:358-364）：状态机 `PENDING_START → ACTIVE → …`（无前端接线说明）。

**修订**（状态机代码块后追加）：

> **前端接线（2026-09-06 裁决方案一 [03-010] 收口）**：Chat.vue 在 `phase='PENDING_START'` 时渲染居中"开始测评"按钮替代输入区，点击 → `POST /sessions/{id}/start` → 重新拉取会话（phase 门放行 → 服务端派发首题 + 开计时区间）；409 `SESSION_ALREADY_ACTIVE` 按幂等处理直接拉取。**不采用** create 后自动 start（架空 §15 计时起算语义）或 get_session 隐式激活（写操作藏进只读 GET）。

## R8b. §18 拒答（枚举位注记）

**现文**（§18 全节 + §12.4 分母规则）。

**修订**（§18 末尾追加一条）：

> **实施注记（2026-09-06）**：score_state 六态枚举位 `INSUFFICIENT_EVIDENCE / NOT_ADMINISTERED / INCOMPLETE` 本期**不产出**（by-design）：现终态由 REFUSED（拒答）、INVALIDATED（题库无效）与聚合层 IMPUTED/PROVISIONAL/NO_VALID_OBSERVATION + missing_warnings（§20.1/§20.2）语义等价覆盖；NOT_ADMINISTERED 的潜在场景（派发未答实例进 finalize）走 §20.1 缺失路径，不做区分。枚举位保留供校验与后续生产（D-28 口径集）。

## R14. §14 变更日志（新增一条，追加在表末）

| 日期 | 变更 | 原因 | 影响面 |
|---|---|---|---|
| 2026-09-06 | **第十轮收口·开放参数与未决事务裁决**：①§6 表数修正 21→26（25 业务+schema_version）；②§31-3 补算复核阈值裁决 0.2、§31-4 清洗词表不启用、§31-5 trace 保留期/脱敏演示期不启用、§31-6 幂等清理演示期不启用（四个 config 占位摘除）；③§19 重大冲突极差阈值登记 `ADJUDICATE_CONFLICT_THRESHOLD=2`（进 config）；④§20.1 补算复核阈值 0.2 登记；⑤§17 客观题引文截断 60 字符 + 命中 5/未中 1 口径登记；⑥§10.4 检查项 6/7 注记 by-design 恒过；⑦§11.3 stable_evidence 轻量口径 by-design；⑧§18 三枚举位本期不产出注记；⑨§12.1 前端 start 接线方案一（Chat.vue 入场确认按钮）；⑩§13.4 幂等清理演示期不启用注记 | 用户 2026-09-06 对第十轮收敛清单逐项裁决（BAD_CASE_DIVERGENCE_THRESHOLD=2、MAX_JD_LENGTH=10000、MAX_JD_FILE_LINES=500、MAX_PAGINATION_LIMIT=100 同日裁决，代码接线随实施不含本次文档写入） | §6/§10.4/§11.3/§12.1/§13.4/§17/§18/§19/§20.1/§31/§14；`server/config.py`、`server/services/{aggregation,scoring,readiness,report}.py`、`server/api/assessment.py`、`web/src/api/index.js`、`web/src/views/assessment/Chat.vue` |

---

# 自查记录（2026-09-06，起草完成后逐条核对）

1. **R1 表数复核**：逐表对照 `grep CREATE TABLE` 实测 26 名（含 schema_version），归属重列后 8+13+2+1+1+1=26 吻合；初稿的 context_raw 重复列与 schema_version 错归已在正文 R1 修正（写入时只采用修正后的整段）。
2. **R2 与既有裁决不冲突**：§31 第 1、2 条保持开放（仅关闭 3/4/5/6 四项），与 §1.4 已裁决区中 MAX_CONTEXT_TOKENS/REFINE_MIN_TOKENS 的「留实测校准」性质一致；第 4 条阈值 0.5 已裁决（2026-09-06）不在本稿重复改写，仅关闭词表部分。
3. **R3/R4 为事实登记非新语义**：2 与 0.2 均为代码已存在值（aggregation.py:23/28），SSOT 只补注记；阈值挪 config 属实施项，不写入 SSOT 正文。
4. **R6 证据核实**：services/forms.py（base 模板 + 会话模型 gate=1 items 动态展开，:63-88 确证）——qualification 表单 schema 由「items 非空」隐式覆盖，R6 注记成立。
5. **R8 与 §13.1 一致**：start 三动作同事务在 §13.1 已有表述，R8 只补前端接线方案（方案一），无契约改动；方案二/三否决理由已述于收敛清单 #16。
6. **影响面文件路径核对**：config.py、services/{aggregation,scoring,readiness,report}.py、api/assessment.py、web/src/api/index.js、web/src/views/assessment/Chat.vue 均为实际存在文件（起草时已逐一 grep 证实）。
7. **越权检查**：全部修订均为注记/登记/开放项关闭；分数链（§17）、权重口径（§8.2）、状态机（§12）、事件契约（§13）正文语义零改动。
8. **代码接线不在本稿**：#1–#4 取值接线、#10 挪 config、#13 常量化、#15 env 化、#16/#17 均属实施项（收敛清单 §6 收口动作第 3–5 步），SSOT 写入后另行 commit 执行；本稿仅覆盖文档侧修改。
