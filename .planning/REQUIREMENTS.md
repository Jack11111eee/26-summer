# Requirements: AI 胜任力测评与人才画像系统（TP）

**Defined:** 2026-09-02
**Core Value:** 端到端可演示（JD 解析→测评框架→交互测评→画像生成）+ 全链可审计（LLM trace 留痕、状态事件 append-only、报告可回溯）
**验收口径权威：** `design/final-design/总设计文档.md`（SSOT v2.0）；文件级差距证据：`research/ssot-code-gap-matrix.md`（68 行契约核对）

## v1 Requirements

两级结构：**REQ-\***（需求级，源自 PRD/SSOT §24 验收口径，7 条）+ **REF-\***（契约级，源自差距矩阵 68 行，每行一个 REF）。REF 只登记行号/层级/一句话定位与 Phase 归属，完整契约文本与 file:line 证据以矩阵文件为准，不在此重复。

### 需求级（REQ）

- [ ] **REQ-jd-parse-model**: JD 文本（粘贴/JSONL）→ 六工位流水线 → 结构化岗位胜任力模型 + 7:3 类目权重（人审 confirm 升版本，confirmed 不被静默覆盖）
- [ ] **REQ-dynamic-question-generation**: 基于岗位 + confirmed 模型版本绑定的题库 + 动态实例化四层选题（不是 LLM 自由出题）；追问每题最多 2 次（代码硬约束）
- [ ] **REQ-interactive-multiturn-assessment**: 有界测评循环（Observation→Policy→Act→Evaluation→Persist）；LLM 输出结构化观察、代码裁决；LLM 不能自行决定切题/结束
- [ ] **REQ-talent-profile-report**: 报告五段式（总分+门槛标签/雷达/逐项明细含逐行异议/优势短板建议/逐题回顾）；score_final 锚点评分；代码排序优势短板；状态机 + 明确点击发布
- [ ] **REQ-data-compliance**: 禁恶意爬虫；JD 接入只走粘贴/JSONL 文件导入；输入限额按类型配置；trace/JD/原文数据分级管理
- [ ] **REQ-e2e-demo-deliverables**: 候选人端完整 E2E（注册→选岗→session→作答/追问→表单→完成→评分→报告→异议）+ 统一 pytest 收集 + CI 为验收入口
- [ ] **REQ-iterative-loop**: 测试闭环（b 一致性 / c 虚拟考生 / bad case 候选 / eval 隔离）；反馈可回溯、异议永不触发改分

### 契约级（REF）— 按矩阵分节

层级标注：**[P0]** 上线阻断 / **[结构]** 结构性重构（表/架构演进）/ **[一般]** 常规修复 / **[保持]** 已合规保持不动 / **[延后]** 登记不排期（附理由）。

#### 矩阵 §1 全局约束（REF-1.1~1.7）

- [ ] **REF-1.1** [P0] 候选人资源级所有权校验：session/report/form/feedback 全部 `WHERE user_id=current`（api/assessment.py 6 处路由）→ Phase 1
- [ ] **REF-1.2** [一般] 角色限制后端执行收口（随 1.1 越权测试矩阵）→ Phase 1
- [x] **REF-1.3** [一般] score_live 由 LLM 直产 1-5 分 → 随 §17 重构（见 REF-5.1）→ Phase 2
- [ ] **REF-1.4** [保持] call_llm_json 统一 trace 落库（合规，不动）
- [ ] **REF-1.5** [P0] 状态事件 append-only 体系落地 → Phase 1
- [x] **REF-1.6** [结构] 单步"LLM 直接决定 action"重构为观察/裁决两层（§11.3/§11.4）→ Phase 2
- [x] **REF-1.7** [结构] LLM 不决定难度迁移/finish（finish 护栏现状合规；难度部分见 REF-4.2）→ Phase 2

#### 矩阵 §2 数据库（REF-2.1~2.11）——演进随阶段走，Phase 6 收口 schema_version

- [ ] **REF-2.1** [结构] 全局 21 张表对齐（汇总行：三新表 + 六表演进）→ Phase 6 收口清点
- [ ] **REF-2.2** [P0] 新表 assessment_state_event（append-only，UNIQUE(session_id,sequence_no)）→ Phase 1
- [ ] **REF-2.3** [结构] 新表 trace_link（统一审计链）→ Phase 5
- [ ] **REF-2.4** [结构] 新表 form_instance（schema 快照/生命周期）→ Phase 3
- [ ] **REF-2.5** [结构] question_bank 演进（model/version 绑定、question_type、measurement_stage、rubric_version、锚点、综合绑定）→ Phase 4 主体（锚点列随 Phase 2 难度状态机先行）
- [ ] **REF-2.6** [结构] assessment_session 演进（phase/计时区间/abandoned/状态机 PENDING_START→ACTIVE→SCORING→COMPLETED）→ Phase 3
- [ ] **REF-2.7** [结构] assessment_question 演进（动态实例列/封存/selection_reason/路径快照；(session_id,sequence_no) 唯一）→ Phase 2
- [ ] **REF-2.8** [结构] assessment_message 分列（raw_content/raw_hash/refined_content/client_request_id/sequence_no）→ Phase 3
- [ ] **REF-2.9** [结构] question_score 演进（统一 score_final 废弃 final_score、score_state、override 列）→ Phase 2 主体（human_override 列随 Phase 5）
- [ ] **REF-2.10** [结构] 证据定位结构化（span/offset/quote_hash；hash 复用限单 session）→ Phase 5
- [ ] **REF-2.11** [结构] schema_version 迁移体系（替换 DDL 字符串嗅探式迁移）→ Phase 6 收口

#### 矩阵 §3 题库与选题（REF-3.1~3.9）

- [x] **REF-3.1** [结构] 岗位级 N + 7:3 最大余数 + tier 0.8/0.6/1.7 公式（废弃固定 CATEGORY_QUOTA）→ Phase 2
- [x] **REF-3.2** [结构] 四层动态选题替换 create_session 一次性预选 → Phase 2
- [ ] **REF-3.3** [结构] experience/qualification 出普通题库，改走表单 → Phase 3
- [ ] **REF-3.4** [一般] 题库绑定 model/version；升版须重建题库否则阻止开考 → Phase 4
- [ ] **REF-3.5** [P0] 开考前可测量性检查（题库 readiness/配额可行/表单 schema；不通过阻止开考+管理员待办）→ Phase 1
- [x] **REF-3.6** [一般] required 刚性例外（每 item 最多一次、仅 medium/hard）→ Phase 2
- [x] **REF-3.7** [结构] 难度→1-5 等级锚点映射（easy[2,3]/medium[3,4]/hard[4,5]，observable_level 列）→ Phase 2
- [ ] **REF-3.8** [延后] 等值备用题组 —— SSOT 未列入 §28 硬项，矩阵标低优先
- [ ] **REF-3.9** [延后] 综合题槽位 —— 综合题生成 Prompt 待讨论（SSOT 附录 A / D-030），实现后排

#### 矩阵 §4 会话运行时（REF-4.1~4.12）

- [x] **REF-4.1** [结构] 动态实例化（每呈现题面新实例；followup 为实例内子轮次）→ Phase 2
- [x] **REF-4.2** [结构] 难度路径状态机（升/降/滞回恢复；不计普通失败；跳级禁止）→ Phase 2
- [x] **REF-4.3** [结构] evidence_sufficient/stable_evidence 结构化观察维度 + 代码布尔裁决 → Phase 2
- [x] **REF-4.4** [结构] answer_state 11 态 + score_state 8 态两层分离 → Phase 2
- [x] **REF-4.5** [结构] 各状态处理原则（拒答一次确认后跳过/技术暂停计时/边界设定等）→ Phase 2
- [ ] **REF-4.6** [一般] 真实 SSE（决策非流式先落库，话术逐 token；前端 sse.js 已就绪）→ Phase 3
- [ ] **REF-4.7** [一般] 接口层 Pydantic 请求/输出 schema（替换裸 dict body）→ Phase 3
- [ ] **REF-4.8** [结构] 计时区间：全场 40min/单题 20min/服务端权威/暂停写事件/6h ABANDONED → Phase 3
- [ ] **REF-4.9** [一般] 幂等与并发（session_id+endpoint+idempotency_key；重复请求返回首次结果）→ Phase 3
- [ ] **REF-4.10** [结构] 表单链（render_form 代码触发/schema 版本化快照/GET 只读不暴露阈值/gate 结构化结果/人工覆盖二次确认）→ Phase 3
- [ ] **REF-4.11** [延后] Tools 白名单 —— 本期无任何工具调用（形式无越界），接口登记随 Prompt 模块讨论（D-030）落位
- [ ] **REF-4.12** [结构] 上下文三层（滑窗 Token 控制/导航摘要层/refine 原文精炼分列）→ Phase 3

#### 矩阵 §5 评分与报告（REF-5.1~5.11）

- [x] **REF-5.1** [结构·核心] score_live 仅导航；废弃 50/50 合成（synthetic final_score 不得用于聚合）→ Phase 2
- [x] **REF-5.2** [结构] 客观题 answer_key 空属题库缺陷 → 判题库无效而非满分（漏洞见 REF-8.1）→ Phase 2
- [x] **REF-5.3** [结构] 拒答 REFUSED=0 特殊状态值，不进能力等级分母，只进行为/完整度聚合 → Phase 2
- [ ] **REF-5.4** [结构] item_measurement 统一裁决（废弃按题数均分；冲突取低留人工标记）→ Phase 5
- [ ] **REF-5.5** [结构] 缺失补算 IMPUTED（r 比例 + 特殊标记 + 覆盖率展示；O=∅ → NO_VALID_OBSERVATION）→ Phase 5
- [ ] **REF-5.6** [结构] required 缺失 → report_status=PROVISIONAL + HUMAN_REVIEW_REQUIRED → Phase 5
- [x] **REF-5.7** [结构] 7:3 权重口径修正（config 旧 55/20/20/5 作废；模块三直接复用 item.weight 不二次乘大类比例）→ Phase 2
- [ ] **REF-5.8** [保持] 报告五段式已合规（雷达 required vs actual 合规，保持）
- [ ] **REF-5.9** [P0] 报告状态机（GENERATING→PROVISIONAL|READY→PUBLISHED|FAILED）+ review_status + 发布前七项一致性校验 + 管理员明确点击发布 + 报告版本化 → Phase 5
- [ ] **REF-5.10** [P0] score→report 串行（实测前端零步断裂：从不调 POST /score，报告聚合恒 no_data；服务端串联修复）→ Phase 1
- [ ] **REF-5.11** [一般] score_live/score_final 双分背离 ≥ 阈值自动创建 bad case 候选（不自动改分）→ Phase 6

#### 矩阵 §6 安全（REF-6.1~6.4）

- [ ] **REF-6.1** [一般] JWT HttpOnly cookie 方向（现 Bearer；SSOT 标"方向"，实施期决定，非 P0）→ Phase 6
- [ ] **REF-6.2** [一般] 生产 secret 启动校验（默认值拒绝/告警）→ Phase 6
- [ ] **REF-6.3** [一般] 输入限额按类型配置（文件/行数/JD/回答/prompt/max_tokens/分页）→ Phase 6
- [ ] **REF-6.4** [一般] Prompt injection 防护 + INJECTION_DETECTED 事件留痕 → Phase 3

#### 矩阵 §7 §28 对账项（REF-7.1~7.6，矩阵 §7 中未被 §1-6/§8 覆盖的独立工作项）

- [ ] **REF-7.1** [一般] /jds/orphan 路由顺序修复（实测被 /jds/{jd_id} 参数路由吞掉恒 404）→ Phase 4
- [ ] **REF-7.2** [一般] 模型编辑字段校验（NaN/范围/类别/重复 std_name）→ Phase 4
- [ ] **REF-7.3** [结构] feedback 补 user_id/note/reviewer/时间戳；question_reviews 补 item_id；submit_feedback 校验 item 属于对应模型 → Phase 5
- [ ] **REF-7.4** [结构] 测试统一 pytest 收集（test_m6/question_bank 脚本式重构）+ CI 配置 → Phase 6
- [ ] **REF-7.5** [结构] M1 回归清单（清洗边界/抽取异常/消歧/权重尾差/冲突 stalled/confirmed 不可覆盖/版本 diff/管理员权限）→ Phase 6
- [ ] **REF-7.6** [结构] 候选人端完整 E2E（含刷新恢复/断线重试/越权/超时）→ Phase 6

#### 矩阵 §8 矩阵外发现（REF-8.1~8.8）

- [x] **REF-8.1** [结构] 空 answer_key 客观题恒满分漏洞（并入 REF-5.2）→ Phase 2
- [ ] **REF-8.2** [一般] completed 会话仍可重复评分/报告（POST /score、/report 无状态护栏）→ Phase 1
- [ ] **REF-8.3** [一般] 报告后台任务异常静默 pass（FAILED 态应可见，前端可区分"生成中/失败"）→ Phase 5
- [ ] **REF-8.4** [一般] 题库生成失败静默（状态 + 管理员待办可见）→ Phase 4
- [ ] **REF-8.5** [一般] 模型 items 为空不阻断开考（并入 REF-3.5 开考检查）→ Phase 1
- [ ] **REF-8.6** [一般] mock interviewer 主观题固定 3 分（测试重构时处理）→ Phase 6
- [ ] **REF-8.7** [结构] llm_trace ref_id 单字段弱关联（随 trace_link 落地迁移导入）→ Phase 5
- [ ] **REF-8.8** [结构] eval 脚本直接操作业务库（违反 §23 隔离；独立/临时数据库改造）→ Phase 6

## Deferred（登记不排期）

矩阵行中三处 [延后]：**REF-3.8**（等值备用题组，低优先）、**REF-3.9**（综合题，Prompt 待讨论）、**REF-4.11**（Tools 白名单，本期无工具调用）。恢复排期须先经用户确认（若涉 SSOT 范围调整，先改 SSOT §14）。

## Out of Scope

| 项 | 理由 |
|----|------|
| 最终录用判断/排序/自动淘汰 | D-002 范围红线；界面/报告/Prompt 均不得出现录用结论表述 |
| 黄金集 / 浏览器插件 / 真实 JD 数据集 | D-029 本期保留不做 |
| 恶意爬虫抓取 | 合规红线；JD 只走粘贴/JSONL 导入 |
| 容器化部署 / 多实例 / 进程重启任务恢复 | D-005 演示上线形态锁定 |
| 公平性离线评估 | D-031 仅留记录 |
| 黄金集替代真实 LLM 验证 | mock 回归不能替代真实 LLM 质量验证（D-027） |

## Traceability

### REQ → Phase

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-jd-parse-model | Phase 4（M1 回归验收在 Phase 6） | Pending |
| REQ-dynamic-question-generation | Phase 2 | Pending |
| REQ-interactive-multiturn-assessment | Phase 2（传输/表单/计时深化在 Phase 3） | Pending |
| REQ-talent-profile-report | Phase 5（链路修复前提在 Phase 1） | Pending |
| REQ-data-compliance | Phase 6 | Pending |
| REQ-e2e-demo-deliverables | Phase 6 | Pending |
| REQ-iterative-loop | Phase 6 | Pending |

### REF → Phase（按 Phase 分组；共 68 行：63 排期 + 2 保持 + 3 延后）

| Phase | REF 条目 | 数量 |
|-------|----------|------|
| 1. P0 安全与主链修复 | REF-1.1, 1.2, 1.5, 2.2, 3.5, 5.10, 8.2, 8.5 | 8 |
| 2. 动态选题与有界循环 | REF-1.3, 1.6, 1.7, 2.7, 2.9, 3.1, 3.2, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.7, 8.1 | 19 |
| 3. 表单/SSE/幂等/计时 | REF-2.4, 2.6, 2.8, 3.3, 4.6, 4.7, 4.8, 4.9, 4.10, 4.12, 6.4 | 11 |
| 4. 题库版本与模块一收口 | REF-2.5, 3.4, 7.1, 7.2, 8.4 | 5 |
| 5. 证据链/报告契约/反馈 | REF-2.3, 2.10, 5.4, 5.5, 5.6, 5.9, 7.3, 8.3, 8.7 | 9 |
| 6. 迁移/测试闭环/验收 | REF-2.1, 2.11, 5.11, 6.1, 6.2, 6.3, 7.4, 7.5, 7.6, 8.6, 8.8 | 11 |
| 保持（不排期） | REF-1.4, 5.8 | 2 |
| 延后（登记） | REF-3.8, 3.9, 4.11 | 3 |

**Coverage:**
- REQ：7/7 mapped ✓
- REF：68/68 accounted（63 排期 + 2 保持 + 3 延后，无孤儿）✓
- 表结构演进（矩阵 2.5–2.10）按矩阵 §10 建议"演进随阶段走"：各 Phase 携带自身新列/新表内嵌迁移，Phase 6 收口 schema_version 登记簿。

---
*Requirements defined: 2026-09-02*
*Last updated: 2026-09-02 after roadmap creation (traceability populated)*
