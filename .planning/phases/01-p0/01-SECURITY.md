---
phase: 01
slug: p0
status: verified
threats_open: 0
asvs_level: 1
created: 2026-09-03
---

# Phase 01 (p0) — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| 候选人 → API 路由 | 任意持有效 JWT 的登录用户携带他人 session_id/report_id 跨越此边界（IDOR 面） | session/report 资源 ID（uuid4 hex 12 位） |
| admin → API 路由 | 合法高权限角色；读豁免 / 写拒绝边界统一在 owner helpers | 同上（读豁免、写 owner-only） |
| DB 写入层 → 事件表 | 任何持有 conn 的代码路径可尝试改写历史事件 | audit 事件行（append-only 触发器强制） |
| 服务层入口 → API / 直调双路径 | 护栏（completed、readiness）收口在服务层，API 与 eval/测试直调同被护 | 业务状态迁移请求 |
| 后台链 → 服务层 | 串行链经 allow_completed / allow_admin_read keyword-only 内部参数豁免，外部调用者不可经 API 伪造 | 评分→报告串行指令 |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-01-01 | Information Disclosure (IDOR) | api/assessment.py 8 条候选人资源路由 | mitigate | load_owned_session/load_owned_report 单查询（WHERE user_id=current）非 owner 404 | closed |
| T-01-02 | Elevation of Privilege | admin 写操作边界 | mitigate | 写路由不传 allow_admin_read（owner-only）；admin 写同路径 404，测试矩阵断言 | closed |
| T-01-03 | Information Disclosure（存在性枚举） | 越权返回码 | mitigate | 404 统一"不存在"，无 403 分支；ID 为 uuid4 hex 12 位不可枚举 | closed |
| T-01-04 | Spoofing | JWT_SECRET 默认值（config.py:16） | accept | 已知安全债，REF-6.2 属 Phase 6 处理；测试以 JWT_SECRET=test-secret 规避 | closed |
| T-01-05 | Tampering（SQL 注入面） | 新 helper 查询 | mitigate | 全部 ? 参数化占位符，禁止值插值 | closed |
| T-01-06 | Information Disclosure | 密码策略 1 字符下限（schemas.py:11） | accept | 已知安全债，Phase 6 处理 | closed |
| T-01-07 | Repudiation（抹痕） | assessment_state_event 行 | mitigate | BEFORE UPDATE/DELETE 触发器 RAISE(ABORT)（db.py:245/248，DB 级强制），test_event_table_rejects_update_delete 证明 | closed |
| T-01-08 | Tampering | sequence_no 取号并发 | mitigate | 同事务 COALESCE(MAX+1) + UNIQUE(session_id, sequence_no) 兜底 | closed |
| T-01-09 | Tampering | actor_type 伪造 | mitigate | append_event 入口三值白名单（candidate/system/admin，state_events.py:11） | closed |
| T-01-10 | DoS（锁死） | 事件写入 vs LLM 调用持锁 | mitigate | 事件行与最终快照同事务，不新增独立事务 | closed |
| T-01-11 | Repudiation | 存量旧会话无事件行 | accept | 预期行为：事件从 Phase 1 起新会话记录，不回填 | closed |
| T-01-12 | Tampering（重复评分覆盖） | completed 会话重调 POST /score | mitigate | score_session completed→ValueError→API 409（scoring.py:157，allow_completed keyword-only 默认 False） | closed |
| T-01-13 | Tampering（0 题评分污染） | in_progress 会话请求报告 | mitigate | request_report 非 completed → 409（api/assessment.py:338） | closed |
| T-01-14 | Repudiation（串行链无留痕） | 评分→报告后台链 | mitigate | TASK_QUEUED/STARTED/SUCCEEDED/FAILED + SESSION_ENTERED_SCORING 事件全程写入 | closed |
| T-01-15 | Tampering | allow_completed 豁免参数被滥用 | mitigate | keyword-only、默认 False；grep 全库仅 _generate_report_task 一处传 True（api/assessment.py:311） | closed |
| T-01-16 | DoS（重复触发后台链） | POST /report 重复请求 | mitigate | 三分支：非 completed→409 / 已有 report 行→409（api/assessment.py:345）/ 无 report 行→202 合法恢复重入 | closed |
| T-01-17 | Repudiation（后台链异常静默） | _generate_report_task except pass | accept | 现状语义（前端轮询 report 空=失败）；TASK_FAILED 事件已留痕，FAILED 可见性属 Phase 5 REF-8.3 | closed |
| T-01-18 | Tampering（0 题会话完整性） | create_session 空题集静默开考 | mitigate | check_session_readiness 三态 409 在 INSERT 会话之前（readiness.py:38），每失败态 _q COUNT==0 断言 | closed |
| T-01-19 | Information Disclosure（业务状态暴露） | 409 detail 形态 | mitigate | dict detail 仅 error_code + 中文 message，无内部阈值/堆栈 | closed |
| T-01-20 | DoS（误伤合法开考） | readiness 对存量种子的判定 | mitigate | "无 task 行 + 题库足量→放行"兼容路径，test_legacy_seed_without_task_row_passes 证明 | closed |
| T-01-21 | Repudiation（生成失败不可见） | question_bank_task FAILED 行 | mitigate | 异常落表（status=FAILED + error_msg + finished_at），todos 聚合计入 | closed |
| T-01-22 | Tampering | task 行 status 枚举 | mitigate | 写入点收口：confirm（QUEUED）+ _update_task_status 字面量恒定 | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01-04 | T-01-04 | JWT_SECRET 默认值——已知安全债，修复归 Phase 6（REF-6.2），本阶段禁止顺手修（Surgical Changes） | user（plan 01-01 定案） | 2026-09-03 |
| AR-01-06 | T-01-06 | 密码策略 1 字符下限——不在本阶段范围，Phase 6 处理 | user（plan 01-01 定案） | 2026-09-03 |
| AR-01-11 | T-01-11 | 存量旧会话无事件行——事件自 Phase 1 新会话起记录，不回填（预期行为） | user（plan 01-02 定案） | 2026-09-03 |
| AR-01-17 | T-01-17 | 后台链异常静默——TASK_FAILED 事件已留痕；FAILED 可见性属 Phase 5 REF-8.3 | user（plan 01-03 定案） | 2026-09-03 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-03 | 22 | 22 | 0 | gsd-secure-phase (gsd-security-auditor verification) |

Audit method: register authored at plan time（四个 PLAN 均含 `<threat_model>` 块）；逐项核对实现证据（代码位置见 Mitigation 列）+ 回归测试全绿（test_p0_security + test_p0_chain 21 passed；m5 7 passed；m6/m7 5 passed）。

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-03
