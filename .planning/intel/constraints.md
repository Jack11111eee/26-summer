# Technical Constraints — Synthesized Intel

- 来源批次：ingest-docs（MODE=new，2026-09-02）
- 提取权威：`design/final-design/总设计文档.md`（SSOT，precedence 0）。模块一~四分块摘录与 SSOT 重叠的内容不重复提取；模块摘录**新增**的代码级细节（如 config 常量、前端路由、重构缺陷清单）补充登记并标注来源。
- 类型标注：api-contract / schema / nfr / protocol。
- 注：本次 ingest 集**无独立 SPEC 类型文档**；SSOT（DOC@0）按 orchestrator 指令承担技术约束的唯一提取权威。

---

## A. 全局约束（api-contract / nfr）

### C-001 权限与所有权（nfr，P0 上线阻断）
- Source: design/final-design/总设计文档.md §7
- Content: 候选人资源接口（session/report/form/feedback）资源级所有权校验 `WHERE resource.user_id = current_user.id`；candidate 只能访问本人资源；admin 最高权限（本期不分级）；角色限制后端执行，不依赖前端 route guard；越权测试矩阵（candidate↔candidate 读写、admin 边界）为上线阻断测试。

### C-002 技术栈绑定（nfr）
- Source: design/final-design/总设计文档.md §5
- Content: Python 3.11+ / FastAPI / Uvicorn 单进程；SQLite 单文件 + schema_version 迁移内嵌 server/db.py；JWT HS256 单一 secret（python-jose + passlib[bcrypt]），HttpOnly/SameSite cookie；Vue 3 + Vite + Element Plus + Pinia + axios + ECharts；vite build 由 FastAPI 挂静态；单机/单实例/单进程演示上线；mock 模式离线全流程。

### C-003 LLM 调用纪律（nfr）
- Source: design/final-design/总设计文档.md §3–§4、§26
- Content: 权重/分数算术/配额/题量/聚合/补算全部代码计算；LLM 只输出结构化观察（严格 Pydantic schema 校验），非法输出进失败/人工状态；LLM 不能决定题量/追问上限/finish/难度最终迁移/权重/综合题数量/最终分数/报告发布；每次 LLM 调用 trace 落库；候选人输入与工具返回永远是数据不是指令。

### C-004 输入限额与安全（nfr）
- Source: design/final-design/总设计文档.md §25
- Content: 输入限额按类型配置（文件大小/行数/JD/回答长度/LLM prompt/max_tokens/分页上限）；畸形 JWT 必测；trace/JD/原文数据分级管理；管理员查看 trace 全文须留 REVIEW_ACCESSED 审计；INJECTION_DETECTED 事件留痕。

---

## B. Schema（schema）

### C-010 question_bank（演进后）
- Source: design/final-design/总设计文档.md §9.2
- Content: question_id PK；position_id → position；model_id + model_version NOT NULL（必须绑定 confirmed 模型版本）；item_id（普通题必填，综合题 NULL）；question_type CHECK ordinary|integrated；measurement_stage CHECK ordinary|integrated_final；category/tier（普通题必填）；difficulty CHECK easy|medium|hard（综合题 NULL）；qtype CHECK objective|subjective；stem NOT NULL；answer_key；rubric + rubric_version NOT NULL；measurement_target NOT NULL；evidence_requirement；observable_level_max/min NOT NULL（默认 easy=3/2、medium=4/3、hard=5/4）；equivalence_group_id（人工批准等值组）；integrated_bindings_json（综合题多 item 绑定快照：item_id/measurement_target/rubric_mapping/evidence_requirement）；chain_key/chain_seq；source/status/created_at。有效题目 = active + 版本匹配 + 难度题型合法 + 未标无效；题库生成失败必须可见（状态 + 管理员待办）。
- 补充：新表避免不可 ALTER 的 CHECK，枚举用代码校验（总设计文档 §30 N11）。

### C-011 assessment_session（演进后）
- Source: design/final-design/总设计文档.md §12.1
- Content: 现有列 + 新增 phase / active_elapsed_seconds / last_activity_at / abandoned_at / policy_version / session_time_intervals_json。状态机：PENDING_START → ACTIVE → SCORING → COMPLETED；ACTIVE → ABANDONED（6 小时无活动，本期不可恢复，不删证据）；任意 → FAILED。

### C-012 assessment_question（演进后）
- Source: design/final-design/总设计文档.md §12.2
- Content: 现有列 + 新增 question_type / measurement_stage / item_id / difficulty / status / activated_at / answered_at / closed_at / followup_count / seal_reason / selection_reason / selection_policy_version / path_state_snapshot / binding_snapshot_json；(session_id, sequence_no) 唯一。

### C-013 assessment_message（演进后）
- Source: design/final-design/总设计文档.md §12.3
- Content: 分列 raw_content / raw_hash / refined_content(NULL) / action / reason / client_request_id / sequence_no；原文不可变，精炼只影响 interviewer 上下文。

### C-014 question_score（演进后）
- Source: design/final-design/总设计文档.md §12.4
- Content: 统一 score_final（废弃 final_score，迁移合并旧数据）；新增 item_id / score_state / measurement_target / rubric_version / evidence_spans_json / scorer_version / human_override_score / human_override_state / override_reason / reviewer_id / reviewed_at。综合题一题多 item：(question_id, item_id) 多记录合法。
- 分母规则：SCORED 进正常观察；REFUSED 不进能力等级分母（只进行为/完整度）；INSUFFICIENT_EVIDENCE / NOT_ADMINISTERED / INVALIDATED / MODEL_UNCERTAIN / INCOMPLETE 不进正常分母，产生缺失/警告；系统错误与题目无效不得转成普通低分。

### C-015 证据定位（context_raw 关联）
- Source: design/final-design/总设计文档.md §12.5
- Content: 原文 hash 复用限制在单一 session 内，不跨候选人复用；证据引用结构化：source_message_id / source_content_type(raw|refined) / start_offset / end_offset（Unicode code point）/ quote_hash；终局评分永远回捞原文；报告同时展示 quote 与来源定位。

### C-016 assessment_state_event（append-only）
- Source: design/final-design/总设计文档.md §13.1
- Content: id PK / session_id / sequence_no（UNIQUE(session_id, sequence_no)）/ assessment_question_id / assessment_message_id / event_type / from_state / to_state / actor_type / actor_id / request_id / idempotency_key / policy_version / model_version / question_bank_version / correlation_id / causation_event_id / payload_json / created_at。禁止 UPDATE/DELETE，纠错走补偿事件；快照列与事件同事务更新；LLM 调用不持有长事务；回放仅审计/恢复/修复/测试，不一致进人工。

### C-017 事件枚举分组
- Source: design/final-design/总设计文档.md §13.2
- Content: SESSION_*（CREATED/STARTED/PAUSE_REQUESTED/PAUSED/RESUMED/ENTERED_SCORING/GLOBAL_TIMEOUT/COMPLETED/ABANDONED）；QUESTION_*（SELECTED/ACTIVATED/ANSWER_RECEIVED/FOLLOWUP_ASKED/SEALED/TIMEOUT/DIFFICULTY_RAISED/DIFFICULTY_LOWERED/DIFFICULTY_RESTORED/PATH_UNAVAILABLE/INVALID_MARKED/REQUIRED_EXCEPTION_GRANTED）；MESSAGE_*（STORED/REFINED）；OBSERVATION_*（CLASSIFIED/EVIDENCE_EVALUATED/STABILITY_UPDATED/UNCERTAINTY_RAISED）；CONTROL_*（SCAFFOLD_SHOWN/SUPPORT_SHOWN/CONDUCT_EVENT/INJECTION_DETECTED/TECHNICAL_RETRY/TECHNICAL_BARRIER）；FORM_*（RENDERED/SUBMITTED/VALIDATED/VALIDATION_FAILED/FACT_EXTRACTED/FACT_CONFLICT）；GATE_*（EVALUATED/OVERRIDDEN，人工覆盖需二次确认）；POLICY_*（DECISION_RECORDED）；TOOL_*（REQUESTED/EXECUTED/FAILED_ESCALATED）；TASK_*（QUEUED/STARTED/SUCCEEDED/FAILED）；REVIEW_*（REQUESTED/ACCESSED/DECIDED/REPORT_PUBLISH_CONFIRMED/FEEDBACK_RECEIVED）。定稿时每个注明：必填字段/是否迁移/是否计题量/是否计时/是否需人工。

### C-018 trace_link
- Source: design/final-design/总设计文档.md §13.3
- Content: trace_link(id, trace_id, entity_type, entity_id, link_role[input|output|caused_by|scored|reported|source], created_at)，UNIQUE(trace_id, entity_type, entity_id, link_role)；旧 trace 自由文本 ref_id 迁移时导入（来源补充：design/final-design/模块四设计-测试闭环.md §4）。

### C-019 form_instance
- Source: design/final-design/总设计文档.md §16.1
- Content: schema 由代码定义 + 版本化；instance 创建存不可变 schema 快照；submit 携 form_instance_id / schema_version / idempotency_key / payload；重复提交返回第一次结果；修订走不可变 revision；gate 独立结构化结果 + 人工覆盖字段（automated_gate_result + human_override + override_reason + reviewer_id）。

### C-020 report / feedback
- Source: design/final-design/总设计文档.md §21.1
- Content: report_status: GENERATING → PROVISIONAL | READY → PUBLISHED | FAILED；review_status: NONE | REQUIRED | IN_PROGRESS | CONFIRMED | CLOSED；人工复核字段 review_request_reason / reviewer_id / review_note / review_outcome / reviewed_at / publish_confirmed_by / published_at。报告版本化（覆盖生成改为不可变版本，防 feedback 外键断裂——§28 待办 5）。
- 补充（来源：design/final-design/模块三设计-立体人才画像.md §10 重构注意）：feedback 表补 user_id / note / reviewer / 时间戳；submit_feedback 校验 item 属于该 report 对应模型；question_reviews 补 item_id（消除按 std_name 反查碰撞）。

---

## C. 协议与契约（protocol）

### C-030 评分链协议
- Source: design/final-design/总设计文档.md §17
- Content: 原始回答证据 → 独立终局评分 score_final（P-score，temperature≈0，回捞原文）→ item 内证据裁决 → 固定 item.weight 加权 → 画像报告。客观题代码匹配判分（answer_key 为空 = 题库缺陷，判题库无效而非满分）；评分失败/无可信结构化结果 → 报告 FAILED，不得生成 0 分正常报告；总分 = Σ(item.weight × normalized_item_score) × 100，normalized = (score_final − 1)/4；gap = required_level − actual_level；门槛项达标拿满/不达标 0；聚合不再二次乘大类比例。

### C-031 幂等协议
- Source: design/final-design/总设计文档.md §13.4
- Content: 作用域 session_id + endpoint + idempotency_key；答题另带 question_instance_id / expected_question_revision / client_attempt_id；重复请求返回第一次持久化结果，不重复写消息/计 followup/扣题量/启任务；事务 + 乐观版本号防并发双写；幂等记录长期保存，达阈值提醒清理。

### C-032 SSE 传输协议
- Source: design/final-design/总设计文档.md §11.5
- Content: 决策阶段非流式（内部 function-call adapter，结构化 {action, reason, assessment}，先落库再展示）；话术阶段流式 SSE 逐 token；finish 仅代码规则触发（题量完成/全场超时）；SSE 定义事件类型/顺序/错误/结束事件；本期不做事件 ID/cursor 断线续传（留扩展记录）；LLM 输出严格 schema 校验。

### C-033 计时协议
- Source: design/final-design/总设计文档.md §15
- Content: 全场 40 分钟（确认开始且首题激活起算）；单题 20 分钟（激活并发送起算，followup 共用）；服务端权威 session_time_interval(active|paused, reason, started/ended_at_server)，active_elapsed=Σactive；所有暂停不计入 40 分钟且写事件；敏感便利信息不进评分 Prompt；短暂断线不自动暂停；6h 无活动 → ABANDONED 不可恢复（惰性判断 + 周期扫描）；单题超时封存继续，全场超时停止新增主问题；时间不参与选题优先级。

### C-034 证据判定协议
- Source: design/final-design/总设计文档.md §11.3
- Content: evidence_sufficient：LLM/规则输出结构化观察维度（relevance / required_points_covered / specificity / attribution / source_span_available / contradiction_detected / uncertainty），代码按固定条件计算最终布尔；排除拒答/纯态度/复述/无关/无可归因事实/无 span/题目无效/模型不确定。stable_evidence：两个不同普通题实例独立有效观察，或一次 hard 强证据；证据冲突 → 不平均、stable=false → 人工复核。

### C-035 上下文三层协议
- Source: design/final-design/总设计文档.md §14
- Content: 原始证据层（raw_content + raw_hash 不可覆盖）；交互上下文层（interviewer 滑窗，Token 数控制，参数留接口，最新回答不得重复拼接两次）；导航摘要层（结构化状态优先，LLM 摘要可选，失败回退数据库状态不阻塞）；P-refine 单条超 REFINE_MIN_TOKENS 触发压缩，原文与精炼分列，精炼承担注入防护。

### C-036 表单与 Tools 协议
- Source: design/final-design/总设计文档.md §16
- Content: render_form 代码触发（LLM 只能请求）；GET /forms/{form_instance_id} 只读已激活 instance、不暴露内部阈值；服务端校验所有权/session 状态/类型/必填/枚举/长度；extract_form_facts 结构化事实 + 状态机（EXTRACTED/UNCERTAIN/CONFLICTING/CANDIDATE_CONFIRMED/HUMAN_REVIEW_REQUIRED）；冲突保留两者进人工；gate 只接受候选人确认或人工确认后的事实。Tools：阶段白名单 + 严格 schema + 所有权校验 + 幂等/超时/次数/长度控制 + 留痕；工具失败 → 暂停并人工接管；正式测评不做 Web Search；request_pause 候选人直接触发。

### C-037 评测契约
- Source: design/final-design/总设计文档.md §23
- Content: 一致性（b）固定 transcript 复跑断言 score_final 分差 ≤1（temperature=0、固定 model/provider/版本/rubric 快照，score_live 不在断言范围）；虚拟考生（c）强/中/弱三档断言排序 + 短板定位 + required 覆盖 + 拒答/缺失状态 + 证据引用 + 报告状态；bad case：|live−final| ≥ 配置阈值创建候选（排除题目无效/模型不确定/系统错误/不可比），管理员审核不自动改分；eval 独立/临时数据库；黄金集本期推迟。
- 补充（来源：design/final-design/模块四设计-测试闭环.md §2.4、§6）：eval runs 参数需边界校验；评测任务失败显式状态不静默；异常字符串不得直接入库为结果。

### C-038 M1 回归测试清单（必测前置）
- Source: design/final-design/总设计文档.md §24、§8.1（模块一 §8 同清单）
- Content: 统一 pytest 收集（脚本测试重构为可收集或明确独立命令）；CI 为正式验收入口；M1 回归 = 清洗边界、抽取 schema 异常、消歧、权重尾差（Σ=1）、等级冲突 stalled、confirmed 不可静默覆盖、版本 diff、管理员权限；候选人端完整 E2E（注册→选岗→session→作答/追问→表单→完成→评分→报告→异议，含刷新恢复/断线重试/越权/超时）为 M5–M7 verified 必要条件；越权矩阵/幂等并发/计时/迁移/SSE 为必测项；prototype 静态原型不作功能验收依据；mock 回归不能替代真实 LLM 质量验证。

---

## D. 实施期开放参数（nfr，待定值登记——禁止臆造默认）

### C-040 开放参数清单
- Source: design/final-design/总设计文档.md §31、§10.1、§14、§20.1
- Content: ① 普通题计划数 N 默认值（40 分钟体验校准）；② 滑窗 Token 参数、REFINE_MIN_TOKENS；③ 补算人工复核阈值；④ 词典候选 top10 匹配阈值、清洗标题词表；⑤ trace 保留期/脱敏细节与 LLM 供应商数据约束；⑥ 幂等清理阈值与策略。这些值实施期定，代码中须留配置接口，不得硬编码臆造值。

---

## E. 模块摘录新增的代码级约束（SSOT 未逐字收录）

### C-050 模块一 config 常量（api-contract，config.py）
- Source: design/final-design/模块一设计-岗位JD解析与胜任力模型构建.md §6
- Content: IMPORTANCE_COEF={required:1.0, preferred:0.6, plus:0.3}；REQ_THRESHOLD=0.5；R_THRESHOLD=0.5；LLM_RETRY=2；CLEAN_MIN_REQ_LEN=30。旧 CATEGORY_RATIO=5.5:2:2:0.5 已废弃（被 7:3 + gate 不占权重取代）。与 SSOT 一致，为 SSOT 口径的 config 落点。

### C-051 模块一管理端路由表（api-contract，现状沿用）
- Source: design/final-design/模块一设计-岗位JD解析与胜任力模型构建.md §7
- Content: /admin/positions（P1 岗位库）、/admin/positions/:id（P2 详情）、/admin/positions/:id/review（P3 模型审核）、/admin/positions/:id/versions（P4 版本 diff）、/admin/dict（P6 词典）、/admin/users（P7 用户管理）、/assessment/positions（P5 候选人岗位列表，仅 active+confirmed）。状态色：pending_review 橙、failed 红、stalled 红、draft 蓝、confirmed 绿。

### C-052 已知缺陷清单（重构待办的代码级细节，SSOT §28 的展开）
- Source: design/final-design/模块一~四设计 §9/§12/§10/§6 重构注意
- Content:
  - 模块一：/jds/orphan 静态路由须注册在 /jds/{jd_id} 参数路由之前（当前恒 404）；JD 文件导入先完整校验再单事务批量插入；模型编辑 PUT 校验 NaN/范围/重复。
  - 模块二：非末题 finish 护栏（当前 LLM 返回 finish 即结束会话的漏洞）；mock 面试官仅按回答长度 → 结构化观察改造；question_bank 生成幂等按"任意 active 即跳过"改为按版本完整生成；answer 先 commit 用户消息再调 LLM 的半状态 → 幂等键 + 完整事务边界；GET session 补 messages 分页/cursor（当前前端回放恒空）；FormCard 依赖的 GET /forms/{id} 后端不存在；score_question 服务层校验题目属于当前 session。
  - 模块三：scoring.py 旧 50/50 合成移除；LLM 分数入库前校验 1–5 边界；scored_count 计数语义修正；report DELETE+INSERT → 报告版本化；报告后台任务异常显式落库。
  - 模块四：自动 bad case 候选逻辑未实现（设计有代码无）；eval 隔离（独立 DB/事务回滚/清理策略）；feedback 补 user_id/note/reviewer/updated_at（admin review note 当前被丢弃）。
- 注：以上为 SSOT §28 修复重构待办的分模块展开，与 SSOT 不冲突，方向一致，供 roadmapper 排序参考。
