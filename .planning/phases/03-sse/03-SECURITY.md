# SECURITY.md — Phase 03 (03-sse)

**Phase:** 3 — SSE / 表单链 / 幂等与乐观锁 / 计时区间 / 入场-暂停-注入收口
**Audited:** 2026-09-05
**ASVS Level:** 2
**Threat register source:** 5× `<threat_model>` blocks (03-01 .. 03-05 PLAN.md), authored at plan time.
**Result:** SECURED — 30/30 resolved (28 mitigate verified in code, 2 accept documented below).

## Threat Verification

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-03-01 | Info disclosure | mitigate | `services/forms.py:31` `_FIELD_WHITELIST_KEYS` = name/label/type/required/options/placeholder; `:41-50` `whitelist_form`; `api/assessment.py:921` GET /forms/{id} returns `whitelist_form(...)` only — years 门槛/required_level never enter snapshot fields |
| T-03-02 | Tampering | mitigate | `api/assessment.py:920` (get_form) + `:935` (submit_form_v2) both `load_owned_session`; `core/security.py:63-81` enforces `user_id=?` ownership → 404 |
| T-03-03 | Repudiation | mitigate | `services/forms.py:173-186` gate 五列 INSERT + `GATE_EVALUATED`; `:92` `FORM_RENDERED`; `:187` `FORM_SUBMITTED` — all via `append_event` (single INSERT in `state_events.py:41`) |
| T-03-04 | Tampering | mitigate | `services/forms.py:114-130` `_validate_payload` (④必填/⑤枚举/⑥长度 → FORM_MISSING_FIELD/INVALID_OPTION/FIELD_TOO_LONG); `:141-158` ②status/③revision; `schemas.py:118-124` FormSubmitRequest |
| T-03-05 | Elevation | mitigate | `api/admin/forms.py:10` `dependencies=[Depends(require_admin)]`; `:18` `override_reason: str = Field(min_length=1)`; `:37` `GATE_OVERRIDDEN` event + `reviewer_id` |
| T-03-06 | DoS | mitigate | `services/scoring.py:247` `DELETE FROM question_score WHERE session_id=? AND gate_result IS NULL` |
| T-03-06b | DoS | mitigate | `api/assessment.py:968-986` submit-v2 finish/next 触发器（`_all_gate_items_collected` → `select_next_question` None → UPDATE completed + `SESSION_COMPLETED` + commit → action='finish'） |
| T-03-07 | DoS | mitigate | `api/assessment.py:331-359` `_event_stream` generator body zero DB symbols（仅 `yield _sse_event`；无 get_conn/conn.execute/conn.commit） |
| T-03-08 | Tampering | mitigate | `api/assessment.py:416-584` 决策/消息/事件/封存/选题全部 commit 后才 `return StreamingResponse`（先落库再推流）；generator 零 DB |
| T-03-09 | DoS | mitigate | `api/assessment.py:586` `decide_next_action` 在 endpoint body 内（StreamingResponse 前）调用；`services/interview.py:242-262` RuntimeError/ValidationError → MODEL_UNCERTAIN 降级 |
| T-03-10 | Tampering | mitigate | `schemas.py:107-114` `field_validator("answer")` strip 后判空 422（WR-02 语义） |
| T-03-11 | Info disclosure | **accept** | 决策扩展键 `answer_state`/`evidence_sufficient` 透传（D-34 观察结论，非内部阈值）——见 Accepted Risks |
| T-03-12 | Tampering | mitigate | `services/idempotency.py:46-48` 三键作用域 `WHERE session_id=? AND endpoint=? AND idempotency_key=?`; `api/assessment.py:417`/`:935` `load_owned_session` 前置 |
| T-03-13 | Info disclosure | mitigate | `api/assessment.py:362-374` `_answer_snapshot` 白名单七键（action/reply/question_id/next_question_id/score_live/answer_state/evidence_sufficient）——无 answer 原文 |
| T-03-14 | DoS | mitigate | `db.py:367` `UNIQUE(session_id, endpoint, idempotency_key)`; `services/idempotency.py:57-63` IntegrityError 捕获重查 |
| T-03-15 | Tampering | mitigate | `services/idempotency.py:25-33` `request_hash_of` sha256 + `sort_keys=True`; `:68-71` COMMITTED 命中先比 hash，不匹配 409 IDEMPOTENCY_KEY_REUSED |
| T-03-16 | Tampering | mitigate | `api/assessment.py:549-562` 乐观锁 `UPDATE assessment_question SET revision=revision+1 WHERE question_id=? AND revision=?` rowcount==0 → 409 QUESTION_REVISION_CONFLICT（原子判，无 TOCTOU） |
| T-03-17 | DoS | **accept** | 幂等表无限增长不实现清理（D-38 Phase 6 数据治理）——见 Accepted Risks；`db.py:369` idx_idem_created 已就位 |
| T-03-18 | Tampering | mitigate | `services/timer.py:123/144/177/193` 全部用 `now_iso()` 服务端时钟；客户端不提供时间（interval 表服务端写入） |
| T-03-19 | Info disclosure | mitigate | `services/interview.py:97-112` `_build_user_prompt` 零 `reason`/`session_time_intervals` 引用（reason 只写 `session_time_intervals` 表 `services/timer.py:73-91`，不进 prompt） |
| T-03-20 | DoS | mitigate | `db.py:209` `CREATE UNIQUE INDEX uq_sti_open ... WHERE ended_at IS NULL` 部分唯一索引; `services/timer.py:83-91` IntegrityError 乐观环重试 |
| T-03-21 | DoS | mitigate | `services/timer.py:189-194` `touch_last_activity` 每写刷新（`api/assessment.py:691/696/963`）; `:163-186` `maybe_abandon_session` 只判 status（不判 phase），6h 判定覆盖暂停中的会话 |
| T-03-22 | Tampering | mitigate | `services/timer.py:30-60` `merge_spans`/`overlap_seconds` 纯函数 Python merge；全文件无 SQL SUM（Anti-pattern 3） |
| T-03-23 | Repudiation | mitigate | `api/assessment.py:511-519` `SESSION_GLOBAL_TIMEOUT` + `phase='SCORING'` 独立小事务 commit 后才调 `_generate_report_task`（内部 ENTERED_SCORING 靠后） |
| T-03-24 | DoS | mitigate | `services/interview.py:77-94` `_truncate_history` reversed 累积保尾部；`:236-237` 只作用 history（当前题/最新回答在 `_build_user_prompt` 组装面外） |
| T-03-25 | Info disclosure | mitigate | `api/assessment.py:617-621` `INJECTION_DETECTED` payload 恰两键 `{answer_state, stability}`——无输入原文 |
| T-03-26 | Tampering | mitigate | `services/interview.py:107-109` 候选人输入以 `候选人：{user_message}` 数据身份包裹; `:135-140` `_INJECTION_WORDS` → PROMPT_INJECTION; `api/assessment.py:853` 七类排除含 PROMPT_INJECTION; `services/interview.py:209-211` 规则 7 → next（不扣不卡） |
| T-03-27 | Tampering | mitigate | `api/assessment.py:208-239` start 端点显式 PENDING_START→ACTIVE; `:157` get_session 派发条件 `s.get("phase") in (None, "ACTIVE")`（PENDING_START 拦截——Pitfall 12） |
| T-03-28 | DoS | mitigate | `api/assessment.py:258-271` pause 幂等护栏（SESSION_ALREADY_PAUSED + SESSION_NOT_ACTIVE phase 门）; `:301-313` resume 护栏（SESSION_NOT_PAUSED phase 门 + 无 open paused 区间拒） |
| T-03-29 | Elevation | mitigate | `api/assessment.py:221`(start) `:251`(pause) `:293`(resume) 全部 `load_owned_session` 前置（D-01） |

## Accepted Risks

| Threat ID | Risk | Rationale |
|-----------|------|-----------|
| T-03-11 | decision 扩展键 `answer_state`/`evidence_sufficient` 对候选人可见 | 属候选人可感知的观察结论（D-34 决策透传），非内部阈值/内部状态——与 GET /forms 阈值白名单不同面，风险可接受 |
| T-03-17 | `idempotency_record` 表无清理、无限增长 | D-38 锁定不实现（Phase 6 数据治理）；演示期数据量级接受；`idx_idem_created` 索引已就位以备后续清理 |

## Unregistered Flags

None. SUMMARY files carry no `## Threat Flags` section with new attack surface (03-04-SUMMARY.md `## Threat Surface` only restates the 7 planned mitigations). Register is complete per task instruction; no new threats were scanned for.

## Review Fixes Accounted For

All 6 code-review Warnings (03-REVIEW-FIX.md, status all_fixed) confirmed present:
- WR-01 `api/admin/forms.py:34-35` rollback before 404
- WR-02 `api/assessment.py:445/454/458` rollback before SESSION_PAUSED / 404 / QUESTION_ALREADY_ANSWERED
- WR-03 `api/assessment.py:948` rollback in submit_form_v2 `!ok` branch
- WR-04 `api/assessment.py:479-482` timeout→form finalizes idempotency
- WR-05 `services/aggregation.py:48-63` `_gate_row` honors `human_override`
- WR-06 `api/assessment.py:268-271`/`:301-304` pause/resume phase guard
