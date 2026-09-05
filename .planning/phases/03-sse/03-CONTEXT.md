# Phase 3: 表单/SSE/幂等/计时 - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning

<domain>
## Phase Boundary

把测评会话的「传输与运行契约」按 SSOT §11.5/§13.4/§14/§15/§16 落地：资格核验表单成为代码触发的真实生命周期链路（form_instance 不可变 schema 快照 + 服务端六维校验 + 重复提交幂等 + gate 结构化结果与人工覆盖位）；答题接口改真实 SSE（决策非流式先落库、话术逐 token、finish 仅代码触发、sse.js 双形态自适应走流式）；幂等协议（session_id+endpoint+idempotency_key 作用域 + 答题付三键 + 事务+乐观版本号防并发双写）；全场 40min/单题 20min 服务端权威计时区间（暂停写事件不计入、单题超时封存续题、全场超时收尾评分、6h ABANDONED 惰性+周期检测）；assessment_session 状态机 PENDING_START→ACTIVE→SCORING→COMPLETED；上下文三层（原文不可覆盖/滑窗 Token 控制/导航摘要层）+ 消息 raw/refined 分列；experience/qualification 出普通题库改走表单（联动 Phase 2 已留的 gate=1 语义）；INJECTION_DETECTED 事件留痕。

对应 REQUIREMENTS.md：REF-2.4, REF-2.6, REF-2.8, REF-3.3, REF-4.6, REF-4.7, REF-4.8, REF-4.9, REF-4.10, REF-4.12, REF-6.4（11 项，支撑 REQ-interactive-multiturn-assessment / REQ-data-compliance）。

**不在本阶段**：题库 model/version 绑定（Phase 4）；证据 span 结构化/trace_link/item_measurement 裁决/报告状态机（Phase 5——human_override 列虽在 §16.1 定义，本 phase 只落 form_instance 表结构与 gate 结构化结果，admin 覆盖 UI 属 Phase 5 报告链）；schema_version 收口/pytest 统一（Phase 6）；断线续传 cursor（SSOT §11.5 明示留扩展记录）；ABANDONED 可恢复（本期不可恢复不留接口）；Tools 白名单（REF-4.11 延后）；JD 侧 P-refine（模块一既有）。

</domain>

<decisions>
## Implementation Decisions

> D-29~D-4x 为 Phase 3 编号（接续 02 的 D-14~D-28）。auto 模式（章程 §1）推荐项选取，逐条依据 = SSOT 条款/既定决策/代码现状三者之一，留痕见 03-DISCUSSION-LOG.md。

### 表单链（计划 03-01 主体）
- **D-29: form_instance = 新表（§16.1 生命周期实体），不是改造 form_submission。** form_submission（Phase 0 遗留）保留兼容旧 UI 直提；form_instance 承载新链路（不可变 schema 快照 + status 生命周期 + revision 不可变修订）。schema 由代码定义（form schema 常量 + 版本号），**版本化 = 字符串版本 "v1" 起 + 快照整体 JSON 落 instance 行**（不引 JSON Schema 库——最小实现：required/enum/长度规则以 Pydantic 校验 + 快照留档）。
- **D-30: render_form 触发点 = 会话进入资格核验阶段的代码判定（select_next_question 池耗尽且存在 gate item 未采集 → render 而非 finish）。** 02-02 的「池耗尽即 finish」在本 phase 扩展为「池耗尽 → 检查 gate 采集 → 表单链 → 之后才 finish」；LLM 只能请求表单（observation 层不新增 action）。表单完成事件的 instance_id 计入 SESSION_* 事件面。
- **D-31: gate 结果落位 = question_score 表 gate 项行换结构化结果（gate_result/gate_status/gate_reason/evaluated_schema_version/evaluated_at），不动 aggregation 的 weight 公式。** 「gate 判定不再从自由 payload 猜测」指 _gate_check 现行的 payload 摸底（aggregation.py:48-70）迁移为 form_instance 结构化结果消费；人工覆盖字段（automated_gate_result/human_override/override_reason/reviewer_id）**列就位 + 校验位（二次确认 = 覆盖时需带 override_reason 非空）**，admin 覆盖操作 UI 属 Phase 5 报告链——本 phase 落库结构 + 写入口（admin API 端点），不做前端。
- **D-32: experience/qualification 出题库 = 题库生成侧排除（question_bank.py 现行 category 过滤已近似）+ readiness/selection 无需改（02-02 已剔除）+ form 链承接采集。** 种子数据中的经验/资格项 item 挂 gate=1（02-04 SUMMARY 已落此形态）——表单完成后 gate 判定消费结构化事实。

### SSE（计划 03-02 主体）
- **D-33: SSE 端点 = submit_answer 现路由升级为 StreamingResponse（同 URL 双 Content-Type 不做——直接改 POST /answer 为 text/event-stream，sse.js 自适应已就绪）。** 决策阶段（非流式：decide_next_action + Pydantic + 落库 + 事件）先完整落库**再开始**推流；话术阶段逐 token（mock 模式用「分块假流」模拟 token 间隔——离线可测）；done 事件携带 next_question_id。falls finish 判定不变（02-02 池耗尽口径）。
- **D-34: SSE 事件类型 = sse.js 注释既有契约对齐**：`decision`（action/reason/score_live + answer_state/evidence_sufficient 扩展键透传）→ `reply`（逐 token content）→ `done`（next_question_id / session 完结标记）；错误事件 `error`（不卡死：LLM 失败降级 MODEL_UNCERTAIN 路径已在 02-04 CR-01 修复——流式形态下走 done 而非 500）。**不做断线续传 cursor**（§11.5 留扩展）。
- **D-35: REF-1.4 trace 不变（SSE 不加新留痕面）**——audit chain 仍走 append_event；SSE 层零持久化（流完成时消息已落库，重连/重放语义 = 幂等协议管辖）。

### 幂等（计划 03-03 主体）
- **D-36: 幂等作用域 = session_id + endpoint + idempotency_key 三键（§13.4），落新表 idempotency_record（key 唯一 + request_hash + response_snapshot JSON + created_at）。** 响应快照 = 首次持久化结果的完整 JSON（重复请求 byte-级回放）；答题另带三键（question_instance_id/expected_question_revision/client_attempt_id）进 request_hash。**幂等键可选（缺省不启用）**——带 key 的请求才走幂等路径（前端 sse.js/表单提交照常无 key 请求不受影响；带上 key 的旧 UI 不存在回归面）。
- **D-37: 并发双写防护 = 事务 + 乐观版本号（§13.4 原文）。** 落点为 assessment_question 的既有 UPDATE 语句扩展 `WHERE ... AND revision=expected`（assessment_question 加 revision INTEGER DEFAULT 1 列——02-01 新列惯例）；单题提交时 revision+1；写失败=乐观冲突 → 409 幂等层返回首次结果或冲突态。
- **D-38: 幂等记录清理策略 = 不实现（阈值提醒留待 Phase 6 数据治理）**——表结构留 created_at 索引；SSOT「策略实施期定」，Phase 6 REF 清单已含数据分级管理。

### 计时区间（计划 03-04 主体）
- **D-39: timer 采样点 = 服务端权威，惰性推进。** session_time_intervals 落为表（session_id/interval_type active|paused/reason/started_at/ended_at——§15 原文）；active_elapsed_seconds 不实时写（派生 Σ 查询 + 会话行缓存列在收尾/报告时刷新）；每次 API 请求（answer/form/pause）先「闭合当前区间再开新区间」。场景探测：入场确认（session.phase PENDING_START→ACTIVE 时开第一个 active 区间 + 首题激活）；单题 20min 判定只在每次请求时点计算（now - 该题 activated_at - Σpaused 重叠）——不启后台 timer 线程（演示形态 D-005）。
- **D-40: 暂停 = 显式 pause 端点（候选人可触发 PAUSE_REQUESTED 事件 + PAUSED 区间）**；技术/无障碍/管理暂停走同一区间类型（reason 区分，敏感 reason 不进评分 prompt §15）；暂停期间答题被拒（409 SESSION_PAUSED）；resume 关闭 paused 区间。短暂断线不自动暂停（§15）。零散决策：暂停写 SESSION_PAUSED/SESSION_RESUMED 事件（§13.2 SESSION_* 组既有枚举）。
- **D-41: 超时行为：单题超时（封存 seal_reason='timeout' + QUESTION_SEALED 事件 + 选下一题——复用 02-04 封存链）；全场超时（停止新增主问题 + SESSION_GLOBAL_TIMEOUT 事件 + 进 SCORING 收尾——复用 _generate_report_task 串行链入口）；6h ABANDONED（惰性判断挂在每次会话访问 + 分钟级周期扫描可选实现——演示形态择惰性为主，周期扫描作为可选独立小函数留 plan 裁量）。** 计时不参与题目筛选优先级（§15 原文兜底）。
- **D-42: 6h 活性判定基准 = last_activity_at 列（本 phase 加于 assessment_session——每次写操作刷新）。**

### 上下文三层 + 消息分列（计划 03-04/03-05 侧带）
- **D-43: assessment_message 分列 = ALTER 加列（raw_content 改名不动——现存 content 列保留不清数据，新列 raw_hash 已有 + 新增 refined_content/client_request_id/sequence_no——§12.3 列名照 SSOT）。** 写入点：submit_answer 决策链内原文与精炼分列落库（refine.py 既有函数现成）；滑窗 Token 控制 = interviewer prompt 拼装时按 MAX_CONTEXT_TOKENS 截断（config 常量，具体数值实施期校准——plan 给占位值，不臆造：mock 模式直接全量）。
- **D-44: 导航摘要层 = 结构化状态优先（数据库查询 item 覆盖/难度/current），LLM 摘要可选（本期不实现——「失败回退数据库状态」天然满足）；SSOT「可选」措辞不强制。**

### Injection 留痕（计划 03-05）
- **D-45: INJECTION_DETECTED = 观察层 answer_state=PROMPT_INJECTION 时落事件（§13.2 枚举既有），payload 含 answer_state/stability 不含敏感输入原文。** 检测器本期 = 分类器字面依赖（answer_state 分类即检测——mock 词表可测；真实 LLM 观察 + severity 分级留 Phase 6 安全收口）。候选人输入永远以数据身份进入 prompt（引号/分隔包裹——interview prompt 既有形态保持）。

### 接口层 schema（REF-4.7，横向）
- **D-46: 接口层 Pydantic = 本 phase 新增端点全部走（answer 请求体/表单提交体/表单 schema 校验）；存量端点（session/get/report 等）不回溯改写**（改动面控制——存量端点 Pydantic 化的价值主要在文档，与 Phase 6 测试收口一并评估）。**SSOT 完成后需核对** §4.7 边界——若 plan-checker 判定 REF-4.7 语义为「全部接口」，此裁量带关口包呈报。

### 开放参数（关口包呈报项 SSOT §31 类）
- **滑窗 Token 上限（MAX_CONTEXT_TOKENS）/REFINE_MIN_TOKENS 复核**：§14「参数待定，留接口」——plan 落 config 占位 + 常量注释标注「实施期校准」，**数值不代决**（同 N=10 先例，关口包列呈报项；若用户不裁决则维持 plan 占位默认）。
- **单题/全场时长 40/20**：SSOT §15 已硬编码——非开放参数，直接落 config 常量。

### Claude's Discretion
- form schema 的具体字段定义（experience/qualification 各自必填项与枚举值——参照 form_submission 现行 payload 形态与 aggregation._gate_check 消费口径就近设计）
- idempotency_record 的 request_hash 算法（sha256 规范化 JSON）与响应快照截断策略
- interval 表闭合/开新的 helper 命名与放置（services 层惯例）
- 测试组织（新 5 个测试文件 test_phase3_*——沿用单文件单进程 + tempfile + mock 三件套纪律）
- SSE 步调器（mock 假流分块大小/间隔——只影响测试耗时不影响语义）

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 设计权威（SSOT）
- `design/final-design/总设计文档.md` §11.5 — SSE 契约（两阶段：决策非流式先落库/话术流式；finish 仅代码；错误与结束事件；无 cursor）
- `design/final-design/总设计文档.md` §13.2 — SESSION_* 事件组（CREATED/STARTED/PAUSE_REQUESTED/PAUSED/RESUMED/ENTERED_SCORING/GLOBAL_TIMEOUT/COMPLETED/ABANDONED——本 phase 激活组）+ INJECTION_DETECTED
- `design/final-design/总设计文档.md` §13.4 — 幂等（作用域三键、答题付三键、重复返回首次、乐观版本号、记录清理策略实施期定）
- `design/final-design/总设计文档.md` §14 — 上下文三层（原文不可覆盖/滑窗 Token/导航摘要）+ P-refine
- `design/final-design/总设计文档.md` §15 — 计时（全场 40/单题 20/服务端区间权威/暂停类型不计入/断线不自动暂停/6h ABANDONED/单题超时封存/全场超时收尾）
- `design/final-design/总设计文档.md` §16.1–16.2 — form_instance 生命周期（schema 版本化快照/render_form 代码触发/GET 只读不暴露阈值/submit 六维校验/重复幂等/不可变 revision/gate 结构化结果/人工覆盖二次确认）+ extract_form_facts 状态机
- `design/final-design/总设计文档.md` §12.1/§12.3 — assessment_session 演进列（phase/active_elapsed_seconds/last_activity_at/abandoned_at/policy_version/session_time_intervals_json）+ assessment_message 分列（raw_content/raw_hash/refined_content/client_request_id/sequence_no）
- `design/final-design/总设计文档.md` §31 — 开放参数（滑窗 Token 上限「实施期校准」——关口包呈报项）

### 证据基线
- `research/ssot-code-gap-matrix.md` — 68 行契约核对（Phase 3 相关行：矩阵 §2 的 2.4/2.6/2.8、§3 的 3.3、§4 的 4.6-4.12、§6 的 6.4）
- `.planning/intel/decisions.md` D-005（演示部署形态——不启后台服务的依据）、D-008/D-009/D-030
- `.planning/phases/02-dynamic-selection/02-CONTEXT.md` — Phase 2 已决（D-25 seal_reason 枚举位预留 timeout 本期填充、gate=1 种子形态、池耗尽即 finish 的扩展点）
- `.planning/phases/02-dynamic-selection/02-VERIFICATION.md` — Acknowledged Gaps（chain_followed 排序退化——Phase 4/5 消化，非本 phase）

### 代码现状（改造对象）
- `web/src/utils/sse.js` — 双形态自适应前端（流式形态已就绪——本 phase 后端对齐即接管）
- `server/api/assessment.py` — submit_answer（SSE 升级对象）/ forms/submit（form_submission 旧链，保留）/ get_session（PENDING_START 入场确认触发点）
- `server/services/interview.py` — decide_next_action 两层化产物（SSE 决策阶段消费其返回；话术 reply 已在 decision dict）
- `server/services/refine.py` — P-refine 既有实现（raw_hash 归档 context_raw + refined 输出——分列落库的直接素材）
- `server/services/aggregation.py` — _gate_check 现行 payload 摸底（gate 结构化结果的迁移基准）+ gate_items 消费面
- `server/services/question_selection.py` — 池耗尽判定与 finish 触发（render_form 插入点）/ select_next_question 单题计时 activated_at 列消费
- `server/services/state_events.py` — append_event（SESSION_* 激活组与 INJECTION_DETECTED 复用入口）
- `server/db.py` — form_submission 现行表 + _DDL/迁移惯例（form_instance/idempotency_record/session_time_intervals 新表 + assessment_session/assessment_message ALTER 段照 02-01 惯例）
- `server/config.py` — 常量区（REFINE_MIN_TOKENS 既有 + 新增 MAX_CONTEXT_TOKENS/SESSION_TOTAL_MINUTES=40/QUESTION_TIMEOUT_MINUTES=20/ABANDON_HOURS=6）
- `.planning/codebase/ARCHITECTURE.md` / `TESTING.md` — 分层纪律/SQLite 单写者两模式/测试纪律

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/services/state_events.py append_event` — SESSION_* 新枚举走同一入口（caller 持事务契约不变）
- `server/services/refine.py refine_user_input` — (refined, raw_hash) 双返回现成——消息分列只差列落点
- `web/src/utils/sse.js streamAnswer` — fetch + ReadableStream + Content-Type 自适应（后端切 text/event-stream 零前端改动）
- `server/services/question_selection.py` select_next_question — 池耗尽返回 None 的语义已是 render_form 插入点的天然锚
- 02-04 封存链（assessment.py 三路 closed_at/seal_reason）——timeout seal_reason 第四路照既有分支形态追加
- 01-03 串行链 `_generate_report_task` — 全场超时收尾复用该入口（ENTERED_SCORING → 串行链）

### Established Patterns
- raw SQL + get_conn() per-call + 显式 commit——新表（form_instance/idempotency_record/session_time_intervals）同风格
- DDL 迁移：手写嗅探式幂等（_migrate_llm_trace/_migrate_question_*_v2 惯例）——新表 CREATE IF NOT EXISTS + 存量表 ALTER 逐列嗅探（02-01 先例：PRAGMA table_info）
- N11 枚举代码校验（form_status/interval_type/gate_status 无 DB CHECK 列上）
- 「先 commit 再调 LLM」与「内存算完单事务落库」（SSE 决策阶段落库在前推流在后——天然合规前一模式）
- mock 双轨：每服务 _mock_* 相邻（话术假流分块进 _mock_interview 相邻或 SSE 层独立 _mock_stream——plan 定）

### Integration Points
- `server/api/assessment.py create_session` — phase='PENDING_START' 初始化 + SESSION_STARTED 事件挂入场确认端点
- `server/api/assessment.py submit_answer` — SSE 化 + 幂等键消费 + revision 乐观锁 + 单题超时点检 + 注入事件
- `server/api/assessment.py` forms 端点组 — GET /forms/{id} 只读 + render_form 响应 + submit 幂等校验六维
- `server/services/interview.py decide_next_action` — prompt 拼装处滑窗截断接入
- `eval/virtual_candidates.py` — answer 提交无幂等键（不受影响）；SSE 端点若被 eval 消费需核对（现状 eval 直调 score/aggregate 层——无 answer API 调用，无影响面）

</code_context>

<specifics>
## Specific Ideas

- 02-DECISIONS 移交项处理：WR-04 张力（§10.5 刚性 vs §11.2 降级避让）呈报关口 A（用户裁决，非本 phase 默认动作）；chain_followed 排序退化非本 phase。
- 表单只读端点绝不暴露内部阈值（schema 快照落库的展示态做字段白名单——渲染字段与内部判分字段分栏）。
- 全场超时进 SCORING 后 SESSION_GLOBAL_TIMEOUT 事件优先于 ENTERED_SCORING（审计算子顺序：先因后果）。
- 暂停窗口内所有写操作（answer/form）409——与 Phase 1 completed 护栏同 error_code 三态形态（{error_code, message}）。
- SSE 推流期间客户端 abort（AbortController）不回滚已落库决策（服务端先落库原则——放弃接收语义等价断线重连，幂等键管辖）。

</specifics>

<deferred>
## Deferred Ideas

- 断线续传 cursor / 事件回放（§11.5 留扩展记录）
- ABANDONED 会话恢复（「后续可开发可恢复，仅留记录」）
- 幂等记录清理阈值与管理员接口（策略实施期定——Phase 6 数据治理）
- LLM 导航摘要生成（结构化优先已满足，可选路径不实现）
- admin 表单人工覆盖前端 UI（Phase 5 报告链）
- Injection 检测 severity 分级与真实 LLM 检测质量（Phase 6 安全收口 + D-027 售后验证）
- grind: REF-4.11 Tools 白名单（延后不变）

</deferred>

---

*Phase: 3-表单/SSE/幂等/计时*
*Context gathered: 2026-09-05*
