# SECURITY.md — Phase 05 (evidence-report-contract)

Security audit of Phase 05 (evidence-report-contract) threat model. Every declared threat
mitigation was verified against implemented code (documentation and intent were not treated
as evidence). Implementation files were read-only during this audit.

- **Phase:** 05 — evidence-report-contract (plans 05-01 ~ 05-05)
- **Threats:** 15 total (14 mitigate + 1 accept)
- **Threats Closed:** 15/15
- **ASVS Level:** default
- **Audit date:** 2026-09-05

## Threat Verification

| Threat ID | Category | Component | Disposition | Evidence |
|-----------|----------|-----------|-------------|----------|
| T-05-01 | Tampering | server/services/trace_link.py `link_entity` | mitigate | `trace_link.py:9` `LINK_ROLES` six-value enum; `trace_link.py:17-18` `if link_role not in LINK_ROLES: raise ValueError` before any INSERT |
| T-05-02 | Tampering | server/db.py `_migrate_trace_link` | mitigate | `db.py:719-780`; `db.py:771-773` `SELECT 1 FROM {table} WHERE {pk}=?` probe; `db.py:775-779` `INSERT OR IGNORE` only on hit (unmatched keeps original `ref_id`, no fabricated `entity_type`) |
| T-05-03 | Tampering | server/services/scoring.py `_locate_span` | mitigate | `scoring.py:116-133` `_locate_span` computes offset/`sha256` in code (hashlib import `:14`); `scoring.py:136-150` `_build_evidence_spans` degrades to `quote_hash`-only span, no throw |
| T-05-04 | Tampering | server/services/aggregation.py `_impute_r` | mitigate | `aggregation.py:55-67` r computed in code; `:65-66` `if den == 0: return None` (no div-zero); float tolerance asserted in `server/test_phase5_report.py:123,131` `abs(r - 0.5) < 1e-6` |
| T-05-05 | Tampering | server/services/aggregation.py `adjudicate` | mitigate | `aggregation.py:23` `ADJUDICATE_CONFLICT_THRESHOLD = 2` single constant; `aggregation.py:50-52` conflict takes `min(levels)` + `human_review=True` |
| T-05-06 | Tampering | impute threshold config | mitigate | `aggregation.py:28` `IMPUTE_RATIO_THRESHOLD = 0.2` single constant; `aggregation.py:368-374` `coverage` display incl. `coverage_ratio`; `aggregation.py:339` `human_review: imputed_ratio > IMPUTE_RATIO_THRESHOLD` |
| T-05-07 | Elevation of Privilege | server/api/admin/reports.py `publish` | mitigate | `admin/reports.py:16` `router = APIRouter(..., dependencies=[Depends(require_admin)])`; `:25` `admin: dict = Depends(require_admin)`; `core/security.py:57-60` non-admin → 403 |
| T-05-08 | Tampering | server/services/report_checks.py | mitigate | `report_checks.py:9` `HIRING_REDLINE_WORDS` exact six-word list; `report_checks.py:12-90` seven consistency checks in code; `report.py:234-243` errors → `report_status='FAILED'` row |
| T-05-09 | Tampering | server/services/report.py state machine | mitigate | `report.py:22-24` `REPORT_STATUSES`/`REVIEW_STATUSES` enums; `report.py:36-47` `_assert_report_status`/`_assert_report_transition` raise on illegal value/transition; `report.py:27-33` `_REPORT_TRANSITIONS` graph (PUBLISHED/FAILED terminal) |
| T-05-10 | Tampering | server/api/assessment.py `_generate_report_task` | mitigate | `assessment.py:1060-1084` exception branch writes FAILED row via `:1081` `_write_failed_report` + `:1082` `TASK_FAILED` event (no silent pass) |
| T-05-11 | Elevation of Privilege | server/api/admin/feedback.py review/bad-case | mitigate | `admin/feedback.py:9` `router = APIRouter(..., dependencies=[Depends(require_admin)])`; `:35,50` `admin: dict = Depends(require_admin)` |
| T-05-12 | Tampering | server/api/assessment.py `submit_feedback` | mitigate | `assessment.py:1164-1172` JOIN `competency_item → assessment_session → report` ownership validation; item not of report's model → 404 "能力项不存在" |
| T-05-13 | Repudiation | submit_feedback event append | mitigate | `assessment.py:1181-1183` `append_event(..., event_type="REVIEW_FEEDBACK_RECEIVED", actor_type="candidate", actor_id=user["user_id"])` same transaction, `:1184` single `conn.commit()` |
| T-05-14 | Tampering | server/api/admin/feedback.py note persistence | mitigate | `admin/feedback.py:38-42` review UPDATE persists `review_note`/`reviewer_id`/`reviewed_at`; `:53-57` bad-case same three columns (body.note no longer dropped) |
| T-05-SC | Tampering | npm/pip/cargo installs | accept | accepted risk — documented below; zero new packages per plan (stdlib only) |

## Accepted Risks

| Threat ID | Risk | Rationale / Acceptance |
|-----------|------|------------------------|
| T-05-SC | Supply-chain surface from package installs | Accepted. Plans 05-01 ~ 05-05 add zero new packages (`hashlib`/`json`/`re`/`sqlite3` stdlib only). No new dependency surface introduced this phase. |

## Unregistered Flags

None. No SUMMARY.md in this phase contains a `## Threat Flags` section; no new attack surface
was surfaced by the executor outside the authored threat register.

## Trust Boundary Notes

- Client→server: quote offset/hash, adjudication/imputation, publish, and feedback are all
  computed/authorized server-side; admin routes gated by `require_admin` (403 on non-admin).
- Service layer→DB: `link_role` enum validated in `link_entity` (T-05-01); `report_status`/
  `review_status` validated in `_assert_report_status`/`_assert_report_transition` (T-05-09);
  `assessment_state_event` is append-only (UPDATE/DELETE triggers in `db.py:355-359`).
