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

## Other notes

- **06-01 did not run `init_db()` against the business `data/app.db`** (red line: business DB never used for tests). The first real server startup by the user will backfill `schema_version` 1..13 on `data/app.db` (idempotent migrations make this safe), with a pre-migration `backups/app-*.db` backup. This is a deployment-time smoke test, not an executor-run test.
