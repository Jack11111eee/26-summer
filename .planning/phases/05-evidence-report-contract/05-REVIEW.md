---
phase: 05-evidence-report-contract
reviewed: 2026-09-05T12:00:00Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - server/api/admin/feedback.py
  - server/api/admin/reports.py
  - server/api/admin/trace.py
  - server/api/assessment.py
  - server/db.py
  - server/main.py
  - server/services/aggregation.py
  - server/services/llm.py
  - server/services/report_checks.py
  - server/services/report.py
  - server/services/scoring.py
  - server/services/trace_link.py
  - server/test_m6_backend.py
  - server/test_phase5_evidence.py
  - server/test_phase5_feedback.py
  - server/test_phase5_report.py
  - web/src/api/index.js
  - web/src/views/admin/TestCenter.vue
  - web/src/views/assessment/Report.vue
findings:
  critical: 1
  warning: 6
  info: 5
  total: 12
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-09-05T12:00:00Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Reviewed the Phase 5 ("evidence-report-contract") surface: structured evidence spans + `trace_link` audit table, item_measurement adjudication + IMPUTED r-proportion imputation with `(score−1)/4` normalization, report state machine + versioned INSERT + 7 consistency checks + admin publish endpoint, and feedback audit-chain fields.

High-level assessment: the SQL layer is clean — all dynamic SQL uses placeholder parameterization, and the only f-string interpolations interpolate hardcoded identifiers (table/PK names and `?` placeholders), so there is no injection surface. Authorization is correct: admin routers gate with `Depends(require_admin)` (cached per request), and candidate report/session reads/writes route through `load_owned_report`/`load_owned_session` with the D-01 unified-404 semantics (no ownership oracle). Unicode span offsets use Python `str.find`/`len` (code-point semantics), consistent with `answer_text[start:end]` slicing — verified correct.

The substantive defects are in the **adjudication → human-review gating** and **report state-machine / versioning** flows, where a designed safety mechanism fails to fire and the `GENERATING` placeholder is never resolved.

## Critical Issues

### CR-01: Adjudication conflict flag never propagates to report review_status / provisional

**File:** `server/services/aggregation.py:269` (and `server/services/report.py:222-225`)
**Issue:** `adjudicate()` returns `(item_final_level, human_review)`, where `human_review=True` signals a "major conflict" (§19 重大冲突取低留人工标记). In the measured-item branch the flag is stored only in the per-item dict (`"human_review": human_review`, line 280), and `_observed_items` explicitly discards it (`level, _ = adjudicate(ms)`, line 81). It is never aggregated into the top-level `review_status` or `provisional` — those are set *only* by required-missing (line 289) and `O=∅` (line 340). As a result, a report whose evidence disagrees wildly (e.g. observed levels 1 and 5) is generated as `READY` (not `PROVISIONAL`) and is publishable without any human review, defeating the entire purpose of the conflict detector. The state machine never sees the flag.

**Fix:** Aggregate any conflict flag upward. In the measured branch, when `human_review` is true set `provisional = True` and `review_status = "HUMAN_REVIEW_REQUIRED"` (or track a separate `conflict_review` boolean and OR it into the report-status decision):
```python
if human_review:
    provisional = True
    review_status = "HUMAN_REVIEW_REQUIRED"
```
and add a corresponding assertion in `_run_consistency_checks` ⑥ so the gap is regression-tested.

## Warnings

### WR-01: coverage_ratio numerator/denominator are inconsistent (can exceed 1.0)

**File:** `server/services/aggregation.py:216-224, 333`
**Issue:** `observed_count = len(observed_items)` (line 223) counts *all* measured items — `_observed_items` groups every SCORED row by `item_id` without filtering `importance`/`category` — while `total_measureable` (line 216-221) *excludes* `gate`, `importance="required"`, and `category="qualification"` items. For a model whose only non-gate items are `required` (exactly the `test_m6_backend.py` seed), `observed_count=2` but `total_measureable=0`, so `coverage_ratio` is forced to `0.0`. In a mixed model the ratio can exceed `1.0`. This value also drives the imputed-item `human_review` flag (`coverage_ratio > IMPUTE_RATIO_THRESHOLD`, line 333), which §31-3 defines as the *imputed* coverage, not observed coverage.

**Fix:** Compute `observed_count` from the same filter as the denominator (only non-gate, non-required, non-qualification measured items), and gate the imputed-item review flag on imputed ratio (`imputed_count / total_measureable`) rather than observed `coverage_ratio`.

### WR-02: Consistency check ① compares rounded per-item scores against unrounded total (false FAILED reports)

**File:** `server/services/report_checks.py:29-31` (vs `server/services/aggregation.py:278,282`)
**Issue:** `total_score` is accumulated from *unrounded* contributions (`total_score += contribution`, line 282) then rounded once at return, but each `item_scores[*]["score"]` is `round(contribution, 2)` (line 278). Check ① recomputes `sum(item_scores[*]["score"])` (rounded) and requires `abs(recomputed - total_score) < 0.01`. With weights whose contribution has >2 decimals (e.g. three items at weight 1/3, level 5 → each 33.33, sum 99.99 vs total 100.0), the diff is exactly `0.01`, so a valid report is spuriously marked `FAILED` and the candidate is denied their report.

**Fix:** Recompute total from the same unrounded formula, or round each contribution only at presentation and keep `item_scores[*]["score"]` unrounded for the check, or widen the threshold to accommodate per-item rounding.

### WR-03: publish endpoint sets review_outcome but never updates review_status

**File:** `server/api/admin/reports.py:45-50`
**Issue:** `publish_report` writes `review_outcome`, `review_note`, `reviewer_id`, `reviewed_at`, but does not touch `review_status`. Publishing a `HUMAN_REVIEW_REQUIRED` report with `review_outcome="CONFIRMED"` leaves `review_status='HUMAN_REVIEW_REQUIRED'` while `report_status='PUBLISHED'` — a contradictory row. `REVIEW_STATUSES` includes `CONFIRMED`/`CLOSED` precisely to represent the resolved review.

**Fix:** On publish, set `review_status = 'CONFIRMED'` (or `'CLOSED'`) when `review_outcome == 'CONFIRMED'`, and add a test assertion on `review_status` alongside the existing `report_status` assertion in `test_publish_flow`.

### WR-04: `_migrate_trace_link` maps report traces to the wrong entity table

**File:** `server/db.py:753` (vs `server/services/report.py:179`)
**Issue:** `tables_by_call["report"] = ("report",)` probes `report.report_id`. But `generate_report` calls `call_llm_json("report", session_id, ...)` — the report LLM trace `ref_id` is a `session_id`, never a `report_id` (the `report_id` is minted only *after* the LLM call). Legacy report traces therefore never resolve to any entity and are silently skipped during migration, leaving the report leg of the audit chain unimported. The same tuple for `interviewer`/`refine`/`score` correctly includes `assessment_session`.

**Fix:** `"report": ("report", "assessment_session")` so a `session_id` ref_id resolves to `entity_type='assessment_session'` (link_role `source`, which matches the runtime `source` link).

### WR-05: `GENERATING` placeholder row is never transitioned on success

**File:** `server/api/assessment.py:1113-1124` and `server/services/report.py:227-232`; `server/api/assessment.py:1040-1044`
**Issue:** `request_report` inserts a `GENERATING` placeholder (version N). `generate_report` then inserts the real report as a *new* version (N+1) and never updates the placeholder. On success the placeholder stays `GENERATING` forever; on consistency-check failure the same happens (a new `FAILED` row is inserted, the placeholder is untouched). Only the `_write_failed_report` *exception* path updates `GENERATING→FAILED`. Consequences: (1) stale `GENERATING` rows accumulate with each regeneration; (2) a later failed regeneration's `UPDATE ... WHERE report_status='GENERATING'` retroactively flips prior stale placeholders to `FAILED`; (3) production version numbering differs from `test_version_immutability` (which calls `generate_report` directly and sees [1,2] with no placeholder skew).

**Fix:** On success (and on the consistency-check `FAILED` branch), transition the `GENERATING` placeholder to a terminal state (`UPDATE report SET report_status=... WHERE session_id=? AND report_status='GENERATING'`) instead of leaving it, or reuse the placeholder's version for the final row.

### WR-06: Consistency check ⑦ scans candidate-controlled text, not just LLM output

**File:** `server/services/report.py:208-211` (vs `server/services/report_checks.py:83-84`)
**Issue:** Check ⑦ receives `report_text=json.dumps(report_data)` — the *entire* serialized report, which includes `question_reviews[].answer` (candidate verbatim answers), `question_reviews[].stem`, and `evidence_quote`. If a candidate answer (or even a question stem) contains any redline phrase like "建议录用", the whole report is marked `FAILED` and — since the input is unchanged — every retry fails, permanently denying the candidate their report. The check's stated intent is "不信任 LLM 文案" (do not trust LLM text), so it should scope to LLM-produced fields only.

**Fix:** Pass only `strengths_text`/`weaknesses_text`/`suggestions_text` (or a dedicated `llm_text` string) to `_run_consistency_checks` for check ⑦, not the full `report_data`.

## Info

### IN-01: `_normalize_score` accepts an unused `source` parameter

**File:** `server/services/aggregation.py:31-37`
**Issue:** `source` is ignored (`return (score - 1) / 4.0`), and the `NORMALIZE_IMPUTED`/`NORMALIZE_OBSERVED` constants exist only to feed it, giving a misleading impression that two scales still exist.
**Fix:** Drop the parameter and constants, or document that normalization is deliberately single-scale.

### IN-02: Frontend `itemReason` still uses std_name matching despite item_id now being available

**File:** `web/src/views/assessment/Report.vue:316-323`
**Issue:** Phase 5 added `item_id` to `_load_question_reviews` (`server/services/report.py:94`), but the comment "question_reviews 未携带 item_id" is stale and `itemReason` falls back to `q.std_name === item.std_name`, which can pick the wrong question's reason for multi-question items.
**Fix:** Match on `q.item_id === itemId` and remove the stale comment.

### IN-03: Redundant private alias `_MAX_ANSWER_LEN`

**File:** `server/services/scoring.py:40`
**Issue:** `_MAX_ANSWER_LEN = MAX_ANSWER_LEN` duplicates the public constant solely for legacy in-module references.
**Fix:** Replace remaining `_MAX_ANSWER_LEN` references with `MAX_ANSWER_LEN` and delete the alias.

### IN-04: `review_outcome` is not validated against an allowed enum

**File:** `server/api/admin/reports.py:19-21, 47`
**Issue:** `_PublishBody.review_outcome` is an unconstrained `str` (default `"CONFIRMED"`), so an admin can persist an arbitrary value into the `review_outcome` column, breaking the `REVIEW_STATUSES`/outcome enumeration contract (N11 code-validated enums).
**Fix:** Validate against an allowed-outcome tuple (e.g. `CONFIRMED`/`REQUIRED`) before the UPDATE, returning 422 on invalid input.

### IN-05: Re-scoring orphans existing `trace_link` rows referencing deleted `question_score` rows

**File:** `server/services/scoring.py:321-333`
**Issue:** `score_session` DELETEs old `question_score` rows (`WHERE gate_result IS NULL`) and re-inserts with fresh `score_id`s. Any prior `trace_link(question_score, link_role='scored')` rows keep pointing at the deleted `score_id`s (weak association by design, D-020), so repeated scoring accumulates dangling audit links.
**Fix:** Document as accepted weak-association behavior, or delete/rewrite the `question_score`-typed trace links for the session in the same transaction.

---

_Reviewed: 2026-09-05T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
