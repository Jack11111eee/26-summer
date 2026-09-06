---
phase: 6
slug: migration-test-closure
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-05
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 |
| **Config file** | none today → add `server/conftest.py` + optional `pytest.ini` (`testpaths = server`) |
| **Quick run command** | `python -m pytest server/test_m1_regression.py -x -q` |
| **Full suite command** | `python -m pytest server/ -q` |
| **Estimated runtime** | ~10-30 seconds (mock LLM, no network) |

---

## Sampling Rate

- **After every task commit:** Run targeted `python -m pytest server/test_<area>.py -q` for the touched file
- **After every plan wave:** Run `python -m pytest server/ -q` (full collection must stay green as files are converted)
- **Before `/gsd:verify-work`:** Full suite green + `npm run build` (web/)
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01 | 01 | 1 | REF-2.11 | T-06-01 / — | registry replay parity + idempotency + legacy-DB migration | unit/integration | `python -m pytest server/test_migration.py -q` | ❌ W0 | ⬜ pending |
| 06-02 | 02 | 2 | REF-7.4 | T-06-02 / — | full collection green (no fixture errors) | collection | `python -m pytest server/ -q` | ❌ (3 errors today) | ⬜ pending |
| 06-03 | 03 | 3 | REF-7.5 / REF-8.6 | T-06-03 / — | M1 eight-item regression locks + mock-fixed-3 documented | unit | `python -m pytest server/test_m1_regression.py -q` | ❌ W0 | ⬜ pending |
| 06-04 | 04 | 2 | REF-7.6 | T-06-04 / — | candidate full-chain E2E + refresh/retry/timeout/authz | integration | `python -m pytest server/test_e2e_full_chain.py -q` | ❌ W0 | ⬜ pending |
| 06-05 | 05 | 2 | REF-5.11 / REF-8.8 | T-06-05 / — | bad-case candidate never auto-scores; eval uses temp DB | unit/integration | `python -m pytest server/test_bad_case.py server/test_eval_isolation.py -q` | ❌ W0 | ⬜ pending |
| 06-05 | 05 | 2 | REF-6.2 / REF-6.3 | T-06-05 / — | startup secret validation; per-type input limits | unit | `python -m pytest server/test_secret_gate.py server/test_input_limits.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `server/conftest.py` — session temp-DB fixture (blocking prerequisite for ALL collection work)
- [ ] `pytest` added to `server/requirements.txt` (CI reproducibility)
- [ ] `server/test_migration.py` — registry replay / idempotency / legacy-DB path
- [ ] `server/test_m1_regression.py` — eight-item locks
- [ ] `server/test_e2e_full_chain.py` — full candidate chain
- [ ] `server/test_bad_case.py` / `test_secret_gate.py` / `test_input_limits.py` / `test_eval_isolation.py`
- [ ] Fix 13 session-test files' direct `question_bank` INSERTs to write `model_id`/`model_version` ([04-011])

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 前端 IMPUTED 徽标 / 覆盖率视觉呈现 | SC #2 (Phase 5 carry-over) | 视觉呈现无法脚本断言 | 打开报告页目验（05-HUMAN-UAT.md 持久化） |
| 管理员发布流 | REF-5.9 | 交互流程 | 管理员登录→点发布（05-HUMAN-UAT.md 持久化） |
| missing_reasons 中文映射 | D-79 | 文案呈现 | 报告页目验 reason 中文串 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
