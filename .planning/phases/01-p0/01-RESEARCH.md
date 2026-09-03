# Phase 1: P0 安全与主链修复 - Research

**Researched:** 2026-09-02
**Domain:** FastAPI + raw SQLite（无 ORM）候选人资源所有权校验 / append-only 状态事件表 / score→report 服务端串行 / 开考前可测量性检查
**Confidence:** HIGH

## Summary

Phase 1 是对既有代码（M5–M7 主体已实现、contract_complete=false）的**修复型**阶段：不加任何新框架、不装任何新包，四项工作全部落在现有分层（router → service → raw SQL）内。核心事实全部来自本仓库代码与设计 SSOT（`design/final-design/总设计文档.md` v2.0），并已逐文件核对：①`server/api/assessment.py` 8 条候选人资源路由全部只查 ID 不查 `user_id`（IDOR，REF-1.1）；②前端从未调用 POST /score——`web/src/api/index.js` 无该方法、Chat.vue finish 直接 `router.push`、Report.vue bootstrap 只调 `generateReport`，真实 UI 流程下 `question_score` 恒空、报告聚合恒 no_data（REF-5.10 零步断裂，测试通过仅因 test_m6_backend.py 在 Python 层直调 `score_session`）；③`create_session`（api/assessment.py:59-94）在选题返回空列表时照样建 0 题会话（REF-3.5/8.5）；④`server/db.py` 无 `assessment_state_event` 表（REF-2.2）；⑤POST /score、/report 只查会话存在不查状态（REF-8.2）。

关键技术机制已在本地实测验证（Python 3.13.2 / SQLite 3.45.3 / FastAPI 0.141.1 / pytest 9.1.1）：SQLite `BEFORE UPDATE/DELETE` 触发器 `RAISE(ABORT)` 能可靠拒绝行级 UPDATE/DELETE（抛 `sqlite3.IntegrityError`）；`CREATE TRIGGER IF NOT EXISTS` 幂等；触发器随 `DROP TABLE` 一并消失（对表重建迁移是个坑）；`UNIQUE(session_id, sequence_no)` 索引兜底取号冲突；TestClient（Starlette）下 `BackgroundTasks` 在**响应返回前同步执行完毕**——评分→报告串行链在测试里是同步可断言的；`HTTPException(409, detail={...dict...})` 的 dict detail 会原样出现在 `r.json()["detail"]`，可供 `error_code` 断言。

**Primary recommendation:** 严格按 4 个 plan 的既定决策（D-01~D-13）落地：01-01 用 `load_owned_session`/`load_owned_report` 共享 helper（404 统一语义、admin 只读豁免）+ 越权测试矩阵；01-02 在 `_DDL` 追加事件表（触发器 + `append_event()` helper + MAX+1 取号）；01-03 把 `POST /report` 的 background task 改为 score→aggregate→generate 链、护栏写服务层（completed→409）；01-04 新增 `question_bank_task` 表 + `check_session_readiness()` 全链骨架（三失败状态 + todos 扩展 + 409 error_code）。全部新测试按 M5/M7 pytest+TestClient 风格，单文件单进程。

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REF-1.1 | 候选人资源级所有权校验（session/report/form/feedback 全部 `WHERE user_id=current`，api/assessment.py 6 处路由） | 8 条路由逐行核对（见 Common Pitfalls 的路由清单表）；D-02 helper 形态；`require_login` 返回 user dict 含 `user_id`/`role` 可直接用 |
| REF-1.2 | 角色限制后端执行收口（随越权测试矩阵） | admin 路由已有 `require_admin` 兜底（admin/trace.py:7 等）；本阶段补候选人资源所有权；越权矩阵覆盖 candidate↔candidate 读写 + admin 边界 |
| REF-1.5 | 状态事件 append-only 体系落地 | §13.1 DDL 逐列对齐；SQLite 触发器实测有效；D-06 取号方案实测（UNIQUE 兜底） |
| REF-2.2 | 新表 assessment_state_event（append-only，UNIQUE(session_id,sequence_no)） | 同上；DDL 追加进 `server/db.py` `_DDL`（幂等 CREATE IF NOT EXISTS 既有模式） |
| REF-3.5 | 开考前可测量性检查（题库 readiness/配额可行；不通过阻止开考+管理员待办） | D-11/D-12/D-13：`check_session_readiness()` 骨架 + `question_bank_task` 表 + todos 扩展 + 409 error_code |
| REF-5.10 | score→report 串行（服务端执行，不依赖浏览器补调） | 零步断裂证据链；D-08 方案 B：request_report 入口链；TestClient 同步执行 background task 实测确认 |
| REF-8.2 | completed 会话仍可重复评分/报告（无状态护栏） | D-09：护栏写 `score_session`/`request_report` 服务层入口（completed→409；in_progress 调评分→409） |
| REF-8.5 | 模型 items 为空不阻断开考 | 并入 01-04 开考检查：`json_array_length(model_json.items)` 可查（list_positions 已用同款 json_extract） |

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

**越权语义与实现（计划 01-01）**
- **D-01: 越权返回语义 = 404 统一"不存在"。** 不引入 403 分支——单查询 `WHERE resource_id=? AND user_id=?`（admin 读豁免用 OR）无行即 404；与现有 not-found 语义一致，ID 为 uuid hex 无枚举风险。
- **D-02: 实现形态 = 共享 helper。** `load_owned_session` / `load_owned_report` 两个 helper（session 直查 / report→session join），路由首调，返回行或抛 404；admin 读豁免在 helper 内统一。覆盖 api/assessment.py 全部候选人资源路由（get_session / submit_answer / submit_form / score / request_report / get_report_by_session / get_report / submit_feedback）。
- **D-03: admin 边界 = 只读。** admin 可读候选人资源与完整 trace（SSOT §7 锁定）；写操作（答题/表单提交/反馈等）一律 owner-only，admin 写同样拒绝。无 admin 代写例外——串行化后评分/报告由服务端内部链触发，不经候选人端点。
- **D-04: 前端 route guard 顺带修复。** `web/src/router/index.js` 中 `/assessment/session/:session_id`、`/assessment/report/:session_id` 的 `meta.role: 'candidate'` 改为 `requiresAuth: true`（与 `/assessment/positions` 一致），后端所有权校验仍是权威。已知缺陷（admin 完成测评被弹回管理页）随 01-01 修复。

**状态事件接入范围（计划 01-02）**
- **D-05: 事件范围 = 全量 + 串行链事件。** 成功标准硬性要求的 session/question 关键迁移点必接；评分→报告后台链也接 `TASK_QUEUED/STARTED/SUCCEEDED/FAILED` + `SESSION_ENTERED_SCORING` + `SESSION_COMPLETED`——主链全程事件可审计（D-003"一切留痕"）。表 DDL 与事件枚举以 SSOT §13.1–13.2 为准，Phase 1 只落已发生的迁移点，DIFFICULTY_*/FORM_*/GATE_* 等枚举值留待对应 Phase 写入。
- **D-06: append-only 强制机制 = SQLite 触发器 + helper。** `assessment_state_event` 建 `BEFORE UPDATE / BEFORE DELETE` 触发器 `RAISE(ABORT)`（DDL 内嵌 server/db.py，满足成功标准"直接 UPDATE/DELETE 被测试证明拒绝"）；`append_event()` helper 单点封装 `sequence_no = MAX+1`（同事务内取号，UNIQUE(session_id,sequence_no) 兜底）与快照列同事务写入。
- **D-07: actor_type 枚举 = candidate / system / admin 三值起步。** helper 内代码校验（N11：无 DB CHECK）；admin 值 Phase 1 预留不写事件。candidate=候选人主动作，system=代码状态机与后台链。

**评分→报告串行（计划 01-03）**
- **D-08: 串行落点 = request_report 入口链（方案 B）。** `POST /report` 的 background task 先调 `score_session` 再 aggregate/generate；复用现有 BackgroundTasks+轮询形态，前端 Report.vue 不动；后台链内部沿用"内存算完单事务落库"既有模式（server/services/scoring.py:107）。不选 finish 直调（同步串两次 LLM 链有超时风险）、不选 generate_report 内部首调（服务层隐式副作用，与 §21.1"报告生成不隐式代替评分"边界模糊）。
- **D-09: POST /score 端点保留 + 护栏写服务层。** 护栏放 `score_session` / `request_report` 服务层入口：completed 再调→409；in_progress 调评分属非法前置→409。API 与服务层直调（eval/测试）双路径都被护。注意：test_m6_backend.py 现有 Python 层直调 score_session 的断言需随修复同步重写（只改断言，不重构脚本式风格——统一 pytest 收集是 Phase 6 REF-7.4）。
- **D-10: session 快照不加中间态。** finish 置 `completed`，串行链进度由 TASK_* 事件表达；`SCORING` 快照态留给 Phase 3 随 REF-2.6 状态机（PENDING_START→ACTIVE→SCORING→COMPLETED）一次做对，避免 CHECK 约束重建。

**开考检查裁剪（计划 01-04）**
- **D-11: 检查骨架分层留扩展点。** 检查函数按 §10.4 全链一次成型；Phase 1 实现可查 4 项（position active / 模型 confirmed / 题库就绪 / required item 覆盖）+ **现行 CATEGORY_QUOTA 口径**的配额校验；综合题槽位/qualification 表单 schema/新配额公式留 no-op 检查位，Phase 2–4 到期只填函数体不改骨架。三个失败状态名（QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE）在检查函数一处统一返回。
- **D-12: 题库 readiness 载体 = 新增 question_bank_task 表。** （position_id + model/version + status: QUEUED/RUNNING/SUCCEEDED/FAILED + 时间戳）；confirm 触发生成时插 QUEUED，后台任务开始/结束更新自身行。"生成中/不完整/就绪"三态真实可查；Phase 4 REF-8.4（生成失败可见）直接复用此表。不用推断式（生成中与缺题不可分）；不用事件表（session_id NOT NULL，题库生成在 session 之外）。
- **D-13: 失败呈现 = todos 聚合扩展 + 409 error_code。** `GET /api/admin/todos` 增加题库不就绪岗位计数/列表（question_bank_task 驱动，SUCCEEDED 之外即待办）；候选人端 `POST /sessions` 失败返回 409 + `error_code`（三状态名，供测试矩阵断言）+ 中文 `detail`，前端 `web/src/views/assessment/Positions.vue` 展示可读提示。

### Claude's Discretion
- helper 具体命名与放置（server/api/assessment.py 顶部 vs server/core/security.py）——plan 阶段定。
- append_event 的参数形状（哪些 SSOT 列位 Phase 1 填 NULL）——按 §13.1 DDL 逐列对齐，未用列填 NULL 即可。
- question_bank_task 的 id 前缀与索引——沿用 new_id() 惯例（如 `qbt_`）。
- 越权测试矩阵的具体用例组织与断言粒度（pytest 可收集、单文件单进程纪律内自由编排）。

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope

</user_constraints>

## Project Constraints (from CLAUDE.md)

- **Think Before Coding**：不臆测；不确定就问；多种解释并存时列出不默选。
- **Simplicity First**：最小代码解决问题；不做推测性功能/抽象/配置化。本阶段 D-11 的"no-op 检查位"是用户明确要求的骨架，不属 speculative。
- **Surgical Changes**：只改必须改的；不"顺手改进"相邻代码；匹配既有风格（中文注释/docstring、raw SQL、`status.HTTP_*` 常量、`# noqa: E402` 等）。发现无关 dead code 只提及不删除。
- **Goal-Driven Execution**：每项工作给出可验证成功标准（本阶段成功标准 1–5 即现成验收口径）。
- **Git**：commit every working-tree change；当前分支 `feature/m5-assessment` 上直接推进（STATE.md 锁定）。
- **项目约定（本仓库 CLAUDE.md）**：SSOT = `design/final-design/总设计文档.md` v2.0；SSOT 修改须用户明确授权，agent 仅可起草；本阶段**不修改任何设计文档**——研究产出只进 `.planning/phases/01-p0/01-RESEARCH.md`。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 资源所有权校验（404 语义） | API 层（api/assessment.py 路由首调 helper） | core/security.py（helper 可选放置位） | SSOT §7"角色限制必须在后端执行"；校验是 HTTP 契约的一部分，必须在路由入口最先执行 |
| 事件写入（append_event） | Service 层 + API 层状态迁移点 | db.py（DDL/触发器） | 事件与快照列同事务（§13.1），迁移点散布在 api/assessment.py（answer/finish）与 services（评分报告链） |
| append-only 强制 | 数据库层（触发器 RAISE(ABORT)） | — | 成功标准要求"直接 UPDATE/DELETE 被测试证明拒绝"，必须是 DB 级强制而非代码约定 |
| score→report 串行编排 | API 层 background task（request_report） | Service 层（score_session/generate_report 内部不变） | D-08 方案 B：编排属入口链职责；服务层保持单一职责 |
| completed 护栏 | Service 层（score_session/request_report 入口） | — | D-09：API 与直调双路径都要被护，必须放服务层 |
| 开考可测量性检查 | Service 层（新 check 函数） | API 层（create_session 调用 + 409） | 检查逻辑属业务规则；§10.4 要求全链一次成型 |
| question_bank_task 状态维护 | db.py（DDL）+ admin/models.py confirm（插行）+ services/question_bank.py（更新行） | — | D-12：confirm 触发点是插行位置，生成任务首尾更新自身行 |
| 管理员待办可见 | API 层（admin/positions.py todos 扩展） | — | D-13：扩展既有聚合入口 |
| 前端 route guard / 409 提示 | Browser 层（router/index.js、Positions.vue） | — | 纯 UX 对齐；后端校验是权威 |
| 越权/护栏/串行/append-only 的证明 | 测试层（server/test_*.py，pytest+TestClient） | — | 成功标准 1/4/5 均要求"被测试证明"；矩阵为上线阻断测试 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.141.1（已装，requirements 声明 >=0.110） | API 层、BackgroundTasks、HTTPException、Depends | 既有栈；本阶段零新依赖 [VERIFIED: 本机 `python3 -c "import fastapi"` 实测] |
| sqlite3（stdlib） | SQLite 3.45.3 | 事件表/触发器/question_bank_task DDL + 全部查询 | 既有栈；触发器 RAISE(ABORT) 行为已实测 [VERIFIED: 本机运行验证] |
| pytest | 9.1.1（已装，未列入 requirements.txt） | 越权矩阵/护栏/append-only 测试 | M5/M7 既有测试风格；测试纪律单文件单进程 [VERIFIED: 本机 `pytest --version`] |
| fastapi.testclient（httpx 传递依赖） | — | API 级集成测试 | 既有模式；BackgroundTasks 在 TestClient 下同步执行（实测确认） |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| passlib[bcrypt] / bcrypt<4.1 | 已装 | 测试种子用户哈希（admin/candidate） | 沿用 test_m7 的 `CryptContext(schemes=["bcrypt"])` 直插 user 行模式 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SQLite 触发器强制 append-only | 纯 helper 约定（不建触发器） | 约定可被任何裸 SQL 绕过，不满足成功标准"被测试证明拒绝"；CONTEXT D-06 已锁定触发器方案 |
| 新增 Pydantic 请求模型 | `body: dict` + 422 | REF-4.7 明确属 Phase 3；本阶段沿用 dict body（CONVENTIONS.md 惯例） |
| HttpOnly cookie | 现行 Bearer | REF-6.1 属 Phase 6，SSOT 标"方向"非 P0，不碰 |

**Installation:**
```bash
# 无需安装任何新包。现有环境已具备全部依赖：
# fastapi 0.141.1 / uvicorn 0.52.4 / pydantic 2.10.3 / pytest 9.1.1 / sqlite3 (3.45.3, stdlib)
# 若需重装环境：pip install -r server/requirements.txt（pytest 需另装，requirements 未列）
```

**Version verification:** 本阶段**零新增包**，无需 registry 检查。已装版本实测：Python 3.13.2、FastAPI 0.141.1、pytest 9.1.1、SQLite 3.45.3。

## Package Legitimacy Audit

> 本阶段不安装任何外部包（零新增依赖），此表为空——不适用。

**Packages removed due to slopcheck [SLOP] verdict:** none（未运行 slopcheck——无新包引入，全部依赖为既有 requirements.txt 中的已在用包）
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
候选人浏览器 (Vue 3 SPA)
   │  Bearer JWT
   ▼
FastAPI 单进程 (server/main.py, uvicorn)
   │
   ├─ /api/assessment/*  router（require_login）
   │    │
   │    ├─ 01-01: 路由首调 load_owned_session / load_owned_report
   │    │      单查询 WHERE id=? AND (user_id=? [OR role='admin' 读豁免])
   │    │      ├─ owner 命中 → 返回行
   │    │      └─ 无行 → 404 "不存在"（候选人和 admin 写操作同路径）
   │    │         （写操作：admin 一律拒绝，仅 candidate 本人可写）
   │    │
   │    ├─ 01-04: POST /sessions 前插 check_session_readiness()
   │    │      position active → model confirmed → 题库 readiness
   │    │      → required item 覆盖 → [no-op 位: 综合槽位/表单 schema/新配额]
   │    │      ├─ 通过 → 建会话（原逻辑）
   │    │      └─ 不通过 → 409 {error_code: GENERATING|INCOMPLETE|MODEL_NOT_MEASURABLE}
   │    │                + 管理员待办（admin/todos 读 question_bank_task）
   │    │
   │    ├─ 01-03: POST /sessions/{id}/report (202)
   │    │      └─ background task（TestClient 下同步执行）:
   │    │           score_session → aggregate → generate_report
   │    │           （评分→报告 服务端串行；护栏见下）
   │    │
   │    └─ 01-02: 全部状态迁移点 → append_event(session_id, event_type,
   │               from_state, to_state, actor_type, ...)
   │               sequence_no = MAX+1（同事务），快照列同事务更新
   │
   └─ /api/admin/*  router（require_admin）
        └─ 01-04: GET /todos 扩展题库不就绪计数/列表
                   （question_bank_task: SUCCEEDED 之外即待办）

数据层: server/db.py
   _DDL 追加:
   ├─ assessment_state_event（§13.1 全列；UNIQUE(session_id, sequence_no)）
   │    + BEFORE UPDATE / BEFORE DELETE 触发器 → RAISE(ABORT)   [append-only]
   └─ question_bank_task（position_id + model/version + status + 时间戳）

admin 后台链（不受所有权 helper 影响）:
   POST /api/admin/models/{id}/confirm → 插 question_bank_task(QUEUED)
   └─ background generate_question_bank → 任务开始/结束更新自身行
   admin 可读候选人资源与完整 trace（helper 内 OR 豁免，读 only）
```

### Recommended Project Structure

```
server/
├── api/assessment.py        # [改] 8 路由接 owned helper；create_session 前插检查；request_report 改串行链；护栏
├── services/
│   ├── scoring.py           # [改] score_session 入口加 completed/in_progress 状态护栏（ValueError→API 转 409）
│   ├── report.py            # [不动] generate_report 本体不变（串行由入口链编排）
│   ├── question_bank.py     # [改] generate_question_bank 开头/结尾更新 question_bank_task 自身行
│   ├── readiness.py         # [新] check_session_readiness() 全链骨架（可查项 + no-op 位）
│   └── state_events.py      # [新·可选名] append_event() helper + actor_type 校验（放置 plan 定）
├── core/security.py         # [可能改] 若 helper 放这里（Claude's Discretion）
├── db.py                    # [改] _DDL 追加 assessment_state_event(+触发器) 与 question_bank_task
└── test_p0_*.py             # [新] 越权矩阵/护栏/串行/append-only/开考检查测试（pytest 可收集，单文件单进程）
web/src/
├── router/index.js          # [改] 两条路由 meta.role → requiresAuth:true
└── views/assessment/Positions.vue  # [改] 409 error_code 可读提示
```

### Pattern 1: 越权 helper（D-01/D-02/D-03，单查询 404 语义）

**What:** 所有 session 资源路由先调 `load_owned_session`；report 资源先调 `load_owned_report`（report→session join 取 owner）。admin **读**豁免在 helper 内统一（OR 条件），admin **写**一律拒绝。

**When to use:** api/assessment.py 中全部 8 条候选人资源路由。

**Example:**
```python
# 形状参考（最终命名/放置 plan 定）。admin 读豁免 = OR；写操作路由不传 allow_admin。
def load_owned_session(conn, session_id: str, user: dict, *, allow_admin_read: bool) -> dict:
    """按 ID + 所有权取会话行；无行统一 404（不存在与越权不可区分，D-01）。"""
    clause = "user_id=?"
    params: list = [user["user_id"]]
    if allow_admin_read and user["role"] == "admin":
        clause = "(user_id=? OR 1=1)"   # admin 只读豁免；写路由不传 allow_admin_read
    row = conn.execute(
        f"SELECT * FROM assessment_session WHERE session_id=? AND {clause}",
        (session_id, *params),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    return dict(row)
```
```python
# report 侧（join session 取 owner）：
# SELECT r.* FROM report r JOIN assessment_session s ON s.session_id=r.session_id
# WHERE r.report_id=? AND s.user_id=?（admin 读豁免同上）
# get_report_by_session 同理：WHERE r.session_id=? AND s.user_id=?
# feedback 侧：submit_feedback 校验 report 所有权（经 load_owned_report）
```
[VERIFIED: 形状由 D-02 锁定；现有 `require_login` 返回 dict 含 user_id/role（server/core/security.py:47），可直接作参数]

**8 条路由 × 读写 × admin 豁免矩阵（helper 覆盖清单）：**

| 路由（api/assessment.py 行号） | 方法 | 资源 | 读写 | admin 读豁免 |
|---|---|---|---|---|
| get_session (:97) | GET | session | 读 | 是 |
| submit_answer (:129) | POST | session+question | 写 | 否（owner-only） |
| submit_form (:209) | POST | session | 写 | 否 |
| score_session_endpoint (:233) | POST | session | 写（触发评分） | 否 |
| request_report (:259) | POST | session | 写（触发报告） | 否 |
| get_report_by_session (:272) | GET | report→session | 读 | 是 |
| get_report (:285) | GET | report→session | 读 | 是 |
| submit_feedback (:297) | POST | report→session | 写 | 否 |

注：`POST /sessions`（create_session :59）与 `GET /positions` 不涉他人资源，无需 helper。admin "可查完整 trace"已由既有 `GET /api/admin/trace/by-session/{session_id}`（require_admin）满足，本阶段不动。

### Pattern 2: append_event helper + 触发器（D-05/D-06/D-07）

**What:** DDL 追加事件表（§13.1 全列）+ 两个触发器；唯一写入口 `append_event(conn, ...)` 在**调用者已持有的同一事务内**取号并插入。

**When to use:** 一切状态迁移点。Phase 1 迁移点清单（只落已发生的迁移，DIFFICULTY_*/FORM_*/GATE_* 留待后续 Phase）：

| 迁移点 | 事件 | from → to | actor_type |
|---|---|---|---|
| create_session 建会话 | SESSION_CREATED | NULL → in_progress | candidate |
| submit_answer 题推进（next/finish 分支置 answered_at） | QUESTION_ANSWERED（或按 §13.2 定名） | active → answered | candidate |
| submit_answer finish 置 session completed | SESSION_COMPLETED | in_progress → completed | system（代码规则触发，interview.py:106-107） |
| request_report 链入队 | TASK_QUEUED | — | system |
| 后台链开跑 | TASK_STARTED + SESSION_ENTERED_SCORING | — / in_progress*→* | system |
| score 落库完成 | TASK_SUCCEEDED（评分子步） | — | system |
| report 落库完成 | TASK_SUCCEEDED（报告子步） | — | system |
| 后台链异常 | TASK_FAILED | — | system |
| 开考检查失败 | 不写事件（无 session 产生）——待办由 question_bank_task/todos 表达 | — | — |

*SESSION_ENTERED_SCORING 的 from/to：session 快照不加 SCORING 态（D-10），from_state=in_progress、to_state=in_progress 或 to 留空（动作类事件允许 from/to 为空，§13.1"动作/事实类事件允许为空"）——plan 阶段按 §13.2 语义定，不影响表结构。

**Example（触发器 DDL，已实测）：**
```python
# server/db.py _DDL 追加（注意：CREATE TRIGGER 无 IF NOT EXISTS 版本问题——已实测支持）：
CREATE TABLE IF NOT EXISTS assessment_state_event (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  sequence_no INTEGER NOT NULL,
  assessment_question_id TEXT NULL,
  assessment_message_id TEXT NULL,
  event_type TEXT NOT NULL,
  from_state TEXT NULL,
  to_state TEXT NULL,
  actor_type TEXT NOT NULL,          -- candidate/system/admin（N11：代码校验，无 DB CHECK）
  actor_id TEXT NULL,
  request_id TEXT NULL,
  idempotency_key TEXT NULL,        -- Phase 3 幂等主体，本期列位留 NULL（§13.4）
  policy_version TEXT NULL,
  model_version INTEGER NULL,
  question_bank_version TEXT NULL,
  correlation_id TEXT NULL,
  causation_event_id TEXT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(session_id, sequence_no)
);
CREATE TRIGGER IF NOT EXISTS ase_no_update BEFORE UPDATE ON assessment_state_event
BEGIN SELECT RAISE(ABORT, 'assessment_state_event 为 append-only：禁止 UPDATE'); END;
CREATE TRIGGER IF NOT EXISTS ase_no_delete BEFORE DELETE ON assessment_state_event
BEGIN SELECT RAISE(ABORT, 'assessment_state_event 为 append-only：禁止 DELETE'); END;
```
[VERIFIED: 本机 SQLite 3.45.3 实测——UPDATE/DELETE 均抛 `sqlite3.IntegrityError: append-only...`；`CREATE TRIGGER IF NOT EXISTS` 幂等可用；INSERT 与他表 UPDATE 不受影响]

**Example（取号，同事务）：**
```python
def append_event(conn, *, session_id: str, event_type: str,
                 from_state: str | None = None, to_state: str | None = None,
                 actor_type: str = "system", actor_id: str | None = None,
                 assessment_question_id: str | None = None, payload: dict | None = None) -> None:
    if actor_type not in ("candidate", "system", "admin"):
        raise ValueError(f"非法 actor_type: {actor_type}")   # D-07：代码校验
    # 同事务内取号；并发下 UNIQUE(session_id, sequence_no) 是最终兜底
    seq = conn.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM assessment_state_event WHERE session_id=?",
        (session_id,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO assessment_state_event(id, session_id, sequence_no, assessment_question_id,"
        " event_type, from_state, to_state, actor_type, actor_id, payload_json, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("asev"), session_id, seq, assessment_question_id, event_type,
         from_state, to_state, actor_type, actor_id,
         json.dumps(payload, ensure_ascii=False) if payload else None, now_iso()),
    )
    # 未用列（idempotency_key/policy_version 等）不写即默认 NULL
```
[VERIFIED: MAX+1 取号 + UNIQUE 兜底本机实测；连接默认隔离级别下同事务先 SELECT 后 INSERT 安全]

**事件写入与 SQLite 单写者纪律（关键）：**
- 事件写入点若与 LLM 调用同函数（答题链、评分报告链）：遵守两条既有模式——先 `conn.commit()` 再调 LLM（assessment.py:167 模式），或内存算完单事务落库（scoring.py:107 模式）。事件行与快照 UPDATE 放**同一个**最终事务。
- 评分报告后台链（01-03）的 TASK_* 事件：`score_session` 内部已先内存计算后单事务落库——TASK_STARTED 在链入口写（先 commit 用户侧数据后）、TASK_SUCCEEDED/FAILED 与最终落库同事务或紧随其后独立小事务。plan 时按"事件不过度持锁"原则逐点安排。

### Pattern 3: request_report 串行入口链（D-08/D-09/D-10）

**What:** `_generate_report_task` 改为链式：score_session → generate_report（generate 内部已调 aggregate）。护栏放服务层。

**Example:**
```python
# api/assessment.py（202 响应、BackgroundTasks、前端轮询均不动）
def _generate_report_task(session_id: str) -> None:
    """后台链：先终局评分再生成报告（§21.1 服务端串行）。异常静默同现状（Phase 5 报告状态机再改 FAILED 可见）。"""
    try:
        score_session(session_id)      # 内部"内存算完单事务落库"，天然不持锁调 LLM
        generate_report(session_id)    # 内部已调 aggregate_session_scores
    except Exception:  # noqa: BLE001
        pass

@router.post("/sessions/{session_id}/report", status_code=status.HTTP_202_ACCEPTED)
def request_report(session_id: str, background: BackgroundTasks, user: dict = Depends(require_login)) -> dict:
    session = load_owned_session(get_conn(), session_id, user, allow_admin_read=False)  # 写操作 owner-only
    # 服务层护栏（D-09）：completed 再请求报告 → 409（与评分同护栏语义）
    ...  # 见 Pattern 4
    append_event(...)  # TASK_QUEUED（01-02）
    background.add_task(_generate_report_task, session_id)
    return {"session_id": session_id, "status": "generating"}
```
[VERIFIED: TestClient 下 BackgroundTasks 在响应返回前同步执行完毕（本机实测）——测试断言 `POST /report` 返回后 `question_score`/`report` 行已存在，无需 sleep/轮询]

### Pattern 4: 服务层状态护栏（D-09）

**What:** 护栏写在 `score_session` 与 `request_report` 的服务层入口，API 与直调双路径都被护。

**Example:**
```python
# services/scoring.py::score_session 入口（现 :114 之后取 session 行处）：
session = conn.execute("SELECT model_id, status FROM assessment_session WHERE session_id=?", ...)
if session is None:
    raise ValueError(f"会话不存在: {session_id}")
if session["status"] == "completed":
    raise ValueError("会话已结束，不允许重复评分")      # API 层捕获 → 409
if session["status"] != "in_progress":
    raise ValueError(f"会话状态 {session['status']} 不可评分")
```
- API 层（`score_session_endpoint`）把服务层 `ValueError` 转 `HTTPException(409, str(e))`——注意现有代码 `score_session` 已抛 `ValueError(f"会话不存在")`，沿用该异常类型作为服务层护栏载体最贴合现状。
- `request_report`（API 层函数）对 completed 会话返回 409（护栏语义与评分一致）。
- **测试影响（D-09 明示）：** `eval/virtual_candidates.py:136` 直调 `score_session` 时 session 已置 completed → 修复后会被护栏拒绝。**这暴露一个真实冲突**：虚拟考生链先 `UPDATE status='completed'` 再 `score_session`。处理选项：(a) eval 属 Phase 6 改造对象（REF-8.8/7.4），本阶段若 eval 测试被护栏破坏，把 eval 内调用顺序改为先 score 后置 completed（一行调整，不改脚本结构）；(b) 同样地 `server/test_m6_backend.py` 的 `_seed_full_chain` 直接插 `in_progress` 会话（未置 completed，m6 直调 score_session 不受影响——已核对其 INSERT 用 `in_progress`），而 m5 的 `test_answer_flow_and_scoring` 在 finish 后调 POST /score → 修复后应得 409，**该断言必须重写为期望 409**（这正是 D-09 说的"test_m6 断言随修复同步重写"的 m5 版本）。m5 现断言 `assert r.status_code == 200`（test_m5_backend.py:257-258）在护栏生效后失败——plan 必须含此重写任务。
- 同理检查 `eval/consistency_test.py`：直调的是 `score_question`（不落 question_score、不走 score_session 护栏），不受影响 [VERIFIED: consistency_test.py:72 只调 score_question]。

### Pattern 5: question_bank_task + 开考检查（D-11/D-12/D-13）

**What:** 新表记录题库生成任务三态；检查函数一次成型、部分 no-op；失败 409 + error_code + todos 扩展。

**Example（表 + 插行点）：**
```python
# db.py _DDL 追加（列型沿用全库 TEXT/INTEGER 惯例；status 无 CHECK——N11 代码校验）：
CREATE TABLE IF NOT EXISTS question_bank_task (
  task_id     TEXT PRIMARY KEY,
  position_id TEXT NOT NULL REFERENCES position,
  model_id    TEXT NOT NULL REFERENCES competency_model,
  model_version INTEGER NOT NULL,
  status      TEXT NOT NULL,   -- QUEUED/RUNNING/SUCCEEDED/FAILED（代码校验）
  created_at  TEXT NOT NULL,
  started_at  TEXT,
  finished_at TEXT,
  error_msg   TEXT
);

# admin/models.py::confirm_model（:98-105 区域）：commit 确认后、add_task 前插行：
conn.execute("INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
             " status, created_at) VALUES(?,?,?,?,?,?)",
             (new_id("qbt"), row["position_id"], model_id, row["version"], "QUEUED", now_iso()))
conn.commit()

# services/question_bank.py::generate_question_bank 开头置 RUNNING，成功结尾置 SUCCEEDED，
# 异常 except 置 FAILED + error_msg（现状"失败静默"改为至少落表，Phase 4 再做 UI 可见）。
```
**readiness 判定逻辑（生成中/不完整/就绪三态）：**
```
最新 question_bank_task（按 position+model/version，created_at DESC）：
  无行且题库有题        → 就绪（兼容 Phase 1 之前已手工种过题库的旧数据/测试种子）
  status=QUEUED/RUNNING → QUESTION_BANK_GENERATING
  status=SUCCEEDED 但选题配额不满 / required 无题 → QUESTION_BANK_INCOMPLETE
  status=FAILED         → QUESTION_BANK_INCOMPLETE（Phase 4 细化失败可见）
模型 items 为空 / 全 gate 无可测项 → MODEL_NOT_MEASURABLE
```
[注：测试种子（m5 `_seed_question_bank`）直接插 question_bank 行、不走 confirm → 无 task 行。readiness 判定必须容忍"无 task 行但题库已就绪"的存量形态，否则现有测试全部被 409 打挂——这是本方案最关键的兼容点。]

**检查函数骨架（§10.4 全链一次成型）：**
```python
# services/readiness.py（新文件，名可 plan 定）
def check_session_readiness(position_id: str) -> None | dict:
    """开考前可测量性检查（§10.4）。通过返回 None；不通过返回 {"error_code": ..., "detail": ...}。
    失败状态三选一：QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE。"""
    # 1) position active                    （可查）
    # 2) 模型 confirmed + items 非空         （可查；items 空 → MODEL_NOT_MEASURABLE）
    # 3) 题库 readiness                     （可查；task 表驱动 → GENERATING / INCOMPLETE）
    # 4) required item 至少一题覆盖          （可查；缺 → INCOMPLETE）
    # 5) 配额可行（现行 CATEGORY_QUOTA 口径） （可查；不足 → INCOMPLETE）
    # 6) 综合题槽位（I>0 时）                （no-op：Phase 2-4 填函数体）
    # 7) qualification 表单 schema 可用      （no-op：Phase 3 填函数体）
```
**失败返回（409 + error_code，供矩阵断言）：**
```python
# api/assessment.py::create_session
result = check_session_readiness(position_id)
if result:
    raise HTTPException(status.HTTP_409_CONFLICT,
                        detail={"error_code": result["error_code"], "message": result["detail"]})
# HTTPException detail 可为 dict（实测 FastAPI 0.141.1 原样序列化进 r.json()["detail"]）
```
**todos 扩展（admin/positions.py:11）：** 在现有返回 dict 增加 `question_bank_not_ready`: 计数 + 可选列表（`SELECT ... FROM question_bank_task WHERE status != 'SUCCEEDED' ...` 或按 position 聚合去重）。前端 AdminPositions 页面若展示计数属顺带 UI 改动——**核实**：现有 AdminNav/Positions 管理页消费 todos 的三个键；新增键不破坏现有渲染（Vue 对未知键安全），但 plan 可决定是否展示。为守住"最小改动"，建议 Phase 1 后端返回新键、前端仅 Positions.vue（候选人端）展示 409 提示（D-13 明示项）；admin 页展示留待 Phase 4 失败可见（REF-8.4）一并做——D-13 原文只要求"todos 聚合扩展"即数据就位，未承诺 admin UI 改版。

**Positions.vue 409 提示（候选人端）：** `PositionAssess.vue` 是实际调 `createSession` 的页面（Positions.vue 只跳转）——**CONTEXT 集成点清单写的 Positions.vue 与实际调用点不符**：`assessment.createSession` 在 `web/src/views/assessment/PositionAssess.vue:131` 调用（onStart），其 catch 现只区分 501。409 的 `e.response?.data?.detail` 此时是 **dict**（`{error_code, message}`），前端取 `detail.message` 展示。plan 应把提示改动落在 PositionAssess.vue 的 catch 分支（或两文件皆轻触，plan 定）；断言口径：后端 `detail` 形态优先以本研究的 dict 方案为准，若 plan 决定用纯字符串 detail，则 error_code 另放顶层字段——**测试矩阵只断言 error_code 存在即可，两形态皆可满足 D-13**。

### Anti-Patterns to Avoid
- **不要在 generate_report 内部首调 score_session**（D-08 已否决）：服务层隐式副作用，与 §21.1"报告生成不隐式代替评分"边界模糊。
- **不要给 session 加 SCORING 中间快照态**（D-10）：现有 `assessment_session.status` CHECK 约束含 `in_progress/completed/abandoned`，加值需重建表（db.py 现有 `_migrate_*` 嗅探式重建正是脆弱区）；SCORING 留 Phase 3。
- **不要用 403 分支表达越权**（D-01 已否决）：404 统一"不存在"，防枚举 + 与现有语义一致。
- **不要在 readiness 检查里要求"必须有 task 行才可开考"**：会打挂全部存量测试种子（m5/m6 直插题库）；必须容忍"无 task 行 + 题库就绪"。
- **不要给新表加 CHECK 约束**（N11 锁定）：actor_type/status 枚举在 helper/代码层校验，避免未来 ALTER 重建。
- **不要把 admin 写豁免做进 helper 默认路径**：写操作 owner-only 是硬边界，helper 的 admin 豁免参数只用于读。
- **不要在新代码里绕过 `call_llm_json`/不写 trace**（强约束 ③）：本阶段无新 LLM 调用点，评分报告链复用既有调用。
- **不要在事件写入点持写事务调 LLM**：两条既有模式二选一（先 commit / 内存算完单事务落库）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| append-only 强制 | 自制"只插入"标志位 / 只靠代码约定 | SQLite `BEFORE UPDATE/DELETE` 触发器 `RAISE(ABORT)` | DB 级强制，测试可直接证明拒绝（成功标准 4）；触发器机制已实测 |
| 取号并发安全 | 分布式锁/单独计数表 | 同事务 `MAX+1` + `UNIQUE(session_id, sequence_no)` | 单进程 SQLite 单写者下同事务取号天然安全，UNIQUE 兜底；SSOT §13.1 明文 |
| 串行评分报告 | 新队列系统/job 表 | 现有 `BackgroundTasks` + 前端轮询 | D-005 锁定单进程形态；TestClient 下同步执行已实测，测试无需异步设施 |
| 越权判定 | 每路由手写各异的 WHERE | 两个共享 helper 单点封装 | 8 条路由语义一致，避免漏接/漂移（D-02） |
| 管理员待办 | 新建待办表/新路由 | 扩展 `GET /api/admin/todos` 聚合 | D-13：扩展现有入口，前端零破坏 |
| 题库生成状态 | 从 llm_trace/时间戳推断 | `question_bank_task` 显式状态行 | D-12 已否决推断式（生成中与缺题不可分） |

**Key insight:** 本阶段全部四项都有"现有形态可复用"的锚点——触发器复用 SQLite 能力、串行链复用 BackgroundTasks、待办复用 todos、取号复用 UNIQUE 约束。任何引外部队列/ORM/权限框架的做法都违反 D-005 与"Simplicity First"。

## Runtime State Inventory

> 本阶段含新表 DDL 追加 + 状态迁移点接入，按 Step 2.5 逐类盘点（rename/refactor 混合型阶段）。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `data/app.db`（gitignored，dev 库）：现有 18 表数据不受影响；新表 `assessment_state_event`/`question_bank_task` 建于既有库（`CREATE IF NOT EXISTS` 幂等，init_db 启动自动补建）。**存量已完成的 session/report/question_score 无事件行**（回放不完整属预期——事件从 Phase 1 起新会话开始记录） | 无数据迁移；代码 edit only |
| Live service config | 无外部服务配置存 DB（n8n/Datadog 类不存在）；llm_trace/report_json 均在库内随代码演进 | None — verified（架构图：唯一外部依赖是 DeepSeek API，走 env 不走 DB 配置） |
| OS-registered state | 无 Task Scheduler/launchd/pm2 注册项；uvicorn 单进程手动起 | None — verified（CONCERNS.md 无相关记录；部署形态 D-005） |
| Secrets/env vars | `.env`（gitignored）：`DB_PATH/LLM_PROVIDER/LLM_API_KEY/JWT_SECRET` 等键名**不变**；本阶段不新增 env 键（readiness/事件无新配置项；SSOT §31 开放参数禁止臆造默认值） | None — 代码不改 env 契约 |
| Build artifacts | `web/dist`（若已 build）：router meta 与 PositionAssess.vue 改动后需 `npm run build` 才反映到演示形态；`data/app.db` 的 SQLite 连接文件锁：运行中进程在 DDL 追加时重启即可；无 pip egg-info（项目未以包安装） | 演示前 rebuild 前端（计划收尾步骤）；后端重启加载新 DDL |

**核心问题回答**：改完仓库文件后，仍有旧状态的运行时 = ①正在跑的 uvicorn 进程（需重启加载新 DDL/路由）；②`data/app.db` 旧会话缺事件行（预期、不补）；③`web/dist` 旧构建（需 rebuild）。均已在计划内，无隐藏运行时。

## Common Pitfalls

### Pitfall 1: TestClient 同步执行 background task——写断言时别按异步想象
**What goes wrong:** 以为 `POST /report` 返回 202 后需要 sleep/轮询才能查 report 表。
**Why it happens:** 生产语义是异步，直觉按异步写测试。
**How to avoid:** 本机实测（FastAPI 0.141.1 / Starlette TestClient）：`BackgroundTasks` 在响应返回前同步跑完——断言直接查库即可。前端（真实浏览器）仍走轮询，不受影响。
**Warning signs:** 测试里出现 `time.sleep`。

### Pitfall 2: 触发器随 DROP TABLE 消失 + 重复 DDL 报错
**What goes wrong:** ①未来任何"表重建迁移"若碰事件表，触发器保护静默消失（实测：DROP TABLE 连带删触发器）；②`CREATE TRIGGER`（无 IF NOT EXISTS）重复执行报 "already exists"。
**Why it happens:** SQLite 触发器绑定表对象；executescript 部分失败留下半套 DDL。
**How to avoid:** 全部用 `CREATE TRIGGER IF NOT EXISTS`（实测支持）；事件表永远不做重建式迁移（Phase 6 schema_version 体系登记此约束）。
**Warning signs:** init_db 二次调用报 OperationalError；迁移函数里出现 DROP TABLE assessment_state_event。

### Pitfall 3: readiness 检查打挂存量测试种子
**What goes wrong:** 检查要求"必须有 SUCCEEDED 的 task 行"才可开考 → m5/m6 测试（直插 question_bank 行、无 task 行）全部 409，现有套件红。
**How to avoid:** 判定顺序：先看题库实际可选题量（沿用 `select_questions_for_session` 同口径），task 行仅用于区分 GENERATING 与 INCOMPLETE；"无 task 行 + 题库足量"→就绪。
**Warning signs:** 新检查合入后 `test_m5_backend.py` 的 session 创建测试失败。

### Pitfall 4: m5 现有断言与 completed 护栏直接冲突
**What goes wrong:** `test_m5_backend.py:257-258` 在 finish 后调 POST /score 并断言 200——护栏生效后必 409。
**Why it happens:** 该断言恰是 REF-8.2 指出的"可重复评分"缺陷的行为固化。
**How to avoid:** plan 必须包含"重写该断言为 409"任务（只改断言，不重构）；同理核查 `eval/virtual_candidates.py:136`（先置 completed 再 score——需把 score 挪到置 completed 之前，一行顺序调整）。m6 `_seed_full_chain` 插的是 in_progress 会话，直调 score_session 不受影响（已核对）。
**Warning signs:** 护栏合入后 m5/eval 任何评分断言失败。

### Pitfall 5: 越权 helper 漏接 submit_feedback 的 report→session 所有权链
**What goes wrong:** submit_feedback（:297）只校验 report 存在 + item 存在，不校验 report 属于当前用户；若只给 session 类路由接 helper 而忘了 feedback 经 report→session 的间接所有权，矩阵测 candidate B 给 A 的 report 提反馈会失败（仍 201）。
**How to avoid:** helper 覆盖清单按本研究"8 条路由矩阵"逐条对账；feedback 用 `load_owned_report`（写操作，owner-only）。
**Warning signs:** 矩阵中 feedback 越权用例返回 201。

### Pitfall 6: 事件写入与 SQLite 单写者纪律冲突
**What goes wrong:** 在答题链/评分链中途插事件行且在 LLM 调用前未 commit → `database is locked`（llm_trace 用第二连接写库）。
**Why it happens:** 事件插入点天然在迁移事务里，容易顺手写在 LLM 调用之前。
**How to avoid:** 两条既有模式二选一：用户消息 + 事件先 commit 再调 LLM（assessment.py:167 模式）；或后台链内存算完单事务落库（scoring.py:107 模式），事件与快照同事务。
**Warning signs:** 测试偶发 `sqlite3.OperationalError: database is locked`。

### Pitfall 7: 409 detail 形态前后端不一致
**What goes wrong:** 后端 detail 用 dict `{error_code, message}`，前端 `PositionAssess.vue` catch 取 `e.response?.data?.detail` 当字符串展示 → 显示 `[object Object]`。
**How to avoid:** 前端取 `detail?.message || detail`（兼容两形态）；测试只断言 `detail.error_code`。前端实际调用点在 PositionAssess.vue（非 Positions.vue——CONTEXT 集成点清单有小误，见 Pattern 5 说明）。
**Warning signs:** 页面提示出现 `[object Object]`。

### Pitfall 8: 单文件单进程测试纪律
**What goes wrong:** 新测试文件与现有文件在同一 pytest 进程收集 → DB_PATH 首个 import 生效，后续文件静默共享别人的库；或新测试函数带参数被 pytest 当 fixture。
**How to avoid:** 新文件按 M5 头部模板（env 先于 import、`init_db()`、TestClient、`sys.path.insert`）；函数无参；一次只跑一个文件。所有 Phase 1 测试可合并在 1-2 个新文件（如 `test_p0_security.py`、`test_p0_chain.py`）——研究建议按 plan 分两个文件避免单文件过大，但**必须各自独立可跑**。
**Warning signs:** 测试只在单独跑时通过、合跑时挂。

### Pitfall 9: score_session 幂等注释与新护栏语义打架
**What goes wrong:** `score_session` 现注释"幂等：重打先删旧行"（scoring.py:108）——护栏后 completed 不可重打，注释不更新会误导后来者。
**How to avoid:** 改护栏时同步改 docstring（"幂等"语义收窄为 in_progress 内重复调用）；这是 D-09 断言重写的伴生小改。
**Warning signs:** 代码评审发现"幂等"字样与 409 行为矛盾。

> **勘误（2026-09-03，checker W-4/B-1）：** `test_m6_backend.py:250-254`（_test_report_idempotent）与 `services/report.py:90` docstring 的"幂等：同会话重复生成覆盖旧行"均为**服务层直调 generate_report 的证据**——不经 API 层，**不构成 request_report 端点重入语义的依据**。据此，request_report 对 completed 会话的裁决按三分支（非 completed→409；completed 且已有 report 行→409；completed 且无 report 行→202）执行，详见 01-03-PLAN.md interfaces 护栏语义裁决。本注记不改变本文件的其余行文与结构。

### Pitfall 10: admin"只读豁免"误伤 admin 自己的测评
**What goes wrong:** route guard 修复（D-04）后 admin 可进入测评页并完成测评（后端允许任何登录用户 create_session）；若 admin 读自己的会话，helper 的 owner 分支必须覆盖 admin 本人资源（admin 既是 admin 又是 owner）。
**How to avoid:** helper 判定顺序：`user_id == current` 恒通过（无论角色）；仅当非 owner 时才看 admin 读豁免。矩阵加一条"admin 访问自己创建的 session/report"用例。
**Warning signs:** admin 完成测评后查报告 404。

## Code Examples

### 越权矩阵测试骨架（M5 风格，pytest 可收集）
```python
# server/test_p0_security.py（新文件）。运行：cd server && python -m pytest test_p0_security.py -v
import os, sys, tempfile
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_p0.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient  # noqa: E402
from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
init_db()
client = TestClient(app)

# 种子：两个 candidate（A/B）+ admin + A 的完整链（复用 m5 的 _seed_* 模式）
# 矩阵最小用例集（断言粒度 plan 定）：
# 1) B GET /sessions/{A的sid}           → 404
# 2) B POST /sessions/{A的sid}/answer  → 404（写越权，非 409）
# 3) B POST /sessions/{A的sid}/score   → 404
# 4) B POST /sessions/{A的sid}/report  → 404
# 5) B GET /reports/by-session/{A的sid} → 404
# 6) B GET /reports/{A的rid}           → 404
# 7) B POST /reports/{A的rid}/feedback → 404（admin 写同样 404）
# 8) B POST /sessions/{A的sid}/forms/submit → 404
# 9) admin GET 上述读端点              → 200（读豁免）
# 10) admin POST answer/forms/feedback → 404/拒绝（写 owner-only）
# 11) A 本人全链                        → 200/201（正常主链不回归）
# 12) admin GET /api/admin/trace/by-session/{A的sid} → 200（完整 trace，既有路由）
```

### append-only 拒绝测试（成功标准 4 的直接证明）
```python
import sqlite3
def test_event_table_rejects_update_delete():
    # 种一条事件行后（走真实业务流或 append_event 直插）
    conn = get_conn()
    row = conn.execute("SELECT id FROM assessment_state_event LIMIT 1").fetchone()
    if row is None:  # 无事件行时先通过 API 建会话产生 SESSION_CREATED
        ...
    try:
        conn.execute("UPDATE assessment_state_event SET event_type='x' WHERE id=?", (row["id"],))
        assert False, "UPDATE 应被触发器拒绝"
    except sqlite3.IntegrityError as e:
        assert "append-only" in str(e)
    try:
        conn.execute("DELETE FROM assessment_state_event WHERE id=?", (row["id"],))
        assert False, "DELETE 应被触发器拒绝"
    except sqlite3.IntegrityError:
        pass
    conn.rollback()
```
[VERIFIED: 本机实测同款触发器行为——UPDATE/DELETE 均抛 IntegrityError]

### 主链修复端到端断言（成功标准 2，不再 Python 直调掩盖）
```python
def test_ui_main_chain_score_report_serial():
    # 候选人经 API 完成整场答题（finish）→ 不调 POST /score → 直接 POST /report
    # TestClient 下 background 同步执行完毕：
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=A_headers)
    assert r.status_code == 202
    # 评分与报告均已落库——零步断裂修复的直接证明：
    assert _q("SELECT COUNT(*) c FROM question_score WHERE session_id=?", (sid,))[0]["c"] > 0
    rpt = client.get(f"/api/assessment/reports/by-session/{sid}", headers=A_headers).json()
    assert len(rpt["radar_data"]["indicators"]) > 0          # 雷达不再空
    assert all(not it.get("no_data") for it in rpt["item_details"] if not it.get("gate"))
    # completed 护栏（成功标准 5）：
    assert client.post(f"/api/assessment/sessions/{sid}/score", headers=A_headers).status_code == 409
    assert client.post(f"/api/assessment/sessions/{sid}/report", headers=A_headers).status_code == 409
```

### 开考检查失败矩阵（成功标准 3）
```python
# 三状态各自可触发的种子形态：
# GENERATING：confirm 后插 task 行 status=QUEUED/RUNNING（或 mock 模式下确认 BackgroundTasks 时序）
# INCOMPLETE：task=SUCCEEDED 但题库只有 1 题（配额不满）/ required item 无题
# MODEL_NOT_MEASURABLE：confirmed 模型 items 为空
r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=h)
assert r.status_code == 409
assert r.json()["detail"]["error_code"] == "QUESTION_BANK_GENERATING"
# 且不创建会话：
assert _q("SELECT COUNT(*) c FROM assessment_session WHERE position_id=?", (pid,))[0]["c"] == 0
# 管理员待办：GET /api/admin/todos 含新键
todos = client.get("/api/admin/todos", headers=admin_h).json()
assert todos["question_bank_not_ready"] >= 1
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 越权=只查 ID 存在（现状） | 单查询 `WHERE id AND user_id`（admin 读 OR 豁免） | 本阶段 D-01/D-02 | 8 路由一处 helper 收口 |
| 报告链无评分（零步断裂） | request_report 入口链 score→report | 本阶段 D-08 | 真实 UI 报告有数据 |
| 0 题会话静默开考 | readiness 三态 409 + todos | 本阶段 D-11~13 | 杜绝空测评 |
| 无事件留痕 | 触发器 + append_event | 本阶段 D-05~07 | 全链可审计 |
| score_session 无状态护栏 | 服务层 completed/in_progress 护栏 | 本阶段 D-09 | 防重复评分/报告 |

**Deprecated/outdated（本阶段不处理、避免误碰）：**
- `config.CATEGORY_RATIO`（55/20/20/5 旧口径）：Phase 2 REF-5.7 作废——**本阶段开考检查的"配额可行"必须用现行 CATEGORY_QUOTA 口径**（D-11 原文），不要提前切 7:3。
- `question_score.final_score` 与 `score_live*0.5` 合成：Phase 2 REF-5.1 废除，本阶段评分逻辑一行不动。
- `@app.on_event("startup")` 弃用警告：Phase 6 再说。
- FormCard 的 `GET /forms/{id}` 缺路由：Phase 3 表单链，与本阶段 readiness 的"表单 schema no-op 位"呼应但**不实现**。

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `question_bank_task` 无 admin UI 展示要求（D-13 只要求 todos 数据键就位；admin 页展示留 Phase 4） | Pattern 5 | 若用户期待 Phase 1 就有 admin 可见 UI，则缺一小块前端工作；数据层不受影响 |
| A2 | 409 detail 采用 dict `{error_code, message}` 形态（CONTEXT 未锁定 detail 具体形状；测试只断言 error_code 故两形态皆满足 D-13） | Pattern 5 | 若 plan 选纯字符串 detail + 顶层 error_code 字段，前端取值路径需同步调整；无功能风险 |
| A3 | 事件命名采用 SESSION_CREATED/SESSION_COMPLETED/QUESTION_ANSWERED 等按 §13.2 枚举组取名的近似；§13.2 定稿要求"每个事件注明必填字段/是否计题量/是否计时/是否需人工"——Phase 1 只写发生过的迁移点，具体 event_type 字符串以 §13.2 枚举对照为准（SESSION_* 有 CREATED 无 ANSWERED 变体，question 级用 QUESTION_* 组） | Pattern 2 | 事件名与后续 Phase 语义不一致时需补偿事件/命名修正；表结构不受影响 |
| A4 | eval/virtual_candidates.py 先置 completed 再 score 的顺序会撞护栏，允许一行顺序调整（属测试资产适配，非业务代码改动） | Pattern 4 / Pitfall 4 | 若用户认为 Phase 1 不许碰 eval/，则虚拟考生后台功能（admin 测试中心）在护栏生效后失效直至 Phase 6 |

**其余全部关键论断均 [VERIFIED]（本仓库代码直读或本机实测）或 [CITED]（SSOT/CONTEXT 原文）。** 无需用户确认即可进入 plan 的：所有权 404 语义、helper 覆盖 8 路由、触发器方案、串行落点、护栏位置、readiness 骨架——全部为 CONTEXT.md 锁定决策。

## Open Questions

1. **SESSION_ENTERED_SCORING 的 from/to 取值（D-10 快照无 SCORING 态的前提下的迁移事件写法）**
   - What we know: §13.1 要求"状态迁移事件必填 from/to"但 D-10 不加 SCORING 快照态；SESSION_ENTERED_SCORING 出现在 §13.2 SESSION_* 组。
   - What's unclear: 该事件是"迁移事件"（必填 from/to）还是"事实类事件"（允许空）——SSOT 未逐事件标注（定稿要求尚未完成）。
   - Recommendation: plan 阶段按"事实类事件"处理（from=in_progress, to=in_progress 或均留空），在事件行 payload_json 注明背景；不阻塞表结构。A3 同源，若用户对事件语义有更强意见可在 plan review 提。
2. **admin 写拒绝的 HTTP 码**
   - What we know: D-03 锁定 admin 写一律拒绝；D-01 锁定 404 用于越权候选。
   - What's unclear: admin（已通过 require_admin 的合法高权限角色）写他人资源，语义上是"资源不存在"（404，与 candidate 同路径）还是"权限不足"（403）——D-01 的"不引入 403 分支"字面覆盖了这一情形（统一 404）。
   - Recommendation: 遵循 D-01 字面：统一 404，不再引入 403 分支。测试矩阵相应断言 admin 写 → 404。若 plan 觉得需要 403 再回到 discuss。
3. **`GET /api/assessment/sessions/{session_id}` 的 admin 读豁免是否与"admin 可查完整 trace"合并理解**
   - What we know: trace 已有独立 admin 路由（trace.py by-session）；SSOT §7 说 admin"可读取候选人数据"。
   - What's unclear: admin 是否需要经候选人端点读 session/report 明细（比如未来 admin 查看会话详情页），Phase 1 无此 UI。
   - Recommendation: helper 读豁免已按 D-02/D-03 实现admin 读全通过（无 UI 消费也无害）；无需额外工作。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | 后端全部 | ✓ | 3.13.2 | — |
| SQLite（stdlib sqlite3） | 事件表/触发器/新表 | ✓ | 3.45.3（支持 IF NOT EXISTS 触发器、RAISE(ABORT)） | — |
| FastAPI | API 层 + TestClient | ✓ | 0.141.1 | — |
| pytest | 新测试矩阵 | ✓ | 9.1.1 | — |
| passlib/bcrypt | 测试种子用户 | ✓ | requirements 锁 bcrypt<4.1 | — |
| Node.js/npm | 前端 router meta + Positions/PositionAssess 提示改动验证 | ✓ | v24.13.0 / npm 11.6.2 | — |
| uvicorn | 手动验证主链（可选） | ✓ | 0.52.4 | — |
| DeepSeek API | 无需（mock 模式覆盖全部测试） | 不适用 | — | LLM_PROVIDER=mock（config 默认） |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none（外部 LLM 不需要：mock 模式确定性覆盖；D-027"mock 回归不能替代真实 LLM 验证"属 Phase 6 验收口径，不阻塞本阶段实现与测试）

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + FastAPI TestClient（httpx） |
| Config file | none — 默认收集；单文件单进程纪律靠约定（无 pytest.ini/conftest.py，Phase 6 REF-7.4 才统一） |
| Quick run command | `cd server && python -m pytest test_p0_security.py -v`（单文件） |
| Full suite command | 逐文件：`python -m pytest server/test_p0_security.py -v` → `test_p0_chain.py` → `test_m5_backend.py` → `test_m7_backend.py`；脚本式：`python server/test_m6_backend.py`、`python server/test_question_bank.py`（**不得**一次 pytest 收多文件） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REF-1.1/1.2 | 越权矩阵：candidate↔candidate 读写 8 路由全 404；admin 读豁免/写拒绝；owner 正常链不回归 | integration（TestClient API 级） | `cd server && python -m pytest test_p0_security.py -v` | ❌ Wave 0（新建） |
| REF-1.5/2.2 | append-only：UPDATE/DELETE 被触发器拒绝；from/to 必填迁移事件落库；actor_type 非法值被 helper 拒 | unit+integration | `python -m pytest test_p0_security.py -v`（事件断言节） | ❌ Wave 0 |
| REF-5.10 | 主链串行：API 完成答题→POST /report→question_score>0 + 报告雷达非空（不 Python 直调掩盖） | integration | `cd server && python -m pytest test_p0_chain.py -v` | ❌ Wave 0 |
| REF-8.2 | completed 护栏：再调 /score、/report → 409；in_progress 直调 score 亦 409（服务层） | integration | 同上 | ❌ Wave 0 |
| REF-3.5/8.5 | 开考检查：三状态 409 + error_code + 不建会话 + todos 新键；存量种子（无 task 行）不误伤 | integration | `python -m pytest test_p0_chain.py -v`（readiness 节） | ❌ Wave 0 |
| REF-1.1 回归 | 现有套件不回归：m5（含断言重写后）/m7 全绿 | regression | `python -m pytest server/test_m5_backend.py -v`（单独跑） | ✅（需改 257-258 断言） |
| REF-5.10 回归 | m6 脚本改断言后仍过 | regression | `python server/test_m6_backend.py` | ✅（需随 D-09 重写断言） |

### Sampling Rate
- **Per task commit:** 受影响单测试文件（<30s，mock 模式离线）
- **Per wave merge:** 全套件逐文件跑（m5/m7/m6/question_bank + 两个新 p0 文件）+ `python -m scripts.seed_admin` 冒烟（可选）
- **Phase gate:** 全绿后 `/gsd:verify-work`；成功标准 1–5 逐条有测试证明

### Wave 0 Gaps
- [ ] `server/test_p0_security.py` — 越权矩阵 + append-only 触发器拒绝 + actor_type 校验（REF-1.1/1.2/1.5/2.2）
- [ ] `server/test_p0_chain.py` — 主链串行 + completed 护栏 + 开考检查三态 + todos（REF-5.10/8.2/3.5/8.5）
- [ ] `server/test_m5_backend.py` — 修改而非新建：257-258 评分断言改 409（Pitfall 4）
- [ ] `server/test_m6_backend.py` — 修改而非新建：直调断言按护栏语义核对/重写（D-09；已核 seed 为 in_progress，多数断言不受影响，需逐条过）
- [ ] 无需安装框架（pytest/TestClient 均已在环境中）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（本阶段不改认证；JWT/登录现状保持） | 既有：python-jose HS256 + require_login（security.py） |
| V3 Session Management | no（无会话管理改动） | 既有 12h token 过期 |
| V4 Access Control | **yes（本阶段核心）** | 资源级所有权校验：单查询 `WHERE user_id=current` + 404 统一语义 + admin 只读豁免/写拒绝（D-01~03）；后端执行为权威（SSOT §7） |
| V5 Input Validation | 部分 | 开考检查对 position_id 的存在性校验沿用既有 422/404；本阶段无新输入面 |
| V6 Cryptography | no（不改密码/token） | 既有 passlib bcrypt |

### Known Threat Patterns for FastAPI + SQLite + JWT Bearer

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR（不安全直接对象引用）——候选人枚举他人 session/report ID | Information Disclosure / Elevation | 本阶段核心修复：8 路由所有权 WHERE 兜底；404 统一防存在性枚举（ID 为 uuid4 hex 12 位不可枚举） |
| 权限提升（candidate 打 admin 端点） | Elevation | 既有 require_admin 每请求 DB 复查 is_active/role（security.py:33-47，CONCERNS 已确认正确） |
| 重复评分/报告篡改（completed 后重打分覆盖） | Tampering | 服务层状态护栏（completed→409）；事件表 append-only 留痕 |
| 事件表篡改（抹痕） | Repudiation | BEFORE UPDATE/DELETE 触发器 RAISE(ABORT) + 测试证明；纠错只走补偿事件（D-006/D-019） |
| SQL 注入 | Tampering | 既有 `?` 参数化全库强制（CONVENTIONS）；新 helper/检查函数沿用，禁止值插值 |
| 0 题会话（业务完整性） | Tampering | readiness 检查 409 阻断 + 管理员待办（D-017） |
| JWT secret 默认值 | Spoofing | **不在本阶段**（REF-6.2 Phase 6；CONCERNS 已登记"change-me-in-.env"风险，plan 不得顺手修——Surgical Changes） |
| Prompt injection | Tampering | **不在本阶段**（REF-6.4 Phase 3；本阶段无新 LLM 面） |

**注**：`config.py:16` 的 JWT_SECRET 默认值与 `schemas.py:11` 的 1 字符密码下限均为已知安全债（CONCERNS.md 记录在案），按 REQUIREMENTS 排期属 Phase 6/原样保留——本阶段**不修**，避免范围蔓延；越权矩阵会间接暴露"默认 secret 可伪造 admin token"的测试前提（测试设 JWT_SECRET=test-secret 规避）。

## Sources

### Primary (HIGH confidence)
- `server/api/assessment.py`（全文 318 行直读）— 8 条路由现状、request_report/BackgroundTasks 形态、answer 链 commit 点
- `server/db.py`（全文直读）— _DDL 18 表、get_conn、init_db 幂等模式、嗅探式迁移现状
- `server/services/scoring.py` / `report.py` / `question_bank.py` / `question_selection.py` / `interview.py` / `aggregation.py`（直读）— 内存算完单事务、幂等注释、生成幂等跳过、finish 规则、配额口径
- `server/core/security.py`（直读）— require_login 返回形状（user_id/role/is_active）
- `server/api/admin/positions.py` / `models.py` / `trace.py`（直读）— todos 聚合、confirm 触发点、by-session trace
- `web/src/router/index.js` / `api/index.js` / `utils/sse.js` / `views/assessment/Positions.vue` / `PositionAssess.vue` / `Report.vue`（直读）— route meta 现状、无 score 方法证据链、409/detail 前端消费、createSession 实际调用点
- `design/final-design/总设计文档.md` §3/§4/§5/§7/§10.4/§13.1-13.2/§21.1/§28/§30-31（直读）— 全部契约原文
- `.planning/phases/01-p0/01-CONTEXT.md`（直读）— D-01~D-13 锁定决策全文
- `research/ssot-code-gap-matrix.md`（直读）— REF-1.1/1.5/2.2/3.5/5.10/8.2/8.5 行证据
- `.planning/codebase/ARCHITECTURE.md` / `CONCERNS.md` / `TESTING.md` / `CONVENTIONS.md` / `STACK.md`（直读）— 测试纪律、反模式、惯例
- `server/test_m5_backend.py` / `test_m6_backend.py` / `test_m7_backend.py` / `eval/consistency_test.py` / `eval/virtual_candidates.py`（直读）— 断言冲突点核对（Pitfall 4）
- **本机实测验证**（Python 3.13.2 / SQLite 3.45.3 / FastAPI 0.141.1）：触发器 RAISE(ABORT) 拒绝 UPDATE/DELETE、CREATE TRIGGER IF NOT EXISTS 幂等、DROP TABLE 连带删触发器、UNIQUE 索引兜底取号、TestClient 下 BackgroundTasks 同步执行、HTTPException dict detail 序列化

### Secondary (MEDIUM confidence)
- 无（未用 WebSearch——本阶段为仓库内修复型工作，无外部库/框架选型问题，全部机制本机可验证）

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新增依赖；既有栈版本全部本机实测
- Architecture: HIGH — 四项落点全部有 CONTEXT 锁定决策 + 代码直读交叉核对；关键机制（触发器/同步 background/取号）本机实证
- Pitfalls: HIGH — 10 项坑中 6 项（Pitfall 1/2/3/4/5/7 的触发条件）来自代码逐行核对或实测复现；Pitfall 3/4 的测试冲突点已核对到具体行号
- 事件语义（A3/开放问题 1）: MEDIUM — §13.2 未逐事件定稿，SESSION_ENTERED_SCORING 写法留 plan 决策

**Research date:** 2026-09-02
**Valid until:** 与代码库同生命周期（仓库内修复型阶段，无外部依赖时效性问题；SSOT v2.0 变更后本文件需按 §14 变更记录重核）
