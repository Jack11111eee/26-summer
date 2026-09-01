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

# 21. 第八轮确认回写与仍需对齐事项

> 本节记录用户对第八轮讨论稿的明确回复。它不是 Prompt 设计，也不是代码授权；但其中已经明确确认的内容，作为后续新总设计文档的输入证据。未列为“已确认”的内容仍不得视为实施依据。

## 21.1 文档治理和范围

### 已确认

1. 当前可以继续以 `design/总设计文档.md` 作为旧 SSOT 的路径约定。
2. `design/final-design/` 的语义是最终设计稿目录，但现有内容已经过时，当前不把它作为权威。
3. 后续新的总设计文档完成后，将放入 `design/final-design/`，并与分模块文档共同作为新的唯一权威设计来源。
4. 新 SSOT 完成前冻结旧 SSOT。
5. 接受将里程碑拆分为：
   - `implemented`：已有代码；
   - `contract_complete`：满足正式设计契约；
   - `verified`：已通过测试/验收；
   - `production_ready`：满足上线要求。
6. 接受系统只提供画像、能力评分、证据、过程记录和人工复核支持，不做最终录用判断、最终录用排序、自动通过/淘汰或替代企业招聘决定。

### 仍需注意

新总设计文档进入 `design/final-design/` 后，需要明确它取代旧 SSOT 的生效节点，并同步更新分模块文档的引用关系，避免两个目录再次并列成为事实上的权威。

## 21.2 普通题量和配额

### 已确认

1. `N` 采用岗位级测评策略配置。
2. 不设置系统级 `N_min/N_max`。
3. required 最低覆盖不足时，允许在 `N` 之外独立增加 required 例外题。
4. 如果题量/题库不可满足开考条件，阻止创建 session，并立即向管理员报告。
5. hard/soft 的 7:3 整数分配采用此前约定的取整方向：例如 `N=15` 时，hard 为 11，soft 为 4。
6. 如果某大类存在能力项但题库不可用，不允许把名额转移给另一大类；应阻止开考并向管理员报告题库不可用。
7. 每个有合法题库的 required item 至少获得一题普通题机会。
8. preferred 不设置独立最低覆盖，按照剩余资源分配。
9. plus 允许没有题，按照剩余资源分配。
10. 类内 required/preferred/plus 的配额不参考 `item.weight`，采用以下比例和优先级：

   ```text
   required  = 0.8
   preferred = 0.6
   plus      = 0.3
   总和      = 1.7
   ```

   先以当前 hard 或 soft 的题目总量分别计算各 tier 的目标数量：

   ```text
   required_target  = ceil(category_quota × 0.8 / 1.7)
   preferred_target = ceil(category_quota × 0.6 / 1.7)
   plus_target      = category_quota - required_target - preferred_target
   ```

   但实际分配必须遵守 `required > preferred > plus` 的优先级：当题目不足时，先保证 required，再保证 preferred，plus 使用剩余名额；不能因为向上取整导致目标数量超过该大类总量。
11. hard/soft 内部配额以 hard/soft 各自的题目数量为总体数量，不把两个大类合并后再做 tier 分配。
12. `N`、required 例外和综合题仍分别记录为：

   ```text
   ordinary_plan_count
   ordinary_exception_count
   integrated_plan_count
   ```

### 仍需继续细化

1. 岗位级策略配置中的 `N` 具体由管理员如何填写、默认值是什么，以及哪些输入会被拒绝，尚未确认。
2. hard/soft 7:3 的奇数取整需要在新文档中写成完整的确定算法，而不仅是示例；当前已确认的方向是取整后合计仍为 `N`，但具体“余数相同”等极端情况仍需写清。
3. 类内题目不足时，required/preferred/plus 的“有效题目数量”如何定义（仅 active 且版本匹配的题目），需要在题库可用性检查中固定。

## 21.3 题库版本、开考条件和动态选题

### 已确认

1. 接受“confirmed model → question bank readiness → quota feasibility → form schema readiness → 创建 session”的开考前检查。
2. 未通过可测量性检查不得创建正常 session。
3. confirmed 新模型版本需要使用匹配的新题库；若不更新题库或不使用新题库，应明确提醒并阻止正常测评启动。
4. 题库不可满足 required 或大类配额时，不允许静默降级或转移名额，必须阻止开考并向管理员报告。
5. 接受“合法性过滤 → 硬约束 → 覆盖优先级 → 候选题排序”的动态选题结构。
6. chain 不是无条件最高优先级；不能挤掉未覆盖 required，不能改变题量槽位，不能绕过难度路径护栏。
7. 接受第一阶段使用人工批准的显式等值题组；等值题至少需要相同主 item、difficulty、measurement target、rubric/evidence requirement 和权重语义。不同难度的替代题不直接归入等值组。

## 21.4 required 刚性例外

### 已确认

1. 同一个 required item 最多触发一次例外。
2. 例外新增一条普通主问题，计入 `ordinary_exception_count`。
3. 例外题不走 easy 起始规则；例外只允许使用 medium。
4. 如果没有可用的 medium 题，选择 hard。
5. 例外不使用综合题。
6. 例外后仍没有有效测量时，采用 required 缺失的临时报告和人工复核处理。

### 仍需继续细化

“例外只允许使用 medium；没有 medium 才使用 hard”已经确认，但还需要在正式状态机中写清：

- 例外题是否必须满足当前 item 已经达到的路径状态；
- medium/hard 题都不可用时的具体错误状态；
- 例外题的证据不足是否直接封存，还是允许当前题内两次 followup；
- 例外后仍缺失时管理员任务的字段和优先级。

## 21.5 难度路径和证据

### 已确认

1. 接受 hard 是有条件的测量阶段，不是所有 item 必经。
2. 中间难度题缺失时，默认不允许运行时静默跳级；路径是否允许跳级必须由模型/rubric 明确配置。
3. 接受“结构化证据维度 + 代码最终裁决 `evidence_sufficient`”。
4. 接受“两个不同普通题实例才算两次普通独立观察”的方向。
5. 接受一次 hard 强证据可以满足稳定证据条件，但仍必须满足该题 rubric 和证据完整性。
6. 证据冲突默认进入人工复核。
7. 难度升级规则采用：
   - easy → medium：一次达到充分证据即可；
   - medium → hard：需要充分且稳定的证据；
   - hard：仅对有机会达到更高等级的 item 开放。
8. 降级规则采用有效候选人证据失败进行判断；技术故障、拒答、题目无效、模型不确定、流程质疑、攻击性事件等不计入普通失败。
9. 降级后允许恢复，恢复需要连续两次充分证据或一次稳定证据。
10. 不设置 item 级路径变更次数上限。
11. 接受 `observable_level_max` 作为题目/rubric 版本的测量配置。
12. hard 仍是条件阶段；是否有机会达到高等级由岗位/rubric 与过程表现共同决定。
13. 多题 item 聚合采用证据裁决而非简单平均；高难度强证据可支撑高等级，但必须满足 rubric；证据矛盾时取较低值。

### 仍需继续细化

以下数值和边界仍没有完全落成正式状态表：

- easy、medium、hard 对 1–5 能力等级的具体上限；
- `required_level`、`target_level` 与最高难度开放的精确关系；
- 稳定证据中“连续两次”的有效实例和状态检查；
- 降级后恢复后能否再次升级/降级的具体顺序；
- hard 题不存在时报告中的说明字段。

## 21.6 综合题

### 已确认

1. 接受综合题以“一题多 item 评分记录”为主，不以一个整体分直接参与最终总分。
2. 接受共享 evidence span，但必须在报告中显式标记，并且每个 item 有独立的 target、解释和评分。
3. 综合题可以作为 item 的最高等级证据来源，但仍受该 item 的 rubric 和证据要求约束。
4. 第二道综合题以剩余联合 measurement target 为主要触发条件。
5. 综合题整体无效时，所有绑定 item 的综合结果均无效。
6. 第一题整体无效可以成为激活第二题的理由，但仍需满足综合题最多两题、题库可用和 session 未超时等代码约束。
7. 接受将综合题结果以 `(question_id, item_id)` 维度写入现有评分结构，而不是把所有 item 结果塞进一个整体分 JSON。

### 仍需继续细化

- 综合题多 item 的具体评分映射字段；
- 共享 span 的去重、展示和重复计分防护；
- 综合题 item 结果与普通题 item 结果的最终合并优先级；
- 综合题第二题的完整决策表；
- 综合题整体无效和单 item 无效的报告文案与人工任务字段。

## 21.7 拒答、缺失和补算

### 已确认

1. 明确拒答是特殊观察值 0，不是 item 的永久终局 0。
2. 同一 item 后续取得有效回答时，可以改变 item 的最终能力等级；拒答事件仍永久保留。
3. `INSUFFICIENT_EVIDENCE` 不进入正常评分分母。
4. 无效题、模型不确定、未实施和系统错误不进入正常评分分母。
5. 普通非 gate item 按之前建议的观察集合定义进行补算：有效观察集合只包括 `SCORED`；拒答不加入能力等级观察集合，只进入行为/完整度聚合；缺证据、无效、模型不确定等也不得混入能力等级观察集合。
6. 没有任何有效观察时不能补算。
7. `IMPUTED` 可以参与总分和雷达展示，但必须明确标记，并显示观察覆盖/完整度信息。
8. 补算比例达到需要人工关注的情况时，同时生成临时报告并触发人工复核。
9. required 缺失采用：

   ```text
   report_status = PROVISIONAL
   review_status = HUMAN_REVIEW_REQUIRED
   ```

10. required 缺失不使用普通比例补算，不触发补测。
11. 人工不能直接修改原始评分结果；原始结果必须保留，通过 override/复核记录表达人工结论。
12. 题库/模型失效或不可用时，需要二次人工确认。
13. 终局评分失败时，报告不能作为正常 READY/PUBLISHED 报告发布。

### 仍需继续细化

- 拒答这一特殊观察值在同一 item 多次观察中的具体数学合并方式；
- `IMPUTED` 参与总分时的完整度展示和报告状态升级规则；
- 人工复核后的 report 是否自动重新生成，以及人工结论是否需要二次发布动作；
- 无效题、系统错误、模型不确定三者在报告中的差异化字段。

## 21.8 状态事件、数据库和 trace

### 已确认

1. 接受 append-only `assessment_state_event`。
2. 接受按领域分组的稳定事件枚举。
3. 接受 `from_state/to_state` 仅用于状态迁移类事件，动作/事实类事件可以为空。
4. 接受 `sequence_no`、当前状态快照和事件历史并存。
5. 接受 append-only 事件纠正，不修改旧事件；通过补偿事件修正。
6. 接受关键字段固定列、非稳定扩展放 `payload_json` 的方向。
7. 接受 `assessment_state_event`、当前状态和业务结果在同一事务中更新；长时间 LLM 调用不得持有数据库事务锁。
8. 接受按 `session_id + endpoint + idempotency_key` 作为幂等作用域。
9. 接受静态题库、动态 assessment_question、assessment_message、question_score 分层。
10. 接受综合题第一阶段使用绑定 JSON，并在题库发布和实例化时校验、保存快照；暂不建立关系表。
11. 接受 `assessment_message` 原文与精炼内容分列，终局评分回捞原文。
12. 接受 `source_message_id + source_content_type + Unicode code point offset + quote_hash` 的证据定位方式。
13. 接受统一 `trace_link`，使 report、session、model/version、question、message、score、task 等实体可以回溯到 trace。
14. 接受报告发布前进行数字、事实、引用和状态一致性校验。
15. 接受 form schema 第一阶段采用代码定义 + form instance 不可变 snapshot。
16. `user_profile` 继续延后，不在本轮为了表结构完整而新增。
17. SQLite 只作为单机演示/单实例部署；迁移、回滚、备份和恢复功能仍需要开发，并列为交付要求但不是本期上线硬门槛。
18. 接受将重试的 POST 设计为返回第一次持久化结果，不重复消息、题数、followup、任务或预算。
19. 幂等记录在当前方向上一直保存；达到系统设定数量后自动触发清理提醒，并保留管理员主动清理接口。清理策略、数量和保留范围仍需确定。

### 仍需继续细化

- `assessment_state_event` 最终完整字段清单；
- 事件领域枚举的最终名称；
- `correlation_id/causation_event_id` 是否加入；
- 事件回放与当前快照不一致时的处理；
- trace link 的具体表结构、唯一性和删除/保留策略；
- `question_score` 中现有重复字段 `score_final/final_score` 的统一语义；
- context_raw 的 hash 去重是否限制在 session/user 范围内，以避免跨候选人隐私关联。

## 21.9 权限和安全

### 已确认

1. candidate session/report/form/feedback 等资源的所有权校验列为 P0。
2. 接受 candidate 只能访问本人资源、管理员按管理员权限读取资源的统一模型。
3. 管理员可以读取候选人相关数据和完整 trace；本期不建立管理员分级，管理员均为最高权限。
4. 使用单一 JWT secret。
5. 采用 HttpOnly、Secure、SameSite cookie 方向。
6. API 密码规则由服务端统一校验。
7. 不把登录限速和生产 secret 校验列为本期上线硬要求，但仍可保留为后续安全增强记录。
8. 接受完整保存 LLM response 的方向。
9. trace、JD、候选人原文等数据需要定义数据分级、保留、脱敏/加密和访问审计；管理员是主要访问者。
10. 真实 LLM 供应商和数据处理/数据驻留约束需要明确。
11. 输入大小和格式限制按输入类型配置。
12. 所有 LLM 输出使用严格 schema 校验。
13. 工具调用失败时暂停并人工接管。
14. 公平性评估不作为本期上线门槛；本期只支持在线测评，不开展离线群体属性评估。
15. 评分不因候选人异议而自动改变；异议只作为反馈进入人工处理。
16. 评分不因人工异议反馈而覆盖或改变；题库/模型失效或不可用时，需要二次人工确认。
17. 所有暂停类型都不计入 40 分钟活跃测评时间。
18. 管理员可以查看暂停相关信息。

### 仍需继续细化

- 单一 JWT secret 的具体环境变量、最小强度和轮换时机；
- 管理员查看 raw/trace 的审计记录格式；
- 完整保存 response 时的脱敏、加密和保留期限；
- 个人信息删除、导出和供应商数据处理边界；
- 在线测评中的无障碍协议和不使用敏感属性评分的具体实现；
- “需要二次人工确认”的状态字段和复核闭环。

## 21.10 表单、计时、恢复和上下文

### 已确认

1. 接受 `form_instance` 作为表单生命周期实体。
2. form schema 在 instance 创建时快照；同一 instance 允许修订，但每次修订不可变。
3. 重复提交返回第一次持久化结果。
4. 表单由代码根据已批准 schema 触发；LLM 只能提出请求。
5. 候选人结构化填写和自动抽取发生冲突时保留冲突，并进入人工确认。
6. gate 只接受候选人确认或人工确认后的事实，不由抽取结果直接通过/拒绝。
7. 全场计时从候选人确认开始测评且首题成功激活开始。
8. 单题计时从题目成功激活并发送给候选人开始。
9. followup 与当前题共用同一个单题计时器。
10. 页面关闭默认不暂停；显式 pause 或技术状态才暂停。
11. 单题超时封存当前题并继续下一题。
12. 全场超时停止新增题并进入评分/收尾。
13. 计时以服务端为权威，客户端只展示倒计时。
14. 所有暂停类型都不计入 40 分钟。
15. 接受消息/事件分页或 cursor 恢复，并要求恢复不重复调用、计数、扣预算或插入消息。
16. 上下文滑窗以 Token 数为控制方向，具体参数待定并预留接口。
17. 结构化状态优先、LLM 摘要可选；摘要失败回退到数据库状态，不阻塞测评。

### 仍需继续细化

- 服务端有效计时区间的具体字段和计算方式；
- 页面关闭后短暂断线、长时间无活动和自动 abandoned 的边界；
- 单题超时后是立即创建下一题还是先写入评分/缺证据结果；
- session 恢复 cursor 的失效和重放规则；
- 滑窗 token 参数、摘要版本和降级策略。

## 21.11 API、SSE 和异步任务

### 已确认

1. 选择真实 SSE 作为最终回答传输方向。
2. function call 作为内部 LLM adapter，不直接把所有业务 API 暴露给模型。
3. 暂不要求事件 ID/cursor 的 SSE 断线续传，但可以留下扩展记录，后续有需求再追加。
4. 接受单进程 `BackgroundTasks`，本期演示上线不要求进程重启后任务可恢复；后续优化方向单独记录。
5. 报告/任务重试覆盖原任务，不允许部分题库或部分评分直接发布。
6. 任务失败直接向用户显示可理解的失败状态。
7. 接受统一 pytest/CI 入口、eval 独立数据库和端到端流程测试。
8. 一致性测试、虚拟候选人测试和 bad-case 候选的阈值/基准/实现方式按第八轮建议执行；mock 回归不能替代真实 LLM 质量验证。

### 已明确的后续优化记录

本期演示上线继续使用单进程 `BackgroundTasks`，不要求进程重启后恢复任务。后续如进入更高并发或更高可靠性阶段，可再评估持久化 job 表、启动扫描恢复、外部队列或独立 worker；本期不展开、不实施，也不把该后续方向作为当前上线条件。

### 仍需继续细化

- SSE 事件名称、事件顺序、错误和结束语义；
- 没有 cursor 时的断线处理；
- 报告生成覆盖原任务时的旧结果、feedback 外键和审计处理；
- 失败状态的用户文案与管理员错误详情边界。

## 21.12 测试、部署和上线范围

### 已确认

1. 目标是演示上线，而不是本期生产高并发上线。
2. 接受 SQLite 只支持单机/单实例演示。
3. 不要求定义最低并发、响应时间、RTO/RPO 等指标；但可以保留后续扩展记录。
4. 迁移、回滚、备份和恢复功能需要开发，但不作为本期上线硬门槛。
5. 接受将 M1 回归作为后续动态测评实施前的硬前置。
6. 接受将候选人端完整流程作为 M5–M7 verified 的必要 E2E 条件。
7. prototype 只作为视觉参考，静态 prototype 不作为功能/API 验收依据。
8. 接受统一 pytest、CI、eval 隔离、权限测试、异常状态测试、迁移测试和前端 E2E 的方向。
9. 一致性测试采用固定 transcript、固定模型/Prompt/rubric 版本和既有分差容差；虚拟候选人同时验证排序、短板、required 覆盖、状态、证据和报告；自动 bad-case 只创建候选，不自动改分。

### 仍需继续细化

- “演示上线”的正式部署说明、启动命令和环境变量清单；
- CI 中哪些测试必须阻断合并；
- E2E 测试的固定样例和成功判定；
- eval 测试的样本规模、短板预设和运行数据格式；
- 真实 LLM 验证的执行环境和凭据管理；
- 迁移、备份、恢复功能的实现范围和验收用例。

## 21.13 当前仍需优先对齐的重大问题

根据本轮回复，绝大多数原未决事项已经有了方向。当前仍需要进一步细化的重点，收缩为：

1. **难度到 1–5 的具体映射：** `observable_level_max`、required/target level、hard 最高等级证据如何形成确定表格。
2. **拒答特殊观察值的数学聚合：** 拒答不进入能力等级聚合，仍需明确行为/完整度聚合的具体字段和计算方式。
3. **综合题与普通题的最终合并：** 各自有独立 item 分数时，如何避免重复证据和重复测量。
4. **事件表最终契约：** 最终字段、枚举、回放不一致修复、trace link 结构。
5. **计时与恢复的边界：** 有效计时区间、断线/无活动/abandoned 的精确规则；本期 abandoned 6 小时后不可恢复。
6. **报告和人工复核发布：** 人工确认、发布校验和明确点击发布的字段及流程。
7. **文档路径生效规则：** 新总设计文档放入 `design/final-design/` 后如何正式取代旧 SSOT。

这些问题属于后续继续讨论事项，不代表本 checkpoint 已经全部收敛。

---

# 22. 快照结论（根据第八轮更新）

截至本轮讨论，系统的总体架构、题库分类、7:3 方向、岗位级 `N`、tier 配额优先级、required 例外、难度路径原则、综合题多 item 评分方向、拒答特殊观察值、普通缺失补算、状态事件、证据锚定、表单 instance、服务端计时、权限 P0、演示上线范围和测试方向均已进一步收敛。

仍不能直接进入完整实施的主要原因已不再是总体方向不明，而是少数关键数学、状态和运行契约尚未写成最终表格/字段/事务规则，尤其是：

- 拒答与多题 item 聚合；
- 综合题与普通题的合并；
- 事件表最终字段和回放；
- 计时恢复边界；
- 报告人工复核发布。

Prompt 仍按原安排暂缓；所有 Prompt 位置继续要求保留接口或稳定记录。

# 23. 原 checkpoint 快照结论

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

# 24. 第九轮确认回写

> 本节记录用户对第九轮讨论稿的明确回复。已确认内容作为后续新总设计文档的输入证据；不代表当前获得代码实施授权。

## 24.1 任务重启恢复

本期目标为演示上线、单机、单实例部署，接受单进程 `BackgroundTasks`，并**移除“进程重启后任务必须恢复”的本期要求**。

后续优化记录：若未来进入更高并发或更高可靠性阶段，可重新评估持久化 job 表、启动扫描恢复、外部队列或独立 worker。本期不展开、不实施，也不要求为此预留接口。

## 24.2 拒答与能力等级

明确拒答仍记录：

```text
score_value = 0
score_state = REFUSED
```

但拒答只进入：

- 行为聚合；
- 测评完整度聚合；
- 拒答事件和报告提示。

拒答不直接进入能力等级聚合。能力项最终等级由有效能力证据决定；同一 item 后续获得有效回答时，可以改变最终能力等级，同时永久保留拒答记录。

## 24.3 无活动和 abandoned

保留无活动状态概念。本期规则为：

```text
连续无活动达到 6 小时
→ 标记为 abandoned
→ 不允许候选人恢复
```

`abandoned` 只表示本期不可恢复的终止状态，不删除原始证据和审计记录。后续可以开发“abandoned 后可恢复”能力，但本期只保留这一条后续优化记录，不做具体设计，也不要求预留接口。

## 24.4 required 缺失报告发布

required 缺失时仍先生成临时报告并进入人工复核：

```text
report_status = PROVISIONAL
review_status = HUMAN_REVIEW_REQUIRED
```

人工复核完成后，允许在人工确认结果满足发布条件时将临时报告发布为正式报告。发布必须由人工明确点击执行，不能因复核记录写入而自动发布。

人工异议反馈本身不改变评分；这里的人工确认是对报告是否可以发布及缺失影响的审核，不等于自动改分。

## 24.5 本轮后的剩余收敛项

依据本轮确认，以下重大矛盾已关闭：

- 本期不要求 BackgroundTasks 重启恢复；
- 拒答不进入能力等级数值聚合；
- 6 小时无活动后 abandoned 且不可恢复；
- required 缺失临时报告允许人工确认后正式发布，且必须明确点击发布。

后续仍需细化的重点为：

1. 综合题与普通题的最终 item 合并规则；
2. `assessment_state_event` 最终字段、枚举和回放一致性；
3. 计时有效区间、断线与无活动检测的实现边界；
4. 报告/人工复核的具体字段和发布校验；
5. 新总设计文档在 `design/final-design/` 生效并取代旧 SSOT 的文档治理步骤。

本节仍不展开 Prompt，也不授权修改代码。
