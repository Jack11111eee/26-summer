# Roadmap: AI 胜任力测评与人才画像系统（TP）

## Overview

本路线图把现有代码基线（M1–M7 大体 implemented、contract_complete=false）重构演进到 SSOT v2.0 契约。阶段顺序唯一权威：SSOT §28 六步实施顺序（P0 四项先行 → 动态选题/有界循环 → 表单/SSE/幂等/计时 → 题库版本绑定 → 证据链/报告契约 → 迁移与测试闭环收口）。每阶段携带自身表结构演进的内嵌迁移（演进随阶段走），最后阶段收口 schema_version 登记簿。文件级证据：`research/ssot-code-gap-matrix.md`；契约级需求：`.planning/REQUIREMENTS.md` REF-* 条目。

**实施红线（贯穿所有阶段）：** 重构演进不重写；LLM 不碰数字 / 人工唯一权威 / 一切留痕 / 代码唯一状态机（D-003）；先改 SSOT 再动代码（D-001）；开放参数排"校准"不臆造（SSOT §31）。

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: P0 安全与主链修复** - 所有权校验 / score→report 串行 / 开考检查 / 状态事件表 + 附带护栏
- [ ] **Phase 2: 动态选题与有界循环** - 四层选题 / 难度状态机 / 回答状态分类 / 评分链 50-50 废除 / 7:3 权重口径
- [ ] **Phase 3: 表单/SSE/幂等/计时** - 表单实例链 / 真实 SSE / 幂等并发 / 计时区间 / 上下文三层
- [ ] **Phase 4: 题库版本绑定与模块一收口** - model/version 绑定 / 生成失败可见 / orphan 路由 / 模型编辑校验
- [ ] **Phase 5: 证据链与报告契约** - 证据 span + trace_link / 报告状态机与发布 / item 裁决与补算 / feedback 补全
- [ ] **Phase 6: 迁移体系与测试闭环收口** - schema_version 收口 / pytest 统一 + CI / M1 回归 / E2E / eval 隔离 / bad case

## Phase Details

### Phase 1: P0 安全与主链修复

**Goal**: 候选人资源不可越权访问，正常 UI 主链（作答完成→评分→报告）真实可用且全程事件留痕，不可创建空测评会话
**Depends on**: Nothing (first phase)
**Requirements**: REF-1.1, REF-1.2, REF-1.5, REF-2.2, REF-3.5, REF-5.10, REF-8.2, REF-8.5（支撑 REQ-interactive-multiturn-assessment / REQ-talent-profile-report 主链）
**Success Criteria** (what must be TRUE):

  1. 候选人 A 无法读写候选人 B 的 session/report/form/feedback（接口层 `WHERE user_id=current` 兜底；越权返回 403/404），admin 可访问且可查完整 trace——越权测试矩阵（candidate↔candidate 读写、admin 边界）通过
  2. 候选人在 UI 正常完成测评后直接进入报告页，报告含真实逐题评分与雷达数据（服务端 score→report 串行，不再出现 no_data 空聚合）
  3. 题库未就绪/模型不可测量时创建 session 返回明确状态（QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE）并产生管理员待办，绝不创建 0 题会话
  4. assessment_state_event 表落地且 append-only：session/question 等关键状态迁移均写事件（from/to 必填），纠错走补偿事件，直接 UPDATE/DELETE 被测试证明拒绝
  5. completed 会话再调 POST /score、/report 被状态护栏拒绝（不再可重复评分/报告）

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 01-01-PLAN.md — 候选人资源所有权校验（load_owned_session/load_owned_report 8 路由 + 404 语义 + admin 只读）+ 越权测试矩阵 + route guard 修复（D-01~D-04）

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 01-02-PLAN.md — assessment_state_event 表落地（触发器 append-only + append_event）+ create_session/submit_answer 迁移点接入（D-05~D-07）

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 01-03-PLAN.md — score→report 服务端串行（request_report 入口链方案 B + allow_completed 豁免）+ completed 护栏 + 回归断言重写（D-08~D-10）

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 01-04-PLAN.md — question_bank_task 表 + check_session_readiness 三态 409 + todos 扩展 + PositionAssess.vue 提示（D-11~D-13）

### Phase 2: 动态选题与有界循环

**Goal**: 测评运行时按 SSOT §10/§11 运转——每题动态实例化、四层代码选题、难度路径状态机导航、回答状态分类驱动处理原则，评分链废除 score_live 50/50 合成、权重对齐 7:3
**Depends on**: Phase 1
**Requirements**: REF-1.3, REF-1.6, REF-1.7, REF-2.7, REF-2.9, REF-3.1, REF-3.2, REF-3.6, REF-3.7, REF-4.1, REF-4.2, REF-4.3, REF-4.4, REF-4.5, REF-5.1, REF-5.2, REF-5.3, REF-5.7, REF-8.1（支撑 REQ-dynamic-question-generation / REQ-interactive-multiturn-assessment）
**Success Criteria** (what must be TRUE):

  1. 会话创建不再一次性预选全部题目；每次 action=next 时按四层选题（合法性过滤→required 硬约束→配额→排序）即时选出下一题，选题理由可审计（selection_reason 落库）
  2. 题量配额按岗位级 N + 7:3 最大余数 + tier 公式（0.8/0.6/1.7）计算，旧固定 CATEGORY_QUOTA{hard:6,soft:2,exp:2} 废除；experience/qualification 不再出现在普通题选题里
  3. 难度升降/恢复由代码状态机执行并写事件（DIFFICULTY_RAISED/LOWERED/RESTORED）：easy→medium 一次充分证据、medium→hard 充分且稳定、降级按有效证据失败、滞回恢复、跳级默认禁止；同实例内不升降级
  4. LLM 面试官输出结构化观察（answer_state 分类 11 态 + 证据维度），代码裁决下一步；拒答经一次确认后跳过且记 REFUSED（score_value=0 不进能力等级分母）；followup ≤2 次由代码硬约束
  5. score_live 只用于导航不进最终分；聚合不再有 50/50 合成的 final_score；客观题 answer_key 为空判题库无效而非满分；权重口径为 7:3（config 旧 55/20/20/5 作废）

**Plans**: TBD

Plans:

- [ ] 02-01: 表结构演进内嵌迁移（assessment_question 实例列 / question_score 统一 score_final / observable_level 锚点列）+ 权重口径 7:3 修正（config/aggregate/aggregation）
- [ ] 02-02: 四层动态选题服务替换一次性预选（岗位级 N + 7:3 + tier 公式 + required 例外）
- [ ] 02-03: 难度路径状态机（升/降/滞回/跳级禁止 + 事件写入）
- [ ] 02-04: 回答状态分类重构（interviewer 两层化：结构化观察 + 代码裁决；拒答 REFUSED；evidence_sufficient/stable_evidence 布尔裁决）
- [ ] 02-05: 评分链契约修正（50/50 废除、score_live 仅导航、answer_key 空判题库无效、score_state 分母规则）

### Phase 3: 表单/SSE/幂等/计时

**Goal**: 资格核验表单成为真实可用链路（schema 版本化实例 + gate 结构化结果），对话话术真实流式推送，重复请求幂等返回首次结果，全场/单题计时按服务端权威区间运转
**Depends on**: Phase 2
**Requirements**: REF-2.4, REF-2.6, REF-2.8, REF-3.3, REF-4.6, REF-4.7, REF-4.8, REF-4.9, REF-4.10, REF-4.12, REF-6.4（支撑 REQ-interactive-multiturn-assessment / REQ-data-compliance）
**Success Criteria** (what must be TRUE):

  1. 候选人在对话中收到代码触发的资格核验表单（form_instance 生命周期实体：不可变 schema 快照、GET 只读已激活实例不暴露内部阈值），提交经服务端校验（所有权/状态/类型/必填/枚举/长度），重复提交返回第一次结果
  2. gate 由代码计算并输出独立结构化结果（gate_result/gate_status/gate_reason），gate 判定不再从自由 payload 猜测；人工覆盖字段就位且需二次确认
  3. 答题话术以真实 SSE 逐 token 推送（决策阶段非流式先落库再展示；finish 仅代码触发）；前端 sse.js 双形态自适应走流式形态；非法 LLM 输出进失败/人工状态不卡死会话
  4. 携 idempotency_key 的重复答题/表单请求返回第一次持久化结果，不重复写消息/计 followup/扣题量；并发双写由事务 + 乐观版本号防护
  5. 计时按服务端权威区间运转：全场 40 分钟（确认开始且首题激活起算）、单题 20 分钟（followup 共用），暂停（候选人/技术/无障碍/管理）不计入且写事件，单题超时封存继续下一题，全场超时进收尾评分；6h 无活动会话 ABANDONED（本期不可恢复，不删证据）

**Plans**: TBD
**UI hint**: yes

Plans:

- [ ] 03-01: form_instance + form schema 版本化 + render_form 代码触发 + GET /forms/{id} + gate 结构化结果（experience/qualification 出题库改走表单）
- [ ] 03-02: 真实 SSE 端点（话术流式 + 决策非流式先落库）+ 请求/输出 Pydantic schema
- [ ] 03-03: 幂等协议落地（session_id+endpoint+idempotency_key 作用域、答题三键、事务+乐观版本号、重复返回首次结果）
- [ ] 03-04: 计时区间（session_time_intervals、active_elapsed、单题超时封存、全场超时收尾、6h ABANDONED 惰性判断+周期扫描）+ 消息 raw/refined 分列 + 上下文三层（滑窗/导航摘要）
- [ ] 03-05: INJECTION_DETECTED 事件留痕（候选人输入与工具返回永远是数据）

### Phase 4: 题库版本绑定与模块一收口

**Goal**: 题库与 confirmed 模型版本强绑定（升版须重建题库否则阻止开考），题库生成失败对管理员可见；模块一管理端已知缺陷修复（orphan 路由、模型编辑校验）
**Depends on**: Phase 3
**Requirements**: REF-2.5, REF-3.4, REF-7.1, REF-7.2, REF-8.4（支撑 REQ-jd-parse-model / REQ-dynamic-question-generation）
**Success Criteria** (what must be TRUE):

  1. question_bank 行携带 model_id/model_version（绑定岗位 + confirmed 模型版本）；模型升版后旧题库不再对新会话生效，未生成新题库时开考被阻止（联动 Phase 1 开考检查）
  2. 题库生成失败不再静默 pass：失败在题库状态与管理员待办中可见（失败状态 + 明确错误信息）
  3. 管理员访问 /jds/orphan 返回孤儿 JD 列表（当前被 /jds/{jd_id} 参数路由捕获恒 404 的缺陷修复）
  4. 管理员编辑模型提交 NaN 权重/越界类别/重复 std_name 被服务端拒绝并返回明确错误（保留 Σ=100% 校验）

**Plans**: TBD

Plans:

- [ ] 04-01: question_bank 绑定 model/version + 升版重建/阻止开考联动 + 生成失败可见（状态+管理员待办）
- [ ] 04-02: /jds/orphan 路由顺序修复 + 模型编辑字段级校验（NaN/范围/类别/重复）

### Phase 5: 证据链与报告契约

**Goal**: 全链审计链通过 trace_link 闭合、证据引用结构化可定位；报告发布走完整状态机（人工明确点击发布 + 七项一致性校验 + 版本化），反馈异议带完整审计字段
**Depends on**: Phase 4
**Requirements**: REF-2.3, REF-2.10, REF-5.4, REF-5.5, REF-5.6, REF-5.9, REF-7.3, REF-8.3, REF-8.7（支撑 REQ-talent-profile-report / REQ-iterative-loop）
**Success Criteria** (what must be TRUE):

  1. 每个证据引用结构化可定位：source_message_id / start_offset / end_offset（Unicode code point）/ quote_hash；终局评分回捞原文；trace_link 闭合 report→session→model/version→question→message→score→trace 审计链，旧 ref_id 关联导入
  2. item 最终等级由统一测量记录裁决（adjudicate 普通题 + 不按题数均分、冲突取低留人工标记）；缺失 item 按观察加权比例 r 补算并标 IMPUTED（特殊视觉标记 + 覆盖率展示）；无有效观察 → NO_VALID_OBSERVATION/HUMAN_REVIEW_REQUIRED；required 缺失 → 报告 PROVISIONAL + HUMAN_REVIEW_REQUIRED
  3. 报告发布契约完整运转：GENERATING → PROVISIONAL|READY → PUBLISHED|FAILED 状态机；发布前七项一致性校验由代码执行；管理员必须明确点击发布才 PUBLISHED；重复生成不再 DELETE 覆盖（报告不可变版本化）
  4. 报告生成失败显式可见（FAILED 状态 + 前端可区分"生成中/失败"，不再静默 pass）
  5. 候选人异议带完整字段（user_id/note/reviewer/时间戳），submit_feedback 校验 item 属于该报告对应模型，admin review note 不再被丢弃

**Plans**: TBD
**UI hint**: yes

Plans:

- [ ] 05-01: 证据 span 结构化 + hash 复用限单 session + trace_link 表与审计链闭合（旧 ref_id 导入）
- [ ] 05-02: item_measurement 统一裁决 + IMPUTED 补算 + required 缺失 PROVISIONAL/人工复核标记
- [ ] 05-03: 报告状态机 + 七项发布校验 + 报告版本化（不可变版本，防 feedback 外键断裂）+ 失败显式可见
- [ ] 05-04: feedback/question_reviews 字段补全 + item 归属校验

### Phase 6: 迁移体系与测试闭环收口

**Goal**: schema_version 迁移登记簿收口全部演进；测试统一 pytest 收集 + CI 为验收入口；M1 回归、候选人 E2E、评测契约（b/c + bad case + eval 隔离）全部兑现——项目达到"端到端可演示 + 全链可审计"验收态
**Depends on**: Phase 5
**Requirements**: REF-2.1, REF-2.11, REF-5.11, REF-6.1, REF-6.2, REF-6.3, REF-7.4, REF-7.5, REF-7.6, REF-8.6, REF-8.8（支撑 REQ-data-compliance / REQ-e2e-demo-deliverables / REQ-iterative-loop / REQ-jd-parse-model 回归验收）
**Success Criteria** (what must be TRUE):

  1. schema_version 迁移体系落地：各阶段内嵌迁移收口进登记簿，迁移可在临时库重放验证（替换 DDL 字符串嗅探），备份/回滚路径开发且迁移测试通过
  2. 全部后端测试 pytest 可统一收集（脚本式测试重构），CI 配置存在且为正式验收入口（基线红灯：question_bank pytest 3 errors 消除）
  3. M1 回归清单通过：清洗边界、抽取 schema 异常、消歧、权重尾差 Σ=1、等级冲突 stalled、confirmed 不可静默覆盖、版本 diff、管理员权限
  4. 候选人端完整 E2E 通过：注册→选岗→session→作答/追问→表单→完成→评分→报告→异议，含刷新恢复、断线重试、越权、超时（M5–M7 verified 必要条件）
  5. 评测契约兑现：b 一致性（固定 transcript 复跑 score_final 分差 ≤1）、c 虚拟考生（强>中>弱 + 短板定位 + required 覆盖 + 拒答/缺失状态 + 证据引用 + 报告状态）、bad case 双分背离自动候选（管理员审核不自动改分）、eval 独立/临时数据库不污染业务库

**Plans**: TBD

Plans:

- [ ] 06-01: schema_version 迁移登记簿收口（各阶段内嵌迁移归档 + 迁移测试 + 备份/回滚）
- [ ] 06-02: 测试统一 pytest 收集 + CI 配置 + 越权/幂等/计时/SSE/迁移必测项
- [ ] 06-03: M1 回归清单（模块一八项）+ mock interviewer 评分恒 3 分问题处理
- [ ] 06-04: 候选人端完整 E2E（主链 + 刷新恢复/断线重试/越权/超时）
- [ ] 06-05: eval 隔离（独立/临时数据库）+ b/c 评测契约 + bad case 自动候选 + 输入限额/secret 启动校验/HttpOnly cookie 方向决策等安全收尾项

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. P0 安全与主链修复 | 1/4 | In Progress|  |
| 2. 动态选题与有界循环 | 0/5 | Not started | - |
| 3. 表单/SSE/幂等/计时 | 0/5 | Not started | - |
| 4. 题库版本绑定与模块一收口 | 0/2 | Not started | - |
| 5. 证据链与报告契约 | 0/4 | Not started | - |
| 6. 迁移体系与测试闭环收口 | 0/5 | Not started | - |
