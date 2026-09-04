---
phase: 3
slug: sse
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-05
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> 内容来源：03-RESEARCH.md「## Nyquist Validation Architecture」；结构先例：02-VALIDATION.md。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + FastAPI TestClient（httpx 0.28.1——`client.stream` + `iter_lines` 流式消费面已实验验证） |
| **Config file** | none — 单文件单进程纪律（TESTING.md；Phase 6 REF 才统一收集） |
| **Quick run command** | `cd server && python -m pytest test_phase3_<area>.py -v`（受影响单文件） |
| **Full suite command** | 逐文件：`test_phase3_forms.py` → `test_phase3_sse.py` → `test_phase3_idempotency.py` → `test_phase3_timer.py` → `test_phase3_misc.py` → `test_m5_backend.py` → `test_p0_chain.py` → `test_p0_security.py` → `test_phase2_interview.py` → `test_phase2_difficulty.py` → `test_phase2_selection.py` → `test_phase2_scoring.py`；脚本式：`python test_m6_backend.py`、`python test_question_bank.py`（**一次 pytest 不得收多文件**——DB_PATH 竞态红线） |
| **Estimated runtime** | ~90–150 seconds（全 mock 离线逐文件串行） |

---

## Sampling Rate

- **After every task commit:** 该任务撞到的单测试文件（<30s）
- **After every plan wave:** 5 个 phase3 文件 + 回归面（02-02 Task 4 同节奏——本 phase 回归面经 03-02/03-05 已含 12 文件）
- **Before `/gsd:verify-work`:** Full suite green + SC 1-5 逐条核（ROADMAP Phase 3 Success Criteria）
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | REF-2.4/4.10 | T-03-01/02 | 迁移双路径（老库放宽保数据）+ render 触发（📎[form:] 标记）+ GET 白名单（无阈值键）+ 六维各错误码 + gate 行五列（question_id/score_state NULL）+ revision 不可变 + admin 覆盖无 reason 422 + 双源优先级 + score_session 保留 gate 行 + exp/qual 不入选题 | integration+unit | `cd server && python -m pytest test_phase3_forms.py -v` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | REF-2.4 | T-03-03 | form_instance DDL/迁移幂等；gate 九列；四步放宽（RENAME）；gate 行可插 NULL 列；无新 DB CHECK | unit | `python -c` DDL 烟测（Task 2 verify）+ `pytest test_phase3_forms.py -v` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | REF-4.10 | T-03-03/06 | forms.py 接 conn 不 commit；GATE_EVALUATED 事件 payload；_gate_check 双源兜底；scoring DELETE gate_result IS NULL | integration | `python -c` 服务 import 烟测 + `pytest test_phase3_forms.py -v` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | REF-4.7/4.10/3.3 | T-03-05 | render 两插入点（gate 全采集面 finish 逐字不动）；GET /forms URL 契约（无 /sessions 前缀）；submit-v2 Pydantic；admin 覆盖端点 + main.py 注册；p0 双文件表单步骤适配（D-09 只改步骤） | integration | `pytest test_phase3_forms.py test_p0_chain.py test_p0_security.py test_m5_backend.py test_phase2_interview.py`（逐文件） | ⚠️ 既有改造 | ⬜ pending |
| 03-02-01 | 02 | 2 | REF-4.6 | T-03-07/08 | Content-Type text/event-stream；事件序 decision→reply×N→done；reply 拼接==落库 reply；done.next_question_id 一致；abort 后决策已落库；generator 静态零 DB；422 三态（缺字段/纯空格 WR-02） | integration | `cd server && python -m pytest test_phase3_sse.py -v` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 2 | REF-4.6/4.7 | T-03-07/09/10 | 三 return 统一 StreamingResponse；commit 锚点零位移；AnswerRequest 五键 + validator；X-Accel-Buffering；form 分支 action='form' 透传 | integration | `pytest test_phase3_sse.py -v` + 零 DB 嵌入断言 | ❌ W0 | ⬜ pending |
| 03-02-03 | 02 | 2 | REF-4.6 | — | 7 回归文件 _answer helper 流式解析适配（断言行零改动——D-09）；错误路径仍 JSON | regression | `for f in test_m5_backend test_p0_chain test_p0_security test_phase2_interview test_phase2_difficulty test_phase2_selection test_phase2_scoring; do pytest`（逐文件） | ⚠️ 既有改造 | ⬜ pending |
| 03-03-01 | 03 | 3 | REF-4.9 | T-03-12/13/14 | 三键回放（消息/事件零增量）；PENDING 409；hash 敏感；键隔离（同 key 跨 endpoint）；revision 乐观锁（rowcount 409）；无 key 零记录；表单幂等；快照白名单无原文 | integration | `cd server && python -m pytest test_phase3_idempotency.py -v` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 3 | REF-4.9 | T-03-14/16 | UNIQUE 三键 IntegrityError 实测拦截；revision 列双轨；_instantiate INSERT 补列；两阶段 check/finalize 职责分置 | unit | `python -c` UNIQUE/revision 烟测（Task 2 verify）+ `pytest test_phase3_idempotency.py -v` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 3 | REF-4.9 | T-03-15/16 | 前置检查在 StreamingResponse 之前（Anti-pattern 2）；快照 200 application/json（sse.js 形态 B）；A4 次序注释；两端点两点接入 | integration | `pytest test_phase3_idempotency.py test_phase3_forms.py test_phase3_sse.py test_m5_backend.py test_p0_chain.py`（逐文件） | ⚠️ 既有改造 | ⬜ pending |
| 03-04-01 | 04 | 4 | REF-2.6/2.8/4.8/4.12 | T-03-18/20/22/24 | merge 纯函数表驱动（SQL SUM 反例）；partial unique 拦截/释放；单题超时封存（seal_reason=timeout + 两事件 + answered_at NULL）；全场超时序（GLOBAL_TIMEOUT < ENTERED_SCORING < COMPLETED）；6h 惰性（状态四值 + 事件 + 证据保留）；暂停 409；phase 回填 + status CHECK 不动；分列三列；滑窗保尾/mock 全量两分支 | unit+integration | `cd server && python -m pytest test_phase3_timer.py -v` | ❌ W0 | ⬜ pending |
| 03-04-02 | 04 | 4 | REF-4.8/4.12 | T-03-20/22 | uq_sti_open 双轨；6 列 3 列 ALTER + phase 回填；timer.py 纯函数/接 conn 分区；config 四常量 + MAX_CONTEXT_TOKENS 占位注释；_truncate_history 不看 provider | unit | `python -c` DDL/svc 烟测（Task 2 verify）+ `pytest test_phase3_timer.py -v` | ❌ W0 | ⬜ pending |
| 03-04-03 | 04 | 4 | REF-4.8 | T-03-18/21/23 | 五挂载点依序（6h/暂停 409/单题超时/闭旧开新/touch）；全场超时 GLOBAL_TIMEOUT 先行独立事务 + 同步串行链；estimated=SESSION_TOTAL_MINUTES 派生；分列 INSERT 扩列 | integration | `pytest test_phase3_timer.py test_phase3_sse.py test_phase3_idempotency.py test_phase3_forms.py`（逐文件） | ❌ W0 | ⬜ pending |
| 03-04-04 | 04 | 4 | REF-2.6 | T-03-18 | m5 estimated==config 派生（20→40）；p0_chain/p0_security 护栏面最小适配；phase2 四文件回归 | regression | `pytest test_m5_backend.py test_p0_chain.py test_p0_security.py` + phase2 四件（逐文件） | ⚠️ 既有改造 | ⬜ pending |
| 03-04-05 | 04 | 4 | SSOT §31-2 | — | MAX_CONTEXT_TOKENS 数值经用户裁决（checkpoint:human-verify——占位 8000 不代决；同 ORDINARY_PLAN_N 02-02 Task 5 先例） | checkpoint | —（呈报流程见 03-04 Task 5） | — | ⬜ pending |
| 03-05-01 | 05 | 5 | REF-2.6/6.4/4.7 | T-03-25/27 | start 状态机（phase 转换 + 首区间 + SESSION_STARTED）+ 幂等 409；PENDING_START 不派发不计时（Pitfall 12）；pause/resume 全环（区间/双事件/409 三态）；注入事件白名单恰两键 + 不卡死 + 数据身份静态断言 | integration | `cd server && python -m pytest test_phase3_misc.py -v` | ❌ W0 | ⬜ pending |
| 03-05-02 | 05 | 5 | REF-2.6 | T-03-27/28/29 | 三端点护栏（load_owned_session + 409 三态）；get_session phase 条件（None/ACTIVE 放行兼容）；INJECTION 挂载段相邻位 | integration | `pytest test_phase3_misc.py -v` + grep 检查 | ❌ W0 | ⬜ pending |
| 03-05-03 | 05 | 5 | REF-6.4 | T-03-25/26 | _INJECTION_WORDS 词表 + mock 分类分支；11 回归文件 start 步骤插入（断言零改动）；Phase 3 全回归闭合 | regression | `pytest test_phase3_misc.py` + 11 文件循环（Task 3 verify） | ⚠️ 既有改造 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ 既有文件改造（非 Wave 0 新建）*

---

## REF Coverage（11/11）

| Req | 行为断言 | 测试文件 | 断言点（Nyquist 每行可断言） |
|-----|----------|----------|------------------------------|
| REF-2.4 | form_instance 生命周期 | test_phase3_forms.py | test_old_db_gateway_relaxation / test_new_db_direct_path / test_revision_immutable / test_render_idempotent_open |
| REF-2.6 | session phase 状态机 + 6 新列 | test_phase3_timer.py + test_phase3_misc.py | test_phase_column_defaults / test_start_transitions_phase / test_abandoned_6h_lazy / test_global_timeout_order（phase=='SCORING'） |
| REF-2.8 | 消息分列三列 | test_phase3_timer.py | test_message_columns_split（refined_content==content / client_request_id / sequence_no 递增） |
| REF-3.3 | exp/qual 出题库走表单 | test_phase3_forms.py | test_exp_qual_not_in_selection（category ⊆ {hard,soft}）+ test_render_on_exhaustion（gate item 采集路径） |
| REF-4.6 | 真实 SSE | test_phase3_sse.py | test_answer_is_sse / test_event_sequence / test_reply_reassembled / test_decision_before_stream_persisted / test_generator_no_db_access |
| REF-4.7 | 新端点 Pydantic | test_phase3_sse.py + test_phase3_forms.py | test_pydantic_422（answer 三态）/ FormSubmitRequest 六维 consume（submit-v2 断言组） |
| REF-4.8 | 计时区间 | test_phase3_timer.py | test_merge_spans / test_partial_unique_open_index / test_question_timeout_seal / test_global_timeout_order / test_abandoned_6h_lazy / test_session_paused_guard |
| REF-4.9 | 幂等与并发 | test_phase3_idempotency.py | test_same_key_returns_first_snapshot / test_revision_optimistic_lock / test_pending_returns_409 / test_no_key_no_records |
| REF-4.10 | 表单链 | test_phase3_forms.py | test_get_form_whitelist / test_submit_six_dimensions / test_gate_row_written / test_admin_override_requires_reason |
| REF-4.12 | 上下文三层 | test_phase3_timer.py | test_truncate_history_tail_preserved / test_truncate_history_mock_passthrough / test_max_context_tokens_placeholder + 分列（REF-2.8 同文件） |
| REF-6.4 | INJECTION 留痕 | test_phase3_misc.py | test_injection_event_whitelist（键集合 == 恰两键）/ test_injection_flow_not_deadlock / test_input_as_data_in_prompt |

---

## Wave 0 Requirements

- [ ] `server/test_phase3_forms.py` — 表单全链 + 迁移（REF-2.4/3.3/4.10）
- [ ] `server/test_phase3_sse.py` — SSE 流式消费（REF-4.6/4.7）
- [ ] `server/test_phase3_idempotency.py` — 幂等三键 + 乐观锁（REF-4.9）
- [ ] `server/test_phase3_timer.py` — 计时区间 + 超时三路 + 分列 + 滑窗（REF-2.6/2.8/4.8/4.12）
- [ ] `server/test_phase3_misc.py` — start/pause/resume + 注入（REF-2.6/6.4）
- [ ] 回归改造（各 plan 内逐 wave 落）：test_m5_backend（流式断言 + estimated 40 + start 步骤）、test_p0_chain（表单步骤 + 流式 + start）、test_p0_security（表单步骤 + 流式 + start）、test_phase2_* 四件（流式 + start）、test_phase3_forms/idempotency/sse/timer（start 互适）
- [ ] 脚本式 test_m6_backend / test_question_bank——预期零改动（gate 双源兼容 + 生成侧无 answer 面）；每 wave 抽查一次确认
- [ ] 无框架安装需求（零新包——RESEARCH Package Audit）

*五个新建测试文件由各 plan Task 1（Wave 0 先红）创建；回归改造分布在 03-02 Task 3 / 03-04 Task 4 / 03-05 Task 3。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| MAX_CONTEXT_TOKENS 生产值裁决 | SSOT §31-2 | 开放参数「实施期校准」——agent 不代决（章程 §2.2 硬关口；02-02 ORDINARY_PLAN_N 先例 [02-007]） | 03-04 Task 5 checkpoint：查看 server/config.py 占位值（8000）→ 依据 §14/§31-2 → 回复「维持 8000」或新整数 → 改值只动 config 一行 |
| A2 gate 行四步放宽法采纳 | RESEARCH Assumptions（03-03 关口包呈报项） | question_id/score_state NOT NULL 放宽是 D-31 字面「gate 项行落 question_score」的实现取舍（研究推荐②；③另途需 D-31 微调） | 关口包呈现：迁移 docstring ASSUMED 标记 + 实验验证摘要 + 三方案对照——用户确认四步法采纳或改向 |
| D-46 REF-4.7 范围（新端点 vs 全量 Pydantic） | CONTEXT D-46 | 存量端点不回溯是改动面裁量（若 checker 判定 REF-4.7 语义为「全部接口」需呈报用户确认） | 关口包呈现：本 phase 已覆盖新端点全集（answer/submit-v2/admin）+ 存量面清单与延后理由（Phase 6 测试收口一并评估） |
| A6 前端 start 接线延后 | RESEARCH A6 | web 零改动约束与 start 端点需要调用方的张力——后端契约已完备（测试证明），前端按钮接线延后属 UI 收口裁量 | 关口包呈现：start 端点行为测试全绿证据 + Phase 6 E2E 前置注记 |

*全部运行时行为（表单/SSE/幂等/计时/注入）均有 API 级自动化验证；上表四项为决策类 checkpoint（三个已有 ASSUMED/呈报标记，一个 SSOT §31 开放参数）。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references（5 新文件）
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s（全 mock 离线）
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
