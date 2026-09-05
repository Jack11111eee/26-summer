---
phase: 06-migration-test-closure
plan: "06-01"
subsystem: database
tags: [sqlite, schema_version, migration, pytest, conftest, set_db_path]

# Dependency graph
requires:
  - phase: "05-evidence-report-contract"
    provides: "13 _migrate_* functions + _DDL (24-table latest schema) in server/db.py"
  - phase: "04-question-bank-version"
    provides: "consumer-side model_id/model_version matching (D-50) exercised by readiness check"
provides:
  - "schema_version registry table + ordered MIGRATIONS (13) replacing DDL-string sniffing (REF-2.11)"
  - "set_db_path() / _DB_PATH_OVERRIDE path override for eval isolation + temp-DB tests (D-74 linchpin)"
  - "server/conftest.py session temp-DB + mock-triple fixture (Wave 0 collection linchpin, D-69)"
  - "server/test_migration.py three migration tests (fresh replay parity / idempotent / legacy-DB)"
affects: ["06-02 (conftest collection)", "06-03 (test seed fixes)", "06-05 (eval isolation via set_db_path)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "schema_version registry loop: bootstrap -> applied lookup -> per-migration backup/run/register/commit -> _DDL"
    - "_DB_PATH_OVERRIDE consulted by _resolve_db_path() in get_conn()/init_db()"
    - "conftest.py env injection (setdefault) before server.* import + session-scoped temp DB"

key-files:
  created:
    - server/conftest.py
    - server/test_migration.py
  modified:
    - server/db.py

key-decisions:
  - "Migration primary skip-decision = schema_version registry lookup; keep _migrate_llm_trace/_migrate_feedback_status DDL-sniff guards as idempotent belt-and-suspenders (Pitfall 4)"
  - "Backup uses stdlib sqlite3 conn.backup() to backups/app-{ts}-pre-{version}.db before each not-yet-applied migration"
  - "Used datetime.now(timezone.utc).isoformat() locally instead of pipeline.now_iso() to avoid db<->pipeline import cycle (plan-authorized fallback)"
  - "test_old_db_migration fixture sets path only (no init_db) so each test controls init_db timing; matches plan <behavior>, avoids poisoning the registry"

patterns-established:
  - "Pattern 1: schema_version ordered migration registry (06-01)"
  - "Pattern 2: conftest.py session temp-DB fixture (06-02 linchpin)"

requirements-completed: [REF-2.1, REF-2.11]

# Metrics
duration: 25min
completed: 2026-09-05
---

# Phase 6 Plan 1: 迁移体系收口（schema_version 登记簿） Summary

**schema_version migration registry (13 ordered migrations + pre-migration backup) replacing DDL-string sniffing, with set_db_path override, conftest mock-triple fixture, and three migration tests (fresh-replay parity / idempotent / legacy-DB)**

## Performance

- **Duration:** 25 min
- **Started:** 2026-09-05T14:00:00Z
- **Completed:** 2026-09-05T14:25:00Z
- **Tasks:** 3
- **Files modified/created:** 3 (server/db.py, server/conftest.py, server/test_migration.py)

## Accomplishments

- `server/db.py` migration system consolidated from a hardcoded 13-call list + DDL-string sniffing into a `schema_version` registry + ordered `MIGRATIONS` list; `init_db` now bootstraps the registry, reads `applied`, and runs only not-yet-registered migrations with a `conn.backup()` snapshot before each (REF-2.11 / D-68).
- `set_db_path()` / `_DB_PATH_OVERRIDE` added so `get_conn()` and `init_db()` can point at a temp DB without mutating the import-time-frozen `config.DB_PATH` — the D-74 eval-isolation linchpin, reused by 06-05.
- `server/conftest.py` landed as the Wave 0 collection linchpin: injects mock triple (`LLM_PROVIDER=mock`, `JWT_SECRET=test-secret`, temp `DB_PATH`) before any `server.*` import, plus a session-scoped `init_db()` fixture and a function-scoped `conn` fixture.
- `server/test_migration.py` three assertions green: fresh-replay (registry 1..13 + table-name parity vs `_DDL` via `re.findall`), idempotent (second `init_db` no-op), legacy-DB migration (CHECK widen + `model_id`/`model_version` columns + registry backfill).

## Task Commits

1. **Task 1: db.py 登记簿化** - `f1617f2` (feat)
2. **Task 2: conftest.py mock 三件套** - `d253fc8` (test)
3. **Task 3: test_migration.py 三断言** - `4117469` (test)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `server/db.py` - `_SCHEMA_VERSION_DDL` + `MIGRATIONS` (13) + `_backup_before_migration` + `set_db_path`/`_resolve_db_path` + registry-loop `init_db`; `get_conn` routed through `_resolve_db_path`
- `server/conftest.py` - mock-triple env injection + session `_session_db` fixture + function `conn` fixture
- `server/test_migration.py` - `test_fresh_replay` / `test_idempotent` / `test_old_db_migration` + `_fresh_db` autouse fixture + `_q` helper

## Decisions Made

- Registry primary skip-decision is the `schema_version` lookup; the two DDL-rebuild migrations keep their internal `"'report'"`/`"'bad_case'"` sniff guards as belt-and-suspenders (Pitfall 4 — do not re-run destructive rebuild on an empty registry against an already-migrated legacy DB).
- Backup uses stdlib `sqlite3.Connection.backup()` (no new dependency) to `backups/app-{ts}-pre-{version}.db`.
- `now_iso()` is imported from `pipeline` in `_migrate_trace_link`, but `pipeline` imports `..db` — so 06-01 uses `datetime.now(timezone.utc).isoformat()` locally in `_backup_before_migration`/`init_db` to avoid a module-level import cycle (plan-authorized fallback).
- `test_old_db_migration`'s `_fresh_db` fixture sets the path only (does not call `init_db`), so each test controls `init_db` timing; this matches the plan's `<behavior>` (which has each test call `init_db` explicitly) and avoids pre-registering all 13 migrations before the legacy-DB hand-crafted schema.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_fresh_db` fixture must not call `init_db()`**
- **Found during:** Task 3 (test_migration.py)
- **Issue:** The plan's `<action>` fixture description had `set_db_path(...); init_db(); yield; set_db_path(None)`. Calling `init_db()` in the autouse fixture registers all 13 migrations first, so `test_old_db_migration`'s subsequent `init_db()` would see every migration as already-applied and never widen the hand-crafted legacy CHECKs/columns.
- **Fix:** Fixture now sets the DB path only; `test_fresh_replay`/`test_idempotent` call `init_db()` themselves, `test_old_db_migration` hand-creates the legacy tables then calls `init_db()` (matches the plan's `<behavior>` block).
- **Files modified:** server/test_migration.py
- **Verification:** `cd server && python -m pytest test_migration.py -q` → 3 passed
- **Committed in:** `4117469` (Task 3 commit)

**2. [Rule 3 - Blocking] Task 1 `<verify>` command used a broken relative import**
- **Found during:** Task 1 verification
- **Issue:** The plan's verify command was `cd server && python -c "from db import init_db, set_db_path, get_conn; ..."`. `server/db.py` uses `from .config import DB_PATH` (relative import), so importing `db` as a top-level module raises `ImportError: attempted relative import with no known parent package`.
- **Fix:** Verified from repo root with `python -c "from server.db import init_db, set_db_path, get_conn; ..."`.
- **Files modified:** none (verification command only)
- **Verification:** output `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]`
- **Committed in:** n/a (no code change)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes were necessary for correctness; neither changed scope. No new features added.

## Issues Encountered

- **Pre-existing regression (out of scope):** `cd server && python -m pytest test_m5_backend.py test_m7_backend.py -q` yields **4 failed / 8 passed**. All 4 failures are in `test_m5_backend.py` and stem from the known deferred item `[04-011]` — `_seed_question_bank` (test_m5 lines 86-90) inserts `question_bank` without `model_id`/`model_version`, which Phase 4's consumer-side readiness check (`services/readiness.py`) rejects at session creation (`QUESTION_BANK_INCOMPLETE`). This is NOT caused by 06-01 (06-01 touched only db.py/conftest.py/test_migration.py); it is assigned to 06-03 (D-71). `test_m7_backend.py` is fully green (5 passed), and 06-01's own `test_migration.py` is green (3 passed). Logged in `.planning/phases/06-migration-test-closure/deferred-items.md`.
- The plan's `<verification>` manual smoke test (`python -c "import db; db.init_db()"` against `data/app.db`) was **not** run by the executor — the red line forbids using the business DB for tests. The first real server startup will backfill `schema_version` 1..13 on `data/app.db` safely (idempotent migrations) with a `backups/` snapshot.

## SSOT Discrepancy Flag (待用户裁决，SSOT 未改)

- **REF-2.1 says "全局 21 张表"; `server/db.py` `_DDL` contains 24 `CREATE TABLE IF NOT EXISTS`** (user / position / position_alias / jd_record / competency_model / competency_item / competency_dict / llm_trace / assessment_session / question_bank / assessment_question / assessment_message / session_time_intervals / context_raw / form_submission / question_score / form_instance / report / feedback / eval_results / assessment_state_event / question_bank_task / idempotency_record / trace_link).
- Per the plan, the parity assertion extracts the table-name set **dynamically** from `_DDL` via `re.findall` (no hardcoded count), so the migration test locks the real 24-table inventory and auto-adapts when 06-05 adds `bad_case_candidate`.
- The 21-vs-24 difference is a **SSOT documentation discrepancy** (not a code defect) — SSOT updates require explicit user authorization, so the executor did **not** write `design/final-design/总设计文档.md`. Flagged here for user decision.

## Threat Flags

None — no new security surface beyond what the plan's `<threat_model>` already covers (T-06-03 `_DB_PATH_OVERRIDE` is process-local and does not persist/env-mutate; T-06-04 conftest uses `setdefault`).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `server/conftest.py` + `server/test_migration.py` are ready for 06-02 (unified pytest collection) to consume the session temp-DB fixture.
- `server/db.py` `set_db_path()` is ready for 06-05 (eval isolation).
- Deferred to 06-03: the 13 session-test files' `question_bank` seed must add `model_id`/`model_version` (`[04-011]`); this is the sole source of the pre-existing `test_m5_backend.py` red.
- Next plan: 06-02 (pytest unification + CI).

---
*Phase: 06-migration-test-closure*
*Completed: 2026-09-05*

## Self-Check: PASSED

- Files exist: server/db.py, server/conftest.py, server/test_migration.py, 06-01-SUMMARY.md, deferred-items.md
- Task commits exist: f1617f2 (feat), d253fc8 (test), 4117469 (test)
- `python -m pytest test_migration.py -q` → 3 passed
