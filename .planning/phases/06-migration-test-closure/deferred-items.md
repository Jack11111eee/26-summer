# Phase 6 — Deferred / Out-of-Scope Items

> Log of discoveries during plan execution that are out of scope for the current plan and deferred to a later plan (or user decision). Kept separate from STATE.md's global Deferred Items for phase-level visibility.

## From 06-01 (migration registry + conftest + migration tests)

### [04-011] — test_m5_backend.py 4 failures are pre-existing (NOT caused by 06-01)

- **Found during:** 06-01 plan-level regression check (`cd server && python -m pytest test_m5_backend.py test_m7_backend.py -q`)
- **Symptom:** 4 failed / 8 passed. All 4 failures in `test_m5_backend.py`:
  - `test_session_creation_and_question_selection` → `QUESTION_BANK_INCOMPLETE: 必备能力项缺题：Python、MySQL、后端开发经验`
  - `test_session_state` / `test_answer_flow_and_scoring` / `test_form_submission` → `KeyError: 'session_id'` (cascading from the session-creation 409)
- **Root cause:** `test_m5_backend.py::_seed_question_bank` (lines 86–90) INSERTs `question_bank` without `model_id`/`model_version`. Phase 4 consumer-side tightening (D-50, `services/readiness.py` `WHERE model_id=? AND model_version=?`) rejects those rows at session-creation readiness check.
- **Why out of scope for 06-01:** The 13 session-test files' `model_id`/`model_version` gap is the known deferred item `[04-011]`, assigned to **06-03 (M1 regression)** per D-71. 06-01's `files_modified` is only `db.py`/`conftest.py`/`test_migration.py`.
- **Evidence it is pre-existing:** documented in `.planning/STATE.md` Deferred Items ("13 个会话类测试文件…直插 question_bank 不写 model_id/model_version，Phase 4 消费侧收紧后失败 → 并入 Phase 6 M1 回归收口（[04-011]）"). 06-01 did not touch `test_m5_backend.py`, `services/readiness.py`, or `question_bank` DDL.
- **Confirmation 06-01 is clean:** `test_m7_backend.py` is fully green (5 passed); `test_migration.py` is green (3 passed). 06-01's own artifacts verified.
- **Action:** 06-03 fixes the seed (add `model_id`/`model_version` to the 13 files' `question_bank` INSERTs). No action for 06-01.

## From 06-03 (M1 regression + config §31-4 + 13-file column fill)

### 2 pre-existing failures unmasked by the 13-file column fill (NOT caused by 06-03)

06-03's Task 3 is a purely mechanical edit: add `model_id`/`model_version` to each `INSERT INTO question_bank` across 13 session-test files + thread `mid`. It does **not** touch `api/assessment.py`, `db.py`, or any migration/report logic. Two failures surfaced after the fill, both in code paths unrelated to `question_bank` columns — they were previously masked because the missing `model_id`/`model_version` caused those tests to fail earlier (at session creation / readiness), before ever reaching these assertions.

| # | Test | Failure | Root cause (pre-existing) |
|---|------|---------|---------------------------|
| 1 | `test_p0_chain.py::test_completed_session_guardrail` (line 426) | second `POST /report` returns **202** instead of 409 | `request_report` guard only rejects `report_status=='GENERATING'` (branch b). A terminal-status row (`READY`/`PUBLISHED`/`FAILED`) falls into branch (c) → new `GENERATING` row + 202. The P0 test expects 409 for *any* existing report row ("已生成报告再请求"). This is a D-08 (score→report serial chain) endpoint-semantics vs P0 "成功标准 5" mismatch — a design-level question, not a column-fill bug. |
| 2 | `test_phase3_timer.py::test_phase_column_defaults` (line 541) | `row["phase"] == "PENDING_START"` fails with `None` after re-running `init_db()` | The phase backfill migration is registered in the `schema_version` registry (D-68). Re-running `init_db()` is idempotent — it does **not** re-apply the `phase=NULL → PENDING_START` backfill to a manually `NULL`ed row, because the migration is already recorded as applied. Unrelated to `question_bank`. |

- **Why out of scope for 06-03:** Task 3 scope is "补 model_id/model_version 两列，不改其他列、不改断言数值、不改测试语义". Fixing #1 requires changing the report endpoint's re-trigger semantics (a D-08 design decision, Rule 4 architectural); fixing #2 requires changing migration-registry idempotency semantics (D-68, also design-level). Neither is a mechanical column fill.
- **Evidence of correctness of 06-03's own changes:** the 3 acceptance files `test_m5_backend.py` / `test_m6_backend.py` / `test_m7_backend.py` are green (16 passed). The grep acceptance check (each `INSERT INTO question_bank` column list contains both `model_id` and `model_version`) is clean for all 13 files.
- **Action:** defer to a design decision. #1 needs SSOT confirmation of whether `POST /report` on a terminal-status report should 409 (test's expectation) or re-generate (current D-08 endpoint). #2 needs a decision on whether the phase backfill should be idempotently re-applied (e.g. a `WHERE phase IS NULL` idempotent backfill outside the registry) or the test's re-run expectation is stale.

## Other notes

- **06-01 did not run `init_db()` against the business `data/app.db`** (red line: business DB never used for tests). The first real server startup by the user will backfill `schema_version` 1..13 on `data/app.db` (idempotent migrations make this safe), with a pre-migration `backups/app-*.db` backup. This is a deployment-time smoke test, not an executor-run test.
