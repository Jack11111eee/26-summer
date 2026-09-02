# Phase 1: P0 安全与主链修复 - Context

**Gathered:** 2026-09-02
**Status:** Ready for planning

<domain>
## Phase Boundary

把 SSOT §28 六步之首的 P0 四项落地：①候选人资源级所有权校验（api/assessment.py 全部候选人资源路由，杜绝 IDOR）+ 越权测试矩阵；②`assessment_state_event` 状态事件表落地（append-only）+ 现有状态迁移点接入；③score→report 服务端串行（修复前端从不调 POST /score 导致报告恒 no_data 的零步断裂）+ completed 会话护栏；④开考前可测量性检查（不通过阻止创建 session + 管理员待办，杜绝 0 题会话）。

对应 REQUIREMENTS.md：REF-1.1, REF-1.2, REF-1.5, REF-2.2, REF-3.5, REF-5.10, REF-8.2, REF-8.5（支撑 REQ-interactive-multiturn-assessment / REQ-talent-profile-report 主链）。附带护栏：前端 route guard admin 例外修复（与后端权限模型对齐）。

**不在本阶段**：动态选题/四层选题/难度状态机（Phase 2）、表单 schema 实体/计时/SSE/幂等（Phase 3）、题库 model/version 绑定主体（Phase 4，本阶段仅立 question_bank_task 表）、报告状态机/发布校验/版本化（Phase 5）、迁移体系收口与 CI（Phase 6）。

</domain>

<decisions>
## Implementation Decisions

### 越权语义与实现（计划 01-01）
- **D-01: 越权返回语义 = 404 统一"不存在"。** 不引入 403 分支——单查询 `WHERE resource_id=? AND user_id=?`（admin 读豁免用 OR）无行即 404；与现有 not-found 语义一致，ID 为 uuid hex 无枚举风险。
- **D-02: 实现形态 = 共享 helper。** `load_owned_session` / `load_owned_report` 两个 helper（session 直查 / report→session join），路由首调，返回行或抛 404；admin 读豁免在 helper 内统一。覆盖 api/assessment.py 全部候选人资源路由（get_session / submit_answer / submit_form / score / request_report / get_report_by_session / get_report / submit_feedback）。
- **D-03: admin 边界 = 只读。** admin 可读候选人资源与完整 trace（SSOT §7 锁定）；写操作（答题/表单提交/反馈等）一律 owner-only，admin 写同样拒绝。无 admin 代写例外——串行化后评分/报告由服务端内部链触发，不经候选人端点。
- **D-04: 前端 route guard 顺带修复。** `web/src/router/index.js` 中 `/assessment/session/:session_id`、`/assessment/report/:session_id` 的 `meta.role: 'candidate'` 改为 `requiresAuth: true`（与 `/assessment/positions` 一致），后端所有权校验仍是权威。已知缺陷（admin 完成测评被弹回管理页）随 01-01 修复。

### 状态事件接入范围（计划 01-02）
- **D-05: 事件范围 = 全量 + 串行链事件。** 成功标准硬性要求的 session/question 关键迁移点必接；评分→报告后台链也接 `TASK_QUEUED/STARTED/SUCCEEDED/FAILED` + `SESSION_ENTERED_SCORING` + `SESSION_COMPLETED`——主链全程事件可审计（D-003"一切留痕"）。表 DDL 与事件枚举以 SSOT §13.1–13.2 为准，Phase 1 只落已发生的迁移点，DIFFICULTY_*/FORM_*/GATE_* 等枚举值留待对应 Phase 写入。
- **D-06: append-only 强制机制 = SQLite 触发器 + helper。** `assessment_state_event` 建 `BEFORE UPDATE / BEFORE DELETE` 触发器 `RAISE(ABORT)`（DDL 内嵌 server/db.py，满足成功标准"直接 UPDATE/DELETE 被测试证明拒绝"）；`append_event()` helper 单点封装 `sequence_no = MAX+1`（同事务内取号，UNIQUE(session_id,sequence_no) 兜底）与快照列同事务写入。
- **D-07: actor_type 枚举 = candidate / system / admin 三值起步。** helper 内代码校验（N11：无 DB CHECK）；admin 值 Phase 1 预留不写事件。candidate=候选人主动作，system=代码状态机与后台链。

### 评分→报告串行（计划 01-03）
- **D-08: 串行落点 = request_report 入口链（方案 B）。** `POST /report` 的 background task 先调 `score_session` 再 aggregate/generate；复用现有 BackgroundTasks+轮询形态，前端 Report.vue 不动；后台链内部沿用"内存算完单事务落库"既有模式（server/services/scoring.py:107）。不选 finish 直调（同步串两次 LLM 链有超时风险）、不选 generate_report 内部首调（服务层隐式副作用，与 §21.1"报告生成不隐式代替评分"边界模糊）。
- **D-09: POST /score 端点保留 + 护栏写服务层。** 护栏放 `score_session` / `request_report` 服务层入口：completed 再调→409；in_progress 调评分属非法前置→409。API 与服务层直调（eval/测试）双路径都被护。注意：test_m6_backend.py 现有 Python 层直调 score_session 的断言需随修复同步重写（只改断言，不重构脚本式风格——统一 pytest 收集是 Phase 6 REF-7.4）。
- **D-10: session 快照不加中间态。** finish 置 `completed`，串行链进度由 TASK_* 事件表达；`SCORING` 快照态留给 Phase 3 随 REF-2.6 状态机（PENDING_START→ACTIVE→SCORING→COMPLETED）一次做对，避免 CHECK 约束重建。

### 开考检查裁剪（计划 01-04）
- **D-11: 检查骨架分层留扩展点。** 检查函数按 §10.4 全链一次成型；Phase 1 实现可查 4 项（position active / 模型 confirmed / 题库就绪 / required item 覆盖）+ **现行 CATEGORY_QUOTA 口径**的配额校验；综合题槽位/qualification 表单 schema/新配额公式留 no-op 检查位，Phase 2–4 到期只填函数体不改骨架。三个失败状态名（QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE）在检查函数一处统一返回。
- **D-12: 题库 readiness 载体 = 新增 question_bank_task 表。** （position_id + model/version + status: QUEUED/RUNNING/SUCCEEDED/FAILED + 时间戳）；confirm 触发生成时插 QUEUED，后台任务开始/结束更新自身行。"生成中/不完整/就绪"三态真实可查；Phase 4 REF-8.4（生成失败可见）直接复用此表。不用推断式（生成中与缺题不可分）；不用事件表（session_id NOT NULL，题库生成在 session 之外）。
- **D-13: 失败呈现 = todos 聚合扩展 + 409 error_code。** `GET /api/admin/todos` 增加题库不就绪岗位计数/列表（question_bank_task 驱动，SUCCEEDED 之外即待办）；候选人端 `POST /sessions` 失败返回 409 + `error_code`（三状态名，供测试矩阵断言）+ 中文 `detail`，前端 `web/src/views/assessment/Positions.vue` 展示可读提示。

### Claude's Discretion
- helper 具体命名与放置（server/api/assessment.py 顶部 vs server/core/security.py）——plan 阶段定。
- append_event 的参数形状（哪些 SSOT 列位 Phase 1 填 NULL）——按 §13.1 DDL 逐列对齐，未用列填 NULL 即可。
- question_bank_task 的 id 前缀与索引——沿用 new_id() 惯例（如 `qbt_`）。
- 越权测试矩阵的具体用例组织与断言粒度（pytest 可收集、单文件单进程纪律内自由编排）。

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 设计权威（SSOT）
- `design/final-design/总设计文档.md` §7 — 权限模型（P0 上线阻断项：所有权校验/admin 只读语义/后端执行/越权矩阵为上线阻断测试）
- `design/final-design/总设计文档.md` §10.4 — 开考前可测量性检查链 + 三个失败状态名
- `design/final-design/总设计文档.md` §13.1–13.2 — assessment_state_event DDL + 事件枚举 + append-only 规则
- `design/final-design/总设计文档.md` §13.4 — 幂等（Phase 1 事件表 idempotency_key 列位依据，幂等主体属 Phase 3）
- `design/final-design/总设计文档.md` §21.1 — score→report 串行要求（服务端执行，不依赖浏览器补调）
- `design/final-design/总设计文档.md` §28 — 六步实施顺序（Phase 1 = 第 1 步 P0 四项）
- `design/final-design/总设计文档.md` §30–31 — 差异登记 N1–N12 与开放参数（避免误入延后/未定项）

### 证据基线（gap matrix）
- `research/ssot-code-gap-matrix.md` — 68 行 SSOT↔代码契约核对（含 file:line 证据；Phase 1 相关行：REF-1.1/1.2/1.5/2.2/3.5/5.10/8.2/8.5 对应矩阵行）

### 代码地图
- `.planning/codebase/ARCHITECTURE.md` — 分层结构/数据流/SQLite 单写者两模式/反模式（Blocking SQLite transactions across LLM calls）
- `.planning/codebase/CONCERNS.md` — IDOR 八处路由清单（api/assessment.py:129-318）、报告零步断裂证据（report.py:89-100 + Report.vue:378-403）、Chat.vue route guard 缺陷、question bank 生成期静默短题集
- `.planning/codebase/TESTING.md` — 两测试风格共存、单文件单进程纪律、mock 模式约定、新测试 checklist
- `.planning/intel/decisions.md` — D-001~D-031 全文（D-017/019/025/026 为本 Phase 直接依据）

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/pipeline.py:14-19` — `new_id(prefix)` / `now_iso()` ID 与时间助手（question_bank_task / 事件行直接复用）
- `server/services/scoring.py:107-154` — "内存算完单事务落库"模式（评分→报告后台链照此写）
- `server/api/assessment.py:167` — "先 commit 再调 LLM"模式（事件写入与 LLM 调用混排时遵守）
- `GET /api/admin/todos`（server/api/admin/positions.py:11）— 现成待办聚合入口，扩展而非新建
- `POST /api/admin/models/{id}/confirm`（server/api/admin/models.py:86）— 题库生成触发点，question_bank_task 插行位置
- `web/src/utils/sse.js` 的 409/detail 处理与全局 ElMessage 惯例 — positions 页错误提示照此展示

### Established Patterns
- raw SQL + `get_conn()` per-call connection + 显式 commit；无 ORM
- 状态机 TEXT 列 + 代码驱动迁移（jd_record / competency_model / assessment_session 三现有实例）
- 后台任务 = BackgroundTasks + 前端轮询（report/eval/jd 均此形态）；进程重启丢任务，本期接受（D-005）
- DDL 内嵌 `server/db.py` `_DDL` + 幂等 `CREATE IF NOT EXISTS`；表迁移为手写字符串嗅探式（schema_version 属 Phase 6，本阶段新表走 _DDL 追加）
- 越权测试沿用 M5/M7 pytest+TestClient 风格：模块顶设 env（DB_PATH/LLM_PROVIDER=mock/JWT_SECRET）→ init_db() → 直调路由断言响应码 + `_q()` 断言 DB 状态

### Integration Points
- `server/api/assessment.py` — 8 条候选人资源路由接入 owned helper；`POST /sessions` 前插入开考检查
- `server/db.py` — `_DDL` 追加 assessment_state_event（+ 触发器）与 question_bank_task 两表
- `server/api/assessment.py` `request_report`（POST /report） — background task 改为 score→aggregate→generate 链式
- `server/services/scoring.py` `score_session` / `server/api/assessment.py` `request_report` — 服务层护栏（状态校验 + 409）
- `server/services/question_bank.py` `generate_question_bank` — 开头/结尾更新 question_bank_task 自身行
- `web/src/router/index.js:50-60` — 两条路由 meta 调整
- `web/src/views/assessment/Positions.vue` — 409 error_code 提示展示

</code_context>

<specifics>
## Specific Ideas

- 报告聚合链修复后必须经真实 UI 流程验证：候选人正常完成测评 → 直达报告页 → 报告含真实逐题评分与雷达数据（不再 no_data）；测试断言不得再用 Python 层直调 score_session 掩盖（STATE.md 已挂账此为 Phase 1 前置阻断项）。
- 开考检查失败绝不创建 0 题会话——这是硬性验收口径，宁可 409 也不允许短/空题集静默开考。

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 1-P0 安全与主链修复*
*Context gathered: 2026-09-02*
