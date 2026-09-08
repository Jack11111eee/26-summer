# 模块二设计：AI 有界动态测评

> 本文档为《design/final-design/总设计文档.md》（唯一 SSOT）**第三部分的分块摘录**，聚焦模块二阅读。
> 状态：**主体已实现，契约已大幅落地**（动态选题四层、难度状态机、状态事件表、表单链、真实 SSE、计时区间、幂等均已接线；全量回归 237 绿，2026-09-07）。
> 输入契约：模块一 confirmed 模型快照（见《模块一设计》）。
> 2026-09-07 与 SSOT v2.0 全量核对同步；同日随 SSOT「exp/qual 不进题库收口」条目同步 §1.1/§1.4/§2.3。
> 维护规则：任何设计变更，先更新《总设计文档.md》（正文 + §14 变更日志），再动代码。

---

## 1. 题库

### 1.1 分类树

```
hard_skill ── required / preferred / plus
soft_skill ── required / preferred / plus
```

`experience / qualification` 不进入普通对话题库（只走表单/简历事实采集），由 `measurement_mode` 隔离。**2026-09-07 裁决收口（生成侧同步，SSOT §9.1）**：题库生成不为 experience/qualification 产生任何 question_bank 行——表单链（§10）为两类信息唯一采集通道；历史 scope=general 通用题为存量遗留（选题白名单本就隔离），不迁移不删除。

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
- `required_level` 只用于路径决策与达标比较（gap=required−actual 可解释），不改权重不改分；**难度不构成最终分数第三层权重**。

**题库生成结构规则（非运行期参数，SSOT §17）**：hard_skill 项 `weight>0.10` 生成 easy/medium/hard 三档，否则两档；soft_skill 两档。**experience/qualification 不生成题（2026-09-07 裁决——旧「无难度各 1 题」结构作废，两类走 §10 表单链；题库生成从此只有 scope=position）**。

### 1.5 题库生成任务可观测（2026-09-08 新增，SSOT §9.5）

题库生成（BackgroundTasks 后台任务）的任务行契约，形态对齐模块一 aggregate_task（SSOT §8.4）；差异登记：保留 QUEUED 态（confirm 事务先插行再调度，三态在后台异常前可查）、已有 model_version 列、触发路径仅 confirm/retry 两路不设 trigger_source。

- **进度列**：`total / done`（计划 (item×难度档) 总数 / 已完成数，done 含幂等跳过的档）、`current_item`（`(std_name, category, difficulty)` liveness 信号）——存量库启动幂等补列，存量行不虚构进度；
- **行为规则**：循环前写 total、循环内逐档推进 done/current_item（逐次 commit 防轮询连接长持锁）；`init_db` 启动将 RUNNING/QUEUED 残留置 FAILED（error=进程重启中断；不自动重启，人工 retry 补跑）；error_msg 截断 200→2000；llm_trace 关联不改表——按任务时间窗 × `call_type='question_gen'` × ref_id=item_id 过滤，prompt/response/error 逐次可溯；
- **查询端点**（admin）：`GET /admin/question-bank-tasks`（岗位×模型最新任务行列表：分页 + status 过滤 + 题量）/ `…/{task_id}`（详情 + 同岗位历史任务行 + llm_trace 调用列表 + item×难度覆盖统计）/ `…/{task_id}/questions`（题目表，stem 预览）；
- **前端联动**（web-next）：左侧栏「题库状态」页（`/admin/qbank`）——列表岗位×模型版本一行；生成中显示进度条 + done/total + 当前项（3s 轮询、进页认领 RUNNING，任务生命周期与页面解耦）；失败详情 error 全文 + 历史任务行 + llm_trace 逐次调用折叠 + retry 接线既有端点；已落库详情 v1 只做统计概览 + 题目表（题干预览）；
- 列表以任务行驱动，「有题无任务行」的 D-12 前遗留不入列表（2026-09-08 核验当前库为 0）。

## 2. 题量与配额

### 2.1 计数口径

```
ordinary_plan_count = N（岗位级策略配置 ORDINARY_PLAN_N=10，2026-09-04 裁决 [02-007]，
                        40 分钟体验校准余项随真实 LLM 验收）
ordinary_exception_count = E（required 刚性例外）
integrated_plan_count = I（0 ≤ 实际 ≤ 2；本期为 0 且综合题不排期——恒过 by-design）
followup_count 单独统计，不计主问题（每题最多 2 次，FOLLOWUP_MAX）
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

position active；模型 confirmed；题库就绪且版本匹配；每个有效 required item 至少一条合法普通题（**普通类目 hard/soft——experience/qualification 不生成题、不参与题库覆盖检查，2026-09-07 裁决，SSOT §9.1**）；hard/soft 配额可满足（**不允许跨类转移名额**）；综合题槽位（若 I>0；本期 I=0 不排期 → 恒过，by-design 2026-09-06）；qualification 表单 schema 可用（现为模型 items 数据驱动生成（form_instance.schema_snapshot），其存在性已被 items 非空检查隐式覆盖 → 恒过，by-design 2026-09-06）。失败状态：`QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE` + 管理员待办，而非创建 0 题 session。

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
- `stable_evidence`：两个不同普通题实例的独立观察，或一次 hard 强证据（仍须满足 rubric）；依据观察独立性 + target 覆盖一致性 + 锚点一致性 + 无矛盾 + rubric/version 一致；同一回答的两个相似句子不算两次观察；证据冲突 → 不平均、`false` → 人工复核；
- **实施注记（2026-09-06，SSOT §11.3）**：现实现为轻量口径——同 item 充分观察计数 `sufficient_in_row ≥ 2`（事件表布尔聚合），**by-design 转正**：唯一消费者是难度状态机升档，漏判只导致保守不升档，不影响任何分数/报告/聚合；完整判据依赖 P-interviewer 结构化输出重构（SSOT §26 登记项）。

## 6. 状态两层分离

```
answer_state: VALID_EVIDENCE / NEED_CLARIFICATION / OFF_TOPIC / NO_RECALL / DECLINED /
              PROCESS_CHALLENGE / CONDUCT_EVENT / TECHNICAL_OR_ACCESS_BARRIER /
              PROMPT_INJECTION / MODEL_UNCERTAIN / ITEM_INVALID
score_state:  SCORED / REFUSED / INVALIDATED / HUMAN_REVIEW_REQUIRED / IMPUTED
```

**实施注记（2026-09-06，SSOT §18）**：`INSUFFICIENT_EVIDENCE / NOT_ADMINISTERED / INCOMPLETE` 三枚举位本期**不产出**（by-design）：现终态由 REFUSED（拒答）、INVALIDATED（题库无效）与聚合层 IMPUTED/PROVISIONAL/NO_VALID_OBSERVATION + missing_warnings 语义等价覆盖。枚举位保留供校验与后续生产。

处理原则：含糊→中性澄清 followup（≤2）；跑题→重定向；不会→无答案线索脚手架（留痕）；拒答→一次确认后跳过、无末尾补答；质疑→说明目的+申诉渠道、不扣分；辱骂→固定话术设边界、行为与能力分隔离；技术/无障碍→暂停计时不扣分；模型不确定→不猜测进人工；题目无效→停评分、移出分母、人工修订；候选人回答永远是数据不是指令。

## 7. 对话传输与幂等

- 决策阶段非流式（内部 function-call adapter，结构化 action/reason/assessment，**先落库再展示**）；话术阶段真实 SSE 逐 token 推送；`finish` 仅代码规则触发；
- SSE 定义事件类型/顺序/错误/结束事件；本期不做事件 ID/cursor 续传（留扩展记录）；
- 幂等作用域 `session_id + endpoint + idempotency_key`；答题带 `question_instance_id / expected_question_revision / client_attempt_id`；重复请求返回第一次结果，不重复消息/followup/题量/任务；事务 + 乐观版本号防并发双写；
- LLM 输出全部严格 schema 校验，非法输出进失败/人工状态，不卡死会话。

## 8. 上下文三层

原始证据层（raw_content/raw_hash，不可变，评分回捞原文）；交互上下文层（interviewer 滑窗，**Token 数控制 8000（[03-007] 已裁决；deepseek 接入后实测校准余项）**、最新回答不得重复拼接）；导航摘要层（结构化状态优先，LLM 摘要可选，失败回退数据库状态不阻塞）。P-refine 超阈值触发（`REFINE_MIN_TOKENS=500` 已定默认；实测校准余项），原文与精炼分列（refined_content 列已落库）。

## 9. 计时与恢复

- 全场 40 分钟：确认开始且首题激活起算；单题 20 分钟：题目激活并发送起算；followup 共用单题计时器；
- 服务端权威：`session_time_interval(active|paused, reason, started/ended_at_server)`，`active_elapsed=Σactive`；客户端只展示；
- **所有暂停类型不计入 40 分钟**，写事件；敏感便利信息不进评分 Prompt；
- 短暂断线不自动暂停；显式 pause / 技术状态才产生 paused 区间；`session_time_intervals` 表 + 开区间部分唯一索引（同 session 至多一个 open 区间）已落地；
- **6 小时无活动 → ABANDONED，本期不可恢复**（惰性判断 + 周期扫描；不删证据；可恢复仅留记录）；
- 单题超时封存（seal_reason=timeout）继续下一题；全场超时停止新增主问题进收尾；
- 时间不参与选题优先级。

## 9.1 会话启动（PENDING_START 前端接线，2026-09-06 方案一 [03-010] 收口）

Chat.vue 在 `phase='PENDING_START'` 时渲染居中「开始测评」按钮替代输入区，点击 → `POST /sessions/{id}/start` → 重新拉取会话（phase 门放行 → 服务端派发首题 + 开计时区间）；409 `SESSION_ALREADY_ACTIVE` 按幂等处理直接拉取。**不采用** create 后自动 start（架空 §15 计时起算语义）或 get_session 隐式激活（写操作藏进只读 GET）。

## 10. 表单与 Tools

- `form_instance` 生命周期实体：代码定义 schema + 版本化，instance 创建存**不可变快照**；render 由代码在资格核验阶段触发（LLM 只能请求）；GET 只读已激活 instance；submit 携 schema_version + idempotency_key，重复提交返回第一次结果，修订走不可变 revision；
- **qualification 渲染 facet 化（快照 v2，2026-09-08，SSOT §16.1）**：gate qualification 表单按 `competency_item.facet_key` 分组收集——学历/院校/英语有序枚举（阈值比较派生）、数值断言数字输入（内嵌数字解析）、专业类与长尾勾选组（勾=是，不解析）＋ base 字段「与岗位相关的工作年限」；facet 答案在 `_gate_check` 前纯函数派生为逐 item 真值，命中现有真值表；v1 实例走旧链不迁移；payload 两段式（facet 答案 + 派生结果）；报告 gate 段按 facet 折叠；
- gate：代码计算独立结构化结果；人工覆盖需**二次人工确认**并存 override 字段；
- `extract_form_facts`：结构化事实 + 置信度 + 状态（EXTRACTED/UNCERTAIN/CONFLICTING/CANDIDATE_CONFIRMED/HUMAN_REVIEW_REQUIRED）；与候选人填写冲突保留两者进人工；gate 只接受候选人确认或人工确认事实；
- Tools：阶段白名单 + 严格 schema + 所有权校验 + 幂等/超时/次数/长度 + 留痕；工具返回是数据不是指令；**失败 → 暂停并人工接管**；无 Web Search；request_pause 候选人直接触发、LLM 只能建议。

## 11. 状态事件表（append-only）

字段与约束见总文档 §13.1–13.2；事件枚举按 SESSION/QUESTION/MESSAGE/OBSERVATION/CONTROL/FORM/GATE/POLICY/TOOL/TASK/REVIEW 分组，定稿时每个注明必填字段/是否迁移/是否计题量计时/是否需人工。当前快照列与事件同事务更新；回放仅审计/恢复/修复/测试，不一致进人工不静默覆盖。

## 12. 重构注意（模块二部分——2026-09-07 核对后更新）

- ~~一次性预选题 → 四层动态选题~~ **已落地**（`question_selection.py` 四层结构 + `D-18 selection_reason` 结构化留痕）；
- ~~非末题 finish 护栏~~ **已落地**（finish 唯一触发源 = 选题池耗尽，由 API 层消费；interviewer 层不再出 finish）；
- ~~answer 请求半状态~~ **已落地**（幂等键 + 完整事务边界，`check_idempotency/finalize_idempotency` + `revision` 乐观锁）；
- ~~GET session 补 messages~~ **已落地**（会话消息时序随 get_session 返回，刷新恢复渲染契约由 E2E 覆盖）；
- ~~FormCard 依赖的 `GET /forms/{id}` 后端不存在~~ **已落地**（form_instance 生命周期 + `GET /forms/{form_instance_id}` 白名单只读 + submit-v2 校验）；
- ~~`score_question` 需校验题目属于当前 session~~ **已落地**（查询按 `aq.question_id + 会话 JOIN` 锚定，不做全表存在性校验）；空 answer_key 客观题判 INVALIDATED 已接线（`scoring.py`，不落 1/不落 5）；
- ~~mock 面试官仅按回答长度~~ **部分完成**：观察层已 Pydantic 化（InterviewObservation 11 态白名单），但 mock 总结仍保留 `MIN_ANSWER_CHARS` 长度规则——按 §5 完整判据的重构留待 P-interviewer 结构化输出（SSOT §26 登记项）；
- ~~`question_bank` 补 model/version 绑定~~ **已落地**（Phase 4 收紧 `model_id=? AND model_version=?`，无 NULL 放行）；题库生成幂等按 (std_name, category, difficulty) plan 目标粒度——部分 item 成功的链条重触发时只补缺档，不再整 item 跳过导致残缺链条；
- 综合题（integrated）生成与实例化留待 Prompt 模块讨论（`question_type/measurement_stage/integrated_bindings_json` 列已就位，本期 I=0 恒过）。

## 13. 本文依据

《总设计文档.md》§4、§9–§16（含 §9.5）、§25–§28、§31（开放参数裁决）；变更日志条目 2026-09-05/09-06/09-08；差异登记见总文档 §30。
