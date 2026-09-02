# Design Decisions — Synthesized Intel

- 来源批次：ingest-docs（MODE=new，2026-09-02）
- 决策权威：`design/final-design/总设计文档.md`（v2.0，2026-09-02 起生效，仓库唯一 SSOT）
- 分类说明：本次 ingest 集内**无 ADR 类型文档**。SSOT 按 manifest 归类为 DOC（precedence 0），但按仓库约定（CLAUDE.md + 总文档 §29/附录 C）与 orchestrator 指令，其设计决策按 **locked（SSOT 权威）** 登记。分类 JSON 中的 `locked:false` 是类型级默认标记，不降低其权威。
- 去重说明：模块一~四为 SSOT 分块摘录（precedence 1），与 SSOT 重叠的内容一律以 SSOT 为准提取，**不重复登记、不构成 competing variants**。
- 状态语义：locked = 任何其他来源（含上游需求文档/技术方案概述）不得自动覆盖；修改须先更新 SSOT 正文 + §14 变更日志，且须用户明确授权（agent 仅可起草）。

---

### D-001 SSOT 文档治理
- Status: locked（SSOT authority）
- Source: design/final-design/总设计文档.md（文档头部、§29、附录 C）
- Scope: 全仓库文档治理
- Decision: `design/final-design/总设计文档.md`（v2.0）为全仓库唯一 SSOT；取代 2026-08-30 版（已入历史档案）。其余文档只有三种身份：从属模块稿（final-design/ 分模块摘录）/ 临时讨论稿（design/ 临时讨论稿-*）/ 历史档案。任何设计变更、范围调整、接口改动，先更新 SSOT（正文 + §14 变更日志），再动代码。变更日志条目格式：日期 / 变更内容 / 原因 / 影响面。

### D-002 系统范围边界（不做录用判断）
- Status: locked
- Source: design/final-design/总设计文档.md §2
- Scope: 全系统（界面/报告文案/Prompt 均受约束）
- Decision: 系统只做：人才画像报告、各能力项评分与证据展示、测评过程状态异常记录、必要的人工复核支持。系统**不做**：最终录用判断、录用排序、自动通过/淘汰、代替企业作招聘决定。任何界面、报告文案、Prompt 不得出现"录用结论""排名"表述；qualification gate 只表达"资格事实核验结果"，报告警告只表达"测量完整性/资格信息提示"。

### D-003 四条强约束
- Status: locked（全系统不可谈判）
- Source: design/final-design/总设计文档.md §3
- Scope: 全系统
- Decision:
  1. **LLM 不碰数字**：权重、分数算术、配额、题量、聚合、补算全部由代码计算；
  2. **人工是唯一权威**：confirmed 模型不被静默覆盖；评分可异议但绝不自动改分；报告发布必须人工明确点击；
  3. **一切留痕**：每道工序中间产物落库；每次 LLM 调用 trace 落库；答案原文不可变归档；状态事件 append-only；
  4. **代码是唯一状态机**：难度升降、追问上限、题量、finish、工具授权等关键迁移全部由代码执行；LLM 只提供结构化观察与建议。

### D-004 有界测评循环（不做自由 ReAct）
- Status: locked
- Source: design/final-design/总设计文档.md §4
- Scope: 模块二运行时
- Decision: 每轮执行 Observation → Policy/Plan → Act → Evaluation → Persist。LLM 可参与回答状态分类与证据观察（结构化输出，代码裁决）；代码依据状态/配额/难度护栏/题量裁决下一步。LLM 永远不能决定：题量、追问上限、finish、难度最终迁移、权重、综合题数量、最终分数、报告发布。

### D-005 技术栈与部署形态（演示上线）
- Status: locked
- Source: design/final-design/总设计文档.md §5
- Scope: 全系统
- Decision: Python 3.11+ / FastAPI / Uvicorn 单进程；`openai` SDK（base_url 可切 DeepSeek 等 OpenAI 兼容端点），JSON 模式 + 内部 function-call 式 adapter；SQLite 单文件，DDL + 迁移内嵌 `server/db.py`，含 schema_version 演进；JWT HS256（python-jose）+ passlib[bcrypt]，单一 secret，HttpOnly/SameSite cookie；Vue 3 + Vite + Element Plus + Vue Router + Pinia + axios + ECharts；vite build 产物由 FastAPI 挂静态文件。本期目标为**演示上线**：单机、单实例、单进程；接受 BackgroundTasks 内存执行，不要求进程重启后任务恢复。迁移/回滚/备份恢复需开发但不作为本期上线硬门槛。mock 模式离线可跑通全流程。

### D-006 类目权重 7:3 + gate 不占权重池
- Status: locked（v2.0 关键修正，取代旧 55/20/20/5）
- Source: design/final-design/总设计文档.md §8.2、§30 N1
- Scope: 模块一聚合、模块三聚合
- Decision: 评分类目比例 hard_skill : soft_skill = 0.70 : 0.30（Σ 各大类 item.weight 分别 = 0.70 / 0.30）；experience/qualification 走表单/简历事实采集，**不占类目权重池**，gate 二值判定。若某大类无有效能力项，现有大类归一到 1.00；若大类有 item 但无合法题库 → 阻止开考，不静默转移权重。类内第二层按 importance 系数（required 1.0 / preferred 0.6 / plus 0.3）分摊，合成结果存 `competency_item.weight`（Σ=1，尾差由权重最大项吸收）。模块三算总分直接复用 item.weight，不再二次乘大类比例。

### D-007 tier 语义（不乘最终分数）
- Status: locked（v2.0 确认）
- Source: design/final-design/总设计文档.md §8.2
- Scope: 权重/配额/评分
- Decision: required/preferred/plus 只影响原始重要性、题量配额和覆盖优先级；**不再额外乘最终分数**。

### D-008 题量配额公式（岗位级 N）
- Status: locked
- Source: design/final-design/总设计文档.md §10.1–10.3
- Scope: 模块二选题
- Decision: 普通题计划数 N 由管理员在岗位测评策略中配置（不设全局上下限，默认值实施期结合 40 分钟体验测定）。大类按最大余数法分配 0.7N/0.3N（小数部分相等时归 hard_skill）。类内以各大类实际题量为总体：`required_target = ceil(quota×0.8/1.7)`、`preferred_target = ceil(quota×0.6/1.7)`、`plus_target = quota − required − preferred`；实际分配优先级 required > preferred > plus，取整不得突破该大类总量。综合题不占 N；required 例外不改变 item.weight；followup 单独统计不计主问题。

### D-009 动态实例化与四层选题
- Status: locked（取代一次性预选题）
- Source: design/final-design/总设计文档.md §10.6、§11.1、§30 N5
- Scope: 模块二选题与实例
- Decision: 每个实际呈现的不同题面创建新 `assessment_question` 实例（方案 A）；followup 是实例内部子轮次（question_id 不变、不建实例、不增主问题数、不占综合槽位、每题最多 2 次，config 硬约束）。选题由代码按四层执行（可审计）：① 合法性过滤（版本/阶段/未用实例/当前题已封存/路径合法）② 硬约束（未覆盖 required 优先）③ 配额（category/tier 剩余）④ 排序（chain 后继条件满足才继续、可让位 required → item.weight → 题目质量 → 稳定随机种子）。LLM 只做题面岗位化/口语化轻包装；chain 不能挤掉 required、不能改题量槽位、不能绕过难度护栏。

### D-010 难度路径状态机
- Status: locked
- Source: design/final-design/总设计文档.md §11.2
- Scope: 模块二难度导航
- Decision: easy→medium 需一次充分证据；medium→hard 需充分且稳定证据，hard 仅对 target_level > 4 的 item 开放。降级仅统计有效候选人证据失败（跳过；同 item 同难度连续两道有效题未达最低锚点；followup 后仍模糊/错误/不足；非最低难度才可降）。恢复采用滞回原则：连续两次充分证据或一次稳定证据。一次实例内不升降级；路径变更由封存后的下一实例承载；不设 item 级路径振荡次数上限。不计入普通失败：技术故障、无障碍、题目无效、模型不确定、合理流程质疑、明确拒答、攻击性事件、单纯紧张/停顿/表达风格。跳级默认禁止运行时静默进行，仅模型/rubric 明确配置允许且报告记录实际路径才可，否则 PATH_UNAVAILABLE → 人工/不完整。

### D-011 难度与 1–5 等级映射
- Status: locked（v2.0 最终确认）
- Source: design/final-design/总设计文档.md §9.4、§30 N6
- Scope: 题库/评分
- Decision: easy max=3/min=2、medium max=4/min=3、hard max=5/min=4（锚点区间 [2,3]/[3,4]/[4,5]）。达到最低锚点在区间内评分；有效作答但低于最低锚点支撑**等级 1**；未形成有效观察（拒答、缺证据、题目无效、系统错误、模型不确定）不产生能力等级证据。rubric 可将单题上限配低，不可超过所属难度默认上限；等级 5 只能由 hard 题 5 级锚点、证据完整且稳定的测量支撑。required_level 只用于难度路径决策与报告达标比较（gap=required−actual），不改变 item.weight、不改变评分；**难度不构成最终分数第三层权重**。

### D-012 score_live 仅导航
- Status: locked（旧版 50/50 合成作废）
- Source: design/final-design/总设计文档.md §17、§30 N2
- Scope: 模块二/模块三评分
- Decision: score_live 只用于过程性选题与难度导航，不参与最终分数；与 score_final 的差值仅用于偏差分析与 bad case 候选，不写回分数。终局评分 score_final（P-score，temperature≈0，回捞原文）为独立逐题评分。

### D-013 拒答 REFUSED=0（特殊状态值）
- Status: locked
- Source: design/final-design/总设计文档.md §18、§30 N8
- Scope: 模块三评分聚合
- Decision: `score_value = 0`、`score_state = REFUSED`；0 是特殊状态值，不是能力量表 1 分。拒答只进入行为聚合与完整度聚合，不进入能力等级聚合；item 最终等级由有效能力证据决定。拒答事件永久保留，报告单独展示拒答次数与位置；可能涉及受保护信息或合法隐私质疑的拒答 → 合规/人工处理边界，不直接记 0。

### D-014 item 内合并与综合题裁决
- Status: locked
- Source: design/final-design/总设计文档.md §19
- Scope: 模块三裁决
- Decision: 普通题与综合题先转为统一测量记录 `item_measurement(question_id, item_id, observed_level, evidence_refs, measurement_source)`，`item_final_level = adjudicate(ordinary + integrated)`。普通最低测量资格先检查（综合题不能替代）；按 rubric/覆盖/稳定性/冲突裁决，**不按来源加权、不按题数重复乘 item.weight**；共享 evidence span 只影响证据解释、不折扣不自动复制；重大冲突取较低值并留人工复核标记。综合题可作为最高等级证据来源（仍受其 rubric 约束）；综合题整体 ITEM_INVALID → 所有绑定 item 综合结果无效、移出分母。

### D-015 缺失补算 IMPUTED
- Status: locked
- Source: design/final-design/总设计文档.md §20
- Scope: 模块三聚合
- Decision: O = 全部 score_state=SCORED 的 item 级测量；r = Σ(i∈O) w_i×s_i / Σ(i∈O) w_i（s_i = (score−1)/4）；缺失普通 item 补算值 = r，标记 IMPUTED。O=∅ → 不能补算 → NO_VALID_OBSERVATION / HUMAN_REVIEW_REQUIRED。required 与 qualification 不适用比例补算。IMPUTED 参与总分与雷达但必须特殊视觉标记 + 展示观察覆盖率/真实观察数/缺失原因；补算比例超阈值 → 临时报告 + 人工复核。required 缺失 → report_status=PROVISIONAL、review_status=HUMAN_REVIEW_REQUIRED，不触发补测；人工确认后可发布正式报告，必须明确点击发布。

### D-016 required 刚性例外
- Status: locked
- Source: design/final-design/总设计文档.md §10.5
- Scope: 模块二选题
- Decision: 普通计划结束后检查 required 覆盖；未获有效普通测量的 required item：同一 item 最多一次例外、新增一条普通主问题（计入 E）；例外题只允许 medium，无 medium 选 hard（不走 easy 起始）；不使用综合题；例外仍受题库版本、session 状态、计时约束；耗尽后 item 状态 REQUIRED_UNMEASURED → 带警告临时报告 + 人工复核。

### D-017 开考前可测量性检查
- Status: locked
- Source: design/final-design/总设计文档.md §10.4
- Scope: session 创建
- Decision: confirmed model → question bank readiness → quota feasibility → form schema readiness → session 可创建。检查项：position active；模型 confirmed；题库绑定当前 model/version 且已生成完成；每个有效 required item 至少一条合法普通题；hard/soft 配额可满足（有 item 但题库不足 → 不允许转移名额，阻止开考）；综合题槽位有合法题（若 I>0）；qualification 表单 schema 可用。不通过返回明确状态 QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE，产生管理员待办，不创建 0 题 session。

### D-018 全局 21 张表 + 三新表
- Status: locked
- Source: design/final-design/总设计文档.md §6、§30 N3
- Scope: 数据库 schema
- Decision: 18 现有 + 3 新增 = 21 张：模块一（8）user/position/position_alias/jd_record/competency_model/competency_item/competency_dict/llm_trace；模块二（7+2）assessment_session/question_bank/assessment_question/assessment_message/context_raw/form_submission/question_score + 新增 assessment_state_event/form_instance；模块三（2）report/feedback；模块四（1）eval_results；公共新增（1）trace_link。题目属于岗位 + confirmed 模型版本；模型升版必须生成/绑定新题库，否则阻止开考；新表避免不可 ALTER 的 CHECK，枚举用代码校验。

### D-019 状态事件 append-only
- Status: locked
- Source: design/final-design/总设计文档.md §13.1–13.2
- Scope: 事件体系
- Decision: assessment_state_event 禁止 UPDATE/DELETE，纠错走补偿事件；状态迁移事件必填 from/to；当前快照列与事件同事务更新；LLM 调用不持有长事务。正常业务读快照列；回放（按 sequence_no 重放迁移事件）仅用于审计/恢复/修复/测试，与快照不一致时标记并进人工，不静默覆盖。事件枚举按 SESSION/QUESTION/MESSAGE/OBSERVATION/CONTROL/FORM/GATE/POLICY/TOOL/TASK/REVIEW 分组，定稿时每个事件注明：必填字段/是否迁移/是否计题量/是否计时/是否需人工。

### D-020 trace_link 统一审计链
- Status: locked
- Source: design/final-design/总设计文档.md §13.3、§22
- Scope: 审计
- Decision: 业务表不逐一加 trace 外键；report→session→model/version→question→message→score→trace 审计链通过 trace_link（link_role: input/output/caused_by/scored/reported/source）闭合，UNIQUE(trace_id, entity_type, entity_id, link_role)。

### D-021 真实 SSE + 内部 adapter + 幂等
- Status: locked（v2.0 确认）
- Source: design/final-design/总设计文档.md §11.5、§13.4、§30 N9
- Scope: 对话传输
- Decision: 决策阶段非流式（内部 function-call adapter 返回结构化 {action, reason, assessment}，**先落库再展示**）；话术阶段真实 SSE 逐 token 推送；finish 仅由代码规则触发（题量完成/全场超时），模型不自主结束。SSE 定义事件类型、顺序、错误与结束事件；本期不要求事件 ID/cursor 断线续传（留扩展记录）。LLM 输出全部走严格 Pydantic schema 校验，非法输出进失败/人工状态，不得卡死会话。幂等作用域 `session_id + endpoint + idempotency_key`；答题另带 question_instance_id / expected_question_revision / client_attempt_id；重复请求返回第一次持久化结果，不重复写消息/计 followup/扣题量/启任务；数据库事务 + 乐观版本号防并发双写；幂等记录长期保存，达阈值提醒清理，留管理员清理接口。

### D-022 计时与 ABANDONED
- Status: locked
- Source: design/final-design/总设计文档.md §15、§30 N7
- Scope: 计时/恢复
- Decision: 全场 40 分钟（候选人确认开始且首题成功激活起算）；单题 20 分钟（题目激活并发送起算，followup 共用同一单题计时器）。服务端权威：session_time_interval(active|paused, reason, started/ended_at_server)，active_elapsed = Σ active 区间；客户端只展示。所有暂停类型（候选人请求/技术故障/无障碍便利/管理）均不计入 40 分钟且必须写事件；敏感便利信息不进评分 Prompt。短暂断线不自动暂停；仅显式 pause 或技术状态产生 paused 区间。无活动 6 小时 → ABANDONED，本期不可恢复（可恢复仅留记录不细化不留接口），检测 = 惰性判断 + 单进程周期扫描，不删证据。单题超时封存（seal_reason=timeout）继续下一题；全场超时停止新增主问题进收尾评分。时间不参与题目筛选优先级。

### D-023 表单生命周期与 gate
- Status: locked
- Source: design/final-design/总设计文档.md §16.1–16.2
- Scope: 资格核验
- Decision: form_instance 为生命周期实体：schema 由代码定义 + 版本化，instance 创建时存不可变 schema 快照；render_form 由代码在资格核验阶段触发（LLM 只能请求）；GET /forms/{id} 候选人只读已激活 instance，不暴露内部阈值；submit_form 服务端校验所有权、session 状态、类型/必填/枚举/长度，重复提交返回第一次结果，修订走不可变 revision。gate 由代码计算，独立结构化结果（gate_result/gate_status/gate_reason/evaluated_schema_version/evaluated_at）；人工覆盖存 automated_gate_result + human_override + override_reason + reviewer_id，需**二次人工确认**。extract_form_facts 输出 fact_type/normalized_value/source_document/source_span/confidence/status（EXTRACTED/UNCERTAIN/CONFLICTING/CANDIDATE_CONFIRMED/HUMAN_REVIEW_REQUIRED）；与候选人结构化填写冲突时保留两者进人工确认；gate 只接受候选人确认或人工确认后的事实。

### D-024 Tools 总边界
- Status: locked
- Source: design/final-design/总设计文档.md §16.3
- Scope: 工具调用
- Decision: 阶段白名单 + 严格输入输出 schema + 所有权校验 + 幂等/超时/次数/长度控制 + 调用留痕；工具返回内容是数据不是指令；LLM 提议后代码二次验证；**工具失败 → 暂停并人工接管**。正式测评不做 Web Search；request_pause 候选人可直接触发、LLM 只能建议。所有 LLM 输出严格 schema 校验。

### D-025 报告五段式与发布契约
- Status: locked
- Source: design/final-design/总设计文档.md §21、§21.1
- Scope: 模块三报告
- Decision: 报告五段：①总分+门槛标签 ②雷达图（required 灰 vs actual 蓝，IMPUTED 特殊标记）③逐项明细（gap 着色、理由、逐行异议）④优势/短板/建议（代码排序：优势=gap≥0 中权重前 3；短板=gap<0 中 |gap|×weight 前 3；LLM 只写文字且只能基于给定短板项）⑤逐题回顾（score_final + 证据 quote + 来源定位）。report_status: GENERATING → PROVISIONAL | READY → PUBLISHED | FAILED；review_status: NONE | REQUIRED | IN_PROGRESS | CONFIRMED | CLOSED。发布前一致性校验（代码，七项）；评分完成 → 聚合与校验 → 生成 → 有人工复核要求则等待 → 管理员复核后**明确点击发布** → PUBLISHED。人工复核字段：review_request_reason/reviewer_id/review_note/review_outcome/reviewed_at/publish_confirmed_by/published_at。报告生成不隐式代替评分；正常 UI 主链必须 score→report 串行（服务端执行，不依赖浏览器补调）。

### D-026 权限模型（P0 上线阻断项）
- Status: locked
- Source: design/final-design/总设计文档.md §7、§28
- Scope: 全部候选人资源接口
- Decision: 全部候选人资源接口（session/report/form/feedback）必须做资源级所有权校验（WHERE resource.user_id = current_user.id），不能只查 ID 存在；candidate 只能访问本人资源；admin 为最高权限（本期不分级），可读取候选人数据与完整 trace；角色限制必须在后端执行，不能依赖前端 route guard；测评入口统一要求 position active + 模型 confirmed；越权测试矩阵（candidate↔candidate 读写、admin 边界）为上线阻断测试。

### D-027 评测契约（b/c + bad case + 隔离）
- Status: locked
- Source: design/final-design/总设计文档.md §22–23
- Scope: 模块四评测
- Decision: 一致性测试（b）：固定 transcript 复跑，断言 score_final 分差 ≤1（temperature=0；固定 model/provider/版本/rubric 快照）；score_live 不在断言范围。虚拟考生测试（c）：强/中/弱三档端到端，断言总分排序（强>中>弱）+ 短板定位符合预设 + required 覆盖 + 拒答/缺失状态 + 证据引用 + 报告状态。自动 bad case：score_live 与 score_final 可比且差值 ≥ 配置阈值 → 创建候选（排除题目无效/模型不确定/系统错误/不可比状态），管理员审核，不自动改分。eval 必须使用独立/临时数据库，不污染业务库；mock 回归不能替代真实 LLM 质量验证。黄金集（模块一）本期推迟。

### D-028 里程碑四维口径
- Status: locked（口径约定）
- Source: design/final-design/总设计文档.md §27、§30 N12
- Scope: 项目管理
- Decision: 每个里程碑记录 implemented（已有代码）/ contract_complete（满足本文契约）/ verified（通过测试验收）/ production_ready（满足上线要求）。当前 M1–M3 大体 implemented + verified 不足；M5–M7 主体 implemented、contract_complete=false、verified=false。

### D-029 M4 范围保留不做
- Status: locked（本期范围决策）
- Source: design/final-design/总设计文档.md 附录 B、§23
- Scope: 项目范围
- Decision: 本期保留不做：黄金集（真实数据收集后另行排期，不作为本期验收项）、浏览器插件、真实 JD 数据集。

### D-030 Prompt 模块接口化登记
- Status: locked（登记扩展点，内容后置）
- Source: design/final-design/总设计文档.md §26、附录 A
- Scope: 全部 LLM 调用位置
- Decision: 所有未来需要 LLM 的位置必须保留可替换接口（classifier/observation/evidence-evaluator/probe/scaffold/integrated-scorer/report-writer 等）或稳定设计记录（Prompt ID/调用阶段/输入输出 schema/允许与禁止影响范围/版本与 trace/启用条件）；接口可注入：Prompt 版本、模型标识、schema、trace 关联、重试策略、人工接管、mock 切换。**任何 Prompt 不得**：把 followup 输出成主问题；把综合题当普通第四级；因绑定多 item 自动完成测量；自由增加综合题数量；绕过普通最低测量；改动 7:3/配额/item.weight/状态机/聚合公式/报告发布条件。

### D-031 安全、公平与数据治理
- Status: locked
- Source: design/final-design/总设计文档.md §25
- Scope: 全系统
- Decision: JWT 单一 secret，生产缺失/默认值时启动校验（不列上线硬门槛，保留增强记录）；服务端统一密码规则；HttpOnly cookie 方向。trace/JD/原文按数据分级管理，管理员可读全文并留访问审计（REVIEW_ACCESSED 事件）；保留期、脱敏、导出、删除策略与第三方 LLM 供应商约束实施期细化。输入限额按类型配置（文件大小/行数/JD/回答长度/LLM prompt/max_tokens/分页上限）。Prompt injection：候选人输入与工具返回永远是数据，INJECTION_DETECTED 事件留痕。公平性：不按口音/停顿/打字速度/语气/"不自信"推断能力；公平性离线评估本期不做（仅留记录）。异议只进人工处理与质量数据，永不触发改分。
