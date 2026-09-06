---
phase: 06-migration-test-closure
reviewed: 2026-09-06T09:00:00Z
depth: standard
files_reviewed: 36
files_reviewed_list:
  - .github/workflows/ci.yml
  - eval/consistency_test.py
  - eval/virtual_candidates.py
  - server/api/admin/eval.py
  - server/api/assessment.py
  - server/conftest.py
  - server/config.py
  - server/db.py
  - server/requirements.txt
  - server/services/input_limits.py
  - server/services/report.py
  - server/test_bad_case.py
  - server/test_e2e_full_chain.py
  - server/test_eval_isolation.py
  - server/test_input_limits.py
  - server/test_m1_regression.py
  - server/test_m5_backend.py
  - server/test_m6_backend.py
  - server/test_m7_backend.py
  - server/test_migration.py
  - server/test_p0_chain.py
  - server/test_p0_security.py
  - server/test_phase2_difficulty.py
  - server/test_phase2_interview.py
  - server/test_phase2_migration.py
  - server/test_phase2_scoring.py
  - server/test_phase3_forms.py
  - server/test_phase3_idempotency.py
  - server/test_phase3_misc.py
  - server/test_phase3_sse.py
  - server/test_phase3_timer.py
  - server/test_question_bank.py
  - server/test_secret_gate.py
  - web/src/api/index.js
  - web/src/components/FormCard.vue
  - web/src/views/assessment/Report.vue
findings:
  critical: 0
  warning: 5
  info: 8
  total: 13
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-09-06T09:00:00Z
**Depth:** standard
**Files Reviewed:** 36
**Status:** issues_found

## Summary

Reviewed the 36 changed source files for Phase 6 (迁移体系与测试闭环收口): the `schema_version` migration registry in `server/db.py`, the pytest `conftest.py` linchpin, the eval isolation runner, input-limit services, report generation, the frontend report/form/API wiring, and ~22 test modules.

Overall the implementation is structurally sound — the migration ledger replay/idempotency paths, eval DB isolation via `set_db_path()`, and the fail-closed JWT secret gate are all well-tested and internally consistent. No critical (BLOCKER) security or data-loss defects were found. The cross-file frontend submit-v2 wiring (`📎[form:id]` → `form_instance_id`) is correct despite a misleading prop name.

The notable defects are robustness/hygiene issues: a migration-backup path that creates 13 redundant backups on fresh init and would crash at startup on Windows (colon in filename), two dead input-limit functions that are the intended-but-unwired fix for an unclamped pagination limit, unclosed `get_conn()` connections in the in-process eval scripts, and a conftest import-order freeze that silently voids per-file `DB_PATH` isolation in ~15 test files.

## Warnings

### WR-01: Migration backup runs 13 times on fresh init and produces a Windows-invalid filename

**File:** `server/db.py:915-927`
**Issue:** `_backup_before_migration` is called for every migration whose `version` is absent from `schema_version`. On a fresh database `applied` is empty, so `init_db()` triggers a backup for all 13 migrations before `_DDL` even creates the tables — producing 13 near-identical backup files on first boot. More seriously, the filename is `app-{datetime.now(timezone.utc).isoformat()}-pre-{version}.db`, and `datetime.isoformat()` emits characters (`:`, `+`) that are illegal in NTFS filenames. On Windows this raises `OSError`/`sqlite3.OperationalError` inside `sqlite3.connect(...)` and crashes `init_db()` at startup (the app never boots). It works on Linux/macOS CI, which masks the issue.
**Fix:** Back up once per `init_db()` call (a single pre-migration snapshot) and use a filesystem-safe timestamp:
```python
def _safe_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

def _backup_before_migration(conn: sqlite3.Connection) -> None:
    if _backup_done_for_this_init:
        return
    _backup_done_for_this_init = True
    bdir = os.path.join(os.path.dirname(os.path.abspath(_resolve_db_path())), "backups")
    os.makedirs(bdir, exist_ok=True)
    target = sqlite3.connect(os.path.join(bdir, f"app-{_safe_ts()}-pre-migration.db"))
    try:
        conn.backup(target)
    finally:
        target.close()
```

### WR-02: Input-limit functions are dead code — the pagination clamp is never wired

**File:** `server/services/input_limits.py:10-23`
**Issue:** `validate_jd_length` and `clamp_pagination_limit` are pure functions imported only by `server/test_input_limits.py`. No production endpoint calls them. `clamp_pagination_limit` is the intended fix for the unclamped `list_history` limit (WR-03), but it is never invoked, so the "input limits" feature of Phase 6 is test-only and inert in production.
**Fix:** Wire the functions into their consumers. For pagination, call `clamp_pagination_limit` in `server/api/admin/eval.py::list_history` (see WR-03). For `validate_jd_length`, call it in the JD-upload/extract endpoint before ingesting JD text (or explicitly document that wiring is deferred pending `MAX_JD_LENGTH` being set — in which case remove the tests-only ambiguity).

### WR-03: `list_history` accepts an unbounded/negative limit

**File:** `server/api/admin/eval.py:118-127`
**Issue:** `list_history(limit: int = 20)` passes the raw query parameter straight into `LIMIT ?` with no validation. In SQLite, `LIMIT -1` means "no limit", so `GET /api/admin/eval/history?limit=-1` returns every row, and `limit=0` returns an empty list. There is no upper bound, so a caller can request the entire table. The parameter is bound (no SQL injection), but the missing clamp is a robustness/abuse-surface gap — and `clamp_pagination_limit` exists precisely for this and is unwired.
**Fix:**
```python
from ...services.input_limits import clamp_pagination_limit

@router.get("/history")
def list_history(limit: int = 20) -> list[dict]:
    limit = clamp_pagination_limit(limit)
    conn = get_conn()
    ...
```

### WR-04: Eval scripts leak `get_conn()` connections in the long-lived server process

**File:** `eval/consistency_test.py:48,68`; `eval/virtual_candidates.py:77,129,181`
**Issue:** `get_conn()` opens a fresh `sqlite3.connect(...)` with no pooling or auto-close. The admin runner (`server/api/admin/eval.py::_run`) executes these functions *in-process* via `background_tasks.add_task`, not as subprocesses, so every unclosed connection stays open in the FastAPI process. Each consistency run leaks 2 connections (`_load_answered_questions` and `test_scoring_consistency`); each virtual-candidate run leaks 5 (`_get_or_seed_bank`, `_ensure_eval_user`, and 3× `_run_one_tier`). Repeated admin-triggered runs accumulate open SQLite connections and file handles.
**Fix:** Close every connection explicitly (or add a context-manager to `get_conn` and use `with`):
```python
def _load_answered_questions(session_id: str) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(...).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

### WR-05: conftest import order silently voids per-file `DB_PATH` isolation in ~15 test modules

**File:** `server/conftest.py`; module-level `os.environ["DB_PATH"] = tempfile.mkdtemp()` in `server/test_m5_backend.py`, `test_m6_backend.py`, `test_m7_backend.py`, `test_p0_chain.py`, `test_p0_security.py`, `test_phase2_difficulty.py`, `test_phase2_interview.py`, `test_phase2_scoring.py`, `test_phase3_forms.py`, `test_phase3_idempotency.py`, `test_phase3_misc.py`, `test_phase3_sse.py`, `test_phase3_timer.py`, `test_question_bank.py`, and others
**Issue:** `conftest.py` imports `from server.db import init_db, get_conn`, which triggers `from .config import DB_PATH` at import time, freezing `config.DB_PATH` before any test module runs. The module-level `os.environ["DB_PATH"] = tempfile.mkdtemp()` assignments in ~15 test files therefore execute *after* `config.py` has already read `DB_PATH` — they are no-ops. All these test files silently share the single session-scoped temp DB from `conftest.py`, contradicting their per-file-isolation docstrings. This is a test-reliability/maintainability hazard: tests can become order-dependent, and a reader is misled into believing each file is isolated. (`server/test_phase2_migration.py:123-130` explicitly documents this freeze; the other files' docstrings still claim isolation.)
**Fix:** Either remove the dead `os.environ["DB_PATH"]` assignments and update the docstrings to state that tests share the conftest session DB (with per-file override via `set_db_path()` where isolation is actually required), or move the env-set before the `server` import and stop relying on conftest for those files.

## Info

### IN-01: `_AQ_NEW_COLS` omits the `revision` column the migration actually adds

**File:** `server/test_phase2_migration.py:153-157`
**Issue:** `_migrate_assessment_question_v2` adds a `revision` column, but `_AQ_NEW_COLS` does not list it. The test asserts `_AQ_NEW_COLS <= _cols(...)` (subset), so it passes while never verifying the `revision` migration actually ran.
**Fix:** Add `"revision"` to `_AQ_NEW_COLS` and add an explicit assertion that the old row received the expected `revision` backfill (e.g., `0` or `1`).

### IN-02: `_resolve_db_path` uses `or`, so an empty-string override falls through

**File:** `server/db.py:22`
**Issue:** `return _DB_PATH_OVERRIDE or DB_PATH` — if a caller passes `set_db_path("")`, the empty string is falsy and silently resolves to the frozen `DB_PATH`. Truthiness is the wrong check for a path override.
**Fix:** `return DB_PATH if _DB_PATH_OVERRIDE is None else _DB_PATH_OVERRIDE`

### IN-03: Lazy `new_id` import inside `_migrate_trace_link`

**File:** `server/db.py:808`
**Issue:** `from .services.pipeline import new_id` is performed inside the function body, unlike every other import in the module. The docstring on the backup helper mentions avoiding a `db<->pipeline` import cycle, but this lazy import is unusual and easy to miss.
**Fix:** If the import cycle concern no longer applies, hoist to module level; otherwise add a one-line comment explaining the cycle avoidance so future editors don't "clean it up" and break startup.

### IN-04: Placeholder GENERATING report row overwrites its `created_at`

**File:** `server/services/report.py:66-71`
**Issue:** When `_insert_report_row` converts the placeholder GENERATING row into the terminal row, the UPDATE sets `created_at = now_iso()`, discarding the placeholder's original creation timestamp (which is what the async generation latency could be measured against).
**Fix:** Preserve the original `created_at` (drop `created_at` from the SET clause) and, if the completion time is needed, record it in a separate `completed_at`/`updated_at` column.

### IN-05: `_render_form_branch` uses direct key access for `decision["reply"]`

**File:** `server/api/assessment.py:399`
**Issue:** `reply = decision["reply"] + ...` uses direct key access, while the rest of the codebase (including `_decision_frame` at line 383 and `_event_stream` reassembly) uses `decision.get("reply") or ""` precisely to tolerate degraded dicts missing `"reply"`. If a future decision producer omits `"reply"`, this line raises `KeyError` and 500s the form branch.
**Fix:** `reply = (decision.get("reply") or "") + f" 请先填写资格核验表单 📎[form:{fi['form_instance_id']}]"`

### IN-06: `None` placeholder config values leave several features inert

**File:** `server/config.py:65,71-78,84-85`
**Issue:** `BAD_CASE_DIVERGENCE_THRESHOLD`, `MAX_JD_LENGTH`, `MAX_JD_FILE_LINES`, `MAX_PAGINATION_LIMIT`, `TRACE_RETENTION_DAYS`, `TRACE_DESENSITIZE`, `IDEMPOTENCY_CLEANUP_THRESHOLD`, `DICT_MATCH_THRESHOLD`, and `TITLE_CLEAN_WORDS` are all `None`/empty placeholders pending user decision. Their consumers intentionally no-op when unset, but this means bad-case divergence detection, JD input limits, trace retention/desensitization, and idempotency cleanup are inactive in production until a value is decided.
**Fix:** No code change required — this is a documented design state — but ensure these are tracked as open decisions and that the no-op branches (e.g., `if threshold is None: return 0`) are covered so they don't silently change behavior when values are filled in.

### IN-07: `FormCard.vue` prop `formId` actually carries `form_instance_id`

**File:** `web/src/components/FormCard.vue:75,92,110`
**Issue:** The prop is named `formId` but the value it receives (extracted from the `📎[form:id]` marker emitted by `_render_form_branch`, which embeds `fi['form_instance_id']`) is the `form_instance_id`, and it is passed as `form_instance_id` to `submit-v2` and as the path segment to `GET /forms/{form_instance_id}`. The wiring is functionally correct but the name invites future misuse.
**Fix:** Rename the prop to `formInstanceId` for clarity (and update the parent `Chat.vue` binding).

### IN-08: Report polling cap (2 min) may undercut real LLM generation time

**File:** `web/src/views/assessment/Report.vue:272`
**Issue:** `MAX_POLLS = 40` at 3s intervals gives a 2-minute window before the UI declares `phase = 'failed'`. Real (non-mock) report generation aggregates scores and invokes the LLM and can exceed 2 minutes; the frontend would show "报告生成超时或失败" while the backend is still generating, and there is no auto-resume once the report completes after the cap.
**Fix:** Raise the cap and/or make the failure state resumable (continue polling in the background, or have the "重新生成" path first re-check `getReportBySession` before re-triggering).

---

_Reviewed: 2026-09-06T09:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
