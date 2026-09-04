# Phase 3: 表单/SSE/幂等/计时 - Research

**Researched:** 2026-09-05
**Domain:** FastAPI StreamingResponse 真实 SSE（同步 generator） / form_instance 生命周期实体与 gate 结构化结果 / SQLite 幂等三键作用域 + revision 乐观锁 / 服务端权威计时区间 / 消息 raw/refined 分列 + 上下文滑窗 / SESSION_* 事件激活
**Confidence:** HIGH

## Summary

Phase 3 是纯运行时行为阶段（11 项 REF），**零新增包、零前端改动**——SSE 前端 `web/src/utils/sse.js`（92 行全文核读）的双形态自适应已就绪，后端 `POST /answer` 直改 `text/event-stream` 即接管（D-33）；表单前端 `web/src/components/FormCard.vue` 的 `📎[form:{id}]` 标记提取 + `getForm`/`submitForm` 调用链也已在位，但**后端 GET /forms/{id} 路由不存在**（grep 全仓库确认），03-01 需要新建。研究逐文件核对了全部改造对象现状：`assessment.py`（636 行——submit_answer 是 SSE+幂等+revision+单题超时四合一改造点；现状是三相 commit 的「先 commit 再调 LLM」链条）、`question_selection.py`（池耗尽返回 None 有 4 处，`_select_next_question_locked` 的两个 `return None` 即 render_form 插入锚）、`interview.py`（266 行——滑窗落点 `_build_user_prompt`:75-90 的 history 循环）、`db.py`（477 行——_migrate_* 嗅探式惯例齐备）、`config.py`（51 行）。CONTEXT D-29~D-46 全部有代码落点可对应，**无 SSOT 冲突项（0 CONFLICT）**。

关键技术机制已通过 11 个本地实验实测验证（Python 3.13.2 / FastAPI 0.141.1 / starlette 1.6.0 / httpx 0.28.1 / pydantic 2.10.3 / SQLite 3.45.3，全部 /tmp 临时库，未碰 data/app.db）：①`StreamingResponse(gen())` 对同步 generator 经 `iterate_in_threadpool` 包装（starlette 1.6.0 源码 + 实测 memoryview 处理确认）——generator 内**不持 DB 连接**是硬纪律（线程池 worker 中连接泄漏无人回收）；②TestClient 下 `with client.stream("POST", ...) as r: r.iter_lines()` 可真正逐行流式消费 SSE（实测 decision/reply×5/done 事件序完整到达）；③HTTPException 在返回 StreamingResponse 前抛出 = 普通 JSON 422/409 错误（不变更现有错误处理惯例）；④幂等唯一索引 `UNIQUE(session_id, endpoint, idempotency_key)` 拦并发双插（IntegrityError 实测）、同 key 不同 endpoint 放行（三键语义正确）；⑤乐观锁 `UPDATE ... WHERE question_id=? AND revision=?` 的 rowcount==0 即冲突（实测 stale revision 被拒）；⑥`session_time_intervals` 部分唯一索引 `ON (session_id) WHERE ended_at IS NULL` 拦并发双开区间（实测闭合后可开新）——这是**数据库层乐观防护**，优于 CONTEXT 提到的应用层检查；⑦区间重叠计算**必须 Python 端 merge**（SQL 聚合 SUM 跨行不去重——重叠段双计，实测 8min vs 正确 6min）；⑧`min(s,e)/max(s,e)` 标量函数 SQLite 3.45 可用（实验 10），但整体判定仍推荐 Python（now_iso() 带微秒+时区，Python `fromisoformat` 全兼容实测）；⑨`assessment_session.status` 既有 CHECK `('in_progress','completed','abandoned')` 拒绝 'PENDING_START'——**phase 新列与 status 双轨并存**是唯一可行形态（PENDING_START 状态落 phase 列，status 存量值不动）；⑩`question_score` 四步放宽法（ADD copy 列→UPDATE 拷→DROP 原列→RENAME）实测成功——gate 行需要 question_id/score_state 双列放宽才能插 NULL 行（四步放宽法为主推荐、哨兵值为备选，三方案对比见 Pitfall 4）。

**Primary recommendation:** 五个 plan 按既定切分落地：03-01 form_instance 新表（schema 快照 TEXT + status 生命周期 + 不可变 revision——新行不 UPDATE）+ question_score gate 列（五 ALTER + 人工覆盖四列）+ render_form 插入池耗尽分支（assessment.py 两处 return-None 前查 gate 采集）+ GET /forms/{id} 只读端点（渲染字段白名单分栏）+ submit 六维校验；03-02 submit_answer 改 StreamingResponse（先落库再推流——决策完整 commit 后才 yield 首个事件；generator 内零 DB 连接，快照提前读成局部变量）+ Pydantic 请求 schema（AnswerRequest）；03-03 idempotency_record 新表 + 两阶段 INSERT PENDING/UPDATE COMMITTED + revision 乐观锁 + 409 三态返回体；03-04 session_time_intervals 新表 + 部分唯一索引 + 闭/开 helper（Python 端区间 merge）+ 单题超时回调 02-04 封存链第四路 seal_reason='timeout' + 全场超时 GLOBAL_TIMEOUT→串行链 + 6h ABANDONED 惰性挂载 + last_activity_at 列 + 消息分列三列 + MAX_CONTEXT_TOKENS 滑窗（mock 全量直通）；03-05 INJECTION_DETECTED 事件（answer_state 分类驱动 + payload 无原文）+ PENDING_START→ACTIVE 入场确认端点。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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
- **D-40: 暂停 = 显式 pause 端点（候选人可触发 PAUSE_REQUESTED 事件 + PAUSED 区间）**；技术/无障碍/管理暂停走同一区间类型（reason 区分，敏感 reason 不进评分 prompt §15）；暂停期间答题被拒（409 SESSION_PAUSED）；resume 关闭 paused 区间。短暂断线不自动暂停（§15）。零散决策：暂停写 SESSION_PAUSE_REQUESTED/SESSION_RESUMED 事件（§13.2 SESSION_* 组既有枚举）。
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

### Deferred Ideas (OUT OF SCOPE)
- 断线续传 cursor / 事件回放（§11.5 留扩展记录）
- ABANDONED 会话恢复（「后续可开发可恢复，仅留记录」）
- 幂等记录清理阈值与管理员接口（策略实施期定——Phase 6 数据治理）
- LLM 导航摘要生成（结构化优先已满足，可选路径不实现）
- admin 表单人工覆盖前端 UI（Phase 5 报告链）
- Injection 检测 severity 分级与真实 LLM 检测质量（Phase 6 安全收口 + D-027 售后验证）
- grind: REF-4.11 Tools 白名单（延后不变）
</user_constraints>

## Project Constraints (from CLAUDE.md)

- **Think Before Coding**：不假设不臆测——**MAX_CONTEXT_TOKENS 数值是本 phase 最大「不臆造」红线**（SSOT §31-2「参数待定，留接口」——plan 只落占位常量 + 注释标注，数值守关口包）。REF-4.7 边界（新端点 vs 全量）已在 D-46 标记呈报项。
- **Simplicity First**：五条运行时行为（SSE/幂等/计时/表单/注入留痕）全部是 CONTEXT 锁定职责；不实现的部分（cursor/周期扫描强制/LLM 摘要/severity 分级）都有 explicit 的 deferred 记录。
- **Surgical Changes**：存量 sse.js/FormCard.vue **零改动**（研究已核对前端契约消费面完全就绪）；api/index.js 无需改（getForm/submitForm 已在）。匹配既有风格（raw SQL `?` 参数化、`{error_code, message}` 409 detail、`# noqa: E402`、mock `_mock_*` 相邻、中文 docstring）。
- **Goal-Driven Execution**：SC 1-5 → Validation Architecture 测试行映射（每 REF 至少一条断言，见 Nyquist 节）。
- **Git**：commit every working-tree change；当前分支 `feature/m5-assessment` 直接推进。
- **SSOT 治理**：本 phase 全部规格来自 SSOT §11.5/§12/§13/§14/§15/§16 既有条款，不需修改 SSOT。研究表明 0 个 CONFLICT。

## Project Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REF-2.4 | 新表 form_instance（schema 快照/生命周期） | DDL 设计（Code Examples #3）+ 不可变 revision 形态（新行不 UPDATE）+ status 生命周期枚举（rendered/submitted/superseded） |
| REF-2.6 | assessment_session 演进（phase/计时区间/abandoned/状态机） | phase TEXT 新列（status CHECK 拦新值——PENDING_START 落 phase 列）+ active_elapsed_seconds/last_activity_at/abandoned_at/policy_version/session_time_intervals_json 6 新列 ALTER（实验 8 验证） |
| REF-2.8 | assessment_message 分列（refined_content/client_request_id/sequence_no） | 3 新列 ALTER（实验 8）+ 写入点 = submit_answer 现行 refine 调用（assessment.py:206-211）扩三列 |
| REF-3.3 | experience/qualification 出普通题库改走表单 | question_bank.py:113 `scope='general'` 生成侧仍为 exp/qual 各 1 题（现状近似 D-32）——生成侧排除点 + gate 题不占 N 的 selection 白名单已在 ORDINARY_CATEGORIES |
| REF-4.6 | 真实 SSE（决策非流式先落库，话术逐 token） | StreamingResponse 同步 generator 骨架（Code Examples #1，实验 1-3 验证）+ sse.js 92 行逐字段对齐核对 + X-Accel-Buffering 头实测 |
| REF-4.7 | 接口层 Pydantic 请求/输出 schema | AnswerRequest/FormSubmitRequest/FormInstance Pydantic 模型（D-46 新端点范围）；存量端点不回溯——呈报项 |
| REF-4.8 | 计时区间（40/20/服务端权威/暂停/6h ABANDONED） | session_time_intervals DDL + 部分唯一索引（实验 6）+ Python 区间 merge 重叠（实验 5——SQL SUM 双计陷阱）+ 三 config 常量 |
| REF-4.9 | 幂等与并发（三键作用域；重复返回首次结果） | idempotency_record DDL + UNIQUE 三键索引（实验 4）+ 乐观锁 UPDATE rowcount（实验 4）+ 两阶段 INSERT PENDING 回放路径 |
| REF-4.10 | 表单链（render_form 代码触发/GET 只读/gate 结构化结果/人工覆盖二次确认） | render_form 插入点两处锚（assessment.py:323/343 picked is None 分支）+ gate 五列（实验 8/9）+ 六维校验执行序（本文件 Q2） |
| REF-4.12 | 上下文三层（滑窗/导航摘要/refine 分列） | MAX_CONTEXT_TOKENS 截断落点 interview.py:75-90 `_build_user_prompt` + mock 直通形态 + raw_hash/context_raw 既有机制核对 |
| REF-6.4 | INJECTION_DETECTED 事件留痕 | answer_state==PROMPT_INJECTION 分类驱动 + 决策链挂事件（assessment.py:239 OBSERVATION_CLASSIFIED 相邻位）+ payload 白名单（无原文） |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SSE 传输（text/event-stream） | API 层（assessment.py submit_answer → StreamingResponse） | — | D-33 锁定同 URL 直改；generator 只推已持久化的决策快照（服务层已完成落库）——传输层零业务逻辑 |
| 决策与落库时序 | API 层（submit_answer 主体，落库在 generator yield 之前完成） | Service 层（decide_next_action/select_next_question 不动） | D-33「先落库再推流」——把现有三相 commit 链条的最终响应 dict 改为事件序列，generator 内零 DB 连接 |
| form_instance 生命周期 | 数据库层（db.py 新表 DDL + _migrate_）+ Service 层（新 form_service 或 aggregation 相邻） | API 层（GET /forms/{id} 只读 + render_form 响应） | §16.1 生命周期实体；schema 快照 TEXT JSON 列——代码定义常量 + version 字符串 |
| gate 结构化结果 | 数据库层（question_score 5+4 新列）+ Service 层（scoring.py 的 INSERT 或 form 提交侧） | aggregation.py（_gate_check 迁移为消费结构化结果） | D-31 gate 判定不再从 payload 猜测——迁移路径保留 form_submission 读兜底 |
| 幂等作用域 + 乐观锁 | 数据库层（idempotency_record 新表 + UNIQUE 三键 + assessment_question.revision 列） | API 层（submit_answer 入口前置三键检查） | D-36/D-37 并发防护在 DB 层（IntegrityError/rowcount=0 是唯一可审计判据）——单写者 SQLite 天然低并发但 EXCEPT 外部客户端仍可双发 |
| 计时区间 | Service 层（timer 惰性推进 helper）+ 数据库层（session_time_intervals + 部分唯一索引） | API 层（answer/pause/form 请求点闭旧开新） | D-39 服务端权威惰性——无后台线程；区间 merge/超时判定是纯函数 |
| 单题超时封存 | API 层（submit_answer 入口单题超时点检）→复用 02-04 封存链 | Service 层（interval 查询 + 重叠计算） | D-41「请求时点计算」——answer 请求先判超时再走决策链 |
| 全场超时 / 6h ABANDONED | API 层（会话访问点检测）+ Service 层（事件写入） | `_generate_report_task` 串行链复用（现成入口） | GLOBAL_TIMEOUT 事件→ENTERED_SCORING→串行链；ABANDONED 惰性挂 load_owned_session 相邻（每个会话访问点） |
| 入场确认（PENDING_START→ACTIVE） | API 层（新端点 POST /sessions/{id}/start） | Service 层（开第一个 active 区间 + 首题激活） | §12.1 state machine + §15「确认开始且首题激活起算」——新端点足够（见 Q6） |
| 滑窗 Token 控制 | Service 层（interview.py `_build_user_prompt` 内截断） | — | D-43 interviewer prompt 拼装时截断——不新增服务、不改 decide_next_action 签名 |
| form 直提兼容（旧链） | API 层（forms/submit 旧端点保持） | — | form_submission 不动（D-29 保留兼容旧 UI）；新链 render→GET→submit→gate 走 instance |
| mock 假流分块 | API 层（generator 内 chunk 循环） | — | D-23 mock 双轨精神推广——reply 分块离线可测（决策语义与真实模式一致，只改传输节奏） |
| 事件留痕（SESSION_*/FORM_*/GATE_*/INJECTION_DETECTED） | state_events.append_event（复用） | 各调用点持事务 | D-06 契约不变；SSE 层零持久化（D-35） |
| 测试证明 | 测试层（test_phase3_* 五文件） | — | 单文件单进程 + /tmp 临时库 + mock 三件套；TestClient stream 消费面已实验验证 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard | Conf. |
|---------|---------|---------|--------------|-------|
| starlette.responses.StreamingResponse | 1.6.0（FastAPI 传递） | POST /answer 改 text/event-stream | 官方唯一路径（无 sse-starlette——`import sse_starlette` 实测失败）；同步 generator 经 `iterate_in_threadpool` 包装 | HIGH（实验 1/源码核读） |
| sqlite3（stdlib） | 3.45.3 | 新表 ×3 + ALTER ×16 列 + UNIQUE/PARTIAL INDEX + 乐观锁 | 既有栈——全部 DDL 特性本地实测（实验 4/6/8/9） | HIGH |
| pydantic | 2.10.3 | AnswerRequest / FormSubmitRequest / FormInstance Pydantic（D-46） | schemas.py 既有惯例（Literal/Field 先例，02-RESEARCH Literal 校验实测有效） | HIGH |
| fastapi.testclient（httpx 0.28.1） | — | SSE 流式消费：`with client.stream("POST",...) as r: r.iter_lines()` | 实测逐 chunk 到达（实验 3/11——POST+stream 组合可用） | HIGH |
| pytest | 9.1.1 | test_phase3_* 五文件 | 三件套纪律（TESTING.md 全文核对） | HIGH |

### Supporting
| Library | Version | Purpose | When to Use | Conf. |
|---------|---------|---------|-------------|-------|
| json（stdlib） | — | SSE 事件行 `json.dumps(..., ensure_ascii=False)` / schema 快照 / response_snapshot | 全部 JSON TEXT 列 | HIGH |
| hashlib（stdlib） | — | request_hash sha256 规范化 JSON / 沿用 raw_hash 机制 | 幂等键 + 消息分列 | HIGH |
| datetime（stdlib） | — | 区间 merge 重叠 + 6h 判定 | now_iso() 产物（带微秒+时区）`fromisoformat` 全兼容实测 | HIGH |
| threading.Timer | stdlib | 周期扫描 ABANDONED（**可选**——D-41 留 plan 裁量） | 惰性为主推荐不启（D-005 演示形态单进程纪律；BackgroundTasks 是既有「后台」边界） | HIGH |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| StreamingResponse 手写 SSE 帧 | sse-starlette 库 | **不可用**（本机未安装，D-005 技术栈锁定不新增依赖）——手写 `data: {...}\n\n` 三行格式是 SSE 子集，sse.js 逐字段对齐已核 |
| POST /answer 同 URL 直改 | 新建 /answer/stream 端点 | D-33 明锁同 URL 直改（sse.js 双 Content-Type 自适应已就绪）——新端点有两套语义漂移面 |
| revision 乐观锁（UPDATE WHERE） | 先 SELECT 后比对再 UPDATE | TOCTOU 窗口——条件 UPDATE 是原子的（rowcount=0 判一次完成） |
| 幂等快照 200 JSON 回放 | 重放 SSE 流 | **推荐快照 200 直返**（D-36「byte-级回放」字面 + 幂等层应在 SSE 启动之前拦截——否则重复请求会重新推流）。见 Q3 依据。Claude 裁量：response_snapshot 存普通 JSON dict |
| 部分唯一索引拦双开区间 | 应用层先查再插 | SELECT-INSERT 竞态窗口；部分唯一索引是 DB 层原子保证（实验 6 验证） |
| Python 端区间 merge | 纯 SQL SUM 聚合 | **SQL 不可用**——跨行 SUM 重叠段双计（实验 5：8min vs 6min）；Python merge 正确且代码可读 |

**Installation:**
```bash
# 无需安装任何新包。本机实测：Python 3.13.2 / starlette 1.6.0（FastAPI 0.141.1）/ httpx 0.28.1 / pydantic 2.10.3 / SQLite 3.45.3
```

**Version verification:** 本阶段**零新增包**——全部依赖为已装版本（本机 import 实测，见 Sources）；无 registry 检查需求。

## Package Legitimacy Audit

> 本阶段不安装任何外部包（零新依赖：sse-starlette 明确排除——手写 SSE 帧足够且 D-005 锁栈），此表不适用——无新包引入即无供应链风险面。

**Packages removed due to slopcheck [SLOP] verdict:** none（未运行——无新包）
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

Phase 3 改造后的答题主链（决策先落库再推流 + 幂等/计时前置）：

```
候选人浏览器 (Chat.vue → sse.js streamAnswer——零改动)
   │  POST /api/assessment/sessions/{id}/answer
   │       {question_id, answer, idempotency_key?, expected_revision?, client_attempt_id?}
   ▼
┌─ submit_answer（API 层，仍是单函数——内部时序重排）──────────────────────┐
│ 1) 能力检查: load_owned_session + status in_progress + 6h ABANDONED 惰性  │
│    （last_activity_at 判定——不在窗口置 abandoned + SESSION_ABANDONED 事件）│
│ 2) 暂停检查: session 有 open paused 区间 → 409 SESSION_PAUSED             │
│ 3) 幂等检查（带 key 时）: idempotency_record 命中且 COMMITTED            │
│    → 直接 200 返回 response_snapshot（不等 SSE——见 Pitfall 5 形态）        │
│ 4) 单题超时点检: now - activated_at - Σpaused 重叠 > 20min               │
│    → 封存 seal_reason='timeout'（02-04 第四路）→ 选下一题或全场超时收尾    │
│ 5) 乐观锁: UPDATE assessment_question SET revision=revision+1           │
│    WHERE question_id=? AND revision=?  → rowcount=0 → 409 版本冲突          │
│ 6) 原文+精炼分列落库（refined_content/columns）→ conn.commit()（先落库）  │
│ 7) decision = decide_next_action(...)（LLM 在无事务状态调用）            │
│ 8) 封存/推进/选题/事件（照 02-04/02-02 既有三相链条）→ 最终 conn.commit() │
│    （全部持久化动作完成——response 快照 dict 已在手）                      │
│ 9) 成功时: INSERT idempotency_record response_snapshot（COMMITTED）       │
└──────────────────┬────────────────────────────────────────────────────────┘
                   ▼
        StreamingResponse(event_gen(snapshot), media_type="text/event-stream")
                   │ （generator 内零 DB 连接——全部数据来自 step 8 快照）
                   ├─ yield 'data: {"type":"decision","action":...}\n\n'
                   ├─ yield 'data: {"type":"reply","content":"<chunk>"}\n\n' ×N
                   │    （mock 假流分块 = 按字符切片 + time.sleep(0)——离线可测节奏）
                   └─ yield 'data: {"type":"done","action":"next","next_question_id":...}\n\n'
                  
                   （客户端 abort → GeneratorExit——决策已落库不回滚，
                     MessageId 已生成；重连语义 = 幂等协议管辖 [D-33]）

表单链（池耗尽扩展，02-02 「None = finish」改三路）：
   select_next_question → None
      ├─ 旧: UPDATE session SET status='completed'（finish）
      └─ 新: 存在 gate=1 item 未采集（form_instance 无提交）
             → INSERT form_instance（schema 快照快照 + status='rendered'）
             → assistant 消息含 📎[form:{instance_id}] 标记（FormCard 已消费）
             → 返回 action='form'（sse.js decision 透传——sse.js 对 action 无白名单）
             → 候选人提交（POST submit_form 新端点六维校验）
             → gate 行写 question_score（gate_result 五列）→ GATE_EVALUATED 事件
             → 再次 select_next_question → None 且 gate 全采集 → finish（原路径）

计时区间（D-39 惰性推进）：
   每次请求（answer/pause/resume/form/start）→ close_open_interval(session_id)
   → open_interval(session_id, type, reason)   [部分唯一索引保证单 open]
   全场超时判定: Σ(active 区间) > SESSION_TOTAL_MINUTES → GLOBAL_TIMEOUT 事件
   → 停止新增主问题 → SCORE_QUEUE（串行链 _generate_report_task——复用 01-03 现成）
```

### Recommended Project Structure
```
server/
├── db.py                      # [改] _DDL 新表 ×3（form_instance/idempotency_record/session_time_intervals）
│                              #      + assessment_session 6 新列 ALTER + assessment_message 3 新列
│                              #      + question_score 5+4 gate 列 + assessment_question.revision
│                              #      + _migrate_phase3_* 嗅探式迁移（02-01 惯例）
├── config.py                  # [改] MAX_CONTEXT_TOKENS（占位）+ SESSION_TOTAL_MINUTES=40
│                              #      + QUESTION_TIMEOUT_MINUTES=20 + ABANDON_HOURS=6
├── schemas.py                 # [改] AnswerRequest / FormSubmitRequest（D-46 新端点 Pydantic）
├── services/
│   ├── forms.py               # [新，名 plan 定] form schema 常量 + render/submit/gate 判定
│   ├── idempotency.py         # [新，名 plan 定] 三键检查 + 快照写入 + 乐观锁 helper
│   ├── timer.py               # [新，名 plan 定] 区间闭/开 + Σactive + 单题超时 + 6h 判定
│   ├── interview.py           # [改] _build_user_prompt 滑窗截断（MAX_CONTEXT_TOKENS）
│   ├── question_selection.py  # [不动] select_next_question None 语义——插入点在 assessment.py
│   ├── state_events.py        # [不动] append_event 复用（SESSION_* 组 + INJECTION_DETECTED）
│   └── refine.py              # [不动] (refined, raw_hash) 现成——分列只扩 INSERT 列
├── api/assessment.py           # [重排] submit_answer 内部九步时序（上图）+ SSE generator
│                              #  + POST /sessions/{id}/start + POST pause/resume
│                              #  + GET /forms/{id} + POST /sessions/{id}/forms/submit-v2
│                              #  + admin 覆盖端点（gate 人工覆盖——路由在 admin/*.py）
└── api/admin/forms.py         # [新，名 plan 定] gate 人工覆盖 POST（override_reason 强制）

server/test_phase3_sse.py       # [新] SSE 流式消费断言（TestClient.stream + iter_lines）
server/test_phase3_forms.py     # [新] 表单全链（render→GET→submit→gate→revision）
server/test_phase3_idempotency.py # [新] 三键回放 + 乐观锁 + 并发双开区间
server/test_phase3_timer.py     # [新] 区间闭开/超时三路/6h ABANDONED/重叠 merge
server/test_phase3_misc.py     # [新] 滑窗/mock 全量/INJECTION/start 端点（名 plan 定）
```

### Pattern 1: SSE generator 骨架（先落库再推流——同步 generator 经 threadpool）
**What:** submit_answer 的持久化链条全部完成、快照 dict 组装完毕后，返回 `StreamingResponse`。generator 只消费局部变量（零 DB 连接、零额外查询）。
**When to use:** 03-02 主体；也在表单 render 路径（decision 事件携带 action='form'）复用。
**依据:** [VERIFIED: 本机实验 1/2——同步 generator 经 iterate_in_threadpool 包装]（starlette 1.6.0 `StreamingResponse.__init__` 源码：`if isinstance(content, AsyncIterable): ... else: self.body_iterator = iterate_in_threadpool(content)`）。
**Example:** 见 Code Examples #1。

### Pattern 2: 幂等两阶段（INSERT PENDING 占位 → UPDATE COMMITTED 快照）
**What:** 请求带 idempotency_key 时：入口先 `INSERT INTO idempotency_record(..., status='PENDING', snapshot=NULL)`（UNIQUE(session_id, endpoint, key) 拦并发双发——IntegrityError 即并发中或已完成）；业务链完成后 `UPDATE SET status='COMMITTED', response_snapshot=? WHERE key`。重复请求命中 COMMITTED → 直接回快照；命中 PENDING → 并发进行中（409 or 等待——推荐 409 快速失败）。
**When to use:** 03-03 主体（answer + submit_form 两端点）；PENDING 态保证崩溃后不留脏 COMMITTED（半事务不回放）。
**依据:** [VERIFIED: 实验 4——UNIQUE 索引 IntegrityError 拦双插实测]。

### Pattern 3: 部分唯一索引 = 并发双开区间的数据库层防护
**What:** `CREATE UNIQUE INDEX uq_sti_open ON session_time_intervals(session_id) WHERE ended_at IS NULL`——每 session 至多一个未闭合区间，DB 层原子保证。
**When to use:** 03-04 interval close/open helper 内。应用层「先 SELECT 后 INSERT」有 TOCTOU 窗口（两并发请求同 SELECT 到无 open → 双 INSERT）；部分唯一索引在 SQLite 3.45 实测拦截。
**依据:** [VERIFIED: 实验 6——双 INSERT IntegrityError 拦截 + 闭合后放行]。

### Pattern 4: 先 commit 再流式（「先 commit 再调 LLM」模式的传输层副本）
**What:** submit_answer 现行三相链条（用户消息 commit → LLM 决策 → 封存/选题/事件 commit）全部完成后，才开始 `yield`。GeneratorExit（客户端 abort）落在链条之外——已 commit 的事务不受影响。
**When to use:** 03-02——这是 D-33「决策先落库再推流」+ CONTEXT specifics「abort 后不回滚已落库决策」的直接实现。generator 体只有 for-loop + `yield`，无任何 `get_conn()`。

### Pattern 5: 不可变 revision（新行不 UPDATE）
**What:** form_instance 修订 = INSERT 新行（instance_id 不变 + revision+1 + status='superseded' 标旧行），不 UPDATE 旧行的内容列。审计链（追溯哪版被消费）+ 幂等（提交时校验 revision）依赖该形态。
**When to use:** 03-01 form_instance rev2+（同 instance_id 多行，active 判定 = revision 最大 + status='rendered'/'submitted'）；§16.1 原文「同一 instance 修订走不可变 revision」。
**对齐 SSOT:** [CITED: SSOT §16.1 — 「同一 instance 修订走不可变 revision」]——D-29 锁定。注意与 question_score 的 ATTRIBUTE 迁移惯例一致（不 UPDATE 历史）。

### Pattern 6: N11 代码校验枚举（全 phase 通用）
**What:** form_status（rendered/submitted/superseded）、interval_type（active/paused）、gate_result 三态、SESSION_* 枚举——全部模块级 tuple/Literal + 代码校验，不进 DDL CHECK。
**When to use:** 全部新表；对齐 02-01 先例（db.py:279 question_bank_task 无 CHECK 保守面）+ SSOT N11。

### Pattern 7: mock 双轨推广——假流分块
**What:** `_stream_tokens(text)` 或 generator 内 `for chunk in [text[i:i+4] for i in range(0, len(text), 4)]`——mock 模式分块推送（0 或极短 sleep——测试耗时不受影响）；分块大小与间隔是 Claude 裁量（D-23 特许——和「mock 模拟观察输出而非绕过裁决」同理，mock 模拟传输节奏而非绕过决策语义）。
**When to use:** 03-02 离线测试断言（decision 1 条 + reply N 条 + done 1 条——计数与单块内容均可断言）。
**注意:** mock 生成的决策 dict（含 reply 文本）与真实模式完全同构——分块只影响传输行为。

### Anti-Patterns to Avoid
- **Anti-pattern 1 — generator 内开 DB 连接：** 同步 generator 在 threadpool worker 里执行——连接泄漏无人回收、长流期间占用写锁。挂了就是 database is locked 全局冻结。**推流前快照 dict 组装完成，generator 纯推。**
- **Anti-pattern 2 — 幂等检查放 SSE 启动之后：** 先流后查会使重复请求重新推流（违背「返回第一次持久化结果」）。幂等命中在 StreamingResponse 返回**之前**。
- **Anti-pattern 3 — SQL SUM 直接算 paused 重叠：** 实验 5 实测——跨行 SUM 重叠段双计（8min vs 正确 6min）。Python 端 merge 后求和。
- **Anti-pattern 4 — status 列塞 PENDING_START/SCORING：** 既有 CHECK `('in_progress','completed','abandoned')` 拦新值（实验 8 实测 IntegrityError）。phase 新列承载状态机（PENDING_START/ACTIVE/SCORING/COMPLETED/ABANDONED），status 列存量语义不动——in_progress↔phase=ACTIVE 一一映射过渡。
- **Anti-pattern 5 — 滑窗截断在 mock 模式绕过：** mock 全量直通是 D-43 明文（「mock 模式直接全量」）——但 plan 必须为真实模式留截断点断言（不可测的常量是无意义的——见 Pitfall 9）。
- **Anti-pattern 6 — 逐 token 推送真的调 LLM 流式接口：** D-33「话术阶段逐 token」指传输形态。interviewer 决策的 reply 已在 decision dict（02-04 reply_suggestion）——SSE 分块推既有文本即可，不新增 LLM 流式调用面（llm.py 无 stream 接口，改动属 Prompt 模块周期）。**Claude 确认 D-33 的最小实现读取 decision['reply'] 后切分推送。**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE 帧解析（前端） | — | web/src/utils/sse.js streamAnswer（现存） | 92 行全文核读——`data: ` 前缀过滤 + 跨 chunk 半行缓存 + type 分发 + AbortController 全部就绪；**后端只需发对格式**（`data: {...}\n\n` + `data.content`） |
| 表单渲染（前端） | — | web/src/components/FormCard.vue（现存） | `📎[form:{id}]` 标记提取 + schema.fields 渲染 + submit 调用链全在——后端 GET /forms/{id} 返回 `{form_type, fields:[...]}` 即接管 |
| 表单 schema 校验 | 手写 if/else 逐字段 | schemas.py Pydantic（Literal + Field） | D-46 明锁；FormSubmitRequest payload dict → 业务校验函数（类型/必填/枚举/长度六维中后四维） |
| LLM 调用 trace | 新 SSE 层 trace | call_llm_json 既有 gateway（不动） | D-35——SSE 零持久化；决策链的 LLM 调用已在 call_llm_json 内 traced |
| 事件写入 | 手拼 INSERT | append_event（D-06） | 取号/actor_type 校验单点封装——SESSION_* 组 + INJECTION_DETECTED + FORM_* + GATE_* 全走此入口 |
| 迁移 | schema_version 登记簿 | _migrate_* 手写嗅探（02-01 惯例） | Phase 6 REF-2.11 收口；本阶段内嵌迁移 |
| 幂等键生成 | 时间戳+随机 | 客户端 uuid（前端 sse.js 现无 idempotency_key 字段——Phase 3 后端可选支持即可，前端补 key 属后续优化） | D-36「幂等键可选（缺省不启用）」——本期后端位就绪即满足 REF-4.9 契约 |
| 并发双开区间防护 | 应用层 SELECT-then-INSERT | 部分唯一索引 + IntegrityError 捕获 | 实验 6 实测原子性；Python 层 except sqlite3.IntegrityError 内 retry 闭合逻辑 |

**Key insight:** Phase 3「新东西」只有四个纯服务（forms idempotency timer 三服务 + admin 覆盖小端点）与三个 DDL 新表。其余是**现存资产的形态升级**——CatForm 卡片插入对话流已是既有设计（📎[form:] 标记解析先于 Phase 3 设计）。真正的复杂度集中在 submit_answer 的时序重排（九步），不是新概念。

## Runtime State Inventory

> 本阶段为 schema 演进 + 行为升级混合——无 rename/字符串替换，5 项核查如下：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | data/app.db（19 表 + question_bank_task；实测 4 session：3 completed / 1 in_progress）——评估列加列后旧行默认 NULL/'PENDING_START' 语义 | code edit——ALTER 迁移；旧行 phase='PENDING_START'（DEFAULT）+ last_activity_at=NULL 代码处处兜底（COALESCE(created_at)）。**无 data migration**（新列全可 NULL/默认） |
| Live service config | None — verified：单进程 uvicorn 手动启动、无 webhook/n8n/queue/pm2/launchd（grep 零命中 + ARCHITECTURE.md 系统图确认） | 无 |
| OS-registered state | None — verified：`git ls-files \| grep -iE "launchd\|plist\|systemd\|pm2"` 无命中 | 无 |
| Secrets/env vars | `.env`（不入库）——DB_PATH/LLM_API_KEY/JWT_SECRET 现有名；**新增 config 常量四位（SESSION_TOTAL_MINUTES/QUESTION_TIMEOUT_MINUTES/ABANDON_HOURS/MAX_CONTEXT_TOKENS）全部 code 常量不引 env 新名**（对齐 ORDINARY_PLAN_N 先例） | 无 |
| Build artifacts | web/dist（前端零改动——sse.js/FormCard 不动）无列名依赖；无 egg-info | 无 |

**结论：** 唯一 runtime 动作 = 03-01/03-04 的迁移函数对 data/app.db 的 ALTER + 新表 CREATE（正式运行时 init_db 触发）。存量 4 session（含 1 in_progress legacy）在新 phase 列下默认 PENDING_START——但 load/ask 链条有 status 兜底，不阻塞。演示数据允许重跑生成（02-DECISIONS 先例）。

## Code Examples

全部骨架已在本机实测验证（实验编号对应 Sources 的实测清单）：

### 1. SSE generator 骨架（03-02 主体——先落库再推流）
```python
# 依据：实验 1/2/3 + starlette 1.6.0 StreamingResponse 源码（iterate_in_threadpool）
# submit_answer 既有持久化链条完成后（decision/response dict 已在手）：
from fastapi.responses import StreamingResponse

def _sse_event(payload: dict) -> str:
    """单条 SSE 帧：`data: {json}\n\n`（sse.js:69-71 逐字段对齐——
    只解析 'data: ' 前缀行 + JSON.parse；ensure_ascii=False 保中文原样）。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

def _event_stream(decision: dict, question_id: str, next_question_id: str | None,
                  mock_chunks: int = 4) -> Iterator[str]:
    """generator 内零 DB 连接（threadpool worker——Anti-pattern 1）。
    mock 假流：reply 按字符等分 mock_chunks 块（决策语义与真实模式一致，
    只改传输节奏——离线可测）。"""
    # ① decision（一次性——sse.js onDecision 消费 action/reason/score_live + 扩展键）
    yield _sse_event({"type": "decision",
                      "action": decision["action"], "reason": decision["reason"],
                      "score_live": decision.get("score_live"),
                      "answer_state": decision.get("answer_state"),       # D-34 扩展键
                      "evidence_sufficient": decision.get("evidence_sufficient")})
    # ② reply 逐块（sse.js onReply 消费 data.content 逐块拼接）
    reply = decision.get("reply") or ""
    if config.LLM_PROVIDER == "mock":
        size = max(1, math.ceil(len(reply) / mock_chunks))
        chunks = [reply[i:i+size] for i in range(0, len(reply), size)]
    else:
        chunks = [reply]  # 真实模式：决策已含完整话术（02-04 reply_suggestion）——单块推送
    for chunk in chunks:
        yield _sse_event({"type": "reply", "content": chunk})
    # ③ done（sse.js onDone 消费 next_question_id + action——finish 时 next_question_id=None）
    yield _sse_event({"type": "done", "action": decision["action"],
                      "next_question_id": next_question_id})

@app.post("/sessions/{session_id}/answer")
def submit_answer(session_id: str, body: dict, user: dict = Depends(require_login)):
    ...  # 既有 1-9 步（幂等/超时/乐观锁/落库/决策/封存/选题）全部完成
    return StreamingResponse(
        _event_stream(decision, question_id, next_question_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # 实验 2 实测
    )
```

### 2. render_form 插入段（03-01——池耗尽三路改形）
```python
# 依据：assessment.py:323-334（picked is None 分支）+ question_selection 返回 None 语义
# 旧代码（两处对称——submit_answer:323 与 legacy:343 提前 return 处同构改造）：
        picked = select_next_question(session_id)
        if picked is None:
            conn.execute("UPDATE assessment_session SET status='completed', ...")
            ...
        # 新（action='form' 分支——池耗尽但 gate 未采集）：
        if picked is None:
            if not _all_gate_items_collected(conn, session_id):   # 检查 gate=1 item 覆盖
                instance = render_form_instance(conn, session_id)   # INSERT + FORM_RENDERED 事件
                conn.execute("INSERT INTO assessment_message(... role='assistant',"
                             " content=..., action='form', created_at=...)")
                # reply 文本含 📎[form:{instance_id}] 标记——FormCard extractFormId 正则
                # /📎\[form:([^\]]+)\]/ 消费（Chat.vue:159-162 核对）
                conn.commit()
                return StreamingResponse(_event_stream(
                    {"action": "form", "reason": "资格核验", "reply": f"请先填写资格核验表单 📎[form:{instance['form_instance_id']}]"},
                    question_id, None), media_type="text/event-stream", ...)
            # gate 全采集 → 原 finish 路径不变（D-30 扩展不改 02-02 池耗尽口径）
            conn.execute("UPDATE assessment_session SET status='completed', ...")
```

### 3. form_instance DDL + 六维校验序（03-01）
```sql
-- 依据：SSOT §16.1 + D-29（N11：无 CHECK 代码校验；列名照 CONTEXT D-29）
CREATE TABLE IF NOT EXISTS form_instance (
  form_instance_id TEXT PRIMARY KEY,
  session_id       TEXT NOT NULL REFERENCES assessment_session,
  schema_version   TEXT NOT NULL,           -- "v1" 起字符串版本（D-29）
  schema_snapshot  TEXT NOT NULL,          -- 快照整体 JSON（实例创建时固定）
  status           TEXT NOT NULL DEFAULT 'rendered',  -- rendered/submitted/superseded 代码校验
  revision         INTEGER NOT NULL DEFAULT 1,        -- 不可变修订（新行=N+1 不 UPDATE 旧行）
  payload_json     TEXT,                    -- submit 后填写（快照分离——渲染列/内部判分列分栏）
  created_at       TEXT NOT NULL,
  submitted_at     TEXT
);
```
```python
# 六维校验执行序（CONTEXT 研究问题 2——顺序按代价递增排列，先廉价后昂贵）：
def _validate_form_submission(conn, instance, session, payload: dict, user_id: str) -> None:
    # ①所有权：session.user_id == user_id（load_owned_session 已保证——复用）
    # ②状态：instance.status == 'rendered'（已 submitted → 409 FORM_ALREADY_SUBMITTED 幂等语义）
    # ③revision：body.expected_revision == instance.revision（乐观锁——409 版本冲突）
    # ④必填：schema 快照 fields[].required 逐项 in payload
    # ⑤枚举：fields[].options + 其他 schema enum 字段
    # ⑥长度：fields[].max_len（值截断拒绝不静默）
    ...
```

### 4. interval 闭/开 helper + 区间重叠 merge（03-04）
```python
# 依据：实验 5/6——重叠必须 Python merge（SQL SUM 双计）+ 部分唯一索引防双开
def close_open_interval(conn, session_id: str, *, ended_at: str | None = None) -> None:
    """闭合当前 open 区间（幂等：无 open 是 no-op）。调用者持事务不 commit。"""
    conn.execute(
        "UPDATE session_time_intervals SET ended_at=? WHERE session_id=? AND ended_at IS NULL",
        (ended_at or now_iso(), session_id))

def open_interval(conn, session_id: str, interval_type: str, reason: str | None = None) -> None:
    """开新区间。并发双开被部分唯一索引 uq_sti_open 拦截：
    except IntegrityError → 先 close 再重试一次（乐观防护环）。"""
    try:
        conn.execute("INSERT INTO session_time_intervals(interval_id, session_id,"
                     " interval_type, reason, started_at) VALUES(?,?,?,?,?)",
                     (new_id("sti"), session_id, interval_type, reason, now_iso()))
    except sqlite3.IntegrityError:
        close_open_interval(conn, session_id)
        conn.execute(...)  # 重试一次

def paused_overlap_seconds(conn, session_id: str, *, since: str, now: str) -> float:
    """单题超时判定：[activated_at, now] 窗口内 paused 区间总重叠（Python merge——实验 5）。"""
    rows = conn.execute("SELECT started_at, ended_at FROM session_time_intervals"
                        " WHERE session_id=? AND interval_type='paused'"
                        " AND ended_at IS NOT NULL", (session_id,)).fetchall()
    spans = sorted((_ts(r["started_at"]), _ts(r["ended_at"])) for r in rows)
    merged: list[list] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return sum((min(e, _ts(now)) - max(s, _ts(since))).total_seconds()
               for s, e in merged if min(e, _ts(now)) > max(s, _ts(since)))
# _ts = datetime.fromisoformat（now_iso 产物带微秒+时区——实验 8 全兼容）
```

### 5. 幂等两阶段 + 乐观锁 UPDATE（03-03）
```python
# 依据：实验 4——UNIQUE 三键 IntegrityError 拦双插 + UPDATE rowcount=0 即 stale revision
def check_idempotency(conn, session_id: str, endpoint: str, key: str,
                      request_hash: str) -> dict | None:
    """命中 COMMITTED 返回快照 dict（直接回放）；PENDING → 409 进行中；None → 首次。"""
    row = conn.execute("SELECT status, response_snapshot FROM idempotency_record"
                       " WHERE session_id=? AND endpoint=? AND idempotency_key=?",
                       (session_id, endpoint, key)).fetchone()
    if row is None:
        # 两阶段第一步：占位——并发双发时本次 INSERT 与 UNIQUE 冲突 IntegrityError
        conn.execute("INSERT INTO idempotency_record(id, session_id, endpoint,"
                     " idempotency_key, request_hash, status, created_at)"
                     " VALUES(?,?,?,?,?, 'PENDING', ?)",
                     (new_id("idem"), session_id, endpoint, key, request_hash, now_iso()))
        return None
    if row["status"] == "COMMITTED":
        return json.loads(row["response_snapshot"])   # 重复请求：byte-级快照直接返回（200 JSON）
    raise HTTPException(409, detail={"error_code": "REQUEST_IN_PROGRESS",
                                    "message": "同幂等键请求处理中"})

def request_hash_of(payload: dict, extra: dict | None = None) -> str:
    """sha256 规范化 JSON（Claude 裁量：sort_keys=True 保证字段序无关）。
    答题付三键并入 extra（question_instance_id/expected_question_revision/client_attempt_id）。"""
    blob = json.dumps({"payload": payload, "extra": extra or {}},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()

# 乐观锁（assessment_question.revision INTEGER NOT NULL DEFAULT 1）：
cur = conn.execute(
    "UPDATE assessment_question SET revision=revision+1"
    " WHERE question_id=? AND revision=?", (question_id, expected_revision))
if cur.rowcount == 0:
    raise HTTPException(409, detail={"error_code": "QUESTION_REVISION_CONFLICT",
                                     "message": f"题目版本冲突（expected={expected_revision}）"})
```

### 6. 滑窗截断落点（03-04/05 侧带——_build_user_prompt 现行 84-89）
```python
# 依据：interview.py:75-90（history 循环）+ D-43（mock 全量直通）
def _truncate_history(history: list[dict], max_tokens: int) -> list[dict]:
    """滑窗：从最新往回累积，超出 MAX_CONTEXT_TOKENS 的较早消息丢弃（近似 token = len//2）。
    最新回答不得重复拼接两次（§14——本题输入单独追加，不进 history 截断面）。
    mock 模式：直接返回全量（D-43——离线测试断言语义不随截断抖动）。"""
    if config.LLM_PROVIDER == "mock" or not history:
        return history
    kept: list[dict] = []
    total = 0
    for m in reversed(history):
        t = len(m["content"]) // 2
        if total + t > max_tokens and kept:
            break
        kept.insert(0, m)
        total += t
    return kept
# 落点：_build_user_prompt(session, question, _truncate_history(history, config.MAX_CONTEXT_TOKENS), ...)
```

## Common Pitfalls

### Pitfall 1: SSE 长连接与 SQLite 写锁的交错（★★★ 最高危）
**What goes wrong:** generator 内查询/落库——同步 generator 在 threadpool worker 执行，持有连接直到流结束。若流期间另一请求需要写库（如后台 `_generate_report_task`、或同一秒另一 answer），SQLite 单写者全部冻结（database is locked）；连接泄漏（client abort 后 finally 不保证跑）。
**Why it happens:** 最直觉的写法是「边查边推」——但 starlette 的 `iterate_in_threadpool` 对同步 generator 的消费是惰性的（客户端慢，yield 阻塞在 send）。
**How to avoid:** Pattern 1/4——**generator 体内零 `get_conn()`**。submit_answer 持久化链条全部 commit 完，快照进局部变量，再返回 StreamingResponse。测试可断言 generator 函数源码无 `get_conn`/`conn.`（静态 grep 断言）。
**Warning signs:** TestClient 下流式响应挂起/超时；uvicorn 多 worker 时 database is locked 间歇出现。

### Pitfall 2: StreamingResponse 里 LLM 调用超时与 CR-01 降级的叠加
**What goes wrong:** decide_next_action 的 LLM 调用（call_llm_json 重试 ×3）在 StreamingResponse **之前**（决策阶段 D-33 非流式先落库）——但若把它挪进 generator（错误尝试「边生成边推」），客户端 abort 会 kill 半途 LLM 调用，且 RuntimeError 无法转 HTTP 响应（stream 已开始，状态码已发）。
**Why it happens:** CR-01 修复（02-04：RuntimeError 降级 MODEL_UNCERTAIN）的前提是决策在普通 endpoint body 内——异常可转 5xx/正常 dict。
**How to avoid:** 决策 LLM 调用保持现状位置（submit_answer body 内，StreamingResponse 之前）；RuntimeError → decision='MODEL_UNCERTAIN' 的降级链 02-04 已内置（interview.py:216-221）。错误路径在流开始前全部消化——SSE 流本身只发 error 事件的场景限于「流中途环境故障」（本期几乎不发生——mock 零网络）。
**Warning signs:** generator 内出现 call_llm_json / try-except RuntimeError——是结构错误。

### Pitfall 3: form 快照不可变 vs 修订（新行不 UPDATE）
**What goes wrong:** 「修订」走 UPDATE payload_json——幂等回放时同一 instance_id 返回不同结果（首次响应快照被覆写），违反 §16.1。
**Why it happens:** UPDATE 比 INSERT 直觉；且 status 迁移似乎「就是更新」。
**How to avoid:** Pattern 5——修订 = INSERT 新行（revision+1）+ 旧行 status='superseded'（这次 UPDATE 只有 status，内容列零触碰——超链审计可解释）。active instance 查询 = `WHERE form_instance_id=? ORDER BY revision DESC LIMIT 1`（instance_id 不变——前端 📎[form:{instance_id}] 引用稳定）。
**Warning signs:** UPDATE form_instance 语句带 payload_json/snapshot 列名。

### Pitfall 4: gate 行进 question_score 的 NOT NULL/FK 拦路（列形态度量）
**What goes wrong:** D-31 目标是「gate 项行」落 question_score——但现行表 `question_id TEXT NOT NULL REFERENCES assessment_question`（db.py:202）。gate 判定源是 form_instance（不是题目实例）——question_id 无值可填。实测：NOT NULL 拦 NULL 插入（实验 9）；score_state 同样 NOT NULL。
**Why it happens:** question_score 是题目评分表，gate 是事实核验——SSOT §12.4 把两者并列于「question_score 演进」但语义源不同。
**How to avoid:** **三选一**（plan 裁量，研究推荐 ①）：
① **哨兵行法（推荐）**：gate 行 question_id 填 form_instance_id 串（如 `fi_xxx`）——但违反 FK（REFERENCES assessment_question）——**不行**，需先放开 FK；
② 四步放宽法：ADD question_id_v2 → UPDATE 拷贝 → DROP 原列 → RENAME（实验 9 实测成功；代价：FK 引用丢失——PRAGMA foreign_key_list 实测后仅剩 session FK；不破坏现存数据；report.py 消费面不受影响——gate 行不在其 SELECT 范围）；
③ gate 结果不落 question_score 而落 form_instance 行上的 gate 判定列 + aggregation._gate_check 直接查 form_instance——**但这与 D-31 字面「gate 结果落位 = question_score 表 gate 项行」冲突，需 checkpoint 呈报**。
推荐：若选择 ②，宽松后 gate 行 score_state 填哨兵'NOT_ADMINISTERED'（§12.4 枚举有位）或一并放宽。**研究中 ③ 与 D-31 字面有出入——正式推 ②，但注意 _gate_check 迁移路径（见下）**。
**Warning signs:** INSERT INTO question_score(...question_id...) VALUES(..., NULL,...) 抛 IntegrityError。
**_gate_check 迁移路径（D-31 具体而言）：** aggregation.py:48-70 现行 `_gate_check(item, form_payload)` 消费 form_submission payload——迁移后改查 question_score gate 行（gate_result 列）。**过渡期双源**：先查 gate 行（新链）→ 无行再回退 form_submission payload（旧链）——两个数据源在 03-01 内并存直至旧演示数据退役。plan 需显式写这个 dual-read。

### Pitfall 5: 幂等快照与 SSE 形态不一致
**What goes wrong:** 首次请求返回 SSE 流（text/event-stream），重复请求命中幂等回放 200 JSON——前端 sse.js 收到 `application/json` 会走形态 B 分支（**已适配**——sse.js:46-53）onDecision/onReply/onDone 照常触发。但「byte-级回放」语义微妙：快照存的是 SSE 事件序还是决策 JSON？
**Why it happens:** D-36 只说「响应快照 = 首次持久化结果的完整 JSON」——SSE 端点的「结果」是决策 dict 而非流本身。
**How to avoid:** 快照存**决策结果 dict**（action/reason/reply/score_live/answer_state/evidence_sufficient/question_id/next_question_id——即现行 submit_answer 的返回体）。重复请求的响应 = 200 `application/json` 直接返回该 dict（sse.js 形态 B 自动处理——`data.reply` 整段、`data.next_question_id`）。**这是 Claude 裁量推荐**（Q3）：重放流需要存储/重发 generator 语义（复杂），快照直返已满足「返回第一次持久化结果」（§13.4 字面）且 sse.js 双形态天然消费。plan 需在 03-03 写明：幂等命中返回 JSON 而非重放 SSE 流（注释引用本 Pitfall）。
**Warning signs:** 重复请求前端无 onReply 触发——检查 content-type 是否 application/json（sse.js:47 的 `contentType.includes('application/json')` 分支需命中）。

### Pitfall 6: interval 端点并发双开区间（乐观防护实测）
**What goes wrong:** 两个并发请求同时进 open_interval：都 SELECT 无 open → 双 INSERT → 两个 active 区间重叠，Σactive 虚增。
**Why it happens:** SQLite 单写者下事务串行但仍有两个连接交错窗口（get_conn 每调用一个新连接——assessment.py:139 先例 conn2）。
**How to avoid:** Pattern 3——部分唯一索引 `WHERE ended_at IS NULL` 拦截 + `except IntegrityError` 内闭合重试一次（乐观环）。标记：SQLite 部分索引官方文档 + 实验 6 双插实测拦截。**注意**：`CREATE UNIQUE INDEX ... WHERE` 子句是部分索引语法——`_DDL` 写 CREATE 语句、迁移写 IF NOT EXISTS 同语句（两轨同步 02-01 Pitfall 2 纪律继承）。
**Warning signs:** session_time_intervals 同 session 两行 ended_at IS NULL（测试断言不可出现）。

### Pitfall 7: 滑窗 Token 截断破坏 Pydantic 输入（挖掉语义）
**What goes wrong:** 截断历史把「当前题 stem」或「最新回答」挖掉——interviewer 分类错乱（例如把题干截掉，误判 OFF_TOPIC）。
**Why it happens:** naive 截断 = 头部截断（丢最新）或把 user_message 也算入窗口。
**How to avoid:** Code Examples #6——截断只作用于 history（`ORDER BY created_at` 的历史消息）；当前题 stem 与候选人回答**永远保留**（§14「最新回答不得重复拼接两次」——user_message 单独追加不进 history 面）。保序从旧往新丢弃（`reversed(history)` 累积法）。mock 全量直通（D-43）。
**Warning signs:** 真实模式（非 mock）下分类质量退化——mock 测试无感（全量）。plan 需为截断函数单独写纯函数单测（构造超长 history 断言保留尾部 N 条 + 当前题不被截）。

### Pitfall 8: mock vs 真实 SSE 的测试断言面差异（TestClient 流式消费方式）
**What goes wrong:** `client.post(...)` 的 `.text` 一次性拿全文+断言——**测不出「分块流式」**（断言通过但传输不是流式——事件全缓冲）。或者以为 TestClient 不支持流式而手写 socket。
**Why it happens:** TestClient 传统教学习惯是同步 `.post().json()`。
**How to avoid:** `with client.stream("POST", url, json=...) as r: for line in r.iter_lines():`——**实测可行**（实验 3/11：POST + stream + iter_lines + `data: ` 前缀逐条解析，decision/reply×5/done 事件序完整）。断言面：(a) Content-Type == text/event-stream、(b) 事件序 decision→reply(N 条)→done、(c) reply 块拼接 == 完整 reply（sse.js onReply 语义对齐）、(d) done.next_question_id 落库一致。注意 httpx 的 `iter_lines()` 注意'\r\n'与'\n'——SSE 标准要求 `\n\n` 帧间隔（sse.js 解析按 '\n' split——`data: {json}\n\n` 每帧两个换行，实验 3 实测通过）。
**Warning signs:** 断言只查 r.text 含 "decision"——流式语义不可证。

### Pitfall 9: MAX_CONTEXT_TOKENS 占位与「mock 全量」的测试覆盖面错位
**What goes wrong:** config 落占位常量（如 8000）+ mock 模式全量直通——**截断逻辑零测试覆盖**（测试全 mock 跑 = 直通分支）。
**Why it happens:** D-43 字面「mock 模式直接全量」。
**How to avoid:** ①截断函数 `_truncate_history` 是纯函数——**直测**不经过 mock 分支（构造非 mock 条件的调用参数，绕过 LLM_PROVIDER 判断——例如把 provider 判断参数化 `${provider}` 或单测传入真实模式风格参数）；②mock 分支另有断言（mock 下 history 全量传入）。两分支都要测。
**Warning signs:** 测试文件中 _truncate_history 只有 mock 一条路径的断言。
**裁量提示:** 这是 Claude 的一处实现建议——若 plan 决定 `_truncate_history` 不看 LLM_PROVIDER（纯函数 + 调用方决定传什么），更干净（推荐：调用方 `interview.py decide_next_action` 在 provider==mock 时传 history 全量）。plan 可改。

### Pitfall 10: 单题超时判定的 activated_at 为 NULL（legacy 实例）
**What goes wrong:** 旧数据/legacy 会话的实例 activated_at 是 NULL（02-02 起新实例才有值——`_instantiate` 写 activated_at=now）；`now - None` 直接 TypeError。
**Why it happens:** 列是 Phase 2 新加；legacy 旧行不回填（D-15）。
**How to avoid:** 超时点检 `activated_at IS NULL → 跳过判定`（不超时不封存——保守，与 D-15 旧数据不参与新路径一致）。同理 followup 共用单题计时器（§15）——实例封存即停止该题计时，followup 期间 activated_at 不变（无需重置）。
**Warning signs:** TypeError: unsupported operand type(s) for -: 'datetime' and 'NoneType'。

### Pitfall 11: 全场超时事件的顺序链（GLOBAL_TIMEOUT 先于 ENTERED_SCORING）
**What goes wrong:** 先写 SESSION_ENTERED_SCORING 再写 SESSION_GLOBAL_TIMEOUT——审计算子顺序倒置（先因后果）。
**Why it happens:** 串行链 `_generate_report_task` 现行 `_append_task_event(SESSION_ENTERED_SCORING)` 已在链条开头（:537）——直接复用会倒序。
**How to avoid:** 全场超时触发点（answer 请求点检超时后）**先** append SESSION_GLOBAL_TIMEOUT（from ACTIVE → SCORING 状态语义在 payload/from/to 标注）**再**调 `_generate_report_task`（其内部 ENTERED_SCORING 事件在链条起点自然靠后）。CONTEXT specifics 原文「SESSION_GLOBAL_TIMEOUT 事件优先于 ENTERED_SCORING（审计算子顺序：先因后果）」——落实为：GLOBAL_TIMEOUT 在调 serial 链**之前**的独立小事务落库。
**Warning signs:** 测试断言事件 sequence_no 顺序 GLOBAL_TIMEOUT < ENTERED_SCORING。

### Pitfall 12: 会话恢复期 PENDING_START 的 get_session 死循环
**What goes wrong:** 引入 PENDING_START 后，若 get_session 的「无未答实例 → select_next_question 派发」在 phase=PENDING_START 时也执行——首题被过早激活（§15「首题激活起算全场计时」——未确认开始就计时）。而若完全不派发，候选人界面无题可看（前端 load() 后 current_question=None 无限「正在准备」）。
**Why it happens:** 02-02 的 get_session 派发点不带 phase 检查（present 状态机前无此概念）。
**How to avoid:** get_session 派发分支加 `phase == 'ACTIVE'` 条件（PENDING_START 时 current_question=None——前端展示「确认开始」按钮，start 端点转换后 get_session 才派发首题）。**入场确认端点（POST /sessions/{id}/start）同时做三件事**：phase PENDING_START→ACTIVE + 开第一个 active 区间 + get_session/首题激活留给下次 GET（或直接返回首题——plan 裁量，前者简单）。
**Warning signs:** 前端_STARTED_后无题；或未点开始计时已开始（事件表 SESSION_STARTED 早于首题 QUESTION_ACTIVATED）。

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|------|------|------|------|
| `POST /answer` 返回一次性 JSON dict | StreamingResponse text/event-stream（decision/reply/done 三段流） | 本 phase（D-33/SSOT N9） | submit_answer 时序重排为九步；sse.js 形态 B 永不触发（成为纯回退路径——幂等 replay 时复用） |
| submit_answer body: dict 裸校验（body.get） | AnswerRequest Pydantic（D-46 新端点范围） | 本 phase | 422 语义不变（FastAPI 自动校验）——注意 `.strip()` 语义（WR-02）要在 validator 内保持 |
| gate 判定：form_submission payload 摸底（aggregation._gate_check:48-70） | question_score gate 行结构化结果（gate_result/gate_status/... 五列） | 本 phase（D-31） | _gate_check 迁移为双源读（gate 行优先 → form_submission 兜底） |
| form_submission 直提（form_type+payload） | form_instance 不可变 schema 快照 + 六维校验 + 幂等 | 本 phase（D-29） | 新增 GET /forms/{id} 只读端点 + 📎[form:] 标记生产者 |
| 计时缺失（无任何时间语义） | session_time_intervals 服务端权威 + 三超时路 + 6h ABANDONED | 本 phase（§15） | 每次请求闭旧开新；interval_type active/paused + reason 分隔 |
| 幂等缺失（重复 answer/表单提交可重复写） | idempotency_record 三键 + revision 乐观锁 | 本 phase（§13.4） | key 可选——不破坏无 key 前端调用 |
| status TEXT 'in_progress' 单调状态机 | phase 列 PENDING_START→ACTIVE→SCORING→COMPLETED + ABANDONED | 本 phase（§12.1） | 双轨并存（status 不动——CHECK 拦新值）；阶段判定以 phase 为准 |

**Deprecated/outdated:**
- `estimated_duration_minutes: 20`（create_session 响应 assessment.py:117）——SSOT §15 全场 40 分钟——**03-04 修正为 SESSION_TOTAL_MINUTES 常量派生**（前端无消费 grep 已核——修正是纯契约对齐）。
- form_submission 直提链（旧 UI）：保留兼容（D-29），不再扩展——新链全面 form_instance。

## Nyquist Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + FastAPI TestClient（httpx 0.28.1） |
| Config file | none — 三件套纪律（env 前置 + tempfile + mock；TESTING.md 全文核对） |
| Quick run command | `cd server && python -m pytest test_phase3_<area>.py -v`（单文件纪律） |
| Full suite command | 逐文件跑 5 个 phase3 文件 + 回归 test_m5/p0_chain/p0_security（**多文件不得同一次 pytest 收集**——DB_PATH 竞态） |

### Phase Requirements → Test Map（11 REF × 至少一条断言）

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REF-2.4 | form_instance 表落地：render→GET 只读→submit→revision 不可变（修订=新行）——instance 的 schema_snapshot 与代码常量一致；GET 不暴露内部阈值字段（白名单分栏断言） | integration | `python -m pytest test_phase3_forms.py -v` | ❌ Wave 0 |
| REF-2.6 | assessment_session 新列 + phase 状态机：PENDING_START→start 端点→ACTIVE→答题→finish→COMPLETED（事件序断言）；last_activity_at 每写刷新 | integration | 同上（forms/sse 文件搭车）+ test_phase3_timer.py | ❌ |
| REF-2.8 | 消息分列：raw_hash（既有）+ refined_content/client_request_id/sequence_no 三列落值；submit 后 content（refined）与 context_raw.full_text（原文）可分查 | integration | `python -m pytest test_phase3_misc.py -v` | ❌ |
| REF-3.3 | experience/qualification 不出普通题：动态选题全 session 提取 category 断言无 exp/qual；gate=1 item 由表单采集覆盖 | integration | test_phase3_forms.py（覆盖式断言） | ❌ |
| REF-4.6 | SSE 真实流式：Content-Type/事件序 decision→reply(N)→done/reply 块拼接完整/next_question_id 一致；Pydantic 422；abort 后决策已落库 | integration | `python -m pytest test_phase3_sse.py -v` | ❌ |
| REF-4.7 | 新端点 Pydantic：answer 缺 question_id → 422（FastAPI 自动）；表单提交体校验 | integration | test_phase3_sse.py + test_phase3_forms.py | ❌ |
| REF-4.8 | 计时区间：闭旧开新每次请求/暂停写 PAUSED 区间期间 answer 409 SESSION_PAUSED/单题超时（时间旅行注入 activated_at）封存 seal_reason=timeout + 续题/全场超时 GLOBAL_TIMEOUT 先于 ENTERED_SCORING/6h ABANDONED（时间旅行 last_activity_at）惰性判定/重叠区间 merge 纯函数直测 | integration + unit | `python -m pytest test_phase3_timer.py -v` | ❌ |
| REF-4.9 | 幂等：同三键重复 answer 返回首次快照（消息表无第二行）/revision 冲突 409/无 key 请求不受影响/form submit 同幂等/concurrent IntegrityError 路径 | integration | `python -m pytest test_phase3_idempotency.py -v` | ❌ |
| REF-4.10 | 表单链全链：池耗尽且有 gate item → form_instance rendered + 📎[form:] 标记/submit 六维校验失败各错误码/gate 行落 question_score 五列/GATE_EVALUATED 事件/admin 覆盖无 override_reason 被拒（二次确认） | integration | `python -m pytest test_phase3_forms.py -v` | ❌ |
| REF-4.12 | 上下文三层：_truncate_history 纯函数直测（保尾部/保题干/mock 全量两分支）/滑窗常量存在/config 占位注释「实施期校准」 | unit | `python -m pytest test_phase3_misc.py -v` | ❌ |
| REF-6.4 | INJECTION_DETECTED：mock 注入词 → answer_state=PROMPT_INJECTION → 事件行存在 + payload 不含原文字段（白名单断言 answer_state/stability） | integration | `python -m pytest test_phase3_misc.py -v` | ❌ |

### Sampling Rate
- **Per task commit:** 撞到的单测试文件（<30s 全 mock 离线）
- **Per wave merge:** 5 个 phase3 文件逐个跑 + 回归三件（test_m5_backend / test_p0_chain / test_p0_security——SSE/answer 响应形态变更的断言重写后）
- **Phase gate:** 全绿 → `/gsd:verify-work`；SC 1-5 逐条核验

### Wave 0 Gaps
- [ ] `server/test_phase3_sse.py` — REF-4.6/4.7（TestClient.stream + iter_lines 断言面）
- [ ] `server/test_phase3_forms.py` — REF-2.4/3.3/4.10（render→GET→submit→gate→revision 链）
- [ ] `server/test_phase3_idempotency.py` — REF-4.9（三键回放+乐观锁+双开区间）
- [ ] `server/test_phase3_timer.py` — REF-2.6/4.8（区间+超时三路+6h+merge 纯函数）
- [ ] `server/test_phase3_misc.py` — REF-2.8/4.12/6.4（分列+滑窗+start 端点+注入事件；名可改）
- [ ] 回归：test_m5_backend 的 answer 断言适配 SSE 响应形态（见 Pitfall 8 消费方式——旧 `r.json()['action']` 断言改流式解析 helper）
- [ ] 无框架安装需求（pytest 已在）

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（不改认证） | 既有 require_login 依赖链不动 |
| V3 Session Management | **yes（phase 状态机）** | PENDING_START→ACTIVE→SCORING→COMPLETED 代码唯一状态机（D-003）；转换全事件留痕；人生周期硬约束在 API 层（409 拒绝非预期转换） |
| V4 Access Control | **yes（新端点）** | GET /forms/{id} 与 submit 走 load_owned_session 同一口径（Phase 1 既有 helper）；admin gate 覆盖端点 require_admin |
| V5 Input Validation | **yes（六维校验+Pydantic）** | FormSubmitRequest Pydantic（D-46）+ 六维校验序（类型/必填/枚举/长度在服务端）；answer 输入 MAX_ANSWER_LEN 既有护栏保持 |
| V6 Cryptography | no | sha256 request_hash/raw_hash 沿用（无新密码学面） |

### Known Threat Patterns for {stack}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 幂等键猜测/劫持（猜他人 idempotency_key 回放他人结果） | Tampering / Info disclosure | 三键作用域含 session_id + 所有权校验前置（load_owned_session）——他人 key 在他人 session 域内命中不了你的 record（UNIQUE 三键含 session_id——查不到=404/409 由所有权先拦） |
| 表单 payload 注入（超长/嵌套 JSON 炸弹） | DoS | 六维校验长度维 + payload JSON 深度/大小上限（MAX_ANSWER_LEN 既有惯例可参照——截断拒绝不静默） |
| 内部阈值泄露（GET /forms/{id} 暴露 gate 判定参数） | Info disclosure | schema 快照分栏：渲染字段白名单（fields/label/type/options）——内部判分字段（years 门槛值/required_level）不出现在 GET 响应（CONTEXT specifics 原文） |
| 幂等快照回放包含敏感数据 | Info disclosure | response_snapshot 只存决策结果 dict（answer_state/reason 等非原文——与 INJECTION_DETECTED 不含原文同纪律） |
| SSE 流中途客户端断开的半写状态 | Tampering | 「先落库再推流」——abort 只影响传输不影响持久化（D-33）——一致性由 revision/幂等层保 |
| 暂停滥用（反复 pause 无限暂停规避 6h ABANDONED） | DoS | last_activity_at 每次写操作刷新（pause 也是写）——但 ABANDONED 判定 = 6h 无活动；暂停中的会话在 6h 后同样 ABANDONED（§15 不细化恢复——本期不可恢复即冻结证据） |
| INJECTION 事件的原文泄露（payload 存原文） | Info disclosure | payload 白名单 {answer_state, stability}——不含输入原文（D-45 字面） |

## Sources

### Primary (HIGH confidence)
- `design/final-design/总设计文档.md` §11.5/§12.1-12.3/§13.2/§13.4/§14/§15/§16.1-16.2/§31 — 全部契约条款逐字核对（本 phase 规格）
- `web/src/utils/sse.js` 92 行全文 — decision/reply/done/error 四事件 + `data: ` 解析 + 半行缓存 + 双形态自适应逐字段核对
- `server/api/assessment.py` 636 行全文 — submit_answer 三相链条（commit 边界：218/316/357）、get_session 派发点、池耗尽两 return-None 分支（:323/:343 与 selection.py:315/343/344 对位）、_append_task_event/_generate_report_task 串行链
- `server/services/question_selection.py`（612 行——select_next_question/_select_next_question_locked/_instantiate/_session_instance_state 全读）— 池耗尽 None 语义 + legacy 判定 + seq/事件落库形态
- `server/services/interview.py` 266 行全文 — decide_next_action 决策链（LLM 调用位置 :212 + RuntimeError 降级 :216-221）+ _build_user_prompt 滑窗落点 :75-90 + _mock_interview 词表
- `server/services/aggregation.py` 192 行全文 — _gate_check payload 摸底（:48-70）+ gate_items 消费 + 分母规则
- `server/db.py` 477 行全文 — _DDL 19 表 + _migrate_* 嗅探式惯例 + status CHECK 拦新值实测依据
- `server/schemas.py` 96 行全文 — InterviewObservation/ANSWER_STATES/pydantic 惯例
- `server/services/llm.py` 63 行全文 — call_llm_json 无流式接口（Anti-pattern 6 依据）+ RuntimeError 语义
- `server/services/refine.py` 44 行全文 — (refined, raw_hash) 返回 + context_raw 归档
- `server/services/scoring.py`（相关段）— INSERT question_score 列清单（:246-249）+ score_session 护栏
- `server/config.py` 51 行 — ORDINARY_PLAN_N 先例 + REFINE_MIN_TOKENS + 常量分区惯例
- `server/services/pipeline.py:14-19` — now_iso() 带 UTC 时区+微秒（实验 7/8 兼容性依据）
- `web/src/views/assessment/Chat.vue`（相关段 :150-266）+ `web/src/components/FormCard.vue`（全文）+ `web/src/api/index.js`（:42-48）— 前端契约消费面（extractFormId 正则/getForm 路由已调/submitAnswer 回调消费/sse.js 形态 B 分支）
- `eval/virtual_candidates.py:102-146` — 直插链（无 answer API 调用——SSE 化无影响面，CONTEXT 代码现状标注已验证）
- 本机实测 11 项（2026-09-05，Python 3.13.2 / FastAPI 0.141.1 / starlette 1.6.0 / httpx 0.28.1 / pydantic 2.10.3 / SQLite 3.45.3）：SSE StreamingResponse 同步 generator / TestClient POST+stream 逐行消费 / X-Accel-Buffering 头 / HTTPException 前置 JSON 错误 / 幂等 UNIQUE 三键 IntegrityError / 乐观锁 rowcount=0 / 部分唯一索引双开拦截 / SQL SUM 双计 vs Python merge / now_iso 时区微秒兼容 / status CHECK 拦 PENDING_START / question_score 四步放宽法 + 哨兵行插入
- `.planning/intel/decisions.md` D-005 全文 — 单进程演示形态（不启后台服务依据）

### Secondary (MEDIUM confidence)
- [FastAPI/Starlette StreamingResponse + client disconnect 行为](https://fastapi.tiangolo.com/advanced/custom-response/)（WebSearch 摘要交叉核对——WebFetch 域名受限）— 同步 generator 经 threadpool、GeneratorExit 需 re-raise、`finally` 比 catch 更稳、`request.is_disconnected()` 可选轮询：「[WebSearch verified with official source]」——与本研究本地实验 1/2 一致，采信。Sources: [FastAPI custom response docs](https://fastapi.tiangolo.com/advanced/custom-response/) 及搜索摘录的社区共识模式（Starlette changelog 与 ASGI 语义）

### Tertiary (LOW confidence)
- 无（外部源唯一依赖点是 starlette 并发语义——已由本地实验 1/2/3 与源码读取双重覆盖，WebSearch 仅作背景确认）

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 幂等命中返回 200 JSON（决策 dict 直返）而非重放 SSE 流——sse.js 形态 B 自动消费 | Pitfall 5 / Q3 | 若 plan-checker 判定 REF-4.9 要求「同 Content-Type 回放」，需把快照改为事件序列 JSON 重发（复杂度小幅上升——generator 消费事件列表）|
| A2 | question_score gate 行采用四步放宽法（question_id/score_state 放开 NOT NULL）——与 D-31 字面「gate 项行」最直接对齐 | Pitfall 4 | 若 plan 选哨兵'NOT_ADMINISTERED'+独立 FK 校验（不放宽），scoring INSERT 需跳过 gate 行（两套 INSERT 列清单）；若彻底走 form_instance 行（③），D-31 需微调（checkpoint 呈报项） |
| A3 | 6h 周期扫描不启（惰性判定唯一实现）——D-41「周期扫描作为可选独立小函数留 plan 裁量」，本研究推荐不实现 | 计时区间 / Q4 | 若 plan 检查器要求实现周期扫描最小形态，`threading.Timer` 循环是 10 行方案（uvicorn 单进程生命周期内 daemon 线程 + unsubscribed 无害退出）；但不启比启更符合 D-005 |
| A4 | submit_answer 幂等检查先于单题超时点检（时序图 step 3→4） | 架构图 | 若超时先判（4→3），已超时题+重复提交会先封存再回快照（重复请求改变了状态——违背幂等）。研究按「幂等最先」排，plan 可对换但需论证 |
| A5 | `estimated_duration_minutes` 由 20 改 40（config 派生）| State of the Art | 前端无消费（grep 已核）——低风险；若改值引入前端断言注意 test_m5 |
| A6 | PENDING_START→ACTIVE 用新端点 POST /sessions/{id}/start（对照 §15「确认开始」语义——get_session 隐式转换会让「刷新页面」误触开始） | Q6 / Pitfall 12 | 若用 get_session 首次派发隐式转换，前端需提交确认交互改造（Chat.vue 有现成「开始测评」页面逻辑可复用）——改动面在前端层——属 UI phase plan 裁量 |
| A7 | form_instance 新表与 idempotency_record 同期落 DDL（03-01/03-03 波次可分） | Recommended Project Structure | 若 wave 顺序调整（03-03 先行），phase 分层依赖需同步调整——无技术风险只有顺序风险 |
| A8 | Chat.vue 加载恢复链 `data.messages` 在后端 get_session 不存在（前端容忍 undefined 不炸——`for (const m of data.messages \|\| [])`）| 代码现状 | Phase 3 不需补 messages 返回（刷新恢复无需求——refactor 属 Phase 6 E2E）；若用户要求刷新恢复需加查询端点——不属本 phase |

## Open Questions（全部 RESOLVED——研究内闭合）

1. **Q1 — SSE 实现形态（决策先落库次序 + abort 处理 + mock 假流）**
   - Resolved: Pattern 1/4 + Code Examples #1 + Pitfall 1/2。同步 generator 经 `iterate_in_threadpool`（starlette 源码确认）；持久化完成→快照 dict→StreamingResponse；generator 内零 DB 连接；GeneratorExit 不 handle（无需——abort 只影响传输，已 commit 决策不回滚）；sse.js:69-71 的 `data: ` + JSON.parse + type 分发逐字段核对一致（decision: action/reason/score_live + 扩展键、reply: content、done: next_question_id + action——`data.action` 在 done 形态 B 也消费）；mock 假流 = 字符等分 4 块（Claude 裁量）。
2. **Q2 — form_instance 全链（DDL/快照形态/render 插入点/六维序/gate 列形 + _gate_check 迁移）**
   - Resolved: Code Examples #2/#3 + Pitfall 3/4 + D-29~D-32 逐条落点。render_form 插入锚 = assessment.py:323-334（submit_answer picked-None 分支）+ :343-353（legacy 对称分支——两者都要改）+ select 直接 None 的另两处（:315/:343 selection 内部 return None 不动——扩展点在 API 层）。六维校验序 = 所有权→状态→revision→必填→枚举→长度（廉价先行）。gate 五列 ALTER + 人工覆盖四列（D-31 全集）。_gate_check 迁移双源（gate 行优先 → form_submission 兜底——Pitfall 4 详述）。
3. **Q3 — 幂等（三键索引形态 / 快照回放形态 / 409 响应体）**
   - Resolved: UNIQUE(session_id, endpoint, idempotency_key) 复合三键索引（不是单列 hash——D-36 字面「key 唯一」在作用域语义下即三键唯一；实验 4 验证同 key 不同 endpoint 放行=语义正确）。重复请求 = 200 JSON 快照直返（A1/Pitfall 5 推荐 + sse.js 形态 B 天然消费）。409 响应体 = `{error_code: 'QUESTION_REVISION_CONFLICT'/'REQUEST_IN_PROGRESS'/'SESSION_PAUSED', message}` 三态沿用 WR-01 惯例。乐观锁 = UPDATE WHERE revision=? rowcount（Code Examples #5）。
4. **Q4 — 计时区间（DDL/事务边界/单题超时 SQL/6h 挂载点/周期扫描形态）**
   - Resolved: DDL + 部分唯一索引（Pattern 3）+ 闭/开 helper Python merge（Code Examples #4）+ 单题超时 Python 计算（**SQL SUM 双计陷阱实验 5 已证**——不推荐 SQL 形态）。与 submit_answer 主事务交错：闭旧开新在主事务**内**（小 UPDATE/INSERT，同事务无交错——不存在独立事务并发窗口）；SQLite 单写者纪律 = 单事务多写合并（append_event 同款契约）。6h 挂载点= load_owned_session 相邻（每次会话访问点——load_owned_session 是全部会话端点的公共入口：answer/get/form/pause）。周期扫描 = 不推荐线程（D-005；A3）——「惰性为主」与 D-41「择惰性为主」一致。
5. **Q5 — 消息分列 + 滑窗（接入点/落点/常量/mock 全量）**
   - Resolved: refine_user_input 现行调用点 = assessment.py:206-211（user 消息 INSERT 处，refined 存 content + raw_hash 存档——分列只扩 INSERT 列：raw_content synonym 不需要（D-43「raw_content 改名不动」——content 列直接复用 refined，原文在 context_raw 表经 raw_hash 引用——现状已如此）；新三列 = refined_content（同 content 值或 NULL——plan 定对齐口径）、client_request_id（幂等扩展键值）、sequence_no（消息序）。滑窗落点 = interview.py:84-89 history 循环前（Code Examples #6）。MAX_CONTEXT_TOKENS = config 占位（SSOT §31-2 开放参数——**数值不代决**：plan 写常量 + 注释「实施期校准，关口包呈报项」）。
6. **Q6 — SESSION_* 事件激活面（PENDING_START→ACTIVE 端点 / GLOBAL_TIMEOUT 次序 / ABANDONED）**
   - Resolved: 入场确认 = **新建 POST /sessions/{id}/start 端点**（对照 §15「从候选人确认开始且首题成功激活起算」——「确认」是有意 action，get_session 是无感读操作不适合承载状态转换——A6 推荐）；转换动作 = phase PENDING_START→ACTIVE + SESSION_STARTED 事件 + 开第一个 active 区间。get_session 派发点加 phase=='ACTIVE' 条件（Pitfall 12——防未确认先计时）。GLOBAL_TIMEOUT = answer 点检超时后独立小事务先落 → 再调 _generate_report_task（Pitfall 11 审计算子顺序）。ABANDONED = 惰性（load_owned_session 相邻判定）+ SESSION_ABANDONED 事件 + abandoned_at 列 + 不删证据。
7. **Q7 — 风险与坑清单**
   - Resolved: 12 Pitfalls（上文）——最高危三项：Pitfall 1（SSE×SQLite 写锁）、Pitfall 4（question_score gate 行 NOT NULL 阻路）、Pitfall 5（幂等快照 vs SSE 形态）。全部有本地实测或逐行代码证据（无纯推演项）。
8. **Q8 — Code Examples 六段**
   - Resolved: #1 SSE generator、#2 render_form 插入、#3 form DDL+六维、#4 interval helper、#5 幂等+乐观锁、#6 滑窗——每段标实验依据。
9. **Q9 — Nyquist 断言清单**
   - Resolved: 11 REF → 测试地图（Validation Architecture 表）——每 REF 至少一条可测断言（含事件序/rowcount/快照回放/流式事件序等强断言形态）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | 全部 | ✓ | 3.13.2 | — |
| FastAPI/starlette | SSE 端点 | ✓ | 0.141.1 / 1.6.0 | — |
| httpx（TestClient 传递） | 流式测试 | ✓ | 0.28.1 | — |
| pydantic | D-46 请求 schema | ✓ | 2.10.3 | — |
| SQLite | 三新表+ALTER | ✓ | 3.45.3（部分索引/RENAME COLUMN 均支持） | — |
| sse-starlette | （备选） | **✗** | — | 不使用（手写 SSE 帧——D-005 锁栈；sse.js 只需标准 `data: ` 帧） |
| pytest | 测试 | ✓ | 9.1.1 | — |
| 业务库 data/app.db | 迁移直升目标 | ✓ | 19 表（state_event/question_bank_task 已在——Phase 1/2 迁移占位） | 演示数据允许重跑 |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** sse-starlette（缺失但明确不使用——不是依赖）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 零新增包；starlette/httpx/sqlite 三个版本本机实测
- Architecture: HIGH — 全部改造对象全文直读 + sse.js/FormCard.vue 前端契约逐字段核对（零前端改动的断言依据）+ 11 项实验验证
- Pitfalls: HIGH — 12 项中 10 项有本地实验或逐行代码证据；A1/A2/A6 三个实现选择项已标 [ASSUMED] 待 plan 呈报

**研究问题解决：** 9/9（CONFLICT 0——D-29~D-46 全部有可行落点，无 SSOT/CONTEXT 违背发现）

**Research date:** 2026-09-05
**Valid until:** 2026-10-05（规格来自仓库内 SSOT 静态文件 + 本机环境，30 天惯例窗口）
