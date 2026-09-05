---
phase: 03-sse
reviewed: 2026-09-05T12:30:00Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - server/api/admin/forms.py
  - server/api/assessment.py
  - server/config.py
  - server/core/security.py
  - server/db.py
  - server/main.py
  - server/schemas.py
  - server/services/aggregation.py
  - server/services/forms.py
  - server/services/idempotency.py
  - server/services/interview.py
  - server/services/question_selection.py
  - server/services/scoring.py
  - server/services/timer.py
  - server/test_m5_backend.py
  - server/test_p0_chain.py
  - server/test_p0_security.py
  - server/test_phase2_difficulty.py
  - server/test_phase2_interview.py
  - server/test_phase2_scoring.py
  - server/test_phase2_selection.py
  - server/test_phase3_forms.py
  - server/test_phase3_idempotency.py
  - server/test_phase3_misc.py
  - server/test_phase3_sse.py
  - server/test_phase3_timer.py
findings:
  critical: 0
  warning: 6
  info: 3
  total: 9
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-09-05T12:30:00Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found

## Summary

Reviewed the Phase 3 (03-sse) backend: FastAPI / raw-SQL SQLite form-chain, SSE streaming, two-phase idempotency, optimistic locking, and server-authoritative timing. No Critical security findings — SQL injection, secret handling, idempotency-key ownership, and the injection/response-snapshot surfaces all check out:

- All user-input queries are parameterized; the only f-string SQL uses hardcoded column names/identifiers.
- JWT fail-closed startup check (`_INSECURE_JWT_DEFAULTS`) correctly rejects default secrets.
- Idempotency three-key scope (`session_id, endpoint, idempotency_key`) plus `load_owned_session` ownership is sound; `request_hash_of` uses sort_keys normalization.
- Optimistic lock is an atomic `UPDATE ... WHERE revision=?` (no TOCTOU), and the revision-conflict path correctly rolls back before raising.
- `INJECTION_DETECTED` event payload and `_answer_snapshot` both carry whitelist keys only — no candidate raw input leaks.
- SSE generator (`_event_stream`) does zero DB work (persist-before-stream discipline).

The findings below are correctness/robustness defects. The dominant class is the **write-then-raise-without-rollback** SQLite RESERVED-lock leak — the same class already fixed once for the revision-conflict path (`assessment.py:536-539` documents it), but five 4xx paths still leak it. One functional gap: the admin gate-override endpoint writes `human_override`/`reviewer_id` but aggregation never reads them, so a manual override is silently a no-op.

Per task instruction, the two known pre-existing full-suite isolation issues (`test_phase2_migration`, `test_question_bank`) are NOT flagged here — they are logged in `deferred-items.md`.

## Warnings

### WR-01: gate_override 404 path leaks a RESERVED write lock

**File:** `server/api/admin/forms.py:34-35`
**Issue:** `gate_override` runs `UPDATE question_score SET human_override=... WHERE ...` and raises `HTTPException(404)` when `cur.rowcount == 0` — without `conn.rollback()`. The UPDATE opens a write transaction and acquires a SQLite RESERVED lock even when it matches zero rows. The connection is never rolled back or closed, so the lock is held until GC (up to the >5s busy timeout). This is the exact bug class the code already documents and fixed for the revision-conflict path (`assessment.py:536-539`).
**Fix:**
```python
if cur.rowcount == 0:
    conn.rollback()
    raise HTTPException(status.HTTP_404_NOT_FOUND, "gate 行不存在")
```

### WR-02: submit_answer 4xx paths leak uncommitted idempotency PENDING insert + RESERVED lock

**File:** `server/api/assessment.py:433, 441, 444`
**Issue:** After `check_idempotency` (line 412) INSERTs a PENDING idempotency row on the main `conn` (an uncommitted write that acquires RESERVED), three branches raise without commit or rollback: `SESSION_PAUSED` (433), question-not-found 404 (441), and `QUESTION_ALREADY_ANSWERED` (444). The `SESSION_NOT_IN_PROGRESS` branch (420-426) correctly commits first; these three do not. The write transaction holds the lock and the PENDING insert dangles until GC.
**Fix:** Roll back before each raise (no state should persist on these paths):
```python
# before each raise in the three branches:
conn.rollback()
raise HTTPException(...)
```

### WR-03: submit_form_v2 4xx paths leak the same RESERVED lock

**File:** `server/api/assessment.py:930-940`
**Issue:** `submit_form_v2` calls `check_idempotency` (line 919), which INSERTs a PENDING row on the main `conn`. When `validate_and_submit` returns `ok=False`, the 404 / 409 / 422 branches (930-940) raise without `conn.rollback()` or `conn.close()`, leaking the RESERVED lock and the uncommitted PENDING insert.
**Fix:**
```python
if not result["ok"]:
    conn.rollback()
    code = result["error_code"]
    ...
```

### WR-04: timeout→form branch never finalizes idempotency (record stuck PENDING)

**File:** `server/api/assessment.py:460-464`
**Issue:** In the single-question-timeout path, when the pool is exhausted and gate items are not yet collected, the code returns `_render_form_branch(...)` at line 464 without calling `finalize_idempotency`. The main-chain form branch (691-696) and the legacy form branch (723-728) both finalize before returning. When `body.idempotency_key` is set, this leaves the idempotency record permanently PENDING — any retry with the same key gets 409 `REQUEST_IN_PROGRESS`.
**Fix:**
```python
if not _all_gate_items_collected(conn, session_id):
    if body.idempotency_key:
        finalize_idempotency(session_id=session_id, endpoint="answer",
                             key=body.idempotency_key,
                             snapshot=_answer_snapshot("form", timeout_decision, question_id, None))
    return _render_form_branch(conn, session_id, question_id, timeout_decision)
```

### WR-05: admin gate override has no functional effect (human_override written but never read)

**File:** `server/api/admin/forms.py:29-31` + `server/services/aggregation.py:53-60`
**Issue:** `gate_override` writes `human_override`/`override_reason`/`reviewer_id`, but `aggregate_session_scores` → `_gate_row` reads only `gate_result`/`gate_reason` (and falls back to `_gate_check` on `form_payload` when no gate row). The manual override never influences the gate pass/fail outcome — an admin's override is silently a no-op, and the `GATE_OVERRIDDEN` event is written with no downstream consumer. Relatedly, `automated_gate_result` (db.py:248) is declared but never written.
**Fix:** Make `_gate_row` honor the override when present:
```python
# _gate_row: prefer human_override, fall back to automated gate_result
row = conn.execute(
    "SELECT gate_result, gate_reason, human_override FROM question_score"
    " WHERE session_id=? AND item_id=? AND gate_result IS NOT NULL LIMIT 1",
    (session_id, item_id),
).fetchone()
if row is None:
    return None
effective = row["human_override"] if row["human_override"] is not None else row["gate_result"]
return (effective, row["gate_reason"])
```

### WR-06: pause/resume lack a phase guard — PENDING_START session can be pause-resumed to ACTIVE

**File:** `server/api/assessment.py:242-310`
**Issue:** `pause_session` and `resume_session` check only `status != "in_progress"`, never `phase`. A freshly created session (`phase='PENDING_START'`, `status='in_progress'`) can be paused (→ `phase='PAUSED'`) and then resumed (→ `phase='ACTIVE'` + opens an `active` interval) without ever passing through `start_session`. This bypasses the PENDING_START→ACTIVE transition and skips the `SESSION_STARTED` event (`assessment.py:235-237`), violating the §13.1 event/snapshot invariant and starting the active timing interval outside the entry-confirmation flow.
**Fix:** Guard on phase rather than only status:
```python
# pause_session
if s.get("phase") != "ACTIVE":
    raise HTTPException(status.HTTP_409_CONFLICT,
                        detail={"error_code": "SESSION_NOT_ACTIVE",
                                "message": "会话尚未开始，不可暂停"})
# resume_session
if s.get("phase") != "PAUSED":
    raise HTTPException(status.HTTP_409_CONFLICT,
                        detail={"error_code": "SESSION_NOT_PAUSED",
                                "message": "会话未暂停"})
```

## Info

### IN-01: FormSubmitRequest.schema_version is required but never validated

**File:** `server/schemas.py:120`
**Issue:** `schema_version: str = Field(min_length=1)` is mandatory, but `validate_and_submit` (forms.py:133-191) never compares `body.schema_version` against `form_instance.schema_version` (or `FORM_SCHEMA_VERSION`). The field is dead — a client submitting a mismatched version is silently accepted.
**Fix:** Validate `body.schema_version == row["schema_version"]` and return a 409 on mismatch, or drop the field from the request model.

### IN-02: automated_gate_result column declared but never written or read

**File:** `server/db.py:248` (and migration listing at `server/db.py:562`)
**Issue:** `automated_gate_result` is declared in the DDL and the migration column list, but no code path writes it (the automated gate result is written to `gate_result` in `forms.py:176`) and no code reads it. Dead column.
**Fix:** Remove the column, or populate it when gate rows are created if automated-vs-override provenance is intended to be tracked.

### IN-03: pervasive get_conn() without close in read-only helpers

**File:** `server/services/aggregation.py:20, 94`; `server/services/report.py:37, 76, 91` (and similar in `interview.py`, `scoring.py`, `question_selection.py`)
**Issue:** Many service helpers call `get_conn()` and never close the returned connection, relying on CPython reference-count GC. Read-only paths do not hold write locks, but this leaks connection objects / file descriptors and is inconsistent with the explicit `try/finally: conn.close()` discipline already present in `readiness.py:60-63` and `idempotency.py:100-101`.
**Fix:** Use a context manager or `try/finally` close in these helpers, matching the existing close discipline.

---

_Reviewed: 2026-09-05T12:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
