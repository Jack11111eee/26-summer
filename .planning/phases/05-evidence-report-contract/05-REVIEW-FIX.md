---
phase: 05-evidence-report-contract
fixed_at: 2026-09-05T11:29:04Z
review_path: .planning/phases/05-evidence-report-contract/05-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 05: Code Review Fix Report

**Fixed at:** 2026-09-05T11:29:04Z
**Source review:** .planning/phases/05-evidence-report-contract/05-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7
- Fixed: 7
- Skipped: 0

## Fixed Issues

### CR-01: Adjudication conflict flag never propagates to report review_status / provisional

**Files modified:** `server/services/aggregation.py`, `server/services/report_checks.py`, `server/test_phase5_report.py`
**Commit:** 69398de
**Applied fix:** In `aggregate_session_scores`, the measured-item branch now sets `provisional = True` and `review_status = "HUMAN_REVIEW_REQUIRED"` whenever `adjudicate()` returns `human_review=True`. Added a consistency-check ⑥ assertion that fails if any item carries `human_review=True` but the top level is not PROVISIONAL/HUMAN_REVIEW_REQUIRED. Added regression tests (`test_conflict_propagates_provisional`, `test_conflict_consistency_guard`).

### WR-01: coverage_ratio numerator/denominator are inconsistent (can exceed 1.0)

**Files modified:** `server/services/aggregation.py`
**Commit:** 1a67626
**Applied fix:** `observed_count` now counts only measured items that are non-gate/non-required/non-qualification (the same filter as `total_measureable`), and the imputed-item `human_review` flag now uses `imputed_count / total_measureable` instead of observed `coverage_ratio`.

### WR-02: Consistency check ① compares rounded per-item scores against unrounded total

**Files modified:** `server/services/aggregation.py`, `server/services/report.py`
**Commit:** a2d63d5
**Applied fix:** Per-item contributions are kept unrounded in `item_scores[*]["score"]` so check ① recomputes the same unrounded total; `report.py` now rounds each score to 2 decimals at presentation (`item_details`).

### WR-03: publish endpoint sets review_outcome but never updates review_status

**Files modified:** `server/api/admin/reports.py`, `server/test_phase5_report.py`
**Commit:** ef862e9
**Applied fix:** On publish, `review_status` is set to `CONFIRMED` when `review_outcome == "CONFIRMED"` (otherwise the existing value is preserved). Added a `review_status == "CONFIRMED"` assertion to `test_publish_flow`.

### WR-04: `_migrate_trace_link` maps report traces to the wrong entity table

**Files modified:** `server/db.py`
**Commit:** e833498
**Applied fix:** `tables_by_call["report"]` now probes `("report", "assessment_session")` so a `session_id` ref_id resolves to `entity_type='assessment_session'` (link_role `source`).

### WR-05: `GENERATING` placeholder row is never transitioned on success

**Files modified:** `server/services/report.py`
**Commit:** 8604042
**Applied fix:** `_insert_report_row` now reuses the latest `GENERATING` placeholder row in place (transitioning it to the final status, reusing its version) instead of always inserting a new version; when no placeholder exists it falls back to a versioned INSERT.

### WR-06: Consistency check ⑦ scans candidate-controlled text, not just LLM output

**Files modified:** `server/services/report.py`
**Commit:** 59eb27a
**Applied fix:** `generate_report` now passes only the LLM-produced text fields (`strengths_text`/`weaknesses_text`/`suggestions_text`) to `_run_consistency_checks` for check ⑦, not the full serialized `report_data`.

---

_Fixed: 2026-09-05T11:29:04Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
