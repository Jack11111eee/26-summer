# Phase 5: 证据链与报告契约 - Research

**Researched:** 2026-09-05
**Domain:** 评分→聚合→报告→反馈链的可审计契约收口（evidence spans / trace_link 审计链 / item 裁决与补算 / 报告状态机与版本化 / feedback 审计字段）
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

> D-55~D-67 为 Phase 5 编号（接续 04 的 D-47~D-54）。auto 模式（章程 §1）推荐项选取，逐条依据 = SSOT 条款/既定决策/代码现状三者之一。

#### 证据 span 结构化（REF-2.10，计划 05-01）

- **D-55: evidence_spans 结构化 = LLM 给 quote 文本、代码定位 offset/hash（D-003「LLM 不碰数字」）。** question_score 新增 `evidence_spans_json` 列（list of `{source_message_id, source_content_type(raw|refined), start_offset, end_offset, quote_hash}`）。P-score 继续输出 `evidence_quote`（文本），代码在 assessment_message 中定位该 quote 计算 start_offset/end_offset（Unicode code point，§12.5）与 quote_hash（确定性 hash）；定位失败（mock 占位 / LLM 改写非原文）→ 降级为 `quote_hash` only + `source_message_id=NULL`。`evidence_quote` 列保留（展示 + 后向兼容），`evidence_spans_json` 为结构化权威。客观题 evidence_quote = `answer_text[:60]`（answer_key 命中的回答片段），span 同理按定位填充。

#### trace_link 统一审计链（REF-2.3/REF-8.7，计划 05-01）

- **D-56: trace_link 新表（§13.3 DDL 照抄）+ link_role 枚举代码校验（N11）。** `trace_link(id, trace_id, entity_type, entity_id, link_role, created_at, UNIQUE(trace_id, entity_type, entity_id, link_role))`，link_role ∈ `{input|output|caused_by|scored|reported|source}`。业务表不逐一加 trace 外键；审计链 report→session→model/version→question→message→score→trace 通过 trace_link 闭合。**trace_id 取值与各环节写点 = Claude's Discretion（planner 定）**，但五要素（report/session/model/version/question/score/trace）必须可达。

- **D-57: 旧 ref_id 导入 trace_link（REF-8.7）= 迁移函数把 llm_trace.ref_id 拆为 entity_type + entity_id 导成 trace_link 行。** 迁移按 call_type 推断 entity_type（extract/disambiguate/aggregate_level → 模块一域；question_gen/interviewer/refine/score → session/question 域；report → report 域）。llm_trace.ref_id 列保留（trace 查看器 admin/trace.py 不破坏），trace_link 为新增统一关联层。

#### item_measurement 统一裁决（REF-5.4，计划 05-02）

- **D-58: item_measurement = 内存统一测量记录（非新表——D-018「21 张表」清单无它）。** §19 pseudocode 落地为 aggregation.py 内中间结构 `(question_id, item_id, observed_level, evidence_refs, measurement_source: ordinary|integrated)`；普通题 → `ordinary`，综合题 `integrated`（本期无综合题，列位预留）。`item_final_level = adjudicate(...)` 替换现行 `actual = sum(finals)/len(finals)`（按题数均分，REF-5.4 明令废弃）：按 rubric/覆盖/稳定性/冲突裁决，**不按来源加权、不按题数重复乘 item.weight**；重大冲突取较低值 + 人工复核标记（human_review 列位）。

#### IMPUTED 补算 + required 缺失（REF-5.5/REF-5.6，计划 05-02）

- **D-59: IMPUTED 补算 = §20.1 公式代码化 + 覆盖率展示 + O=∅ → NO_VALID_OBSERVATION。** `r = Σ(i∈O) w_i×s_i / Σ(i∈O) w_i`（s_i=(score−1)/4）；缺失普通 item 补算值 = r，标记 IMPUTED；IMPUTED 参与总分/雷达但特殊视觉标记 + 展示观察覆盖率/真实观察数/缺失原因；O=∅ → 不能补算 → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED；required 与 qualification 不补算（§20.1）。**补算比例超阈值 → 临时报告 + 人工复核，阈值 = §31-3 开放参数 → 关口包呈报项（不臆造）**。

- **D-60: required 缺失 → report_status=PROVISIONAL + review_status=HUMAN_REVIEW_REQUIRED（§20.2）。** 判定 = required item 在观察集合 O 中缺失（未 SCORED 且补算不适用）；不触发补测；人工确认后可发布为正式报告（必须明确点击发布）；系统不做录用判断。

#### 报告状态机 + 发布 + 版本化（REF-5.9/REF-8.3，计划 05-03）

- **D-61: report 表演进 = 加 report_status/review_status/version + 发布与人工复核字段。** report_status: `GENERATING → PROVISIONAL|READY → PUBLISHED|FAILED`；review_status: `NONE|REQUIRED|IN_PROGRESS|CONFIRMED|CLOSED`；版本字段 `version`（session 内递增）+ 发布字段（review_request_reason/reviewer_id/review_note/review_outcome/reviewed_at/publish_confirmed_by/published_at，§21.1）。覆盖生成 `DELETE FROM report WHERE session_id=?` + INSERT → 改为不可变版本化（新版本 INSERT 新行，旧行保留）。

- **D-62: 报告版本化 key = report_id 每版本新行（session 内多版本），feedback FK → 具体版本 report_id 天然防外键断裂。** 现行 report PK=report_id，`get_report_by_session` 已 `ORDER BY created_at DESC LIMIT 1` 取最新——版本化后同 session 多行仍取最新；feedback.report_id 已 FK → report_id，指向具体版本不悬空（旧行保留故不 DELETE）。**重复生成语义**：现行 `request_report` 对「已存在 report 行」409 拒绝——版本化后改为「允许重生成创建新版本」（REF-5.9 SC-3「重复生成不再 DELETE 覆盖」），409 仅保留给 GENERATING 进行中（防并发重入），具体边界 planner 定。

- **D-63: 七项一致性校验 = 代码执行（§21.1），任一失败 → report_status=FAILED。** 七项：数字可重算 / weight 总和一致 / 引用 question·message 属于该 session / model·version 与快照一致 / 无效题·系统错误未进正常分母 / IMPUTED·REFUSED·required 警告与结构化状态一致 / 文案无录用判断表述。校验在聚合后、生成 PROVISIONAL|READY 前执行；失败不生成正常报告（与 §17「评分失败 → FAILED，不得生成 0 分正常报告」同源）。

- **D-64: 发布流程 = 管理员显式 POST publish 端点（明确点击）+ 前端最小化（零破坏优先，沿用 Phase 4 [04-010] 先例）。** 后端 `POST /api/admin/reports/{report_id}/publish`（require_admin），校验 review_status 满足（required 缺失需 CONFIRMED 人工复核完成）→ report_status=PUBLISHED + publish_confirmed_by + published_at + REVIEW_REPORT_PUBLISH_CONFIRMED 事件。前端：状态机/发布按钮走**后端优先 + 最小前端**——report_status 字段与端点落库后，仅在既有 Report.vue 轮询里区分 GENERATING/FAILED（真实 FAILED 态替代超时猜测）；发布按钮并入 admin（TestCenter.vue 反馈 review 界面既有）。具体 UI 范围 planner 裁量，倾向后端完整 + 前端最小。

- **D-65: 报告生成失败显式可见（REF-8.3）= `_generate_report_task` 异常捕获 → report_status=FAILED 行落库 + TASK_FAILED 事件（保留）。** 现状异常静默（前端轮询 report 表为空 + 超时猜测失败）；改 = 异常捕获写 FAILED 报告行（report_json 含 error 摘要，str(e)[:200] 截断同 Phase 4 T-04-01）+ TASK_FAILED 事件留痕。前端 Report.vue 轮询读 report_status 确定性区分「生成中/失败」。

#### feedback 字段补全（REF-7.3，计划 05-04）

- **D-66: feedback 表补列 + admin note 持久化 + question_reviews 补 item_id。** feedback 加 `user_id`（submit 时从 require_login 取）/`note`/`reviewer`/`reviewed_at`；`review_feedback`/`mark_bad_case` 现有 `note` 入参被丢弃 → 补持久化 note + reviewer + reviewed_at；`submit_feedback` 校验 item 属于对应模型（现有 assessment.py:1124-1130 已做，保留不动）；question_reviews（report.json 逐题回顾，`_load_question_reviews`）补 `item_id` 列。

- **D-67: 审计字段 = REVIEW_* 事件（§13.2）落地。** feedback 提交 → `REVIEW_FEEDBACK_RECEIVED`；发布确认 → `REVIEW_REPORT_PUBLISH_CONFIRMED`。异议只进人工处理，永不触发改分（D-031）。

#### 开放参数（关口包呈报项 SSOT §31 类）

- **补算复核阈值（§31-3）**：IMPUTED 补算比例超阈值 → 临时报告 + 人工复核。plan 落 config 占位 + 常量注释标注「实施期校准」，**数值不代决**（同 N=10 / MAX_CONTEXT_TOKENS 先例，关口包列呈报项；若用户不裁决则维持 plan 占位默认）。

### Claude's Discretion
- trace_link 具体写点与 trace_id 取值（session 级关联 vs llm_trace.trace_id）
- evidence_spans 定位算法（quote 在 raw/refined 中的子串定位 + 多命中策略 + hash 算法 sha256 规范化）
- item_measurement 中间结构字段命名与 adjudicate 裁决规则实现（§19 冲突取低 + 人工标记的具体代码形态）
- 报告版本号生成规则（session 内 MAX(version)+1 vs created_at 排序）
- 七项校验的代码实现形态与失败错误细分
- request_report 重复生成/409 的精确状态边界
- 测试组织（新 test_phase5_* 文件——沿用单文件单进程 + tempfile + mock 三件套纪律）

### Deferred Ideas (OUT OF SCOPE)
- trace 保留期/脱敏细节（§31-5）——Phase 6 数据治理
- 补算复核阈值的真实校准（§31-3）——实施期校准，关口包呈报
- 综合题 integrated measurement_source 的 item_measurement 实现（REF-3.9 延后）
- score_live/score_final 双分背离 bad case 自动候选（REF-5.11）——Phase 6
- admin 报告发布/人工复核的完整前端 UI（若本 phase 仅最小前端，完整 UI 随 Phase 6 E2E 收口）
- 报告版本的历史浏览/对比 UI（VersionHistory.vue 已存在，报告版本对比是否并入该 UI 属 Phase 6 E2E 收口裁量）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REF-2.3 | 新表 trace_link（统一审计链） | §13.3 DDL + D-56/D-57；Pattern 1（trace_link 建表 + 旧 ref_id 导入迁移） |
| REF-2.10 | 证据定位结构化（span/offset/quote_hash；hash 复用限单 session） | §12.5 + D-55；Pattern 2（evidence_spans 定位算法） |
| REF-5.4 | item_measurement 统一裁决（废弃按题数均分；冲突取低留人工标记） | §19 + D-58；Pattern 3（adjudicate 裁决） |
| REF-5.5 | 缺失补算 IMPUTED（r 比例 + 特殊标记 + 覆盖率；O=∅ → NO_VALID_OBSERVATION） | §20.1 + D-59；Pattern 4（IMPUTED 补算） |
| REF-5.6 | required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | §20.2 + D-60；Pattern 5（状态机推进） |
| REF-5.9 | 报告状态机 + review_status + 七项校验 + 明确点击发布 + 版本化 | §21.1 + D-61~D-64；Pattern 5/6（七项校验 + publish 端点） |
| REF-7.3 | feedback 补 user_id/note/reviewer/时间戳；question_reviews 补 item_id；submit_feedback 校验 item 属对应模型 | D-66/D-67；Pattern 7（feedback 字段 + REVIEW_* 事件） |
| REF-8.3 | 报告后台任务异常静默 pass（FAILED 态可见，前端可区分生成中/失败） | §17 + D-65；Pattern 5（FAILED 行 + TASK_FAILED 事件） |
| REF-8.7 | llm_trace ref_id 单字段弱关联（随 trace_link 落地迁移导入） | D-57；Pattern 1（旧 ref_id → trace_link 迁移） |
</phase_requirements>

## Summary

Phase 5 把模块三「评分→聚合→报告→反馈」链收口为可审计、可回溯的契约，是 SSOT §28 第 5 步（证据 span/trace_link 落地、报告发布校验、feedback 字段、报告版本化）的代码实现。九项 REF 分属四个计划（05-01 证据链 / 05-02 裁决与补算 / 05-03 状态机与发布 / 05-04 feedback）。

**改造对象均已精确定位**：`server/db.py`（question_score/report/feedback 三表演进 + trace_link 建表）、`server/services/scoring.py`（evidence_spans 生成点）、`server/services/aggregation.py`（adjudicate 替换 `sum/len` 均分 + IMPUTED）、`server/services/report.py`（七项校验 + 版本化 INSERT + 状态机推进）、`server/api/assessment.py`（FAILED 捕获 + 重复生成语义）、`server/api/admin/feedback.py`（note 持久化）、`server/api/admin/trace.py`（trace_link 消费）。

**核心不变式**（贯穿全 phase）：D-003 四条强约束（LLM 不碰数字——offset/hash/r 比例全部代码计算；人工唯一权威——发布必须显式点击；一切留痕——trace_link/事件/spans 落库；代码唯一状态机——report_status/review_status 全代码裁决）。SQLite 单写者两模式（「先 commit 再调 LLM」/「内存算完单事务落库」）在 scoring score_session 已有「内存算完单事务落库」先例，item_measurement 裁决层与 evidence_spans 定位沿用同一模式。

**Primary recommendation:** 四个计划严格串行（05-01 → 05-02 → 05-03 → 05-04），每计划独立 commit；aggregation 的 adjudicate/IMPUTED 与 report 的七项校验/状态机是同一事务内「内存算完单事务落库」；trace_link 与 evidence_spans 的写点一律走既有 `get_conn()` + 显式 commit + `append_event` 模式，不引入 ORM、不引入新外部包（quote_hash 用 stdlib `hashlib.sha256`）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| evidence_quote → structured span 定位（offset/quote_hash） | API/Backend（scoring.py 服务层） | — | 定位是确定性代码计算（D-003 LLM 不碰数字），发生在 score_question 拿到 evidence_quote 之后、score_session INSERT 之前 |
| trace_link 审计链闭合（写点 + 旧 ref_id 导入） | API/Backend（db.py 迁移 + 各服务写点） | — | 审计链是持久层统一关联，业务表不加 trace FK（D-020）；迁移函数注册于 init_db |
| item_measurement 裁决（adjudicate 替换均分） | API/Backend（aggregation.py） | — | 纯内存中间结构（D-58 非新表），在 score_session 产出 question_score 后、报告生成前 |
| IMPUTED 补算 + required 缺失判定 | API/Backend（aggregation.py） | — | r 比例 + 覆盖率 + O=∅ 判定全代码；provisional 标记回写 report 状态 |
| 报告状态机 + 七项校验 + 版本化 | API/Backend（report.py + db.py） | Browser（Report.vue 轮询读状态） | 状态机与校验代码唯一权威；前端只读 report_status 展示生成中/失败/就绪 |
| 发布端点（明确点击） | API/Backend（admin 路由） | Browser（admin UI 按钮） | require_admin + 代码校验 review_status 满足；前端只是触发器 |
| feedback 字段 + REVIEW_* 事件 | API/Backend（assessment.py + admin/feedback.py） | — | 审计字段随业务行同事务落库；事件走 append_event |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `hashlib` | 3.13 内置 | quote_hash 确定性 sha256 | 确定性 hash 无第三方依赖；D-55 要求「确定性 hash」，sha256 是唯一合理选择 |
| Python stdlib `json` / `re` / `sqlite3` | 3.13 内置 | spans JSON 序列化 / 子串定位 / raw SQL | 项目全栈 no-ORM raw SQL，沿用既有 `get_conn()` + 显式 commit |
| FastAPI + Pydantic v2 | 0.141.1 / 2.10.3 | publish 端点 + request body schema | 既有技术栈（D-005），发布端点复用 require_admin + BackgroundTasks |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| 既有 `server/services/state_events.py` `append_event` | — | REVIEW_FEEDBACK_RECEIVED / REVIEW_REPORT_PUBLISH_CONFIRMED / TASK_FAILED 事件 | 所有 REVIEW_*/TASK_* 事件走同一入口（§13.1 append-only） |
| 既有 `server/services/llm.py` `call_llm_json` | — | P-score/P-report 调用（trace 落库 + mock） | evidence_quote 与报告文字仍由 LLM 产文本，数字由代码算 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| quote_hash 用 `hashlib.sha256` | 自定义 hash / md5 | md5 弱、自定义无审计价值；sha256 唯一合理 |
| trace_link 用 llm_trace.trace_id 作 trace_id | 合成 audit id（report_id 等） | Claude's Discretion——llm_trace.trace_id 已存在且天然唯一，复用最省事；但 report/session 级关联无对应 trace 行时需合成 id（见 Open Question 1） |
| adjudicate 用 `statistics.median`/均值 | 自写冲突裁决 | §19 冲突取低留人工标记，无现成库满足「重大冲突取低」语义，需自写（见 Pattern 3） |

**Installation:**
```bash
# 无新外部包。本 phase 仅用 Python stdlib（hashlib/json/re/sqlite3）+ 既有 FastAPI/Pydantic。
# 不需要 pip install 任何新依赖。
```

**Version verification:** 已核实 Python 3.13.2、fastapi 0.141.1、pydantic 2.10.3、pytest 9.1.1 均在环境可用（见 Environment Availability）。quote_hash 依赖的 `hashlib.sha256` 为 stdlib，无需注册表验证。

## Package Legitimacy Audit

> **结论：本 phase 不安装任何新外部包。** 全部实现落在 Python stdlib（`hashlib`/`json`/`re`/`sqlite3`）+ 既有项目依赖（FastAPI 0.141.1 / Pydantic 2.10.3 / python-jose / passlib）。无 npm/PyPI 新包、无 postinstall 脚本风险面、无 slopcheck 验证需求。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| （无） | — | — | — | — | — | N/A — 无新安装 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                        ┌──────────────────────────────────────────────────┐
                        │  candidate submits objection (feedback)          │
                        └──────────────┬───────────────────────────────────┘
                                       │ POST /reports/{id}/feedback
                                       ▼
              ┌──────────────────────────────────────────────────────────┐
              │  assessment.py submit_feedback                            │
              │   load_owned_report → item∈model 校验 → INSERT feedback   │
              │   (user_id/note) + REVIEW_FEEDBACK_RECEIVED event         │
              └──────────────────────────────────────────────────────────┘
                                       │

  POST /sessions/{id}/report (202) ──► BackgroundTasks _generate_report_task
        │                                     │
        │ (guard: GENERATING 中 → 409)        ▼
        │                          ┌────────────────────────────────────┐
        │                          │ 1. score_session (allow_completed) │
        │                          │    └─ score_question per question  │
        │                          │       ├─ LLM P-score → evidence_quote│
        │                          │       └─ 代码定位 span → evidence_ │
        │                          │          spans_json + quote_hash    │
        │                          │    └─ 单事务 INSERT question_score  │
        │                          │       (+ rubric/scorer version)     │
        │                          │ 2. aggregate_session_scores         │
        │                          │    └─ item_measurement 内存裁决     │
        │                          │    └─ adjudicate (冲突取低+人工标记)│
        │                          │    └─ IMPUTED r 比例补算 (缺失 item)│
        │                          │    └─ required 缺失 → PROVISIONAL   │
        │                          │ 3. generate_report                  │
        │                          │    └─ 七项一致性校验 (任一失败→FAILED)│
        │                          │    └─ 版本化 INSERT (version+1 新行)│
        │                          │    └─ trace_link 写点 (report→…→trace)│
        │                          └────────────────────────────────────┘
        │                                     │ (异常 → FAILED 行 + TASK_FAILED)
        ▼                                     ▼
  get_report_by_session (ORDER BY created_at DESC LIMIT 1)
        │
        ▼
  ┌────────────────┐      POST /api/admin/reports/{id}/publish      ┌────────────────┐
  │ Report.vue 轮询 │ ◄───────────── (admin 明确点击) ──────────────► │ admin publish  │
  │ 读 report_status│                                              │ 校验 review_status│
  │ GENERATING/FAILED│                                             │ → PUBLISHED + 事件 │
  └────────────────┘                                              └────────────────┘
```

### Recommended Project Structure

```
server/
├── db.py                          # trace_link 建表 + report/feedback/question_score ALTER + 旧 ref_id 导入迁移
├── services/
│   ├── scoring.py                 # evidence_spans 定位生成点（score_question 内）
│   ├── aggregation.py             # item_measurement + adjudicate + IMPUTED + required 缺失标记
│   ├── report.py                  # 七项校验 + 版本化 INSERT + report_status 状态机推进 + trace_link 写点
│   └── trace_link.py              # [新] trace_link 写点 + 旧 ref_id 导入 + link_role 校验（建议独立服务）
├── api/
│   ├── assessment.py              # FAILED 捕获 + 重复生成语义 + submit_feedback 补 user_id
│   └── admin/
│       ├── feedback.py            # note 持久化（review/bad_case）
│       └── reports.py             # [新] POST /reports/{id}/publish 端点
└── test_phase5_*.py               # 新测试文件（单文件单进程三件套纪律）
```

### Pattern 1: trace_link 建表 + 旧 ref_id 导入迁移（REF-2.3/8.7，D-56/D-57）

**What:** 新增第 21 张表 `trace_link`（§13.3 DDL 照抄），迁移函数 `_migrate_trace_link` 注册于 `init_db` 收尾，把存量 `llm_trace.ref_id` 拆成 `(entity_type, entity_id)` 导入。
**When to use:** init_db 启动时一次；link_role 枚举 `{input|output|caused_by|scored|reported|source}` 代码校验（N11 无 DB CHECK）。
**Example:**
```python
# server/db.py — trace_link 表（§13.3 DDL 逐字照抄）
# link_role 无 DB CHECK（N11）；entity_type/entity_id 为弱关联（业务表不加 FK）
_DDL += """
CREATE TABLE IF NOT EXISTS trace_link (
  id          TEXT PRIMARY KEY,
  trace_id    TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id   TEXT NOT NULL,
  link_role   TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  UNIQUE(trace_id, entity_type, entity_id, link_role)
);
"""

# 旧 ref_id 导入（D-57）：以「能命中实体表」为准，命不中保留 ref_id 原值不拆
# call_type → 实体表映射：
#   extract/disambiguate/aggregate_level → jd_record / position / competency_model（模块一域）
#   question_gen/interviewer/refine/score → assessment_question / assessment_session（session/question 域）
#   report → report（report 域）
# 命中规则：逐实体表尝试 `SELECT 1 FROM <table> WHERE <pk>=ref_id`，命中即定 entity_type
```

### Pattern 2: evidence_spans 定位算法（REF-2.10，D-55）

**What:** score_question 拿到 LLM 返回的 `evidence_quote` 文本后，代码在回捞的原文（`_fetch_answer_text`）中定位子串，计算 `start_offset/end_offset`（Unicode code point）+ `quote_hash`（sha256）。Python `str` 索引天然按 code point 计数，`text.find(quote)` 直接返回 code point offset（无需 UTF-16 代理对处理）。
**When to use:** score_question 内，evidence_quote 非空且能在原文定位到时；定位失败降级为 `quote_hash` only + `source_message_id=NULL`。
**Example:**
```python
# server/services/scoring.py — evidence_spans 定位（Claude's Discretion：多命中取最早）
import hashlib

def _locate_span(answer_text: str, quote: str, source_message_id: str | None) -> dict | None:
    """在原文中定位 quote，返回结构化 span。定位失败返回 None（调用方降级）。"""
    if not quote:
        return None
    idx = answer_text.find(quote)          # 取最早命中（多命中策略，Claude's Discretion）
    if idx == -1:
        return None                          # mock "mock quote" / LLM 改写非原文 → 降级
    return {
        "source_message_id": source_message_id,
        "source_content_type": "raw",        # §12.5 raw|refined；终局评分回捞原文故为 raw
        "start_offset": idx,                 # Unicode code point（Python str 索引天然）
        "end_offset": idx + len(quote),
        "quote_hash": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
    }
```

### Pattern 3: item_measurement adjudicate 裁决（REF-5.4，D-58）

**What:** aggregation.py 内把 question_score 分组为内存测量记录 `(question_id, item_id, observed_level, evidence_refs, measurement_source)`，`adjudicate(measurements)` 产出 `item_final_level`，替换 `actual = sum(finals)/len(finals)`。
**When to use:** 聚合时每个非 gate item 的最终等级；综合题 integrated 本期列位预留（REF-3.9 延后）。
**Example:**
```python
# server/services/aggregation.py — 裁决（Claude's Discretion：冲突阈值与组合规则）
# 约束（D-14/§19）：不按来源加权、不按题数重复乘 item.weight；重大冲突取较低值 + 人工复核标记
def adjudicate(measurements: list[dict]) -> tuple[float | None, bool]:
    """返回 (item_final_level, human_review)。冲突取低留人工标记。"""
    levels = [m["observed_level"] for m in measurements if m["observed_level"] is not None]
    if not levels:
        return None, False
    if max(levels) - min(levels) >= 2:        # 重大冲突 → 取低 + 人工复核
        return float(min(levels)), True
    return round(sum(levels) / len(levels), 2), False   # 一致场景仍可均分（但不再乘 item.weight 逐题）
    # 注：D-58 明令废弃的是「按题数均分 + 不裁决冲突」，非禁止一致场景取均值；具体阈值 planner 定
```

### Pattern 4: IMPUTED 补算（REF-5.5，D-59）

**What:** 缺失普通 item（非 SCORED 且非 required/qualification）按 `r = Σ(i∈O) w_i×s_i / Σ(i∈O) w_i`（`s_i=(score−1)/4`）补算，标记 IMPUTED；O=∅ → NO_VALID_OBSERVATION。
**When to use:** 聚合时 item 无 SCORED 测量且补算适用时；覆盖率超阈值（§31-3 config 占位）→ 临时报告 + 人工复核。
**Example:**
```python
# server/services/aggregation.py — IMPUTED 补算（§20.1 公式，s_i=(score−1)/4）
def _impute_r(observed: list[dict]) -> float | None:
    """观察集合 O 的加权归一化均值 r。observed: [{weight, score}]。O=∅ → None。"""
    if not observed:
        return None
    num = sum(o["weight"] * ((o["score"] - 1) / 4) for o in observed)
    den = sum(o["weight"] for o in observed)
    return num / den if den else None
# 缺失普通 item：补算值 = r，标记 IMPUTED；required/qualification 不补算（§20.1）
# O=∅ → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED（不能补算）
```

### Pattern 5: 报告状态机 + 七项校验 + FAILED 行（REF-5.9/8.3，D-61/D-63/D-65）

**What:** report 表加 `report_status/review_status/version` + 发布字段；生成流程 = 聚合 → 七项校验（任一失败 → FAILED 行落库）→ 版本化 INSERT 新行；后台任务异常 → FAILED 行（report_json 含 `error` 摘要）+ TASK_FAILED 事件。
**When to use:** generate_report 与 `_generate_report_task` 异常捕获路径。
**Example:**
```python
# server/services/report.py — 状态机推进（§21.1 五态）
REPORT_STATUSES = ("GENERATING", "PROVISIONAL", "READY", "PUBLISHED", "FAILED")
REVIEW_STATUSES = ("NONE", "REQUIRED", "IN_PROGRESS", "CONFIRMED", "CLOSED")  # 代码校验 N11

def generate_report(session_id: str) -> dict:
    # ... 聚合 → 七项一致性校验（任一失败 → 写 FAILED 行，不生成正常报告）
    errors = _run_consistency_checks(agg, session_id)
    if errors:
        _insert_report_row(session_id, status="FAILED", version=_next_version(session_id),
                           report_json={"error": "; ".join(errors)[:200]})
        return ...
    # 版本化 INSERT（不再 DELETE 覆盖）：version = MAX(version)+1 per session
    # report_status = PROVISIONAL（required 缺失）| READY（否则）
```

### Pattern 6: publish 端点（REF-5.9，D-64）

**What:** `POST /api/admin/reports/{report_id}/publish`（require_admin），校验 review_status（required 缺失需 CONFIRMED）→ report_status=PUBLISHED + publish_confirmed_by + published_at + REVIEW_REPORT_PUBLISH_CONFIRMED 事件。
**When to use:** 管理员显式点击发布（D-003 人工唯一权威）；候选人不触发。
**Example:**
```python
# server/api/admin/reports.py — 发布端点（D-64 后端完整 + 前端最小）
@router.post("/reports/{report_id}/publish")
def publish_report(report_id: str, body: _PublishBody, admin: dict = Depends(require_admin)) -> dict:
    # 校验：report 存在；review_status 满足（required 缺失 → 需 CONFIRMED）
    # 推进：report_status=PUBLISHED + publish_confirmed_by + published_at
    # 事件：REVIEW_REPORT_PUBLISH_CONFIRMED（append_event，同一事务）
```

### Pattern 7: feedback 字段 + REVIEW_* 事件（REF-7.3，D-66/D-67）

**What:** feedback 表补 `user_id/note/reviewer/reviewed_at`；`review_feedback`/`mark_bad_case` 持久化 note + reviewer + reviewed_at；submit_feedback 补 user_id + REVIEW_FEEDBACK_RECEIVED 事件。
**When to use:** 候选人提交异议 / 管理员处理异议时。
**Example:**
```python
# server/api/assessment.py submit_feedback — 补 user_id + REVIEW_* 事件
conn.execute(
    "INSERT INTO feedback(feedback_id, report_id, item_id, feedback_text, status, user_id, created_at)"
    " VALUES(?,?,?,?,?,?,?)",
    (feedback_id, report_id, item_id, feedback_text, "pending", user["user_id"], now_iso()),
)
append_event(conn, session_id=..., event_type="REVIEW_FEEDBACK_RECEIVED",
             actor_type="candidate", actor_id=user["user_id"],
             assessment_message_id=None, payload={"feedback_id": feedback_id, "item_id": item_id})
# 注意：append_event 不 commit——submit_feedback 既有 conn.commit() 覆盖
```

### Anti-Patterns to Avoid

- **DELETE FROM report WHERE session_id=?（版本化对象）:** 覆盖生成违反 D-61/D-62「报告不可变版本化」+ 会在 SQLite FK 开启时连带/阻断 feedback（feedback.report_id FK→report）。改为版本化 INSERT 新行。
- **LLM 输出 offset/hash（违反 D-003）:** evidence_spans 的 start_offset/end_offset/quote_hash 必须代码计算，LLM 只给 evidence_quote 文本。
- **在持写事务的 conn 上跨 LLM 调用:** evidence_spans 定位/七项校验都在「内存算完单事务落库」模式内，不要在持有 question_score 写事务时调 P-score。
- **新列加 DB CHECK 约束（违反 N11）:** report_status/review_status/link_role 枚举全代码校验，SQLite 无法 ALTER CHECK。
- **submit_feedback 未校验 item 属于报告对应模型（已做，勿回退）:** assessment.py:1124-1130 的 JOIN 校验保留；只补字段不动校验逻辑。
- **异常静默 pass（REF-8.3 反模式）:** `_generate_report_task` 的 except 分支必须写 FAILED 行，不能只发 TASK_FAILED 事件就静默。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| quote_hash 确定性 hash | 自定义 hash / 字符串拼接 | stdlib `hashlib.sha256` | 确定性 + 审计可验证 + 无依赖 |
| evidence_quote 子串定位 | 手写字符偏移（UTF-16 代理对） | Python `str.find` + `len`（天然 code point） | Python str 索引已是 code point 语义，无需代理对处理 |
| trace_link 审计链 | 业务表逐一加 trace 外键 | 独立 trace_link 表（§13.3）+ 弱关联 | D-020 明令业务表不加 trace FK |
| 报告版本化 | DELETE+INSERT 覆盖 | version 字段 + 新行 INSERT | D-61/D-62 不可变版本 + feedback FK 防断裂 |
| REVIEW_*/TASK_* 事件 | 手写 INSERT 事件 | `state_events.append_event`（既有唯一入口） | §13.1 append-only + 触发器防 UPDATE/DELETE |
| 状态机枚举校验 | DB CHECK | 代码常量 + 校验函数 | N11：SQLite 无法 ALTER CHECK |

**Key insight:** 本 phase 的「deceptively complex」问题不是算法（hash/定位/比例都是几十行纯函数），而是**审计链闭合与状态机一致性**——trace_link 五要素可达性、七项校验与结构化状态一致、版本化不破坏 feedback FK。所有新逻辑都落在既有分层（db.py 迁移 / services 服务 / api 路由），不引入 ORM、不引入新表外的抽象层。

## Runtime State Inventory

> 本 phase 是 **schema 演进 + 数据迁移**（非 rename/rebrand），无「renamed string」概念。但迁移触发的存量数据回填是「代码改动不会自动修复」的运行时状态，必须显式列明。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 存量 `llm_trace` 行（ref_id 单字段，call_type 决定语义）| 数据迁移：`_migrate_trace_link` 拆 entity_type/entity_id 导入 trace_link（D-57） |
| Stored data | 存量 `report` 行（无 report_status/review_status/version/发布字段）| 数据迁移：ALTER 加列 + 存量行回填（report_status/review_status/version 默认值——见下方「迁移默认值」待裁） |
| Stored data | 存量 `feedback` 行（无 user_id/note/reviewer/reviewed_at）| 数据迁移：ALTER 加列，旧行 user_id/note/reviewer/reviewed_at 保持 NULL（历史异议无审计字段，接受；D-66 只保证新行落全字段） |
| Stored data | 存量 `question_score` 行（无 evidence_spans_json/rubric_version/scorer_version/measurement_target）| 数据迁移：ALTER 加列，旧行 evidence_spans_json 保持 NULL（历史评分无结构化 span，接受——「终局评分回捞原文」只保证新评分）；rubric_version 可回填 'v1'（D-54 Phase 4 先例） |
| Live service config | 无（SQLite 单文件，无外部服务配置）| none — verified |
| OS-registered state | 无（无 Task Scheduler/launchd/systemd 注册）| none — verified |
| Secrets/env vars | 无（本 phase 不新增 secret/env var；补算阈值 §31-3 为 config 常量占位，非 secret）| none — verified |
| Build artifacts | 无（Python 无编译产物；无 pip egg-info 受影响）| none — verified |

**迁移默认值（关键待裁项，planner 须在 plan 中明确，不能静默代决）：**
- 存量 `report` 行的 `report_status` 回填：旧报告是「已生成且候选端可见」的终态，语义最接近 `PUBLISHED`（或 `READY`）；`review_status` 回填 `NONE`（旧报告无人工复核概念）；`version` 回填 `1`。**推荐 PUBLISHED+1**，但若业务要求旧报告「未正式发布」则 READY——这是关口包呈报项。
- 存量 `question_score` 行的 `rubric_version` 回填 `'v1'`（D-54 既定）；`scorer_version`/`measurement_target`/`evidence_spans_json` 回填 NULL（历史评分不追溯补 span）。

## Common Pitfalls

### Pitfall 1: 报告版本化破坏现有测试断言「同会话仅 1 行 report」
**What goes wrong:** 现有 `test_m6_backend.py`（`_test_aggregation`，TESTING.md 记录「重复生成幂等（同会话仅 1 行 report）」断言 `COUNT(*)==1`）在版本化后必然失败。
**Why it happens:** D-61/D-62 把 DELETE+INSERT 改为「每次生成新版本 INSERT 新行」，同 session 多行成为合法态。
**How to avoid:** 重写该断言为「重复生成后 `COUNT(*)==2` 且最新行 version=2、旧行 version=1 保留」；同时 `get_report_by_session` 的 `ORDER BY created_at DESC LIMIT 1` 仍取最新行，读路径不破坏。
**Warning signs:** 跑旧 test_m6 出现 `n == 1` 失败。

### Pitfall 2: SQLite FK 开启下 DELETE FROM report 连带阻断 feedback
**What goes wrong:** 现行 `generate_report` 的 `DELETE FROM report WHERE session_id=?` 在 `PRAGMA foreign_keys=ON`（get_conn 已开启）下，若该 session 已有 feedback 行，会触发外键约束错误（feedback.report_id FK→report）。
**Why it happens:** feedback 是 report 的子资源，删除父行时 SQLite FK 默认 RESTRICT。
**How to avoid:** 版本化 INSERT（旧行保留）根治；迁移阶段不 DELETE report 行。
**Warning signs:** 生成报告时 `sqlite3.IntegrityError: FOREIGN KEY constraint failed`。

### Pitfall 3: evidence_spans 定位「LLM 改写非原文」导致 span 无法定位
**What goes wrong:** P-score 返回的 evidence_quote 可能是 LLM 改写/拼接的文本（非原文精确子串），`str.find` 返回 -1。
**Why it happens:** LLM 输出非逐字引用（temperature≈0 仍可能改写标点/省略）。
**How to avoid:** D-55 已锁定降级路径——定位失败 → `quote_hash` only + `source_message_id=NULL`，不抛异常不静默丢 quote；测试断言覆盖 mock "mock quote" 降级路径。
**Warning signs:** 大量 span 的 source_message_id 为 NULL（可用 SELECT 统计兜底验证）。

### Pitfall 4: Unicode code point offset 被误当 UTF-16/字节偏移
**What goes wrong:** 前端或测试用 JS 的 `indexOf`（UTF-16 码元）对比后端 Python 的 code point offset，emoji/生僻字处偏移错位。
**Why it happens:** 前后端字符串索引语义不同（JS UTF-16 code unit vs Python code point）。
**How to avoid:** §12.5 锁定「Unicode code point」——后端用 Python `str.find`/`len`（天然 code point）；测试用多字节 CJK + emoji（如 "😀" 是单 code point、双 UTF-16 码元）断言 offset 正确。
**Warning signs:** 含 emoji 的回答 span 偏移对不上原文。

### Pitfall 5: 七项校验的「文案无录用判断表述」用 LLM 判或词表过宽
**What goes wrong:** 校验要么依赖 LLM（违反 D-003 代码唯一状态机）要么词表过宽误杀正常文案（如「表现优秀」含「优」）。
**Why it happens:** 「录用判断」是语义概念，词表边界难定。
**How to avoid:** D-63 锁定「代码执行」——用**精确词表**（如「建议录用」「不予录用」「排名第」「推荐淘汰」等 D-002 红线词）匹配报告 JSON 全文；LLM 违规则 FAILED（与 D-002 范围红线一致）。词表集中一处常量，勿散落。
**Warning signs:** 正常报告被误标 FAILED（词表过宽）或含「录用」文案漏过（词表过窄）。

### Pitfall 6: 事件写点遗漏导致审计链断裂
**What goes wrong:** REVIEW_FEEDBACK_RECEIVED / REVIEW_REPORT_PUBLISH_CONFIRMED / TASK_FAILED 少写一处，审计链不闭合。
**Why it happens:** append_event 是显式调用，易漏；发布端点/反馈端点分散在 admin/assessment 两个 router。
**How to avoid:** 用「审计链闭合」确定性测试（Validation Architecture §Audit chain closure）断言每个环节的事件行存在；submit_feedback 与 publish 的 INSERT + append_event 在同一 conn 同一事务（单 commit）。
**Warning signs:** 测试 grep 不到 REVIEW_* 事件行。

### Pitfall 7: 重复生成 409 边界过严/过松（REF-5.9 SC-3）
**What goes wrong:** 若 409 仍保留「已存在 report 行」语义，重生成被拒（违反 D-62）；若 409 全撤，GENERATING 中并发重入导致重复评分/报告。
**Why it happens:** D-62 只锁定「409 仅保留给 GENERATING 进行中」，精确边界留给 planner。
**How to avoid:** request_report 三分支改为：(a) 非 completed → 409 SESSION_NOT_COMPLETED；(b) completed 且存在 `report_status='GENERATING'` 行 → 409 REPORT_GENERATING（防并发重入）；(c) 其余（无行 / 已有 FAILED/READY/PUBLISHED 行）→ 202 入队新版本。
**Warning signs:** 连续两次 request_report 第二个 202 但报告只多一行（边界错）。

## Code Examples

Verified patterns from official SSOT + existing code (all file:line confirmed this session):

### evidence_spans 定位（§12.5 + scoring.py:78-99 回捞原文复用）
```python
# 回捞原文已有现成链路（scoring.py _fetch_answer_text / report.py _load_question_reviews 均 raw_hash 回捞）
# evidence_spans 的 source 定位直接复用 _fetch_answer_text 的拼接原文
answer_text = _fetch_answer_text(session_id, question_id)   # 已含 raw_hash 回捞
span = _locate_span(answer_text, evidence_quote, source_message_id)  # Pattern 2
```

### 状态机枚举（§21.1 五态 + N11 代码校验）
```python
# report_status: GENERATING → PROVISIONAL | READY → PUBLISHED | FAILED
# review_status: NONE | REQUIRED | IN_PROGRESS | CONFIRMED | CLOSED
# 校验函数（N11 无 DB CHECK）——与 scoring.py SCORE_STATES 常量同形态
def _assert_report_status(s: str) -> None:
    if s not in REPORT_STATUSES:
        raise ValueError(f"非法 report_status: {s}")
```

### IMPUTED 覆盖率（§20.1 覆盖率展示）
```python
# 报告需展示：观察覆盖率 / 真实观察数 / 缺失原因
coverage = {
    "observed_count": len(observed_items),          # 真实 SCORED 观察数
    "imputed_count": len(imputed_items),            # IMPUTED 补算数
    "total_measureable": len(measurable_items),     # 可测量普通 item 总数
    "coverage_ratio": len(observed_items) / max(len(measurable_items), 1),
    "missing_reasons": missing_warnings,             # 缺失原因（复用既有 missing_warnings）
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| evidence_quote 单字段自由文本 | evidence_spans_json 结构化（source_message_id/offset/quote_hash）+ evidence_quote 并存 | Phase 5（D-55，§12.5） | 证据可定位、可回捞原文、可审计 |
| 按题数均分 `sum(finals)/len(finals)` | item_measurement adjudicate 裁决（冲突取低留人工标记） | Phase 5（D-58，§19） | REF-5.4 明令废弃均分；裁决语义对齐 §19 |
| 缺失 item 直接 0 分 no_data | IMPUTED r 比例补算 + 特殊标记 + 覆盖率 | Phase 5（D-59，§20.1） | 缺失可补算、可展示覆盖率；O=∅ 显式 NO_VALID_OBSERVATION |
| report DELETE+INSERT 覆盖生成 | 不可变版本化（version 新行） | Phase 5（D-61/D-62，§21.1） | 报告可回溯、feedback FK 不悬空 |
| 报告生成失败静默（前端超时猜测） | report_status=FAILED 行 + TASK_FAILED 事件 | Phase 5（D-65，REF-8.3） | 失败确定性可见 |
| feedback 无审计字段（note 丢弃） | user_id/note/reviewer/reviewed_at + REVIEW_* 事件 | Phase 5（D-66/D-67，§13.2） | 异议可回溯、note 持久化 |
| llm_trace.ref_id 单字段弱关联 | trace_link 统一关联表（entity_type/entity_id/link_role） | Phase 5（D-56/D-57，§13.3） | 审计链 report→…→trace 闭合 |

**Deprecated/outdated:**
- `aggregation.py` 的 `actual = sum(finals) / len(finals)`（按题数均分）——REF-5.4 明令废弃，由 adjudicate 替换。
- `report.py` 的 `DELETE FROM report WHERE session_id=?`（覆盖生成）——REF-5.9 SC-3 明令禁止，由版本化 INSERT 替换。
- `request_report` 的「已存在 report 行 → 409 REPORT_ALREADY_EXISTS」——由「仅 GENERATING 进行中 409」替换（D-62）。

## Assumptions Log

> 所有 `[ASSUMED]` / 未锁定 / 待裁项在此登记，planner 与 discuss-phase 用此表识别需用户确认的决策。

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | trace_link 的 trace_id 取值：推荐复用 llm_trace.trace_id（score/question/message 级写点），report/session 级无对应 trace 行时合成 audit id（如 `new_id("tl")`）——Claude's Discretion，D-56 未锁定 | Standard Stack / Pattern 1 | 审计链闭合语义漂移；需 planner 定，错误会导致 trace 查看器消费需返工 |
| A2 | evidence_spans 多命中策略取「最早命中」（`str.find` 首个）——Claude's Discretion，D-55 未锁定多命中 | Pattern 2 | 多题重复 quote 时 source_message_id 指向非预期消息；影响回溯准确性 |
| A3 | quote_hash = `sha256(quote.encode("utf-8"))` 精确文本（不做空白规范化）——Claude's Discretion「sha256 规范化」语义未锁定 | Pattern 2 | 若 SSOT 意图是「规范化后再 hash」，则 hash 不可跨实现复现 |
| A4 | adjudicate 冲突阈值「max−min ≥ 2 视为重大冲突取低」+ 一致场景取 round(mean)——Claude's Discretion，D-58/§19 未给定量化阈值 | Pattern 3 | §19「重大冲突」无量化定义；阈值错误会误判冲突或漏判冲突 |
| A5 | 存量 report 行回填 report_status='PUBLISHED' + review_status='NONE' + version=1（旧报告已候选端可见，语义最接近终态）——未锁定 | Runtime State Inventory | 若业务要求旧报告未发布态，则历史报告展示/发布语义错误；关口包呈报 |
| A6 | question_score 除 evidence_spans_json 外，同时补 rubric_version/scorer_version/measurement_target 审计快照列（§12.4 + code_context 标 MISSING）——D-55 只锁定 evidence_spans_json | Standard Stack / db 迁移 | 若超 scope，则 §12.4 审计快照列留待 Phase 6；若漏补，审计链「scorer/rubric 版本」不可追溯 |
| A7 | 总分归一化公式维持现状 `(score/5)`，IMPUTED r 按 `(score−1)/4` 计算后映射 display level = `r×4+1` 参与雷达/总分——§20.3「normalized_item_score」与 §20.1 `(score−1)/4` 存在 SSOT 内部张力，gap matrix row 5.7 标现状「公式合规」 | Pattern 4 / Open Question | 若 SSOT 意图是统一 `(score−1)/4`，则 total_score 数值与现有测试断言全变；须关口包用户裁决 |

**用户需确认项（关口包）：** A5（存量报告状态回填）、A7（总分归一化公式）、§31-3（补算复核阈值）。

## Open Questions

1. **trace_id 取值语义（D-56 Claude's Discretion）**
   - What we know: §13.3 只定 DDL + link_role 枚举；D-020 定审计链五要素；llm_trace.trace_id 已存在。
   - What's unclear: trace_link.trace_id 是「复用 llm_trace.trace_id」还是「独立合成 audit id」；report/session 级（非 LLM 调用产生的关联）用什么 id。
   - Recommendation: score/question/message 级写点复用 llm_trace.trace_id（天然对应单次 LLM 调用）；report→session 等纯结构关联用 `new_id("tl")` 或 report_id 作为 trace_id。planner 定后写入 plan `<interfaces>`。

2. **总分归一化公式（§20.3 张力，最高风险项）**
   - What we know: §20.1 锁 `s_i=(score−1)/4`；§20.3 说「normalized_item_score」未给公式；现状 `aggregation.py` 用 `(actual/5)`；gap matrix row 5.7 标现状「公式合规」。
   - What's unclear: IMPUTED r 用 `(score−1)/4` 与 total 用 `(score/5)` 是两个尺度，同一报告内混用会导致 observed 与 imputed 贡献不一致。
   - Recommendation: 关口包呈报。若用户裁决统一 `(score−1)/4`（SSOT 字面），则改 total 公式 + 重写 test_m6 数值断言；若维持 `(score/5)`（gap matrix 口径 + 最小改动），则 IMPUTED 补算值 r 需映射回 1-5 级（`r×4+1`）再进 total。**默认倾向最小改动**（见 A7）。

3. **七项校验的「无效题·系统错误未进正常分母」如何可重算验证**
   - What we know: 校验须证明 INVALIDATED/INCOMPLETE/系统错误行未混入 SCORED 分母。
   - What's unclear: 校验是「重新跑一遍分母过滤」还是「比对聚合结果的 missing_warnings 与 question_score 的 score_state」。
   - Recommendation: 用「重算分母」——校验函数独立重跑 `_EXCLUDED_STATES` 过滤，比对聚合结果的 SCORED 行数一致；避免校验逻辑与聚合逻辑重复漂移（提取单一 `_score_state_denominator` 助手两处复用）。

4. **adjudicate 冲突量化阈值（见 A4）**
   - What we know: §19「重大冲突取较低值」无量化定义；本期无综合题、item 通常 1-3 题。
   - What's unclear: 「重大冲突」= 差 ≥1 还是 ≥2 级。
   - Recommendation: 差 ≥2 视为冲突（同 item 两题一个 2 分一个 5 分是明显冲突；2 分 vs 3 分是正常邻级）；planner 定常量集中一处。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3 | 全部实现 | ✓ | 3.13.2 | — |
| stdlib hashlib | quote_hash sha256 | ✓ | 内置 | — |
| stdlib json/re/sqlite3 | spans 序列化/定位/raw SQL | ✓ | 内置 | — |
| FastAPI | publish 端点 + require_admin | ✓ | 0.141.1 | — |
| Pydantic v2 | publish request body schema | ✓ | 2.10.3 | — |
| pytest | 测试收集 | ✓ | 9.1.1 | — |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

## Validation Architecture

> Nyquist 验证：本 phase 是「链式审计契约」收口，测试重点是**确定性断言审计链闭合**与**状态机迁移合法性**，而非 UI 交互。全 mock 模式（LLM_PROVIDER=mock）离线跑，DB 用临时文件。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1（TestClient 集成 + 服务层直调） |
| Config file | none（无 pytest.ini/conftest.py——沿用 M5/M7 单文件三件套） |
| Quick run command | `cd server && python -m pytest test_phase5_evidence.py -v` |
| Full suite command | `cd server && python -m pytest test_phase5_evidence.py test_phase5_report.py test_phase5_feedback.py -v`（**逐文件跑，禁止单进程同跑多文件——DB_PATH import 冲突**） |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REF-2.10 | evidence_spans_json 落库含 source_message_id/start_offset/end_offset/quote_hash | unit | `pytest test_phase5_evidence.py::test_span_located_in_original -x` | ❌ Wave 0 |
| REF-2.10 | 定位失败降级 quote_hash only + source_message_id NULL（mock "mock quote"） | unit | `pytest test_phase5_evidence.py::test_span_degrade_on_mock_quote -x` | ❌ Wave 0 |
| REF-2.10 | offset 在 Unicode 边界（emoji/CJK）正确（code point 非 UTF-16） | unit | `pytest test_phase5_evidence.py::test_span_unicode_code_point -x` | ❌ Wave 0 |
| REF-2.3 | trace_link 建表 + link_role 枚举校验（非法值 raise） | unit | `pytest test_phase5_evidence.py::test_trace_link_role_validation -x` | ❌ Wave 0 |
| REF-8.7 | 旧 ref_id 迁移导入 trace_link（命中实体表拆 entity_type，命不中保留） | unit | `pytest test_phase5_evidence.py::test_ref_id_import_migration -x` | ❌ Wave 0 |
| REF-5.4 | adjudicate 替换按题数均分；冲突取低 + human_review 标记 | unit | `pytest test_phase5_report.py::test_adjudicate_conflict_lower -x` | ❌ Wave 0 |
| REF-5.5 | IMPUTED r 比例补算（`(score−1)/4` 加权均值）+ IMPUTED 标记 | unit | `pytest test_phase5_report.py::test_impute_r_math -x` | ❌ Wave 0 |
| REF-5.5 | O=∅ → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED | unit | `pytest test_phase5_report.py::test_impute_no_valid_observation -x` | ❌ Wave 0 |
| REF-5.6 | required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | integration | `pytest test_phase5_report.py::test_required_missing_provisional -x` | ❌ Wave 0 |
| REF-5.9 | 状态机迁移合法性（GENERATING→PROVISIONAL\|READY→PUBLISHED\|FAILED，非法迁移拒绝） | unit | `pytest test_phase5_report.py::test_status_transition_legality -x` | ❌ Wave 0 |
| REF-5.9 | 七项校验任一失败 → FAILED（不生成正常报告） | integration | `pytest test_phase5_report.py::test_consistency_check_fails_to_failed -x` | ❌ Wave 0 |
| REF-5.9 | 版本不可变（重复生成 2 版本，旧行保留，feedback FK 不悬空） | integration | `pytest test_phase5_report.py::test_version_immutability -x` | ❌ Wave 0 |
| REF-5.9 | publish 端点：admin 显式点击 → PUBLISHED + REVIEW_REPORT_PUBLISH_CONFIRMED 事件；review 未满足拒绝 | integration | `pytest test_phase5_report.py::test_publish_flow -x` | ❌ Wave 0 |
| REF-8.3 | 生成异常 → FAILED 行 + TASK_FAILED 事件（前端可区分生成中/失败） | integration | `pytest test_phase5_report.py::test_generate_failed_visible -x` | ❌ Wave 0 |
| REF-7.3 | submit_feedback 落 user_id + REVIEW_FEEDBACK_RECEIVED 事件 | integration | `pytest test_phase5_feedback.py::test_feedback_audit_fields -x` | ❌ Wave 0 |
| REF-7.3 | review/bad-case 持久化 note + reviewer + reviewed_at（不再丢弃） | integration | `pytest test_phase5_feedback.py::test_admin_note_persisted -x` | ❌ Wave 0 |
| REF-7.3 | question_reviews 补 item_id | integration | `pytest test_phase5_feedback.py::test_question_reviews_has_item_id -x` | ❌ Wave 0 |

### Edge Cases the Tests Must Cover

- **offsets at Unicode boundaries**: 含 emoji（单 code point / 双 UTF-16 码元）与 CJK 生僻字的回答，断言 `start_offset/end_offset` 用 Python `str` 语义（code point），并与 `answer_text[start:end] == quote` 精确相等。
- **quote_hash collisions**: 断言 `sha256` 确定性——同一 quote 两次定位 hash 相同；不同 quote hash 不同；空 quote 不产生 span（降级或跳过）。
- **IMPUTED r-proportion math**: 用已知权重/分数构造 observed 集合，手算 `r = Σ w_i(s_i)/Σ w_i` 断言浮点误差 < 1e-6；weight 全 0 → den=0 不除零；单一观察 r 等于该观察自身归一化值。
- **state machine transition legality**: 建合法迁移表（GENERATING→PROVISIONAL/READY/FAILED；PROVISIONAL→PUBLISHED；READY→PUBLISHED；任意→FAILED）与非法迁移（PUBLISHED→READY、FAILED→PUBLISHED 等）断言拒绝。
- **version immutability + FK integrity**: 重复生成 2 次，断言 report 2 行、version 1/2、`get_report_by_session` 取 version 2、旧 version 1 行仍在；对 version 1 提 feedback 后 FK 不断裂（无 DELETE 触发）。
- **seven-check determinism**: 每个校验项用「最小破坏」构造（如篡改 weight Σ≠1、引用不属于该 session 的 question_id、文案含「建议录用」），断言各触发 FAILED。

### Audit Chain Closure (deterministic test)

```python
def test_audit_chain_closure(ctx):
    """report→session→model/version→question→message→score→trace 全链可达，确定性断言。"""
    # 1. 生成报告后，从 report 反查 trace_link 链：
    #    report.report_id → trace_link(entity_type='session', entity_id=session_id)
    # 2. 沿链查 session→model/version（assessment_session 快照列）、question→score（question_score）
    # 3. score→trace：question_score.score_id → trace_link(link_role='source'|'scored') → llm_trace.trace_id
    # 4. 断言五要素（report/session/model/version/question/score/trace）全部非空且能 JOIN 贯通
    # 5. 旧 ref_id 导入：断言迁移后 llm_trace.ref_id 命中的实体都在 trace_link 有对应行
    for step in ["session", "model", "question", "message", "score", "trace"]:
        assert _resolve(ctx["report_id"], step) is not None, f"审计链断裂 @ {step}"
```

### Sampling Rate
- **Per task commit:** `cd server && python -m pytest test_phase5_evidence.py -v`（单文件快速回归，< 30s）
- **Per wave merge:** `cd server && python -m pytest test_phase5_evidence.py test_phase5_report.py test_phase5_feedback.py -v`（逐文件）
- **Phase gate:** 全套新测试绿 + 既有 test_m6（改断言后）/ test_m7 绿，再 `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `server/test_phase5_evidence.py` — REF-2.10/2.3/8.7（span 定位/降级/Unicode/trace_link/迁移）
- [ ] `server/test_phase5_report.py` — REF-5.4/5.5/5.6/5.9/8.3（adjudicate/IMPUTED/状态机/七项校验/版本化/publish/FAILED）
- [ ] `server/test_phase5_feedback.py` — REF-7.3（feedback 审计字段/note 持久化/question_reviews item_id）
- [ ] 重写 `server/test_m6_backend.py` 的「重复生成幂等（同会话仅 1 行 report）」断言 → 版本化断言（Pitfall 1）
- [ ] 共用测试助手 `_q()`/`_auth()`/`_seed_*` 沿用 M5/M7 既有形态（不建 conftest——单文件纪律）

*(Wave 0 需新建 3 个测试文件 + 改 1 个既有断言；无现成基础设施覆盖本 phase)*

## Security Domain

> `security_enforcement` 未显式 false（config.json workflow 无该键，默认启用）。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 本 phase 不新增认证；publish 端点复用既有 require_admin（JWT HS256） |
| V3 Session Management | no | 报告/反馈无新会话态 |
| V4 Access Control | yes | publish 端点 require_admin；submit_feedback 复用 load_owned_report（所有权）+ item∈model 校验（已做，保留） |
| V5 Input Validation | yes | publish body（review_outcome/review_note）用 Pydantic 校验；feedback_text 长度上限（沿用 MAX_ANSWER_LEN 同口径）；report_status/link_role/review_status 枚举代码校验 |
| V6 Cryptography | no | quote_hash 是 sha256 指纹（非密码学用途，仅审计可验证性）；不新增密钥 |

### Known Threat Patterns for {Python/FastAPI/SQLite}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 越权 publish（候选人调用 admin publish 端点） | Elevation of Privilege | publish 路由级 `Depends(require_admin)` + 资源所有权校验 |
| feedback 挂无关 model 的 item（破坏回溯链） | Tampering | submit_feedback 已有 `JOIN report→session→competency_item` 校验（assessment.py:1124-1130）保留 |
| LLM 注入「录用判断」文案进报告 | Tampering | 七项校验「文案无录用判断表述」精确词表代码校验（D-002 红线）→ FAILED |
| 状态机非法迁移（代码外直改 DB 状态） | Tampering | report_status/review_status 枚举代码校验 + 迁移合法性测试 |
| 补算阈值未配置导致无上限补算 | Information Disclosure | §31-3 config 占位 + 覆盖率展示 + 超阈值 PROVISIONAL（人工复核兜底） |

## Sources

### Primary (HIGH confidence)
- `design/final-design/总设计文档.md`（v2.0，SSOT）— §12.4/12.5（evidence_spans + question_score 演进）、§13.2/13.3（REVIEW_* 事件 + trace_link DDL）、§17（评分链/FAILED）、§19（item_measurement/adjudicate）、§20.1-20.3（IMPUTED/required 缺失/总分）、§21.1（报告状态机/七项校验/发布/版本化）、§28-5、§31-3（开放参数）
- `.planning/phases/05-evidence-report-contract/05-CONTEXT.md` — D-55~D-67 锁定决策 + Claude's Discretion + Deferred
- `.planning/intel/decisions.md` — D-003/D-014/D-015/D-018/D-020/D-025/D-031 全文
- `research/ssot-code-gap-matrix.md` — row 2.9/2.10/5.4/5.5/5.7（合同核对 + 总分公式「形式合规」口径）

### Secondary (MEDIUM confidence)
- `server/db.py`（question_score/report/feedback/llm_trace/context_raw DDL + 迁移函数形态）
- `server/services/scoring.py`（score_question evidence_quote 单字段 + score_session 单事务落库 + _fetch_answer_text）
- `server/services/aggregation.py`（`actual=sum/len` 均分 + _EXCLUDED_STATES 三路分流 + _gate_row/_gate_check）
- `server/services/report.py`（DELETE+INSERT 覆盖生成 + _load_question_reviews + _collect_evidence_quotes）
- `server/services/state_events.py`（append_event 唯一入口）、`server/services/llm.py`（call_llm_json + trace 落库）
- `server/api/assessment.py`（request_report 409 / _generate_report_task 静默 / submit_feedback item 校验 / get_report_by_session）
- `server/api/admin/feedback.py`（note 丢弃）、`server/api/admin/trace.py`（ref_id IN 弱关联）
- `.planning/codebase/{ARCHITECTURE,TESTING}.md`（分层纪律 / SQLite 单写者两模式 / 单文件单进程测试纪律）

### Tertiary (LOW confidence)
- 无——本 phase 全部结论可回溯到 SSOT + 现有代码 + 锁定决策，无 WebSearch 依赖。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 无新外部包（stdlib + 既有 FastAPI/Pydantic），版本已实测核实。
- Architecture: HIGH — 改造对象 file:line 全部读源码确认；分层沿用既有 ARCHITECTURE.md 契约。
- Pitfalls: HIGH — 直接来自既有测试断言（test_m6 幂等断言）、get_conn PRAGMA FK 语义、SSOT 内部张力（§20.3）实测确认。

**Research date:** 2026-09-05
**Valid until:** 2026-09-19（稳定域——SSOT v2.0 已冻结，无快变外部依赖）
