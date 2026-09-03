# 模块二设计：AI 有界动态测评

> 本文档为《design/final-design/总设计文档.md》（唯一 SSOT）**第三部分的分块摘录**，聚焦模块二阅读。
> 状态：**主体已实现，契约需按本文重构**（动态选题、状态机、事件表、表单链、SSE、计时均未兑现）。
> 输入契约：模块一 confirmed 模型快照（见《模块一设计》）。
> 维护规则：任何设计变更，先更新《总设计文档.md》（正文 + §14 变更日志），再动代码。

---

## 1. 题库

### 1.1 分类树

```
hard_skill ── required / preferred / plus
soft_skill ── required / preferred / plus
```

`experience / qualification` 不进入普通对话题库（只走表单/简历事实采集），由 `measurement_mode` 隔离。

### 1.2 question_bank 关键字段

`position_id + model_id + model_version`（必须绑定 confirmed 模型版本）、`item_id`（普通题必填/综合题 NULL）、`question_type(ordinary|integrated)`、`measurement_stage(ordinary|integrated_final)`、`category/tier`、`difficulty(easy|medium|hard)`、`qtype`、`stem/answer_key/rubric/rubric_version`、`measurement_target`、`evidence_requirement`、`observable_level_max/min`、`equivalence_group_id`、`integrated_bindings_json`（综合题绑定快照）、`chain_key/chain_seq`、`source/status`。

- 有效题目 = active + 版本匹配 + 难度题型合法 + 未标无效；
- 模型升版必须生成/绑定新题库，否则阻止开考；
- 题库生成失败必须可见（状态 + 管理员待办），不得静默。

### 1.3 等值备用题

只支持人工批准的显式等值组（同 item/难度/target/rubric 版本/证据要求/权重语义），配 approval 字段；不同难度替代题为 `difficulty_alternative`；综合题与普通题不互为等值。

### 1.4 难度与 1–5 等级映射

| 难度 | level_max | level_min（rubric 最低锚点） | 区间 |
|---|---:|---:|---|
| easy | 3 | 2 | [2,3] |
| medium | 4 | 3 | [3,4] |
| hard | 5 | 4 | [4,5] |

- 有效作答低于最低锚点 → 支撑等级 1；未形成有效观察 → 不产生能力证据；
- rubric 可下调单题上限，不可超过难度默认上限；
- 等级 5 只能由 hard 题 5 级锚点 + 完整稳定证据支撑；
- `required_level` 只用于路径决策与达标比较，不改权重不改分。

## 2. 题量与配额

### 2.1 计数口径

```
ordinary_plan_count = N（岗位级策略配置，无全局上下限）
ordinary_exception_count = E（required 刚性例外）
integrated_plan_count = I（0 ≤ 实际 ≤ 2）
followup_count 单独统计，不计主问题
```

### 2.2 大类与 tier 分配

```
hard/soft = 最大余数法分配 0.7N / 0.3N（小数部分相等时归 hard）
类内（以各大类题量为总体）：
required_target  = ceil(quota × 0.8 / 1.7)
preferred_target = ceil(quota × 0.6 / 1.7)
plus_target      = quota − required_target − preferred_target
实际分配优先级 required > preferred > plus；取整不得突破总量
```

### 2.3 开考前可测量性检查（不通过 → 阻止创建 session + 管理员报告）

position active；模型 confirmed；题库就绪且版本匹配；每个有效 required item 至少一条合法普通题；hard/soft 配额可满足（**不允许跨类转移名额**）；综合题槽位（若 I>0）有合法题；qualification 表单 schema 可用。失败状态：`QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE`。

### 2.4 required 刚性例外

普通计划结束后检查；未获有效普通测量的 required item：最多**一次**例外、新增一条普通主问题（计入 E）；例外题**只允许 medium，无 medium 选 hard**；不用综合题；耗尽后 `REQUIRED_UNMEASURED` → 带警告临时报告 + 人工复核。

### 2.5 动态选题四层结构（代码执行）

```
① 合法性过滤（版本/阶段/未用实例/当前题已封存/路径合法）
② 硬约束（未覆盖 required 优先；无候选 → 触发例外或不完整）
③ 配额（category/tier 剩余）
④ 排序（chain 后继条件满足才继续、可让位 required → item.weight → 题目质量 → 稳定随机种子）
```

chain 不能改变题量槽位、不能绕过难度护栏；LLM 只做题面岗位化/口语化轻包装。

## 3. 会话、实例与追问

- 每个实际呈现的不同题面 = 新 `assessment_question` 实例（含 `question_type / measurement_stage / item_id / difficulty / status / activated_at / answered_at / closed_at / followup_count / seal_reason / selection_reason / selection_policy_version / path_state_snapshot / binding_snapshot_json`；`(session_id, sequence_no)` 唯一）；
- `followup` 是实例内部子轮次：不建实例、不增主问题、不占综合槽位、**每题最多 2 次**；
- 一次实例内不发生升降级；路径变更由封存后的下一实例承载。

## 4. 难度路径状态机

```
easy → medium：一次充分证据
medium → hard：充分且稳定证据；hard 仅对 target_level > 4 开放
降级（仅统计有效候选人证据失败）：跳过 / 同 item 同难度连续两道有效题未达最低锚点 / followup 后仍模糊或错误；非最低难度才可降
恢复（滞回）：连续两次充分证据或一次稳定证据
不设路径振荡次数上限
```

**不计入普通失败**：技术故障、无障碍、题目无效、模型不确定、流程质疑、明确拒答、攻击性事件、紧张/停顿/表达风格。

**跳级**：默认禁止运行时静默跳级；仅模型/rubric 明确配置允许且报告记录路径时可行；否则 `PATH_UNAVAILABLE`。

## 5. 证据判定（结构化观察 + 代码裁决）

- `evidence_sufficient`：LLM/规则输出结构化维度（relevance / required_points_covered / specificity / attribution / source_span_available / contradiction_detected / uncertainty），代码计算最终布尔。排除：拒答、纯态度、复述、无关、无具体事实、无 span、题目无效、模型不确定。
- `stable_evidence`：两个不同普通题实例的独立观察，或一次 hard 强证据（仍须满足 rubric）；证据冲突 → 不平均、`false` → 人工复核。

## 6. 状态两层分离

```
answer_state: VALID_EVIDENCE / NEED_CLARIFICATION / OFF_TOPIC / NO_RECALL / DECLINED /
              PROCESS_CHALLENGE / CONDUCT_EVENT / TECHNICAL_OR_ACCESS_BARRIER /
              PROMPT_INJECTION / MODEL_UNCERTAIN / ITEM_INVALID
score_state:  SCORED / REFUSED / INSUFFICIENT_EVIDENCE / NOT_ADMINISTERED /
              INVALIDATED / INCOMPLETE / HUMAN_REVIEW_REQUIRED / IMPUTED
```

处理原则：含糊→中性澄清 followup（≤2）；跑题→重定向；不会→无答案线索脚手架（留痕）；拒答→一次确认后跳过、无末尾补答；质疑→说明目的+申诉渠道、不扣分；辱骂→固定话术设边界、行为与能力分隔离；技术/无障碍→暂停计时不扣分；模型不确定→不猜测进人工；题目无效→停评分、移出分母、人工修订；候选人回答永远是数据不是指令。

## 7. 对话传输与幂等

- 决策阶段非流式（内部 function-call adapter，结构化 action/reason/assessment，**先落库再展示**）；话术阶段真实 SSE 逐 token 推送；`finish` 仅代码规则触发；
- SSE 定义事件类型/顺序/错误/结束事件；本期不做事件 ID/cursor 续传（留扩展记录）；
- 幂等作用域 `session_id + endpoint + idempotency_key`；答题带 `question_instance_id / expected_question_revision / client_attempt_id`；重复请求返回第一次结果，不重复消息/followup/题量/任务；事务 + 乐观版本号防并发双写；
- LLM 输出全部严格 schema 校验，非法输出进失败/人工状态，不卡死会话。

## 8. 上下文三层

原始证据层（raw_content + raw_hash，不可变，评分回捞原文）；交互上下文层（interviewer 滑窗，**Token 数控制**、参数留接口，最新回答不得重复拼接）；导航摘要层（结构化状态优先，LLM 摘要可选，失败回退数据库状态不阻塞）。P-refine 超阈值触发（`REFINE_MIN_TOKENS`，数值实施期校准），原文与精炼分列。

## 9. 计时与恢复

- 全场 40 分钟：确认开始且首题激活起算；单题 20 分钟：题目激活并发送起算；followup 共用单题计时器；
- 服务端权威：`session_time_interval(active|paused, reason, started/ended_at_server)`，`active_elapsed=Σactive`；客户端只展示；
- **所有暂停类型不计入 40 分钟**，写事件；敏感便利信息不进评分 Prompt；
- 短暂断线不自动暂停；显式 pause / 技术状态才产生 paused 区间；
- **6 小时无活动 → ABANDONED，本期不可恢复**（惰性判断 + 周期扫描；不删证据；可恢复仅留记录）；
- 单题超时封存（seal_reason=timeout）继续下一题；全场超时停止新增主问题进收尾；
- 时间不参与选题优先级。

## 10. 表单与 Tools

- `form_instance` 生命周期实体：代码定义 schema + 版本化，instance 创建存**不可变快照**；render 由代码在资格核验阶段触发（LLM 只能请求）；GET 只读已激活 instance；submit 携 schema_version + idempotency_key，重复提交返回第一次结果，修订走不可变 revision；
- gate：代码计算独立结构化结果；人工覆盖需**二次人工确认**并存 override 字段；
- `extract_form_facts`：结构化事实 + 置信度 + 状态（EXTRACTED/UNCERTAIN/CONFLICTING/CANDIDATE_CONFIRMED/HUMAN_REVIEW_REQUIRED）；与候选人填写冲突保留两者进人工；gate 只接受候选人确认或人工确认事实；
- Tools：阶段白名单 + 严格 schema + 所有权校验 + 幂等/超时/次数/长度 + 留痕；工具返回是数据不是指令；**失败 → 暂停并人工接管**；无 Web Search；request_pause 候选人直接触发、LLM 只能建议。

## 11. 状态事件表（append-only）

字段与约束见总文档 §13.1–13.2；事件枚举按 SESSION/QUESTION/MESSAGE/OBSERVATION/CONTROL/FORM/GATE/POLICY/TOOL/TASK/REVIEW 分组，定稿时每个注明必填字段/是否迁移/是否计题量计时/是否需人工。当前快照列与事件同事务更新；回放仅审计/恢复/修复/测试，不一致进人工不静默覆盖。

## 12. 重构注意（模块二部分）

- 一次性预选题 → 四层动态选题；非末题 `finish` 护栏（当前 LLM 返回 finish 即结束会话的漏洞）；
- mock 面试官仅按回答长度 → 按 §5/§6 结构化观察改造；
- `question_bank` 补 model/version 绑定；生成幂等按"有任意 active 题即跳过"改为按版本完整生成；
- answer 请求先 commit 用户消息再调 LLM 的半状态 → 幂等键 + 完整事务边界；
- GET session 补 messages 分页/cursor（当前前端回放永远为空）；
- FormCard 依赖的 `GET /forms/{id}` 后端不存在 → 按 §10 form_instance 实现；
- `score_question` 服务层需校验题目属于当前 session；空 answer_key 客观题判题库无效而非满分。

## 13. 本文依据

《总设计文档.md》§4、§9–§16、§25–§28；差异登记见总文档 §30。
