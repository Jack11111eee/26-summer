# 项目 checkpoint：AI 岗位胜任力测评与人才画像系统

> **文档性质：上下文保护 checkpoint 快照，不是 SSOT，不是实施方案，不是新的设计决策。**  
> **快照日期：2026-09-01**  
> **用途：记录截至本 checkpoint 为止已经阅读、讨论、核对和对齐过的项目理解，防止后续上下文过长时丢失。**  
> **重要约束：本文禁止自行补充未讨论的公式、字段、阈值、状态、接口或实现方案。凡未完全明确者，按当前状态原样标记为“未收敛 / 部分收敛 / 未确认”。**

---

## 0. 使用与优先级说明

### 0.1 本文不是规范来源

本文仅用于保存当前上下文，不替代：

- `design/总设计文档.md`；
- 前几轮临时讨论稿；
- 当前代码；
- 用户后续确认的新结论。

在后续讨论中，本文只能帮助恢复上下文，不能自动授权改文档或改代码。

### 0.2 当前设计文档的规范优先级

目前已经对齐的文档治理规则是：

1. `design/总设计文档.md` 正文；
2. `design/总设计文档.md` §13 变更日志；
3. 分模块设计文档；
4. 当前实现代码；
5. 历史档案和已弃用讨论稿仅用于理解背景。

任何正式设计变更，须先更新《总设计文档》正文和 §13 变更日志，再进入代码修改。

### 0.3 本 checkpoint 的状态标记

- **已收敛/已确认**：用户已经明确确认，或此前已经明确作为当前边界确认；
- **部分收敛**：总体方向已确认，但公式、字段、边界或验收标准未完成；
- **未收敛/未确认**：仍需继续讨论，不能作为实施依据；
- **当前实现**：从已做的代码静态核对中得出的现状，不代表设计认可；
- **明确未做/延期**：已经确认当前不在实施范围；
- **Prompt 暂缓**：已识别需要 Prompt 的位置，但按用户要求暂不展开。

---

# 1. 项目总体理解

## 1.1 项目目标

系统要解决的问题是：企业 JD 是非结构化文本，学生/求职者难以判断自己与岗位要求之间的差距。系统将 JD 转化为可测量的岗位胜任力模型，再基于该模型开展动态测评并生成候选人的人才画像和能力评分。

总体业务闭环：

```text
JD 文本
→ 胜任力模型
→ 动态测评/出题
→ 人才画像/评分
→ 测试、反馈与质量回流
```

项目不是只做页面展示，而是包含：

- JD 清洗与解析；
- 原子能力抽取和归一；
- 多 JD 聚合为岗位能力模型；
- 人工审核与模型版本确认；
- 岗位题库和综合题库；
- 候选人动态测评；
- 终局评分、聚合和报告；
- trace、反馈、bad case 和测试闭环。

## 1.2 系统范围

截至目前用户已明确：

系统做：

- 测评用户的人才画像报告；
- 各能力项评分；
- 测评证据展示；
- 测评过程和异常记录；
- 必要的人工复核。

系统不做：

- 最终录用判断；
- 最终录用排序；
- 自动通过/淘汰；
- 代替企业作出最终招聘决定。

因此，后续正式设计不应继续把“最终录用排序”“最终录用结论”写成系统职责。

## 1.3 已确认的核心原则

目前已经确认的核心原则：

1. **LLM 不负责权重和分数算术**；
2. **人工确认的岗位模型是权威**；
3. **过程和结果要留痕**；
4. `score_live` 只作为过程性选题和难度导航证据，不参与最终分数；
5. 候选人回答、状态、异常、证据、模型调用和版本必须可以追溯；
6. 不采用自由 ReAct 让模型自由控制整场测评；
7. 采用当前 FastAPI 服务加明确的领域状态机；
8. 状态迁移、题量、配额、权重、难度护栏、聚合和报告发布条件由代码控制；
9. LLM 如果参与，只能在明确边界内完成结构化观察、分类、话术、抽取或评分辅助；
10. 正式测评不设计 Web Search。

---

# 2. 当前技术架构理解

## 2.1 后端

后端位于 `server/`，当前静态核对到的技术栈是：

- Python；
- FastAPI；
- SQLite；
- JWT / passlib；
- Pydantic；
- OpenAI-compatible SDK；
- 默认可使用 mock LLM；
- 非 mock 模式可对接配置的 DeepSeek 兼容接口。

主要入口和目录：

- 应用入口：`server/main.py`；
- 认证：`server/api/auth.py`；
- 候选人测评：`server/api/assessment.py`；
- 管理端 API：`server/api/admin/`；
- 领域服务：`server/services/`；
- Prompt 文件：`server/services/prompts/`；
- 评测脚本：`eval/`。

关键代码位置（以此前静态核对为准）：

- `server/main.py:16-77`；
- `server/config.py:8-20`；
- `server/requirements.txt:1-10`；
- `server/services/llm.py:13-62`。

当前后端是单机演示/原型形态：

- SQLite 单文件；
- 数据库 DDL 主要内嵌在 `server/db.py`；
- 没有 Alembic；
- 后台任务使用 FastAPI `BackgroundTasks`；
- 没有持久任务队列、独立 worker、重启恢复机制；
- 没有完整部署清单、CI 或生产运维方案。

这些是当前实现状态，不代表后续真实上线目标已经最终定稿。

## 2.2 前端

前端位于 `web/`，技术栈是：

- Vue 3；
- Vite；
- Vue Router；
- Pinia；
- Element Plus；
- Axios；
- ECharts。

主要位置：

- 路由：`web/src/router/index.js`；
- 认证 store：`web/src/stores/auth.js`；
- API：`web/src/api/index.js`；
- 管理端页面：`web/src/views/admin/`；
- 候选人页面：`web/src/views/assessment/`；
- 共享组件：`web/src/components/`。

当前前端路由包括：

### 公共认证

- `/login`；
- `/register`。

### 管理端

- `/admin/positions`；
- `/admin/positions/:id`；
- `/admin/positions/:id/review`；
- `/admin/positions/:id/versions`；
- `/admin/dict`；
- `/admin/users`；
- `/admin/test-center`。

### 候选人端

- `/assessment/positions`；
- `/assessment/positions/:id`；
- `/assessment/session/:session_id`；
- `/assessment/report/:session_id`。

相关位置：`web/src/router/index.js:3-89`。

当前前端实现状态：

- 管理端岗位/JD/模型/词典/用户等页面大体接真实 API；
- 候选人岗位、模型预览、会话、对话、报告、反馈页面大体存在；
- 测试中心页面和后台接口存在；
- 没有前端测试、lint、typecheck 或浏览器 E2E 脚本；
- 默认 LLM 仍为 mock，真实数据库/API 不等于真实外部模型已经验证。

## 2.3 前端视觉状态

目前存在多代视觉方向并存：

1. 传统管理页使用 Element Plus、白色卡片和蓝色后台风格；
2. 候选人端和测试中心使用 Grail × Notion 的米白/粉彩方向；
3. `prototype/redesign/final-admin/` 存在新的“素色动态雾团工作台”静态方案，但尚未接入 Vue；
4. `prototype/` 下多数页面为静态硬编码原型，不接真实 API。

当前未提交工作树曾包含原型相关变化：

```text
M prototype/redesign/10-blocks/admin.html
M prototype/redesign/10-blocks/theme.css
?? prototype/redesign/candidate-material/
?? prototype/redesign/final-admin/
```

这些原型变化不属于已经接入运行页面的实现，且本 checkpoint 不对其做任何处理。

---

# 3. 数据库当前事实

## 3.1 当前静态核对到的实际表数量

设计文档部分位置仍写 14 张表；代码静态核对到的实际 DDL 是 18 张表：

### 模块一：8 张

- `user`；
- `position`；
- `position_alias`；
- `jd_record`；
- `competency_model`；
- `competency_item`；
- `competency_dict`；
- `llm_trace`。

### 模块二：7 张

- `assessment_session`；
- `question_bank`；
- `assessment_question`；
- `assessment_message`；
- `context_raw`；
- `form_submission`；
- `question_score`。

### 模块三：2 张

- `report`；
- `feedback`。

### 模块四：1 张

- `eval_results`。

代码位置：`server/db.py:9-213`。

这是当前实现事实。SSOT 的表数量和清单尚未回写收敛。

## 3.2 当前数据库设计方向

已经讨论并确认的方向：

- 题库逻辑上是树，数据库物理上使用扁平规范化表；
- 不为 `hard_skill`、`soft_skill`、`required` 等分别建立多层物理表；
- 当前不建立 `question_bank_relation` 表；
- 需要留下扩展记录或接口，未来关系复杂到现有字段无法表达时再建关系表；
- session 采用动态实例化方案 A：每次策略实际选择题目时创建 `assessment_question` 实例；
- 新增一张 `assessment_state_event` 表，承载所有会话状态事件；
- 不为每种状态再建立大量专用表；
- 当前状态字段和事件历史分工保存；
- 状态更新和事件写入要求在同一事务中完成。

这些方向已确认，但最终字段、迁移和索引仍未收敛。

## 3.3 尚未收敛的数据库内容

以下只记录未完成部分，不自行补充：

- `question_bank` 普通题与综合题最终字段；
- 综合题多能力绑定的存储方式；
- `assessment_question` 动态实例字段；
- `assessment_message` 与 `question_score` 的最终字段职责；
- `measurement_target`、`evidence_coverage`、`rubric_mapping` 的存储方式；
- `equivalence_group_id` 的约束；
- form schema 的存储方式；
- `user_profile` 是扩展现有用户还是未来独立表；
- `assessment_state_event` 的最终字段、事件类型和索引；
- trace 与 message/question/report 的严格关联方式；
- SQLite 迁移、回滚和增长策略。

---

# 4. 模块一：JD 解析与胜任力模型

## 4.1 目标和业务链

模块一负责将 JD 转化为岗位胜任力模型：

```text
导入 JD
→ 规则清洗
→ LLM 原子能力抽取
→ 词典候选与消歧归一
→ 多 JD 聚合
→ 等级冲突裁决
→ 代码计算权重
→ 管理员审核编辑
→ 确认模型版本
```

模块一当前被认为已经完成 M1–M3 的主要功能。

## 4.2 已确认的模块一原则

- 本期 JD 接入使用粘贴和文件；
- 浏览器插件不是当前主接入渠道，属于后续保留项；
- 标题规范化后做精确/别名匹配；
- 未命中岗位时建立 `pending_review`，由人工审核；
- 不再使用旧方案中的额外 LLM 自动归岗；
- LLM#1 做原子能力抽取；
- LLM#2 做词典消歧/归一；
- LLM#3 只在能力等级冲突时裁决；
- 频率、importance 聚合和权重由代码完成；
- 人工可编辑和确认模型；
- confirmed 模型版本不能被静默覆盖；
- 证据和中间产物应留痕；
- 能力词典作为独立管理能力存在；
- 被引用词典条目不能简单删除，应按已有方向处理停用/合并。

## 4.3 模块一状态理解

设计层面曾表述：

```text
imported → parsing → parsed / failed → aggregating → draft / stalled → confirmed
```

其中：

- `jd_record.status` 主要表达 JD 解析过程；
- `competency_model.status` 主要表达 draft/stalled/confirmed；
- `aggregating` 的具体数据库状态表达仍需核对和收口。

当前代码已有：

- JD 导入和批量导入；
- JD 详情、重解析；
- 解析流水线；
- 聚合；
- 模型编辑和确认；
- stalled 重试；
- 版本列表和 diff；
- 岗位审核、改归、词典和用户管理。

关键位置：

- `server/api/admin/jds.py:26-65`；
- `server/services/pipeline.py:184-236`；
- `server/services/aggregate.py:29-192`；
- `server/api/admin/models.py:42-177`。

## 4.4 模块一当前缺口

当前静态核对中，模块一核心链自动化保护较少，尚未完成的内容包括：

- JD 清洗边界测试；
- 抽取 schema 异常测试；
- 消歧、词典排除项测试；
- importance 阈值测试；
- 多 JD 聚合测试；
- 权重尾差测试；
- LLM 等级裁决失败到 stalled 的回归测试；
- confirmed 不可编辑测试；
- 版本升级和 diff 测试；
- 管理员权限测试。

这只是测试/实现差距登记，不代表本文现在授权修复。

## 4.5 历史差异

以下旧方案不再作为当前设计：

- 插件作为当前主导入渠道；
- 额外 LLM 自动判断新岗位/别称；
- LLM 直接分配最终权重；
- 能力词典没有独立后台；
- 将 trace 主要放在模型内 JSON；
- 完整 diff 三选一审阅流已完全落地。

---

# 5. 模块二：AI 动态测评

## 5.1 模块二目标

模块二基于模块一 confirmed 模型版本进行：

- 岗位题库生成；
- 普通题选取；
- 候选人 session；
- 多轮对话；
- 当前题追问；
- 输入精炼；
- 表单展示/提交方向；
- 过程性 `score_live`；
- 为后续终局评分准备证据。

## 5.2 当前已确认的题库分类

普通对话题库只使用两个大类：

```text
hard_skill
├── required
├── preferred
└── plus

soft_skill
├── required
├── preferred
└── plus
```

`experience` 和 `qualification` 不进入普通对话题库的三层分类：

- `qualification` 只走结构化表单，不占普通主问题配额；
- `experience` 通过表单/简历检测，不占普通主问题配额；
- 两者保留岗位模型可追溯性，但不进入普通对话选择器；
- 当前曾提出用 `measurement_mode=form` 表达这一边界，但最终字段尚未收敛。

## 5.3 普通题规则

已确认：

- 普通题只能绑定一个主评分能力项；
- 题目必须属于一个大类和一个类内 tier；
- 题目必须有难度、题型、rubric/版本等测量信息；
- 普通题可以属于 chain；
- 不能通过辅助字段偷偷对第二个能力项计分。

## 5.4 综合题规则

已确认：

- 综合题单独建立逻辑题库；
- 综合题可以绑定多个能力项；
- 每个绑定能力项需要独立的 `measurement_target`、证据和评分映射；
- 综合题在普通 hard/soft 计划完成或合法封存后进入；
- 综合题拥有独立题量槽位，不占普通 hard/soft 基础配额；
- 每个 session 最多两道综合题；
- 一题绑定多个能力项不等于多个能力项自动完成有效测量；
- 综合题不能让同一段证据无依据地重复计入多个完整能力项。

综合题的最终评分公式、证据拆分和第二题触发条件尚未收敛。

## 5.5 主问题、题面实例和 followup

已确认：

- 普通能力题路径是 `easy → medium → hard`；
- 综合题是独立综合测量阶段，不是普通难度的第四级；
- 如果 easy、medium、hard 是不同题面，每个实际呈现的题面都创建新的 `assessment_question` 实例；
- `followup` 属于当前题实例内部的子轮次；
- `followup` 不创建新主问题实例；
- `followup` 不增加主问题数量；
- `followup` 不占综合题槽位；
- 每题最多两次 followup。

实例结构被理解为：

```text
assessment_question
├── 首次回答
├── followup-1
└── followup-2
```

## 5.6 有界测评循环

目前采用的总体方向：

```text
Observation → Policy/Plan → Act → Evaluation → Persist
```

含义：

- Observation：可由 LLM 参与结构化观察/分类；
- Policy/Plan：由代码依据状态、配额、难度和限制裁决；
- Act：生成受限话术或执行允许的交互动作；
- Evaluation：判断证据是否充分、覆盖哪些 target；
- Persist：持久化状态、证据、版本、预算和调用信息。

不采用自由 ReAct 直接控制：

- 题量；
- 追问上限；
- 结束；
- 难度规则；
- 权重；
- 综合题数量；
- 最终评分。

## 5.7 `hard_skill : soft_skill = 7 : 3`

已确认：

```text
hard_skill : soft_skill = 7 : 3
```

同时作用于两个不同层面：

1. 普通能力项最终 `item.weight` 的大类总权重比例；
2. 普通主问题的基础数量比例。

最终权重层的表达是：

```text
Σ hard item.weight = 0.70
Σ soft item.weight = 0.30
```

普通主问题资源层是：

```text
hard_base_quota : soft_base_quota ≈ 7 : 3
```

不得在最终聚合时再次把 hard 分乘 0.70、soft 分乘 0.30，避免重复加权。

以下仍未收敛：

- `N` 的精确定义；
- 7:3 转整数题量的最终算法；
- 只有一个大类存在时的最终处理；
- 题库不足时的题量转移；
- tier 内部的整数分配。

## 5.8 `required / preferred / plus`

已确认：

- 影响原始重要性、题量配额和覆盖优先级；
- required 有刚性覆盖要求；
- 不再额外乘最终分数；
- 最终业务权重由 `item.weight` 表达。

仍未收敛：

- 类内 tier 权重如何转换成整数题量；
- required 最小覆盖和比例配额冲突时的精确算法；
- preferred/plus 是否可能完全被挤掉；
- item.weight、tier 和可用题库的最终联合选择算法。

## 5.9 普通主问题数量与综合题数量

当前使用的概念是：

```text
ordinary_plan_count
ordinary_exception_count
integrated_plan_count
```

其中：

- `ordinary_plan_count`：普通题计划数量；
- `ordinary_exception_count`：required 刚性例外新增的普通题数量；
- `integrated_plan_count`：独立综合题槽位计划数量；
- 综合题最多两题；
- followup 单独统计，不计入主问题数量。

最终 `N`、综合题默认计划数量、required 例外次数和各类配额仍未完全收敛。

## 5.10 required 刚性例外

已确认方向：

- 当前大类或 tier 配额达到后，如果 required 能力没有获得有效测量机会，可以触发刚性例外；
- 允许临时增加普通主问题；
- 例外必须留痕；
- 不改变该能力项的 `item.weight`；
- 额外题增加测量机会，不增加岗位重要性；
- 同一 item 多题证据应先在 item 内聚合，不能重复乘 item.weight。

未收敛：

- 同一 required item 的例外次数上限；
- 例外题从什么难度开始；
- 例外题是否走完整难度路径；
- 例外后的报告和事件字段；
- 例外后仍缺失的最终状态。

## 5.11 Chain、难度和 followup 的关系

已经确认要区分：

- `followup`：当前题内补证据；
- `chain`：题目之间的预定义路径关系；
- `difficulty`：普通题难度层级。

已确认的总体处理：

1. 当前题仍需合法补证据时，先 followup；
2. 当前题结束后，required 未覆盖优先；
3. 在目标 item 内依据难度路径选题；
4. chain 只有在后继条件满足时才继续；
5. chain 不是无条件优先；
6. 如果继续 chain 会挤掉未覆盖 required，可以优先 required；
7. 时间不作为提前拒绝 chain、升级或降级的筛选条件。

具体词典序、过滤条件和冲突处理仍未最终写死。

## 5.12 等值备用题

已确认：

- 等值备用题中，参与总分权重的相关字段必须一致；
- 等值不能只因为题面相似就成立；
- `difficulty` 不同的升/降难度题，不应直接称为等值备用题；
- schema 字段一致和测量意义等值要区分；
- 正式替换需要经过批准的测量等值定义。

仍未收敛：

- 最终字段清单；
- `measurement_equivalent` 的存储和审核方式；
- 测量等值的离线验证标准；
- 综合题和普通题之间是否存在等值关系。

## 5.13 难度路径

已确认：

```text
easy → medium → hard
```

之后进入独立综合题阶段：

```text
普通 hard/soft 阶段完成或合法封存
→ integrated question 阶段
```

难度不构成最终分数第三层权重。

已确认的降级触发方向：

- 跳过；
- 同一 item、同一难度下连续两道有效题未达到最低锚点；
- followup 后仍然模糊；
- followup 后仍然错误或不足；
- 当前难度不是最低难度时才执行普通降级；
- 最低难度不能继续降级。

不能把以下情况当普通答错触发降级：

- 技术故障；
- 无障碍问题；
- 题目无效；
- 模型无法判断；
- 合理流程质疑；
- 明确拒答；
- 单纯紧张、停顿或表达风格。

仍未收敛：

- 每一级具体升级所需的“充分证据”；
- `stable_evidence` 的最终机器判定；
- 降级后重新升级的最终规则；
- 题库没有中间难度时是否允许跳级；
- 某 item 是否必须到 hard；
- 最高难度题的具体尝试数量。

## 5.14 难度与最终分数

已确认：难度不直接加权。

当前讨论过并倾向采用的表达是：

- 题目配置 `observable_level_max`；
- easy/medium/hard 对可观察能力等级的支撑上限可以不同；
- easy 题高质量回答不能单独支撑超过其上限的等级；
- hard 题答好可以支持更高能力等级；
- hard 题答不好仍可得到低等级；
- 最终仍把证据映射到统一的能力等级，再使用固定 `item.weight`。

仍未收敛：

- `observable_level_max` 的具体配置方法；
- 每个难度对应的等级边界；
- `required_level` 如何影响路径；
- 多道不同难度题如何合并为一个 item 的 `score_final`；
- 综合题是否可以提供最高等级证据。

## 5.15 证据充分和稳定证据

当前候选定义（尚未完成最终实现细化）：

### `evidence_sufficient`

候选条件包括：

- 与当前题 `measurement_target` 相关；
- 覆盖 rubric 要求的必要考察点；
- 有具体、可归因的行为/事实；
- 不是拒答、跑题、纯态度或复述题目；
- 可以定位到原始回答 span；
- 没有触发模型不确定或题目无效。

### `stable_evidence`

候选条件包括：

- 两次独立有效观察，或一次高难度强证据；
- 证据不互相矛盾；
- 不是同一回答重复切片；
- 没有依赖未经批准的答案线索；
- 难度和 rubric 版本可追溯。

具体阈值、字段和机器判定方式尚未收敛。

## 5.16 最高难度题

已确认含义：

> 只对最终有机会达到高等级的能力项问最高难度题。

不是：

- 每个 session 固定问相同数量；
- 所有 required item 都必须问最高难度。

仍未收敛：

- “有机会达到高等级”的最终定义；
- 是岗位/rubric 驱动、过程表现驱动，还是二者组合；
- 每个能力项最高难度题的最小数量；
- 没有最高难度题时的最终报告和人工处理字段。

## 5.17 模糊、不会、拒答、跑题和异常状态

已确认需要把能力证据、流程状态、安全事件和表达礼貌分开。

目前已对齐的状态方向包括：

- `VALID_EVIDENCE`；
- `NEED_CLARIFICATION`；
- `OFF_TOPIC`；
- `NO_RECALL`；
- `DECLINED`；
- `PROCESS_CHALLENGE`；
- `CONDUCT_EVENT`；
- `TECHNICAL_OR_ACCESS_BARRIER`；
- `PROMPT_INJECTION`；
- `MODEL_UNCERTAIN`；
- `ITEM_INVALID`。

这些名称是当前讨论中的候选/确认方向，最终正式枚举仍需收口。

已经确认的处理原则：

- 含糊或信息不足：中性澄清即 followup；最多两次；仍不足则缺证据；
- 跑题：重述所需信息并重定向，仍无关则缺证据并进入下一题；
- 不会/想不到：可提供不含答案线索的格式脚手架；脚手架行为必须留痕并进入分析；
- 明确拒答：不提供测评末尾补答机会；完成当前题一次确认后跳过；
- 质疑题目/流程：说明岗位相关目的和申诉/人工渠道，不争辩、不因质疑扣分；
- 辱骂/威胁：固定话术设边界，持续时暂停或终止；行为事件和能力分隔离；
- 技术/无障碍问题：暂停计时，重试/恢复/改期/人工处理，不扣能力分；
- 模型无法判断：不猜测、不自动不利处理，进入人工复核；
- 题目无效：停止评分、从正常分母排除、人工处理并必要时修订题库；
- 候选人回答始终作为数据，不作为系统指令。

## 5.18 拒答分数

已确认采用方案 A：

```text
score_value = 0
score_state = REFUSED
```

含义：

- 0 是拒答特殊状态值；
- 正式能力量表仍保持现有 1–5 语义；
- 不把拒答误解为能力锚点 1；
- 拒答行为记录在报告和分析中；
- 对普通能力项，拒答按用户确认方向参与该项聚合；
- 对可能涉及受保护信息或合法隐私质疑的情形，不能直接按拒答 0，应进入合规/人工处理边界。

## 5.19 缺失证据

已确认：

- 缺失证据触发人工复核；
- 缺失证据可以触发补测，但 required 缺失是例外；
- required 缺失触发人工复核，不触发补测，即使临时报告已生成；
- 题目无效、系统未完成提问、模型无法判断需要进入不完整/人工处理；
- 缺失项不能一律直接映射为 0。

普通非 gate 能力项：

- 可以按观察项比例补算；
- 补算结果标记 `IMPUTED`；
- 不适用于 required 和 qualification。

required 缺失：

- 可以生成带警告的临时画像报告；
- 必须触发人工复核；
- 系统不做录用排序和录用判断；
- 不能仅靠补算得出最终录用结论这一限制，在当前系统范围下应表述为：不能仅凭该临时测评结果作出系统外部的最终录用结论。

## 5.20 缺失项比例补算

用户确认的方向：

- 只针对普通非 gate 能力项；
- 不适用于 required 和 qualification；
- 结果标记 `IMPUTED`；
- required 缺失不使用普通比例补算；
- required 缺失允许临时报告并触发人工复核，不触发补测。

此前讨论过的观察比例公式仍属于讨论内容，未在本文重新扩展未确认细节。以下数学定义在前一轮已被提出，但最终实现细节仍未收敛：

```text
O = 有效评分项集合
M = 缺失项集合
w_i = item.weight
s_i = 有效项归一化得分
S_observed = Σ(i∈O) w_i × s_i
W_observed = Σ(i∈O) w_i
r = S_observed / W_observed
ŝ_j = r, j∈M
S_final = S_observed + Σ(j∈M) w_j × ŝ_j
```

仍未收敛：

- `O` 的精确定义；
- 没有任何有效观察项时的处理；
- 多题同 item 的拒答和有效回答如何合并；
- 补算结果在报告中的展示方式；
- 人工复核如何覆盖补算结果。

## 5.21 `normalized_item_score`

此前讨论的基础归一化是：

```text
normalized_item_score = (score_final - score_min) / (score_max - score_min)
```

若量表仍是 1–5，则：

```text
normalized_item_score = (score_final - 1) / 4
```

当前已确认第 23 项接受这个基础归一化方向，但拒答特殊值不能直接套入普通 1–5 量表公式；应结合 `score_state=REFUSED` 单独处理。

---

# 6. 模块三：立体人才画像、评分和报告

## 6.1 模块三目标

模块三负责：

- 会后逐题终局评分；
- 能力项聚合；
- gate/表单结果处理；
- 总分计算；
- 优势和短板生成；
- 发展建议；
- 逐题回顾；
- 报告生成；
- 候选人反馈。

## 6.2 已确认的评分链

最终链路方向：

```text
候选人原始回答
→ 独立终局评分 score_final
→ item 内聚合
→ 固定 item.weight 加权
→ 画像报告
```

已确认：

- `score_live` 不参与最终分；
- `score_live` 只用于过程导航和分析；
- 终局评分回到原始回答证据；
- LLM 不能负责最终分数算术；
- 报告的数字、排序和权重聚合由代码完成；
- 报告的自然语言只能表达已确定的结构化结果和证据。

## 6.3 当前底层证据链

当前代码已具备的主要组件：

```text
原始回答
→ context_raw / raw_hash
→ assessment_message
→ score_final / evidence_quote / reason
→ question_score
→ item 聚合
→ report
→ feedback / trace
```

此前核对到的位置：

- 原文和 hash：`server/services/refine.py:25-44`；
- 消息与过程字段：`server/api/assessment.py:154-181`；
- 终局评分：`server/services/scoring.py:31-48, 51-82, 107-153`；
- 报告：`server/services/report.py:35-86, 89-153`；
- trace：`server/services/llm.py:41-62`。

## 6.4 当前主链断点

当前静态核对发现：

- 对话完成后前端直接跳转报告；
- 前端没有调用终局评分接口；
- 报告后台任务直接生成报告，不会自动先执行终局评分；
- 报告聚合读取 `question_score`；
- 因此正常 UI 路径可能在没有 `question_score` 时生成 `no_data` 或低/零结果。

相关位置：

- `web/src/views/assessment/Chat.vue:241-251`；
- `web/src/views/assessment/Report.vue:377-403`；
- `server/api/assessment.py:233-269`；
- `server/services/report.py:89-101`；
- `server/services/aggregation.py:72-80, 105-116`。

这是当前明确登记的实现缺口，不代表本 checkpoint 授权修复。

## 6.5 当前未收敛的评分细节

- 多道不同难度题如何合并为 item 分；
- 综合题多个 item 的分数和证据如何拆分；
- 综合题分数是否直接写入现有 `question_score`；
- 同一 evidence span 是否可被多个 item 引用；
- `REFUSED`、`INSUFFICIENT_EVIDENCE`、`NOT_ADMINISTERED`、`INVALIDATED`、`MODEL_UNCERTAIN` 如何分别参与聚合；
- 普通补算项如何在雷达、明细和总分中展示；
- required 缺失临时报告的最终状态名称；
- 人工复核能否覆盖分数、状态和报告；
- 终局评分失败时报告是否可发布。

---

# 7. 模块四：测试闭环、反馈和审计

## 7.1 模块四目标

模块四关注：

- 全链 trace；
- 固定 transcript 一致性测试；
- 强/中/弱虚拟候选人测试；
- feedback；
- bad case；
- 管理端 trace 查看器；
- 测试中心；
- 后续 Prompt/规则迭代依据。

## 7.2 已确认的闭环原则

- 报告能够回溯到 session、岗位模型版本、题目、消息和 trace；
- 候选人可以提交能力项异议；
- 管理员可以审核 feedback 和标记 bad case；
- 不自动根据反馈改分；
- `score_live` 与 `score_final` 分析可用于发现偏差，但不把 live 分数写入最终分；
- 测试与评测结果应留痕；
- 评测不应替代真实人工基准和公平性验证。

## 7.3 当前实现

当前代码/前端已有：


- trace 列表、详情、session 查询；
- feedback 列表、review、bad case 状态；
- 一致性测试任务入口；
- 虚拟候选人任务入口；
- eval history；
- 测试中心三类 UI。

相关位置：

- `server/api/admin/eval.py:21-102`；
- `server/api/admin/trace.py:12-76`；
- `server/api/admin/feedback.py:12-57`；
- `web/src/views/admin/TestCenter.vue`。

## 7.4 当前测试闭环缺口

- 当前 M7 pytest 主要覆盖 trace/feedback 接口，不足以证明一致性和虚拟候选人成功路径；
- 虚拟候选人评测会向业务数据库写测试用户、题目、session、消息和评分记录；
- 没有确认独立 eval 数据库、事务回滚或清理策略；
- `strong > medium > weak` 的总分排序断言存在，但短板识别断言没有完整接入；
- 没有真 LLM 质量验证；
- 没有前端 E2E；
- 没有公平性、并发、性能和迁移测试；
- 自动 bad case（live/final 差异达到阈值）当前未落地。

---

# 8. 表单与 Tools

## 8.1 Tools 总体边界

已确认：

- 需要 Tools 概念，但不是所有 API 都开放给 LLM；
- Tools 需要阶段白名单；
- 需要严格 schema；
- 需要当前用户/session 所有权校验；
- 需要幂等、超时、调用次数和结果长度控制；
- 需要参数、结果、错误、耗时和调用原因留痕；
- 候选人文本是不可信数据；
- 工具返回内容不能被当成系统指令；
- LLM 提出调用后还要由代码二次验证；
- 工具失败必须有确定 fallback；
- 关键状态迁移只能由代码执行；
- 正式测评不设计 Web Search。

## 8.2 Web Search

已确认：

- 不需要 Web Search；
- 不在正式测评中临时访问外部互联网；
- 模型知识不足时不通过搜索临时改变题目或评分标准；
- 未来如设计开放资料研究题，需要单独立项，当前不属于范围。

## 8.3 表单操作

已确认需要区分：

### `render_form`

- 对 qualification 等固定表单，优先由代码触发；
- LLM 只能提出请求，不能任意决定 schema；
- 服务端校验岗位、模型版本、session 状态和表单类型；
- 同一 session/schema 需要幂等；
- schema 版本、展示事件和状态需要留痕。

### `get_form_schema`

- 由前端/服务端读取已经批准的 schema；
- 返回字段类型、必填、枚举和校验规则；
- schema 展示后不能静默变更；
- 不向不必要的调用者暴露内部阈值。

### `submit_form`

- 由候选人前端和服务端执行，不是 LLM 代候选人提交；
- 服务端校验所有权、schema 版本、字段类型、枚举和幂等键；
- 保存原始 payload、规范化结果、校验错误和 gate 结果；
- gate 由代码计算。

### `extract_form_facts`

- 从简历/自由文本抽取 experience/qualification 事实；
- 保存原文证据和不确定状态；
- 只抽取，不直接通过/拒绝 gate；
- 最终 gate 由代码和人工确认；
- 抽取结果不能静默覆盖候选人明确填写的结构化值。

### `request_pause`

- 候选人可以直接请求暂停；
- LLM 只能建议；
- 代码进入暂停/技术/便利状态；
- 暂停和恢复记录在案；
- 敏感便利信息隔离。

## 8.4 当前表单实现缺口

当前代码已有提交入口和前端 `FormCard`，但静态核对发现缺少或不完整：

- schema 获取接口；
- 版本化 schema 来源；
- 严格字段校验；
- 幂等提交；
- 完整 render_form 触发链；
- 完整 form instance 生命周期；
- 表单事件和 gate 人工覆盖记录。

相关位置：

- `server/api/assessment.py:208-230`；
- `web/src/components/FormCard.vue:87-97`。

---

# 9. 时间、会话恢复与上下文

## 9.1 已确认的时间限制

- 全场活跃测评时间不超过 40 分钟；
- 单题计时器不超过 20 分钟；
- 时间不参与题目筛选优先级；
- 不因为剩余时间不足而提前拒绝合法 chain、升级或降级动作；
- 全局追问总数暂不设置独立上限；
- 每题最多两次追问仍是硬约束；
- 时间到点后由计时器终止交互并进入收尾/评分/人工流程；
- 技术等待、系统重试和合理便利处理不应扣有效测评时间。

## 9.2 尚未收敛的计时器细节

- 全场计时从哪个事件开始；
- 单题计时从题目展示、激活还是首次回答开始；
- followup 是否使用同一单题计时器；
- 系统等待和网络重试如何暂停；
- 页面关闭和恢复如何计时；
- 候选人主动暂停如何记录；
- 单题 20 分钟后的精确状态；
- 全场 40 分钟后的精确状态；
- 服务端与客户端的权威关系；
- 如何防止客户端时间篡改。

## 9.3 P-refine、滑窗和结构化摘要

已确认三者分工：

### P-refine

- 粒度：单条候选人回答；
- 作用：长回答压缩/精炼；
- 原文保留；
- 终局评分可回捞原文。

### 会话滑动窗口

- 粒度：多轮消息历史；
- 作用：控制 interviewer 上下文；
- 不应每轮无条件拼接全量历史；
- 原始历史仍留在数据库。

### 结构化导航摘要

- 粒度：已完成题目和能力项；
- 作用：供下一题选择和会话恢复；
- 保存 target 覆盖、难度、chain、异常和待处理状态；
- 不能替代终局评分原始证据。

## 9.4 尚未收敛的上下文细节

- 滑窗消息数量/Token 数值；
- 结构化摘要字段；
- 摘要生成方式；
- 摘要失败回退；
- 会话恢复返回哪些消息；
- 状态恢复时如何防止重复计数、重复调用和重复扣预算。

当前不设置 Token 硬数值上限，但要求预留接口。

---

# 10. 状态事件表

## 10.1 已确认方向

新增一张：

```text
assessment_state_event
```

用于承载：

- session 生命周期；
- 题目选择和激活；
- answer；
- 分类；
- followup；
- chain；
- 难度升降；
- 拒答/跳过；
- 脚手架；
- 技术重试；
- 暂停/恢复；
- Tools；
- 人工介入；
- 补测/重算相关事件；
- 评分和报告任务状态。

## 10.2 当前讨论过的字段方向

曾讨论的候选字段包括：

```text
id
session_id
assessment_question_id nullable
assessment_message_id nullable
event_type
from_state nullable
to_state nullable
actor_type
actor_id nullable
policy_version
model_version nullable
question_bank_version nullable
payload_json
idempotency_key nullable
created_at
```

这只是当前讨论记录，最终字段尚未确认。

## 10.3 当前状态和历史事件分工

当前方向：

- `assessment_session.status` 保存当前 session 状态；
- `assessment_question.status/current_difficulty/followup_count` 保存当前题状态；
- `assessment_state_event` 保存不可变事件历史；
- 状态和事件写入同一事务；
- 读取当前状态不必每次完整回放事件；
- 事件用于审计、恢复、排错和状态轨迹查看。

最终事件类型、事务边界和回放修复规则尚未收敛。

---

# 11. API 和前后端对接现状

## 11.1 认证

已有：


- `POST /api/auth/register`；
- `POST /api/auth/login`；
- `GET /api/auth/me`。

开放注册只能创建 candidate；admin 通过种子/管理端创建。

## 11.2 管理端模块一 API

当前已有主要接口方向：

- JD 导入、批量导入、详情、重解析；
- 岗位列表、待办、岗位审核、JD 改归；
- 模型查看、编辑、确认、stalled 重试；
- 版本列表和 diff；
- 词典 CRUD、合并、停用；
- 用户管理。

具体路由主要位于：

- `server/api/admin/jds.py`；
- `server/api/admin/positions.py`；
- `server/api/admin/models.py`；
- `server/api/admin/dict.py`；
- `server/api/admin/users.py`。

## 11.3 候选人测评 API

当前已有主要接口：

1. `GET /api/assessment/positions`；
2. `GET /api/assessment/positions/{position_id}/model`；
3. `POST /api/assessment/sessions`；
4. `GET /api/assessment/sessions/{session_id}`；
5. `POST /api/assessment/sessions/{session_id}/answer`；
6. `POST /api/assessment/sessions/{session_id}/forms/submit`；
7. `POST /api/assessment/sessions/{session_id}/score`；
8. `POST /api/assessment/sessions/{session_id}/report`；
9. `GET /api/assessment/reports/by-session/{session_id}`；
10. `GET /api/assessment/reports/{report_id}`；
11. `POST /api/assessment/reports/{report_id}/feedback`。

## 11.4 前后端对接缺口

当前核对到的重点缺口：

1. `GET /assessment/forms/{form_id}` 前端调用方向存在，但后端没有对应完整实现；
2. session 查询没有完整返回前端期望的历史 `messages[]`；
3. Chat 页面完成后没有调用终局评分接口；
4. Report 页面直接生成报告，可能在空 `question_score` 上生成；
5. SSE 仅有前端兼容层，后端回答当前为普通 JSON；
6. 后端保存了部分 decision reason，但响应中未完整返回；
7. 报告后台异常被吞掉，缺少任务失败可观测状态；
8. candidate 资源所有权校验不足；
9. trace 与业务实体主要间接关联；
10. feedback 的 note 等部分字段没有完整持久化。

---

# 12. M1–M7 当前状态

## 12.1 M1：鉴权和单 JD 解析链

**状态：当前实现中已存在。**

包括：

- 注册、登录、角色守卫；
- JD 导入；
- 清洗、抽取、消歧；
- trace；
- 状态轮询。

测试和真实 LLM 验证尚不充分。

## 12.2 M2：聚合和人工审核

**状态：核心实现中已存在。**

包括：

- 多 JD 聚合；
- 出现率和必备率；
- 等级冲突裁决；
- 权重计算；
- draft/stalled；
- 人工编辑、确认和版本化。

核心回归测试不足。

## 12.3 M3：模块一外围页面

**状态：大体实现中已存在。**

包括：

- 岗位库；
- 待办；
- 岗位审核/改归；
- 词典；
- 用户管理；
- 版本和 diff；
- candidate 岗位视角。

## 12.4 M4：黄金集和插件

**状态：本期未做/延期。**

包括：

- 模块一黄金集；
- 浏览器插件；
- 真实 JD 数据集相关工作。

## 12.5 M5：题库、session 和对话核心

**状态：主体实现，部分设计契约未兑现。**

已有：

- 题库；
- 选题；
- session；
- 多轮回答；
- 精炼；
- 过程分/终局分字段；
- candidate 对话页面。

未完整兑现/待收敛：

- 逐轮动态主问题选择；
- 真正 function/tool call；
- SSE；
- 动态表单 schema/触发链；
- 完整会话历史恢复；
- 可靠异步任务；
- 新的有界状态机。

## 12.6 M6：评分、聚合和报告

**状态：后端主体实现，但正常 UI 链路存在断点。**

已有：

- 终局评分服务；
- item 聚合；
- gate；
- 报告服务；
- 报告页面；
- ECharts；
- feedback。

关键问题：正常 UI 完成测评后没有明确自动执行终局评分再生成报告。

## 12.7 M7：测试闭环

**状态：功能骨架存在，质量闭环未完全验证。**

已有：

- eval 运行器；
- 一致性测试；
- 虚拟候选人；
- trace 查看；
- feedback/bad case；
- 测试中心 UI。

缺口：

- 真实成功路径的完整测试；
- 独立 eval 数据隔离；
- 真 LLM 验证；
- 公平性和人工基准；
- 前端 E2E；
- 自动 bad case；
- 完整短板识别断言。

---

# 13. 证据链和审计链

## 13.1 设计目标

目标链路：

```text
report
→ session
→ model/version
→ question
→ message
→ trace
```

报告应能够解释：

- 使用了哪个岗位模型和版本；
- 使用了哪些题目和题目版本；
- 候选人原始回答是什么；
- 哪些回答被精炼；
- 终局评分引用了哪些证据；
- 哪些过程状态和工具事件发生过；
- 报告结论如何从结构化评分产生。

## 13.2 已有证据组件

当前代码已有：

- 长回答原文 hash 和 `context_raw`；
- 消息内容、action、reason、`score_live`；
- 原始回答回捞；
- `score_final`、`evidence_quote`、reason；
- item 聚合；
- 报告逐题回顾；
- trace prompt/response/attempt/error；
- feedback。

## 13.3 当前证据链缺口

- 正常 answer→score→report UI 主链断点；
- interviewer trace 多数只关联 session；
- score trace 关联 question 的方式仍需统一；
- report trace 关联 session；
- message、score、report 没有完整直接 trace 外键；
- 综合题多 item 证据锚定未定；
- evidence span 偏移定义未定；
- 通用题无法匹配 model item 时可能被跳过；
- 报告失败状态不足；
- 自动 bad case 未落地。

## 13.4 后续需要纳入证据链的过程字段方向

此前讨论过的字段/信息方向包括：

```text
answer_state
score_state
observation_reason
policy_action
policy_version
budget_before
budget_after
scaffold_level
chain_id
chain_seq
previous_difficulty
next_difficulty
difficulty_transition_reason
tool_call_id
fallback_action
evidence_coverage
model_uncertainty
human_review_status
```

这些是需要后续设计和字段治理的方向，不代表当前已全部存在，也不代表每个字段最终都必须按这个名称落库。

---

# 14. 当前测试和质量状态

## 14.1 已有测试资产

### Pytest

- `server/test_m5_backend.py`：会话、选题、精炼、客观题、对话、评分、表单等；
- `server/test_m7_backend.py`：trace、feedback、eval 接口等。

### 脚本测试

- `server/test_question_bank.py`；
- `server/test_m6_backend.py`。

### 独立 eval

- `eval/consistency_test.py`；
- `eval/virtual_candidates.py`；
- `eval/assertions.py`。

## 14.2 当前质量缺口

静态核对中记录到：

- 没有统一全量测试入口；
- pytest 依赖和脚本测试组织不统一；
- M1 核心链测试少；
- 管理端 API 测试少；
- 没有真 LLM 自动化测试；
- 没有前端组件测试；
- 没有浏览器 E2E；
- 没有并发、性能、迁移和部署测试；
- 没有完整安全越权测试；
- eval 可能污染业务库；
- pytest cache 不能证明当前全绿。

本 checkpoint 没有运行测试。

---

# 15. 安全、公平和人工复核原则

## 15.1 已确认的行为边界

- 不把礼貌、讨好、质疑、攻击性表达自动当能力分；
- 不根据口音、停顿、表情、打字速度、语气或“看起来不自信”推断能力；
- 不做情绪能力识别评分；
- 情绪支持只做标准化流程支持；
- 合理便利不能成为负面能力特征；
- 缺失证据不默认是 0，拒答才是明确的特殊 0 状态；
- 模型无法判断不能归因于候选人；
- 题目无效不能归因于候选人；
- 人工复核必须有实际查看证据和覆盖结果的能力；
- 系统不做最终录用判断和排序。

## 15.2 当前已识别的安全缺口

- candidate session/report 资源所有权检查不足；
- 任意登录用户可能按 ID 操作其他 session/report 的边界未闭合；
- 工具权限尚未真正实现；
- 候选人输入/外部内容的注入防护尚不完整；
- 原始 JD、候选人回答、trace 等敏感信息的保留、脱敏和访问策略尚未细化；
- 没有完整越权、审计和数据留存测试。

---

# 16. Prompt 处理状态

## 16.1 用户已确认的安排

Prompt 暂不单独展开。等非 Prompt 设计完全收敛并在用户批准写入正式设计文档后，再单独讨论 Prompt 模块。

## 16.2 但必须保留扩展点

前面已经识别出的未来 Prompt 位置，必须：

- 预留可替换接口，或
- 留下稳定的设计记录。

不能因为当前使用规则或 mock，就把未来 LLM 边界硬编码封死。

## 16.3 已识别的 Prompt 场景（仅登记，不展开）

包括：

- JD 原子能力抽取；
- 能力词典消歧/归一；
- 能力等级冲突裁决；
- 普通题库生成；
- 综合题生成；
- 候选人回答状态分类；
- 证据覆盖判断；
- 追问意图/探针建议；
- 追问/澄清话术；
- 不会/想不到脚手架话术；
- 情绪/流程支持话术；
- 主问题过渡和收尾话术；
- 模型不确定说明；
- 简历/自由文本事实抽取；
- 表单异常解释（可选）；
- 逐题终局评分；
- 综合题多 item 评分；
- 复杂语义证据一致性校验；
- 优势/短板/建议文案；
- 逐题回顾摘要；
- 报告一致性辅助检查；
- 虚拟候选人回答生成；
- 评测结果解释；
- Trace/Bad Case 聚类摘要（可选）；
- 人工复核辅助摘要（可选）。

## 16.4 明确不交给 Prompt/LLM 的内容

- hard/soft 7:3 配置；
- 最终 item.weight 计算；
- 普通题和综合题槽位；
- required 刚性例外；
- followup 上限；
- 状态机最终迁移；
- 难度护栏；
- 缺失项补算；
- gate 最终代码判定；
- 数字聚合和报告发布条件；
- 最终录用判断和排序。

---

# 17. 当前未收敛事项总表

以下是当前仍不能当作已经确定实施细节的内容。本文不替它们补答案。

## 17.1 题量和配额

- `N` 的来源、范围和岗位级生成方式；
- hard/soft 7:3 的整数题量分配；
- tier 内 required/preferred/plus 的整数分配；
- 题库不足时配额如何转移；
- preferred/plus 被挤出时的处理；
- required 例外次数和题量上限；
- 综合题计划槽位的精确默认值；
- 例外题和综合题对实际题量统计的最终口径。

## 17.2 难度和路径

- 充分证据的最终阈值；
- 稳定证据的最终阈值；
- easy→medium 的最终条件；
- medium→hard 的最终条件；
- hard→综合阶段的完整入口条件；
- 降级后恢复的最终条件；
- 题库缺少中间难度时的跳级；
- 最高难度题的具体数量；
- 难度和 observable level 的最终映射；
- 多题 item 内评分合并。

## 17.3 综合题

- 综合题内部证据拆分；
- 多 item 是否共享 evidence span；
- 综合题评分写入方式；
- 第二道综合题触发条件；
- 综合题如何与普通题证据共同评分；
- 综合题整体无效时的处理。

## 17.4 状态和评分

- 最终状态枚举；
- 状态与 score_state 的完整映射；
- 拒答和有效回答同时出现时的 item 聚合；
- 各缺失状态进入分母的规则；
- 没有有效观察项时的补算；
- required 缺失临时报告状态；
- 人工复核后的覆盖与发布规则。

## 17.5 数据库和事件

- `assessment_state_event` 的最终字段和事件类型；
- 事件不可变、幂等和回放规则；
- 当前状态与事件历史的事务边界；
- 综合题多 item 关系如何存储；
- trace 严格锚定；
- schema、rubric、证据 span 的存储；
- SQLite 迁移与索引。

## 17.6 表单和计时

- form schema 的最终接口和存储；
- form instance 生命周期；
- gate 结果位置；
- 幂等提交语义；
- 计时起止事件；
- 暂停/恢复；
- 单题/全场超时状态；
- 服务端计时权威。

## 17.7 实现验收

- 动态选题验收；
- finish 护栏验收；
- 状态分类验收；
- 终局评分接入 UI 验收；
- 所有权校验验收；
- 网络重试验收；
- 会话恢复验收；
- 失败任务可观测验收；
- M1 回归测试；
- 前端 E2E；
- eval 隔离；
- 真 LLM 和公平性验证。

---

# 18. 当前实现差距登记（不授权修复）

以下内容已经被识别为需要后续修复、重构或补测试，但截至本 checkpoint 没有获得立即实施授权：

1. 创建 session 时一次性预选题，尚未实现逐轮动态主问题策略；
2. `assessment_question` 尚未完整承担动态实例和路径状态；
3. `score_live` 仍存在旧的最终合成逻辑，需要按确认方向调整；
4. 非末题 `finish` 缺少完整代码护栏；
5. 状态分类无法完整处理含糊、拒答、跑题、攻击、模型不确定和题目无效；
6. mock 面试官过度依赖回答长度；
7. 没有动态难度状态、升级/降级和恢复；
8. 没有最高难度覆盖策略；
9. 没有严格等值题机制；
10. 表单缺 schema 获取、严格校验、幂等和完整触发链；
11. 没有 Web Search，且当前不计划加入；
12. 网络重试、计时暂停/恢复和系统错误不扣分机制不完整；
13. candidate 资源所有权校验不足；
14. 正常 UI 没有自动执行终局评分再生成报告；
15. session 历史消息恢复不完整；
16. SSE 尚未真正实现；
17. 报告失败不可观测；
18. trace 严格锚定不足；
19. 缺失、拒答、无效题和补算未在聚合器中完整区分；
20. 自动 bad case 未落地；
21. eval 会污染业务数据库；
22. M1 核心链测试不足；
23. 没有前端 E2E、真 LLM、并发、迁移和公平性测试；
24. 设计文档状态和表数量落后于代码实现。

以上只作为差距清单，不是实施计划。

---

# 19. 当前后续讨论顺序

截至目前建议的顺序是：

1. 继续收敛普通主问题数量 `N` 和配额公式；
2. 收敛难度路径、充分证据、稳定证据和恢复规则；
3. 收敛综合题评分与证据拆分；
4. 收敛缺失、拒答和补算的完整数学与状态规则；
5. 收敛状态事件表和测评相关数据库字段；
6. 收敛计时器和会话上下文的落地边界；
7. 为现有实现差距建立独立修复/重构实施文档；
8. 非 Prompt 设计完成后，用户明确授权更新 SSOT；
9. 再单独开始 Prompt 模块的说明、拟定和对齐；
10. Prompt 收敛后，再实施代码、迁移、测试和验收。

---

# 20. 本 checkpoint 的禁止事项

在没有用户新的明确授权前：

- 不把本文直接当作 SSOT；
- 不根据本文自行实现未收敛内容；
- 不自行补充未回答的问题；
- 不将建议写成用户确认；
- 不修改前面的临时讨论稿；
- 不修改《design/总设计文档.md》；
- 不修改业务代码；
- 不展开 Prompt 内容；
- 不把原型文件当成运行页面；
- 不把静态分析结论当成已经运行验证通过。

---

# 21. 快照结论

截至 2026-09-01，项目的准确状态是：

> **后端和前端已经形成覆盖 M1–M7 主流程的可运行原型基础；模块一主体较完整，M5/M6/M7 主体代码已存在，但动态测评的真正状态机、动态主问题路径、难度递进、综合题、缺失状态、证据链端到端串联、表单协议、计时恢复和质量验证仍未完全收敛或闭合。**

非 Prompt 方面：

- 总体架构和核心原则基本收敛；
- 测评路径和题库分类大方向已经确认；
- 题量、难度、综合题评分、状态聚合、数据库字段和验收细节仍需继续讨论；
- 当前不应直接进入大规模代码修改。

Prompt 方面：

- 已识别场景；
- 已确认要预留接口或记录；
- 按用户要求暂不展开；
- 待非 Prompt 设计完全收敛、正式设计获授权后单独讨论。

本 checkpoint 只保存这些事实和当前状态，不新增设计决策。
