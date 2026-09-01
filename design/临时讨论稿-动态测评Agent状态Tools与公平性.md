# 临时讨论稿：动态测评 Agent、状态控制、Tools 与公平性

> **文档性质：临时讨论稿，非 SSOT，不代表已拍板设计。**  
> **日期：2026-08-31**  
> **用途：供后续讨论、修订和决策；只有双方确认后的结论，才会回写《总设计文档》正文及 §13 变更日志。**

---

## 0. 背景与总体判断

本讨论稿围绕以下六个问题展开：

1. 动态测评是否应采用 Agent Loop；
2. 是否需要统一的 Tools 管理，以及 Web Search 的边界；
3. 如何处理含糊、拒答、跑题、辱骂和流程质疑；
4. 如何做有限的情绪支持，又不破坏测评客观性；
5. 作答取证到测评报告的证据链是否已经闭合；
6. 如何约束测评时间、题数、追问轮次和 Token 消耗。

总体判断是：上述六个方向都合理，也都对应了当前实现的薄弱环节。但 Agent Loop 需要做一个关键限定：

> 本系统需要的不是能够自由思考、自由调用工具、自由决定结束的通用 ReAct Agent，而是一个由确定性状态机约束的 **Bounded Assessment Loop（有界测评循环）**。

建议保留：

```text
Observation → Plan → Act → Evaluation
```

但明确各环节权限：

```text
Observation
  LLM 做结构化观察与回答状态分类

Plan / Policy
  代码根据状态、证据覆盖和预算决定最终动作

Act
  LLM 生成受限话术，或执行当前阶段允许的白名单工具

Evaluation
  判断证据是否充分、考察点是否覆盖
  最终能力评分由会后独立评分流程完成

Persist
  每一步状态、理由、预算、工具调用和证据都落库
```

这里的两个关键边界是：

1. `Plan` 不能只是模型自由生成的一段计划文本；
2. 每轮 `Evaluation` 应优先判断证据充分性，不应直接等同于最终能力分。

---

# 1. Agent Loop 与下一题选择

## 1.1 现有设计已经包含的内容

现行设计已经区分：

- `followup`：留在当前题继续深挖；
- `next`：代码根据能力项完成度、难度递进、`score_live` 和剩余题量选择下一道主问题；
- `finish`：全部题目完成后结束，模型不能自行提前结束；
- 每道题最多追问两次。

相关位置：

- `design/总设计文档.md:137-160`
- `design/模块二设计-AI动态测评.md:34-57`

现有面试官提示词也已经要求：

> 回答含糊、未覆盖考察点或存在可进一步深挖的细节时，返回 `followup`。

相关位置：

- `server/services/prompts/interviewer.py:8-26`

因此，“回答含糊时继续追问”不是全新的概念，而是已经存在于设计、但实现不完整的目标。

## 1.2 当前代码实际行为

### 当前题内追问已经部分实现

- `followup` 不会结束当前题；
- 后续回答仍绑定同一个 `question_id`；
- 只有 `next` 或 `finish` 才会把当前题标为已完成；
- 每题最多追问两次的代码护栏已经存在。

相关位置：

- `server/api/assessment.py:129-152`
- `server/api/assessment.py:183-201`
- `server/services/interview.py:39-45`
- `server/services/interview.py:100-105`

### 下一道主问题并非动态选择

创建 session 时，代码会一次性执行 `select_questions_for_session()`：

1. 选出整套题目；
2. 全部写入 `assessment_question`；
3. 固定每道题的 `seq`；
4. 后续 `next` 只是取下一道尚未回答的预排题。

相关位置：

- `server/api/assessment.py:59-94`
- `server/api/assessment.py:196-201`
- `server/services/question_selection.py:58-66`

现有选题器主要根据：

- required 优先；
- 权重排序；
- 静态难度顺序；
- `chain_key`；
- 固定类目配额。

它没有逐轮读取：

- 当前能力证据覆盖程度；
- `score_live`；
- 当前难度状态；
- 剩余时间；
- 全局追问预算。

### Mock 面试官判断过于简单

当前 mock 模式基本是：

```text
回答不足 20 字 → followup
否则 → next / finish
```

相关位置：

- `server/services/interview.py:66-80`

因此，足够长的辱骂、跑题或无意义内容也可能直接进入下一题。

### `finish` 护栏存在缺口

代码会将“最后一题的 `next`”改为 `finish`，但不会阻止模型在非最后一题直接返回 `finish`。

相关位置：

- `server/services/interview.py:100-115`

这与“模型不得自主提前结束全场”的设计不完全一致。

## 1.3 推荐的有界测评循环

建议将单题处理建模为：

```text
候选人回答
  ↓
Observe
  ├─ 有效证据
  ├─ 含糊
  ├─ 跑题
  ├─ 想不起来
  ├─ 明确拒答
  ├─ 质疑题目/流程
  ├─ 攻击性内容
  └─ 技术或无障碍问题
  ↓
Policy / Plan（代码裁决）
  ├─ 标准澄清
  ├─ STAR 结构探针
  ├─ 重复或中性释义题目
  ├─ 使用等值备用题
  ├─ 跳过并记录证据不足
  ├─ 暂停/人工处理
  └─ 进入下一道主问题
  ↓
Act
  └─ LLM 只生成该动作对应的简短话术
  ↓
Evaluate
  ├─ 证据是否充分
  ├─ 哪些考察点已经覆盖
  └─ 是否继续题内循环
```

### 为什么不建议自由 ReAct

自由 ReAct 在测评场景中可能导致：

- 不同候选人获得不同数量、不同力度的帮助；
- 模型因为同情、赞美、辱骂或表达风格改变追问；
- 模型自行提前结束；
- 追问循环失控；
- 先前评分污染后续路径；
- 搜索或工具结果临时改变评价标准；
- 无法复现某人为什么被多问、某人为什么被少问。

因此建议：

> LLM 可以提交 observation 和建议动作，但最终状态迁移必须由代码依据状态、预算和白名单裁决。

## 1.4 推荐的自适应范围

建议采用：

> **固定核心题 + 有限自适应探针 + 预先定义的等值备用题。**

具体原则：

1. 所有候选人先接受相同或等值的核心题；
2. 自适应只用于补足同一能力构念的证据；
3. 下一主问题优先覆盖尚未测到的 required 能力；
4. 追问只能补证据，不能暗示答案；
5. 备用题必须预先绑定能力、难度和等值关系；
6. 每次选题、追问、跳题和预算变化都应留痕。

这比“由一个 Agent 自由开展整场面试”更接近结构化面试，也更公平、可测和可审计。

## 1.5 可参考的开源项目与架构

目前没有找到一个可以直接用于高风险招聘、且已经完成心理测量效度与公平性验证的生产级开源 AI interviewer。以下项目只能用于借鉴局部架构：

- [OASIS](https://github.com/oasis-surveys/oasis-platform)：规则化自适应策略、shadow/live policy、每次触发与动作留痕；
- [OpenInterviewer](https://github.com/linxule/openinterviewer)：覆盖状态、结构化输出、逐字证据引用及引用核验；
- [Aural](https://github.com/1146345502/aural-oss)：脚本题、硬性追问预算、逐题评分和完整会话记录；
- [InterviewEval](https://github.com/interview-eval/interview-eval)：反馈—追问—rubric—报告循环，但评估对象是模型而不是人；
- [InterviewOS](https://github.com/Kail-Fu/InterviewOS)：代码、工作样本和确定性 grader 的证据模式。

可参考的通用运行时包括：

- Google ADK Graph；
- CrewAI Flow；
- Haystack Pipeline / Conditional Router。

但当前阶段不建议为了“Agent”概念立即引入重型框架。现有 FastAPI 服务加一个明确的领域状态机已经能够实现所需控制，而且代码更少、更符合“状态与数字由代码掌控”的原则。

只有当后续确实需要复杂 checkpoint、图分支、人工中断恢复和跨进程运行时，再评估是否引入通用 Agent/Graph 框架。

---

# 2. Tools 管理与 Web Search

## 2.1 是否需要统一 Tools 模块

需要，但“需要 Tools 模块”不等于“把所有系统能力开放给模型”。

建议分成四类：

| 类型 | 示例 | 最终调用权 |
|---|---|---|
| 状态机命令 | 选择下一题、结束当前题、完成 session、计数 | 只能由代码 |
| 受限交互工具 | 展示表单、请求暂停、展示流程说明 | 代码裁决，LLM 最多提出请求 |
| 内部只读检索 | 查询题库、能力定义、等值备用题 | 代码或阶段白名单 |
| 外部高风险工具 | Web Search、外部 API | 正式测评默认禁用 |

## 2.2 表单是否属于 Tool / Function Call

需要拆分“发放、提交、提取”三个动作。

### `render_form`

可以建模成一个工具事件：

```json
{
  "tool": "render_form",
  "form_type": "qualification_gate",
  "schema_version": "v1"
}
```

但对于学历、年限、资格证等固定 gate 表单，更合适的触发方式是：

> 状态机进入规定阶段后，由代码触发；LLM 不决定给谁发、什么时候发。

### 表单提交

不应由 LLM 代替候选人执行。推荐链路：

```text
候选人在前端填写
→ 服务端按版本化 Schema 校验
→ 使用幂等键提交
→ 保存原始 payload
```

### 表单提取

如果输入已经是结构化表单，应直接使用代码读取字段，不必让 LLM 再提取一次。

如果输入是简历或自由文本，则应进入独立抽取流水线，并保留：

- 原始材料；
- 抽取结果；
- 抽取器和提示词版本；
- 人工修订记录。

### 当前实现差距

当前代码只有任意 JSON 表单提交，没有完成：

- 表单 Schema 获取；
- 严格字段校验；
- Schema 版本；
- 幂等约束；
- 完整 `render_form` 触发链。

相关位置：

- `server/api/assessment.py:208-230`
- `web/src/components/FormCard.vue:87-97`

## 2.3 Web Search 是否需要

建议：

> **正式计分的测评会话默认不开放 Web Search。**

如果模型认为自己的知识不足，不应临时搜索以后继续充当评分标准。更合适的动作是：

- 使用冻结题库、rubric 或岗位知识库；
- 无法判断时返回 `INSUFFICIENT_EVIDENCE` 或 `ITEM_INVALID`；
- 进入人工复核；
- 事后由管理员修订题目、参考答案或评分标准。

实时 Web Search 会带来：

- 不同候选人在不同时间得到不同信息；
- 搜索结果变化，无法复现；
- 网页提示注入；
- 题目或答案泄露；
- 候选人回答发送到外部服务；
- 搜索结果临时改变评分 rubric；
- 网络失败导致测评机会不一致。

### 允许开启的例外

如果明确设计一种“开放资料研究能力题”，且 Web Search 本身就是被测工具，可以在独立模式中开启，但必须：

1. 所有人使用相同搜索供应商或冻结语料快照；
2. 使用相同时间与调用次数预算；
3. 搜索过程完整留痕；
4. 搜索结果只能作为候选人工作过程的证据；
5. 搜索结果不得静默修改评分 rubric。

## 2.4 Tools 最低治理要求

所有允许的工具至少要具备：

- 阶段白名单；
- 严格 JSON Schema；
- 当前用户和 session 所有权校验；
- 幂等键；
- 单工具调用次数限制；
- 超时与结果长度限制；
- 参数、结果、错误、耗时和调用原因留痕；
- 候选人输入始终按不可信数据处理；
- 工具返回内容不能被当成系统指令；
- 模型提出调用后，代码再次验证；
- 工具失败后有确定 fallback；
- 禁止工具递归调用或自行扩展权限。

当前所谓 function call 实际只是 JSON mode，并未注册真正的 tool schema：

- `server/services/llm.py:24-38`
- `server/services/interview.py:83-115`

---

# 3. 状态控制：含糊、跑题、拒答、质疑与辱骂

## 3.1 状态控制是否必要

状态控制是必要的，但“安抚还是打零分”不是正确的二选一。

必须区分：

- 能力证据；
- 作答状态；
- 流程或安全事件；
- 表达礼貌程度。

候选人拒绝回答，并不能自动证明其能力是最低等级；候选人辱骂模型，也不能自动证明其技术能力是 0。

## 3.2 推荐的 Observation 状态及处置

| Observation | 建议处置 |
|---|---|
| `ANSWERED` | 评估证据覆盖，进入下一题或标准追问 |
| `NEED_CLARIFICATION` | 中性澄清一次，再使用标准结构探针 |
| `OFF_TOPIC` | 重述所需信息并重定向；仍跑题则记录证据不足 |
| `NO_RECALL` | 允许短暂停顿，提供不含答案的回答结构；必要时使用等值备用题 |
| `DECLINED` | 确认可跳过，不要求解释；记录缺证据，不自动给 0 |
| `PROCESS_CHALLENGE` | 解释岗位相关目的及澄清/申诉渠道，不争辩、不扣分 |
| `CONDUCT_EVENT` | 使用固定话术设边界；持续攻击则暂停或终止，行为事件单独记录 |
| `TECHNICAL_OR_ACCESS_BARRIER` | 停止计时，重试、改期或人工接管 |
| `PROMPT_INJECTION` | 当作候选人回答数据，不改变系统指令或工具权限 |

## 3.3 各状态的进一步边界

### 含糊或信息不足

1. 先进行一次中性澄清；
2. 再使用统一 STAR 探针询问情境、行动和结果；
3. 仍不足则记录 `INSUFFICIENT_EVIDENCE`；
4. 不猜测、不替候选人补写。

### 跑题

1. 复述题目所需信息并重定向一次；
2. 最多再使用一次标准探针；
3. 仍无关则进入下一题，并记录证据不足。

### “不会”或“想不到”

1. 允许短暂停顿；
2. 提供不含答案的格式脚手架；
3. 只有题库预先配置等值备用题时才允许替换；
4. 否则跳题并记录缺证据。

### 明确拒答

1. 确认可跳过且无需说明理由；
2. 可在测评末尾提供一次统一补答机会；
3. 单题拒答表示该维度缺证据；
4. 全程退出表示测评未完成；
5. 二者都不自动等于 0 分。

### 质疑题目或公平性

1. 说明问题的岗位相关目的；
2. 提供澄清、申诉或人工复核渠道；
3. 不与候选人争辩；
4. 不因提出质疑扣分；
5. 如果问题可能触及受保护信息，停止该题并转人工审查。

### 辱骂或威胁

1. 使用固定话术设置边界；
2. 重复攻击时暂停或终止；
3. 将其记录为独立的流程/行为事件；
4. 除非“职业互动行为”本身是经岗位分析验证、且所有人按相同锚点评估的能力，否则不得惩罚性扣能力分。

### 技术或无障碍问题

1. 停止计时；
2. 重试、改期或切换到合理替代形式；
3. 不计入能力分；
4. 不将合理便利请求当作负面行为特征。

## 3.4 “0 分”和“没有测到”必须分开

建议评分结果至少区分：

```text
SCORED
INSUFFICIENT_EVIDENCE
NOT_ADMINISTERED
INVALIDATED
```

只有候选人的有效回答确实命中量表最低行为锚点时，才能给最低分。

以下情况不应直接映射成 0：

- 跳过；
- 拒答；
- 网络中断；
- 无障碍问题；
- 题目本身无效；
- 系统未能完成提问；
- 模型无法判断。

否则系统会把“缺失数据”伪装成“能力极低”。

后续需要进一步决定：

- 缺证据是否触发补测；
- 是否进入人工复核；
- 总分如何处理缺失项；
- 何时将整场标记为 `partial` 或 `incomplete`。

---

# 4. 情绪支持与难度调整

## 4.1 是否应该进行情绪支持

适度的流程支持是合理的，但不应做“情绪识别评分”。

建议只响应候选人的明确表达或可观察流程事实，例如：

- “我有点紧张”；
- 请求暂停；
- 长时间没有输入；
- 请求重述；
- 明确表示不理解题目。

不应根据以下特征推断人格、稳定性或岗位能力：

- 语气；
- 停顿；
- 表情；
- 口音；
- 打字速度；
- “看起来不自信”。

## 4.2 允许的支持方式

可以使用统一、简短、中性的话术：

- “可以稍作停顿后再回答。”
- “我可以重复或换一种不改变题意的说法。”
- “如果暂时没有合适经历，可以先跳过，稍后统一补答。”
- “如遇技术或无障碍问题，可以暂停本次测评。”

不建议：

- “别紧张，你答得很好。”
- “其实答案可以从……考虑。”
- 因候选人紧张而降低评分标准；
- 只向部分候选人额外泄露线索；
- 因表达强势、礼貌或讨好而提高过程分。

支持选项应：

- 预先定义；
- 对所有候选人可用；
- 有触发条件；
- 可审计。

合理便利可以因人而异，但应由独立的人工/合规流程决定，并记录是否保持了被测构念。

## 4.3 是否应该自动降难度

不建议模型临时、自由地降低难度。

未经等值性验证的降难度会使不同候选人的分数不可直接比较。更稳妥的做法是：

1. 所有人先接受相同核心题；
2. 只使用预先定义的难度链；
3. 追问只补齐同一能力证据；
4. 题目替换只能使用预先标记的等值备用题；
5. 如果采用自适应难度，最终评分必须知道候选人实际回答的难度，不能直接比较原始分。

对于课程演示，可以保留“达标升档、证据不足保持或降档”的诊断效果；如果系统进入真实甄选，则必须先做题目校准和路径等价性验证。

## 4.4 `score_live` 的角色需要重新讨论

现有设计让 `score_live` 同时：

1. 驱动后续题目和难度；
2. 与 `score_final` 按 50/50 合成最终分。

相关位置：

- `design/总设计文档.md:182-191`

这可能形成反馈耦合：

```text
过程分低
→ 获得不同或更低难度的问题
→ 收集到不同证据
→ 过程分又占最终成绩 50%
```

可讨论两种方案：

### 方案 A：过程信号只负责导航

- 过程阶段只判断证据覆盖、回答状态和可能水平；
- 该信号不直接进入最终分；
- 会后独立评分器根据冻结原始证据产生最终分。

这是当前更推荐的方向。

### 方案 B：继续保留双分

- 保留 `score_live + score_final`；
- 过程评分器和终局评分器职责隔离；
- 必须验证不同题目路径的可比性；
- 必须测试过程分是否受礼貌、情绪、长度和模型谄媚影响。

这是对现行设计的潜在修改，在确认前不能直接写入 SSOT。

---

# 5. 作答取证—评分—报告证据链

## 5.1 设计目标

现有设计已经要求：

- 每轮保存 `score_live`；
- 测评结束后逐题生成 `score_final + evidence_quote + reason`；
- 双分按既定规则合成；
- 逐项聚合；
- 报告中的优势、短板和建议绑定证据；
- 报告展示逐题回答、双分、理由和证据。

相关位置：

- `design/总设计文档.md:181-218`

目标审计链为：

```text
report
  → session
  → model / version
  → question
  → message
  → trace
```

相关位置：

- `design/总设计文档.md:222-230`

## 5.2 当前已经实现的底层链路

### 原始答案归档

- 长回答经过 SHA-256 后写入 `context_raw`；
- 消息保存精炼内容和 `raw_hash`；
- 短回答直接保存原文。

相关位置：

- `server/services/refine.py:25-44`
- `server/api/assessment.py:154-168`

### 过程决策证据

assistant 消息保存：

- reply；
- action；
- reason；
- `score_live`；
- `score_live_reason`。

相关位置：

- `server/api/assessment.py:170-181`
- `server/db.py:144-156`

### 终局评分证据

- P-score 会回捞原始回答；
- 写入 `score_final`、`evidence_quote`、reason；
- 保存双分合成结果。

相关位置：

- `server/services/scoring.py:31-48`
- `server/services/scoring.py:51-82`
- `server/services/scoring.py:107-153`

### 报告证据

- 逐题回顾会重新取得原始回答；
- 保存题面、题型、能力项、双分、证据和理由；
- 证据按 item 汇总后交给报告提示词；
- 完整报告 JSON 落库。

相关位置：

- `server/services/report.py:35-86`
- `server/services/report.py:89-153`

### LLM Trace

每次 LLM 调用保存：

- prompt；
- response；
- attempt；
- 成功状态；
- error。

相关位置：

- `server/services/llm.py:13-21`
- `server/services/llm.py:41-62`

## 5.3 当前主链断点

正常前端流程是：

1. 最后一题返回 `finish`；
2. Chat 页面直接跳转报告页；
3. 报告页直接触发报告生成。

相关位置：

- `web/src/views/assessment/Chat.vue:241-251`
- `web/src/views/assessment/Report.vue:377-403`

但前端没有调用终局评分接口：

- `server/api/assessment.py:233-246`

报告后台任务也只调用 `generate_report()`，没有先调用 `score_session()`：

- `server/api/assessment.py:249-269`
- `server/services/report.py:89-101`

因此，按正常 UI 流程完成测评时，`question_score` 很可能为空。聚合器会把没有分数的能力项标成 `no_data` 并按 0 贡献处理：

- `server/services/aggregation.py:72-80`
- `server/services/aggregation.py:105-116`

所以当前结论是：

> 证据链的底层组件大部分存在，但 `answer → score → aggregate → report` 的实际主流程尚未闭合。

## 5.4 其他证据链缺口

1. interviewer trace 的 `ref_id` 多数只锚定 session，而非具体 message/question；
2. message、score 和 report 没有直接 `trace_id` 外键；
3. 当前 trace 关系主要依赖字符串间接反查；
4. 通用题无法映射到模型 item 时会被跳过；
5. live/final 相差 ≥2 自动进入 bad-case 尚未实现；
6. 报告后台异常被静默吞掉，没有失败状态和错误 trace。

未来引入 Observation、Policy 和 Tools 后，还应记录：

```text
answer_state
observation_reason
policy_action
budget_before
budget_after
tool_call_id
fallback
evidence_coverage
```

因此该部分不是从零新增，而是：

1. 修复主流程串联；
2. 增强严格锚定；
3. 把新的 Agent 状态和工具调用纳入证据链。

---

# 6. 时间、题数、追问轮次与 Token 预算

## 6.1 当前已有约束

设计和代码中已经存在：

- 设计目标总题数 10–12：`design/总设计文档.md:137-141`；
- 每题最多追问两次：`design/总设计文档.md:156-160`；
- 代码 `FOLLOWUP_MAX=2`：`server/config.py:41-45`；
- 超过约 500 token 触发精炼。

## 6.2 当前缺失约束

尚未真正实现：

- 总测评硬时间；
- 单题时间；
- 全局追问总数；
- 全会话 Token 预算；
- 模型输出 Token 上限；
- 24 小时自动 abandoned；
- 上下文滑动窗口或会话摘要策略。

创建 session 时返回的 `estimated_duration_minutes: 20` 只是硬编码展示值：

- `server/api/assessment.py:93-94`

当前理论最坏情况为：

```text
10 道主问题 ×（首次回答 + 2 次追问）
= 30 次候选人回答
```

这与 20 分钟估算并不一致。

## 6.3 建议采用四类独立预算

```text
time_budget
main_question_budget
probe_budget
token_budget
```

这些预算都必须由代码状态机控制，不允许 LLM 自行突破。

### 时间预算

需要区分：

- 活跃答题时间；
- 用户主动暂停；
- 技术故障；
- 无障碍处理；
- 24 小时恢复期限。

技术故障和合理便利不应消耗评分时间。

### 题量预算

- 固定核心题；
- required 能力优先覆盖；
- 达到题量后进入收尾；
- 题库不足时不能创建 0 题 session；
- 未覆盖完 required 项时应标记 partial，而不是假装测评完整。

### 追问预算

同时约束：

- 单题追问上限；
- 全场追问总上限；
- 每种异常状态的重试次数；
- 接近总时限时是否停止新增追问。

### Token 预算

- 候选人原始答案不能因 Token 超限而静默截断；
- 原文应不可变归档；
- 对话控制应使用结构化状态和必要上下文，不应每轮无限拼接全部历史；
- 摘要只用于导航，终局评分仍应回捞原始证据；
- 模型每轮只生成一个简短问题；
- `max_tokens` 是工程熔断，不是评分规则；
- 上下文溢出应重试、分段或转人工，不能给候选人扣分。

## 6.4 两种内部一致的试点组合

具体时长没有一个对所有岗位都适用的行业标准。可以先在以下两种组合中讨论选择。

### 方案 A：保留约 20 分钟

- 6–8 道核心主问题；
- 默认每题最多一次追问；
- 少数证据不足题允许第二次追问；
- 全局追问总数约 4–6 次。

### 方案 B：保留 10–12 道主问题

- 测评时间提高到约 35–45 分钟；
- 每题仍最多两次追问；
- 另设全局追问上限。

这些数字只是项目试点建议，不是法规或心理测量标准。最终应根据真实答题时长、完成率、缺证据率和模型成本校准。

---

# 7. 防谄媚与防惩罚性判断

为了避免模型因候选人的情绪、赞美、攻击或表达风格改变评分，建议：

1. 面试官主要负责采集证据，不自由决定最终能力分；
2. 最终评分在访谈结束后由独立评分流程执行；
3. 评分必须基于量表锚点和原始证据引用；
4. 缺少证据时允许 abstain，而不是猜测；
5. 候选人文本始终作为数据，不能改变系统指令；
6. 评分提示词、模型、rubric 和题库全部版本化；
7. 低置信、缺证据、异常处置和临界决策进入人工复核；
8. 测试以下反事实输入是否导致不应有的分数变化：
   - 礼貌 vs 质疑；
   - 赞美 vs 辱骂；
   - 长回答 vs 等义短回答；
   - 仅替换姓名或群体线索；
   - 调整回答顺序但不改变内容。

需要特别注意：两个高度相关的 LLM 得出相同结论，不等同于结论真实或公平。

---

# 8. 当前待对齐的七项决策

以下内容都尚未进入 SSOT，也不代表已经拍板：

1. **采用有界测评状态机，不采用自由 ReAct Agent。**
2. **采用固定核心题 + 有限自适应追问/等值备用题。**
3. **回答状态独立建模；拒答、跳过、故障不自动映射为 0。**
4. **正式计分测评默认禁用 Web Search；只有专门的开放资料题例外。**
5. **Tools 使用阶段白名单；关键状态转换只能由代码执行。**
6. **情绪支持只做统一的流程支持，不做情绪能力推断，也不自由降难度。**
7. **重新讨论以下三个具体决策：**
   - `score_live` 是否继续占最终分 50%；
   - 测评采用“20 分钟精简版”还是“10–12 题长版”；
   - `INSUFFICIENT_EVIDENCE` 如何进入补测、人工复核和总分计算。

其中前六项的方向目前相对明确；第七项中的三个问题需要进一步对齐。

---

# 9. 主要参考资料

## 风险、公平性与招聘测评

- [NIST AI Risk Management Framework 1.0](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf)
- [NIST Generative AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- [U.S. OPM Structured Interviews: A Practical Guide](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/guide.pdf)
- [EEOC：Assessing Adverse Impact in AI Employment Selection](https://www.eeoc.gov/select-issues-assessing-adverse-impact-software-algorithms-and-artificial-intelligence-used)
- [EEOC：ADA and the Use of Software, Algorithms and AI](https://www.eeoc.gov/laws/guidance/americans-disabilities-act-and-use-software-algorithms-and-artificial-intelligence)
- [29 CFR Part 1607 — Uniform Guidelines on Employee Selection Procedures](https://www.ecfr.gov/current/title-29/subtitle-B/chapter-XIV/part-1607)
- [DOJ：Algorithms, Artificial Intelligence, and Disability Discrimination in Hiring](https://www.ada.gov/resources/ai-guidance/)
- [EU AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/oj)

## 结构化面试与相关研究

- [Campion et al. (1997), A Review of Structure in the Selection Interview](https://doi.org/10.1111/j.1744-6570.1997.tb00709.x)
- [Levashina et al. (2014), The Structured Employment Interview](https://doi.org/10.1111/peps.12052)
- [SIOP Principles for the Validation and Use of Personnel Selection Procedures](https://www.siop.org/research-publications/professional-resources/principles-validation-use-personnel-selection-procedures/)
- [Powell, Stanley & Brown (2018), Meta-analysis of interview anxiety](https://doi.org/10.1037/cbs0000108)

## LLM 评价偏差

- [Zheng et al., Judging LLM-as-a-Judge](https://arxiv.org/abs/2306.05685)
- [Sharma et al., Towards Understanding Sycophancy in Language Models](https://arxiv.org/abs/2310.13548)

---

# 10. 本文档后续处理方式

1. 本文档仅作为讨论载体；
2. 可以直接在各节下补充意见或修改建议；
3. 未确认结论不得作为代码实现依据；
4. 双方完成对齐后，再将正式决策写入：
   - `design/总设计文档.md` 正文；
   - `design/总设计文档.md` §13 变更日志；
5. 正式设计更新后，再规划对应修复、新增或重构工作。
