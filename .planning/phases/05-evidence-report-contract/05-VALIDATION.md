---
phase: 5
slug: evidence-report-contract
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-05
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> 本 phase 是「链式审计契约」收口，测试重点是**确定性断言审计链闭合**与**状态机迁移合法性**，而非 UI 交互。全 mock 模式（LLM_PROVIDER=mock）离线跑，DB 用临时文件。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1（TestClient 集成 + 服务层直调） |
| **Config file** | none（无 pytest.ini/conftest.py——沿用 M5/M7 单文件三件套） |
| **Quick run command** | `cd server && python -m pytest test_phase5_evidence.py -v` |
| **Full suite command** | `cd server && python -m pytest test_phase5_evidence.py test_phase5_report.py test_phase5_feedback.py -v`（**逐文件跑，禁止单进程同跑多文件——DB_PATH import 冲突**） |
| **Estimated runtime** | ~30s per file |

---

## Sampling Rate

- **After every task commit:** `cd server && python -m pytest test_phase5_evidence.py -v`（单文件快速回归，< 30s）
- **After every plan wave:** `cd server && python -m pytest test_phase5_evidence.py test_phase5_report.py test_phase5_feedback.py -v`（逐文件）
- **Before `/gsd:verify-work`:** 全套新测试绿 + 既有 test_m6（改断言后）/ test_m7 绿
- **Max feedback latency:** ~90s（三文件逐跑合计）

---

## Per-Requirement Verification Map

*Task 级映射由 planner 落 plan 后回填；下表以 REF-ID 为锚（executor 按 task→REF 归属执行对应命令）。*

| Req ID | Behavior | Test Type | Automated Command | File Exists | Status |
|--------|----------|-----------|-------------------|-------------|--------|
| REF-2.10 | evidence_spans_json 落库含 source_message_id/start_offset/end_offset/quote_hash | unit | `pytest test_phase5_evidence.py::test_span_located_in_original -x` | ❌ Wave 0 | ⬜ pending |
| REF-2.10 | 定位失败降级 quote_hash only + source_message_id NULL（mock "mock quote"） | unit | `pytest test_phase5_evidence.py::test_span_degrade_on_mock_quote -x` | ❌ Wave 0 | ⬜ pending |
| REF-2.10 | offset 在 Unicode 边界（emoji/CJK）正确（code point 非 UTF-16） | unit | `pytest test_phase5_evidence.py::test_span_unicode_code_point -x` | ❌ Wave 0 | ⬜ pending |
| REF-2.3 | trace_link 建表 + link_role 枚举校验（非法值 raise） | unit | `pytest test_phase5_evidence.py::test_trace_link_role_validation -x` | ❌ Wave 0 | ⬜ pending |
| REF-8.7 | 旧 ref_id 迁移导入 trace_link（命中实体表拆 entity_type，命不中保留） | unit | `pytest test_phase5_evidence.py::test_ref_id_import_migration -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.4 | adjudicate 替换按题数均分；冲突取低 + human_review 标记 | unit | `pytest test_phase5_report.py::test_adjudicate_conflict_lower -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.5 | IMPUTED r 比例补算（`(score−1)/4` 加权均值）+ IMPUTED 标记 | unit | `pytest test_phase5_report.py::test_impute_r_math -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.5 | O=∅ → NO_VALID_OBSERVATION + HUMAN_REVIEW_REQUIRED | unit | `pytest test_phase5_report.py::test_impute_no_valid_observation -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.6 | required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | integration | `pytest test_phase5_report.py::test_required_missing_provisional -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.9 | 状态机迁移合法性（GENERATING→PROVISIONAL\|READY→PUBLISHED\|FAILED，非法迁移拒绝） | unit | `pytest test_phase5_report.py::test_status_transition_legality -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.9 | 七项校验任一失败 → FAILED（不生成正常报告） | integration | `pytest test_phase5_report.py::test_consistency_check_fails_to_failed -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.9 | 版本不可变（重复生成 2 版本，旧行保留，feedback FK 不悬空） | integration | `pytest test_phase5_report.py::test_version_immutability -x` | ❌ Wave 0 | ⬜ pending |
| REF-5.9 | publish 端点：admin 显式点击 → PUBLISHED + REPORT_PUBLISH_CONFIRMED 事件；review 未满足拒绝 | integration | `pytest test_phase5_report.py::test_publish_flow -x` | ❌ Wave 0 | ⬜ pending |
| REF-8.3 | 生成异常 → FAILED 行 + TASK_FAILED 事件（前端可区分生成中/失败） | integration | `pytest test_phase5_report.py::test_generate_failed_visible -x` | ❌ Wave 0 | ⬜ pending |
| REF-7.3 | submit_feedback 落 user_id + FEEDBACK_RECEIVED 事件 | integration | `pytest test_phase5_feedback.py::test_feedback_audit_fields -x` | ❌ Wave 0 | ⬜ pending |
| REF-7.3 | review/bad-case 持久化 note + reviewer + reviewed_at（不再丢弃） | integration | `pytest test_phase5_feedback.py::test_admin_note_persisted -x` | ❌ Wave 0 | ⬜ pending |
| REF-7.3 | question_reviews 补 item_id | integration | `pytest test_phase5_feedback.py::test_question_reviews_has_item_id -x` | ❌ Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/test_phase5_evidence.py` — REF-2.10/2.3/8.7（span 定位/降级/Unicode/trace_link/迁移）
- [ ] `server/test_phase5_report.py` — REF-5.4/5.5/5.6/5.9/8.3（adjudicate/IMPUTED/状态机/七项校验/版本化/publish/FAILED）
- [ ] `server/test_phase5_feedback.py` — REF-7.3（feedback 审计字段/note 持久化/question_reviews item_id）
- [ ] 重写 `server/test_m6_backend.py` 的「重复生成幂等（同会话仅 1 行 report）」断言 → 版本化断言（Pitfall 1）
- [ ] 共用测试助手 `_q()`/`_auth()`/`_seed_*` 沿用 M5/M7 既有形态（不建 conftest——单文件纪律）

*(Wave 0 需新建 3 个测试文件 + 改 1 个既有断言；无现成基础设施覆盖本 phase)*

---

## Edge Cases the Tests Must Cover

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

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 补算复核阈值（§31-3）超阈值 → 人工复核 UI 展示 | REF-5.5 | 阈值为开放参数，数值未定（关口包呈报），自动化只断言「超阈值 → PROVISIONAL + 覆盖率展示」分支可达，不锁数值 | 手工置 config 阈值极小值，触发补算超阈值，目视确认 PROVISIONAL 标记 + 覆盖率 |
| 前端「生成中/失败」可区分 | REF-8.3 | 前端视觉态（轮询读 report_status），自动化只覆盖后端 FAILED 状态 + 事件，UI 视觉待 E2E | 手动触发一次生成失败，前端报告页应显示「生成失败」而非无限「生成中」 |

*其余行为均有自动化验证。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
