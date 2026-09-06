---
phase: 03-sse
plan: 01
subsystem: api
tags: [fastapi, sqlite, forms, gate, pydantic, testclient]

# Dependency graph
requires:
  - phase: 02-dynamic-selection
    provides: "assessment chain (assessment.py / select_next_question), question_score table, p0_chain & p0_security test baseline"
provides:
  - "form_instance table with immutable revision model (composite PK form_instance_id+revision)"
  - "render → GET /forms/{id} → POST submit-v2 form chain with six-dimension validation"
  - "gate structured rows in question_score (question_id NULL) + dual-source aggregation"
  - "admin gate human-override endpoint with override_reason enforcement"
affects: [03-sse remaining plans, 02-dynamic-selection p0_chain regression]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SQLite four-step NOT NULL relaxation on FK column (ADD v2 → UPDATE copy → DROP → RENAME COLUMN)"
    - "immutable revision via composite PK + status superseded (INSERT new row, never UPDATE payload columns)"
    - "dual-source gate aggregation (_gate_row new chain → _gate_check legacy form_submission fallback)"

key-files:
  created:
    - server/test_phase3_forms.py
    - server/services/forms.py
    - server/api/admin/forms.py
  modified:
    - server/db.py
    - server/schemas.py
    - server/services/aggregation.py
    - server/services/scoring.py
    - server/api/assessment.py
    - server/main.py
    - server/test_p0_chain.py

key-decisions:
  - "form_instance uses composite PK (form_instance_id, revision) — single-column PK breaks the immutable-revision INSERT-new-row semantics"
  - "form marker 📎[form:{id}] emitted in BOTH response reply AND assistant message content so frontend Chat.vue extractFormId regex matches"
  - "gate consumption is dual-source: _gate_row (new chain) first, then _gate_check (legacy form_submission payload) fallback for transition"
  - "question_score gate rows store gate_result as string 'true'/'false' with question_id NULL (structured result, §16.1)"

patterns-established:
  - "SQLite four-step column relaxation for removing NOT NULL (verified DROP COLUMN on FK column succeeds in SQLite)"
  - "immutable revision: new row revision+1 same instance_id + old row status='superseded'"

requirements-completed: [REF-2.4, REF-3.3, REF-4.7, REF-4.10]

# Metrics
duration: 20min
completed: 2026-09-05
---

# Phase 3 Plan 1: Form Chain (表单链) Summary

**Form chain via form_instance table (composite-PK immutable revision) with render → GET → submit-v2 six-dimension validation, gate structured rows, and admin human-override endpoint**

## Performance

- **Duration:** 20 min
- **Started:** 2026-09-05T09:50:01+08:00
- **Completed:** 2026-09-05T10:10:03+08:00
- **Tasks:** 4
- **Files modified:** 10 (7 modified, 3 created)

## Accomplishments
- `form_instance` table with immutable revision model — composite PK `(form_instance_id, revision)`, status lifecycle (rendered/submitted/superseded), schema_snapshot stored per row
- Six-dimension form submission validation (ownership → status → revision → required → enum → length) with distinct 422 error codes (FORM_MISSING_FIELD / FORM_INVALID_OPTION / FORM_FIELD_TOO_LONG) and 409 idempotency (FORM_ALREADY_SUBMITTED / FORM_INSTANCE_REVISION_CONFLICT)
- Gate structured rows written to `question_score` (question_id NULL, gate_result/gate_status/gate_reason/evaluated_schema_version/evaluated_at) with NOT NULL relaxation via SQLite four-step method
- Dual-source gate aggregation (`_gate_row` new chain → `_gate_check` legacy fallback) + scoring preserves gate rows (DELETE scoped to `gate_result IS NULL`)
- `submit-v2` closes the gate-collection chain: after validate+commit, `_all_gate_items_collected` + `select_next_question` None → reuses main-chain finish; pool non-empty → next_question_id
- Admin `gate_override` endpoint enforces `override_reason` (min_length=1) and returns 404 on non-gate rows

## Task Commits

1. **Task 1: test_phase3_forms.py 表单全链断言（先红）** - `c0d46a9` (test) — 15 failing tests
2. **Task 2: db.py — form_instance 新表 + question_score gate 列与四步放宽迁移** - `a15c9ca` (feat)
3. **Task 3: services/forms.py + aggregation 双源迁移 + scoring gate 行保留** - `73dc22d` (feat)
4. **Task 4: assessment.py 端点 + admin/forms.py + schemas + main.py + p0_chain 回归** - `c9be1d4` (feat)

## Files Created/Modified
- `server/test_phase3_forms.py` - 15 form-chain tests (created)
- `server/services/forms.py` - render/validate/submit/revise + gate write (created)
- `server/api/admin/forms.py` - gate_override admin endpoint (created)
- `server/db.py` - form_instance DDL + migration, question_score gate columns + four-step relaxation, composite PK
- `server/schemas.py` - FormSubmitRequest
- `server/services/aggregation.py` - _gate_row + dual-source gate consumption
- `server/services/scoring.py` - preserve gate rows in score_session
- `server/api/assessment.py` - get_form + submit_v2 + two render insert points + form marker
- `server/main.py` - include admin_forms router
- `server/test_p0_chain.py` - form-step regression adaptation (extract id → submit-v2)

## Decisions Made
- Composite PK `(form_instance_id, revision)` for form_instance (immutable revision requires INSERT-new-row, not UPDATE)
- Form marker emitted in both reply and assistant message content (frontend extractFormId)
- Dual-source gate aggregation for transition period (new chain → legacy fallback)
- gate_result stored as string `'true'/'false'` with question_id NULL

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] form_instance single-column PK broke revision INSERT**
- **Found during:** Task 4 (revision-immutable verification)
- **Issue:** plan's literal DDL used `form_instance_id TEXT PRIMARY KEY` (single-column), so inserting a second row with the same `form_instance_id` (revision+1) raised `sqlite3.IntegrityError`, contradicting the plan's own revision semantics ("INSERT 新行 revision+1 同 instance_id")
- **Fix:** changed DDL and `_migrate_form_instance` to `PRIMARY KEY (form_instance_id, revision)`
- **Files modified:** server/db.py
- **Verification:** test_revision_immutable passes
- **Committed in:** c9be1d4 (Task 4)

**2. [Rule 1 - Bug] form marker missing from response "reply"**
- **Found during:** Task 4 (form-render assertion)
- **Issue:** `_render_form_branch` put `📎[form:id]` only in the assistant message content, but the response `reply` used bare `decision["reply"]` — frontend `extractFormId` reads the reply and would not match
- **Fix:** build `reply` once (decision reply + marker) and use it in both message content and response
- **Files modified:** server/api/assessment.py
- **Verification:** test asserts `reply` contains `📎[form:id]`
- **Committed in:** c9be1d4 (Task 4)

**3. [Rule 1 - Bug] test seed INSERT column/placeholder mismatch**
- **Found during:** Task 1 (RED setup)
- **Issue:** `_seed_question_bank` `_add` INSERT listed 13 columns but only 12 `?` placeholders → sqlite error
- **Fix:** added the 13th placeholder
- **Files modified:** server/test_phase3_forms.py
- **Verification:** 15 tests pass
- **Committed in:** c9be1d4 (Task 4, seed fix folded with regression adaptation)

---

**Total deviations:** 3 auto-fixed (all Rule 1 bugs)
**Impact on plan:** All fixes necessary for correctness against the plan's own semantics; no scope creep.

## Issues Encountered
- `_migrate_question_score_phase3` `_relax` initially used `info[column].notnull` (Row) but `init_db` uses raw `sqlite3.connect` (no row_factory) → PRAGMA returns tuples. Fixed with tuple index `info[column][3]`.
- Out-of-scope pre-existing failures (not from plan 03-01 changes): `test_phase2_migration.py` full-suite isolation `IndexError` (passes standalone 8 passed), `test_question_bank.py` `no such table: user` (missing init_db). Logged in `deferred-items.md`.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Form chain complete and self-contained; remaining phase 03 plans (03-02 through 03-05) can build on form_instance, gate rows, and dual-source aggregation.
- No blockers. Two pre-existing test-harness gaps deferred (see `deferred-items.md`).

---
*Phase: 03-sse*
*Completed: 2026-09-05*

## Self-Check: PASSED
- 10 key files found on disk (3 created, 7 modified)
- 4 task commits present (c0d46a9, a15c9ca, 73dc22d, c9be1d4)
- 36 tests pass across test_phase3_forms.py + test_p0_chain.py + test_p0_security.py
