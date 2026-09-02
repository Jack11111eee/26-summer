# Codebase Concerns

**Analysis Date:** 2026-09-02

## Tech Debt

**Frontend/backend contract drift in Chat.vue session rendering:**
- Issue: `web/src/views/assessment/Chat.vue` renders `session.position_name`, `session.model_version`, and `data.messages` from `GET /api/assessment/sessions/{session_id}`, but the backend endpoint (`server/api/assessment.py:97-126` `get_session`) returns only `session_id, status, position_id, model_version, current_question, answered_count, total_count` — it does not return `position_name` and does not return `messages` at all.
- Files: `web/src/views/assessment/Chat.vue` (lines 9-10, 176-183), `server/api/assessment.py:97`
- Impact: Chat header subtitle never shows position name; reloading a chat in progress loses the entire conversation history (fresh page shows only the opening blurb + current question). Users must not refresh mid-assessment or their context disappears from the UI (data persists server-side in `assessment_message`).
- Fix approach: Extend `get_session` in `server/api/assessment.py` to also select `p.name AS position_name` (JOIN position) and return `messages` (role/content/created_at from `assessment_message`), matching what Chat.vue's `load()` consumes.

**FormCard references a nonexistent backend endpoint:**
- Issue: `web/src/components/FormCard.vue` calls `assessment.getForm(formId)` → `GET /api/assessment/forms/${formId}` (`web/src/api/index.js:46`), but no such route exists anywhere in `server/api/` — the only form route is `POST /api/assessment/sessions/{session_id}/forms/submit` (`server/api/assessment.py:209`). There is also no backend logic anywhere that emits the `📎[form:xxx]` marker that `Chat.vue` extracts (`extractFormId`), and no form schema definitions exist server-side.
- Files: `web/src/components/FormCard.vue`, `web/src/api/index.js:46`, `web/src/views/assessment/Chat.vue:159-162`
- Impact: The form flow (resume/gate items such as work years and education that `_gate_check` in `server/services/aggregation.py:42-63` depends on for gate scoring) can never be presented to candidates in the real UI. Gate items will always score as "未提供或不达标" unless payloads are inserted manually.
- Fix approach: Add a form schema registry (or derive schemas from gate items of the session's model) plus `GET /api/assessment/forms/{form_id}`; emit the `📎[form:form_id]` marker in the interview reply at the appropriate point (e.g., before first gate-relevant question or at session start).

**`estimated_duration_minutes` is hardcoded:**
- Issue: `server/api/assessment.py:94` returns a constant `20` for `estimated_duration_minutes` regardless of question count or difficulty.
- Files: `server/api/assessment.py:94`
- Impact: Frontend displays misleading duration estimates if question count varies.
- Fix approach: Compute from question count (e.g., `len(questions) * 2` minutes) or remove the field.

**Duplicate session-scoring logic entry points with unclear orchestration:**
- Issue: `generate_report` (`server/services/report.py:89`) calls `aggregate_session_scores` but never calls `score_session` first. The frontend never calls `POST /api/assessment/sessions/{session_id}/score` (`web/src/api/index.js` has no score call; `web/src/views/assessment/Report.vue:378-403` `bootstrap()` only triggers report generation). If a candidate finishes a session and goes straight to the report, `question_score` rows are never written, so the report shows empty item scores, empty radar, and "未出题/未作答" everywhere.
- Files: `server/services/report.py:89-100`, `server/api/assessment.py:233-246`, `web/src/views/assessment/Report.vue:378-403`
- Impact: Reports generated through the normal UI flow (Chat.vue `finish` → Report.vue) have no scoring data. The M6 test (`server/test_m6_backend.py:164`) calls `score_session` explicitly before asserting report content, which masks the gap.
- Fix approach: Either have `generate_report` invoke `score_session(session_id)` first (idempotent already — deletes and re-inserts), or have `request_report` API endpoint chain scoring into the background task.

**Unused dependencies in requirements.txt:**
- Issue: `pypinyin>=0.50` and `httpx>=0.27` are listed in `server/requirements.txt` but never imported by any server code (`httpx` is only an indirect transitive dep of fastapi TestClient; `pypinyin` has zero usage).
- Files: `server/requirements.txt`
- Impact: Bloated install surface; future maintainers may assume pinyin normalization exists somewhere.
- Fix approach: Remove both unless planned for upcoming milestones.

**Deprecated FastAPI `@app.on_event("startup")`:**
- Issue: `server/main.py:53` uses the deprecated `on_event` API; deprecation warnings fire in every test run (see `.baseline/backend-tests.txt`).
- Files: `server/main.py:53-55`
- Impact: Will break on a future FastAPI major upgrade; noisy test output.
- Fix approach: Migrate to the `lifespan` context manager pattern when FastAPI is next touched.

**Custom `.env` loader bypasses standard tooling:**
- Issue: `server/main.py:16-28` hand-rolls `.env` parsing with `os.environ.setdefault` (first-value-wins, no quoting support, no multiline). Comment in `server/config.py` claims loading is "main 入口（--env-file 或手动）负责" which does not match the actual implementation.
- Files: `server/main.py:16-28`, `server/config.py:1-5`
- Impact: Env vars set before startup always win (may or may not be intended); quoted values keep their quotes; subtle divergence if the project later adopts python-dotenv.
- Fix approach: Low priority — document the semantics or adopt `python-dotenv` (one small dep).

**Prototype tree duplicates styles that drift from web app:**
- Issue: `prototype/grail-notion.css` and `web/src/assets/grail-notion.css` have already diverged (verified different). The prototype directory is a large parallel artifact set (dozens of HTML/CSS files under `prototype/`, `prototype/redesign/`, `prototype/final/`).
- Files: `prototype/` (entire tree), `web/src/assets/grail-notion.css`
- Impact: Styling fixes must be applied twice or the prototype silently misleads design review.
- Fix approach: Treat `prototype/` as frozen archive (it is gitignored-adjacent reference material per `.gitignore` comments for similar dirs); do not port CSS by copy-paste — diff before reusing.

## Known Bugs

**`test_question_bank.py` is broken under pytest (fixture 'pid' not found):**
- Symptoms: Running `cd server && python -m pytest` yields `ERROR test_generation / test_idempotent / test_selection` — the file is a `__main__`-style script (functions take `pid`, `mid`, `model` as plain args, run via `if __name__ == "__main__"` block) that pytest misinterprets as parametrized tests.
- Files: `server/test_question_bank.py:72,118,126`
- Trigger: `cd server && python -m pytest` (pytest auto-discovers `test_*.py`)
- Workaround: Run it only as `python test_question_bank.py`; baseline records 13 passed + 3 errors for the suite.
- Fix approach: Rename functions to not start with `test_` (e.g., `check_generation`) and keep the `__main__` runner, or convert to proper pytest with fixtures.

**Broken tests recorded in committed baseline:**
- Symptoms: `.baseline/backend-tests.txt` (committed) documents the 3 fixture errors above as the pre-refactor baseline — meaning any "passing tests" gate must special-case these errors or the gate is already red.
- Files: `.baseline/backend-tests.txt`
- Trigger: Any refactor verification comparing against baseline.
- Workaround: Accept "13 passed, 3 errors" as the reference state.
- Fix approach: Fix the test file (see above) and regenerate the baseline.

**Chat.vue route guard conflict for admin users:**
- Symptoms: `/assessment/session/:session_id` and `/assessment/report/:session_id` have `meta.role: 'candidate'` (`web/src/router/index.js:53,59`). An admin who creates a session (any logged-in user can call `POST /api/assessment/sessions`) gets bounced to their home path by the guard.
- Files: `web/src/router/index.js:50-60`
- Trigger: Admin completes an assessment, `Chat.vue:249` pushes to `/assessment/report/...`, guard redirects to `/admin/positions` — report never renders.
- Workaround: None from UI.
- Fix approach: Change route meta to `requiresAuth: true` (matching `/assessment/positions`), since the backend permits any logged-in user to assess.

**LLM mock mode is the default and silently fakes all AI output:**
- Symptoms: `LLM_PROVIDER` defaults to `"mock"` (`server/config.py:10`). All 8 LLM call types (extract, disambiguate, aggregate_level, question_gen, interviewer, refine, score, report) return hardcoded rule-based outputs. Subjective scores are always 3 in mock (`server/services/scoring.py:27-28`); interviewer decides purely on answer length (`server/services/interview.py:66-80`).
- Files: `server/config.py:10`, `server/services/llm.py:51-52`
- Trigger: Running without `.env` — the default mode.
- Impact: A fully "working" demo produces meaningless assessments; switching to `deepseek` without `LLM_API_KEY` will fail every call after retries.
- Workaround: Set `LLM_PROVIDER=deepseek` and `LLM_API_KEY` in `.env` for real behavior.

## Security Considerations

**JWT secret defaults to a known constant:**
- Risk: If `JWT_SECRET` env var is unset, tokens are signed with `"change-me-in-.env"` (`server/config.py:16`) — anyone can forge admin tokens for any deployment that forgets to configure it.
- Files: `server/config.py:16`
- Current mitigation: `.env.example` documents the var; startup does not warn when the default is in use.
- Recommendations: Refuse to start (or log a loud warning) when `JWT_SECRET == "change-me-in-.env"` and `LLM_PROVIDER != "mock"`; generate a random secret on first boot and persist it.

**No session ownership checks on assessment endpoints (IDOR):**
- Risk: `server/api/assessment.py` endpoints for answer submission (`submit_answer:130`), form submission (`submit_form:210` — checks session exists but does not verify `user_id` matches), scoring (`score_session_endpoint:234`), report request/view (`request_report:260`, `get_report_by_session:272`, `get_report:285`), and feedback (`submit_feedback:297`) accept any `session_id`/`report_id` from any authenticated user. A candidate can enumerate and submit answers to another candidate's session, read anyone's report by ID, or spam feedback on any report.
- Files: `server/api/assessment.py:129-318`
- Current mitigation: Only `require_login` (router-level dependency at line 15); admin/candidate role not distinguished, ownership not compared.
- Recommendations: For each session-scoped endpoint, verify `session.user_id == current_user.user_id` (or allow admin); for report/feedback endpoints verify report → session → owner. This is the highest-priority security fix.

**Admin routes rely solely on role claim in JWT — fine — but role is read from DB each request:**
- Risk: `_current_user` (`server/core/security.py:33-47`) does a DB lookup per request and checks `is_active` — good. No issue here; noted as correct behavior (revocation works). No action needed.
- Files: `server/core/security.py:33-47`

**Password policy mismatch between register and admin-created users:**
- Risk: `POST /api/auth/register` uses `schemas.RegisterRequest` with `min_length=1` for password (`server/schemas.py:11`) — a 1-character password is accepted via the public endpoint. Admin-created users require 6+ chars (`server/api/admin/users.py:28`). Frontend Register.vue validates 6+ client-side only.
- Files: `server/schemas.py:11`, `web/src/views/Register.vue`
- Current mitigation: Frontend validation (bypassable via direct API call).
- Recommendations: Set `min_length=6` on `RegisterRequest.password` to match the admin path.

**CORS allows localhost:5173 only — acceptable for dev, but production serves from same origin; no CORS hardening needed. However `allow_methods=["*"]`/`allow_headers=["*"]` is broader than necessary:**
- Risk: Minor.
- Files: `server/main.py:44-50`
- Current mitigation: Single known origin.
- Recommendations: Optional tightening to explicit methods/headers.

**SQL built with f-strings (parameterized values, safe but fragile pattern):**
- Risk: Several places build SQL by string interpolation of *clauses* (values still bound via `?`): `server/api/admin/trace.py:34-39`, `server/api/admin/dict.py:26-42`, `server/api/admin/feedback.py:16-24`, `server/services/pipeline.py:124-127`, `server/services/report.py:77-80`, `server/services/aggregate.py` (none), `server/api/admin/models.py` diff (none). Currently no injection (only `?` placeholders interpolated), but a future edit that interpolates a value here becomes injectable.
- Files: listed above
- Current mitigation: All user values use bound parameters.
- Recommendations: Keep the pattern but add a comment convention; consider a tiny query-builder helper if this grows.

**`.claude/worktrees/` contains 18 agent worktrees committed to the repo tree:**
- Risk: Directory is gitignored (verified via `git check-ignore`), so not committed, but it holds 18 stale worktrees pinned at an old commit (69c3a29), consuming disk and potentially confusing tooling that walks the tree.
- Files: `.claude/worktrees/` (not committed)
- Current mitigation: Gitignored.
- Recommendations: Periodic `git worktree prune`; not urgent.

**llm_trace stores full prompts/responses with no retention policy:**
- Risk: Prompts contain full JD text and candidate answers (PII in a hiring context). Unbounded growth in `data/app.db`; admin trace viewer exposes full content to any admin (that part is by design).
- Files: `server/services/llm.py:13-21`, `server/db.py:88-100`
- Current mitigation: None (no pruning, no size cap).
- Recommendations: Define retention (e.g., purge raw prompt/response beyond N days, keep metadata), or at minimum document it.

## Performance Bottlenecks

**Blocking LLM calls inside synchronous FastAPI endpoints:**
- Problem: All endpoints are `def` (not `async def`) — FastAPI runs them in the threadpool, so this is actually handled correctly for the most part. However `POST /api/assessment/sessions/{session_id}/answer` (`server/api/assessment.py:130`) performs refine (potential LLM call) + interview decision (LLM call) + multiple sequential DB writes synchronously within one request; with real DeepSeek calls this takes many seconds and the frontend has a 15s axios timeout (`web/src/api/index.js:8`) — but note `submitAnswer` uses raw `fetch` (`web/src/utils/sse.js:21`) which has no timeout, so the UI just waits indefinitely.
- Files: `server/api/assessment.py:129-206`, `web/src/utils/sse.js:17-91`
- Cause: Synchronous LLM round trips in the request path.
- Improvement path: Acceptable for current scale; if real-LLM latency matters, move answer processing to background + poll (pattern already exists for reports).

**SQLite connection per operation, never closed:**
- Problem: `get_conn()` (`server/db.py:218-223`) is called ~73 times across the codebase; only 1 `conn.close()` exists (in tests). Python's GC closes sqlite3 connections when unreferenced, and commits are explicit, so this mostly works — but each abandoned connection holds a file handle until GC runs, and under concurrency the "database is locked" issue has already been worked around twice (comments at `server/api/assessment.py:167-168` and `server/services/scoring.py:108-112`).
- Files: `server/db.py:218-223` (callers everywhere in `server/api/`, `server/services/`)
- Cause: No context-manager helper.
- Improvement path: Add a `@contextmanager def get_conn_ctx()` that commits/closes, or a FastAPI dependency; also set `PRAGMA busy_timeout` to make lock contention degrade gracefully instead of erroring.

**Background tasks run in-process threadpool with no queue or retry:**
- Problem: `BackgroundTasks` is used for JD parse pipeline (`server/api/admin/jds.py:42,64,102`), aggregation (`server/api/admin/models.py:21,126`), question bank generation (`server/api/admin/models.py:105`), report generation (`server/api/assessment.py:268`), and eval runs (`server/api/admin/eval.py:56,72`). If the process restarts mid-task, the work is lost with no recovery (JD stuck in `parsing` forever, eval stuck in `running` forever, question bank never generated with no re-trigger UI except confirm-model re-click).
- Files: listed above
- Cause: In-memory task execution, no persistence of task state.
- Improvement path: At minimum add startup reconciliation: reset `jd_record.status='parsing'` rows older than X to `failed` with a message; same for `eval_results.status='running'`. A real queue (arq/celery) is out of scope for this scale.

**`llm_trace` queries without indexes:**
- Problem: `llm_trace` has only a PK on `trace_id`; the admin trace list filters by `call_type`/`ref_id` and orders by `created_at DESC` (`server/api/admin/trace.py:33-41`), and by-session lookup scans `ref_id IN (...)` (`trace.py:49-65`). With thousands of traces this is a full table scan per admin page view.
- Files: `server/db.py:88-100` (DDL, no indexes), `server/api/admin/trace.py`
- Cause: DDL has no secondary indexes at all on any table.
- Improvement path: `CREATE INDEX IF NOT EXISTS idx_trace_ref ON llm_trace(ref_id, created_at)` and `idx_trace_type ON llm_trace(call_type, created_at)` in `init_db`; audit other hot lookups (question_bank by position_id/std_name, assessment_question by session).

**Frontend bundle size — single 1.1MB vendor chunk:**
- Problem: Production build emits `dist/assets/index-*.js` at 1,117 KB and `Report-*.js` at 1,139 KB (echarts is bundled into the report chunk; element-plus into index) — see `.baseline/web-build.txt` warnings.
- Files: `web/vite.config.js` (no `manualChunks` config), `web/src/views/assessment/Report.vue` (echarts import)
- Cause: No code-splitting configuration; echarts fully bundled.
- Improvement path: `build.rollupOptions.output.manualChunks` to split element-plus/echarts; or lazy `import('echarts')` inside `renderRadar()`. Low priority for an internal tool.

**`_gate_check` reads experience qualification from freeform form payload keys:**
- Problem: Gate pass/fail depends on `form_payload.get(std_name)` matching magic values `("true","yes","是","达标","本科","硕士","博士")` or a `years_of_experience` field (`server/services/aggregation.py:42-63`). Any qualification std_name other than degree-level strings will never pass; the "conservative fail" default silently zeroes gate weight.
- Files: `server/services/aggregation.py:42-63`
- Cause: No schema contract between form submission and gate items.
- Improvement path: Tie gate items to structured form schemas (overlaps with the FormCard endpoint gap above).

## Fragile Areas

**Weight normalization + drift absorption in `_compute_weights`:**
- Files: `server/services/aggregate.py:81-98`
- Why fragile: The round-to-4-decimals plus drift-absorption-into-max-item logic is subtle; any change to rounding or category ratios shifts every weight silently. The admin edit path (`server/api/admin/models.py:59-63`) re-validates Σ within 0.5% tolerance but uses a different tolerance than the generator's exact-Σ logic.
- Safe modification: Add unit tests locking example weight outputs before touching; keep tolerance semantics documented (generator Σ=1 exact vs editor ±0.005).
- Test coverage: Partial — `server/test_m6_backend.py` checks specific computed scores but not `_compute_weights` edge cases (empty categories, single item, all-gate models).

**SQLite CHECK-constraint table-rebuild migrations:**
- Files: `server/db.py:226-275` (`_migrate_llm_trace`, `_migrate_feedback_status`)
- Why fragile: Migrations rebuild tables by string-matching the stored DDL text (`"'report'" in row[0]`). A future CHECK value that is a substring of an existing one (or formatting change) silently skips or re-runs migration. Each new enum value for any CHECK table requires a hand-copied DDL duplicate — already a 3rd copy of llm_trace DDL exists in the file (lines 91-99, 235-246).
- Safe modification: Extract shared DDL constants; add a schema_version table instead of DDL-string sniffing.
- Test coverage: None for the migration functions themselves.

**`decide_next_action` rule guardrails vs LLM output contract:**
- Files: `server/services/interview.py:83-115`
- Why fragile: Correctness depends on the LLM returning `action` in `{followup,next,finish}` and JSON-parsable output; `result.get("action", "next")` defaults silently. The followup cap forces `next` but the reply text still says whatever the LLM produced (can contradict). The `finish` override when `is_last` fires even if LLM said `followup`, silently dropping the followup.
- Safe modification: Any prompt change to `server/services/prompts/interviewer.py` must be regression-tested against `server/test_m5_backend.py` mock expectations.
- Test coverage: Mock only; real-LLM behavior untested.

**`_mock_*` functions parse their own prompts:**
- Files: `server/services/aggregate.py:22-26` (regex `Lv(\d)` on prompt text), `server/services/question_bank.py:32-53` (splits prompt lines by `：`), `server/services/report.py:15-32` (finds lines starting `优势项：`), `server/services/pipeline.py:55-77` (regex on JD text)
- Why fragile: Mock correctness is coupled to the exact wording/line format of the corresponding prompt builders. Any prompt refactor (e.g., changing `优势项：` label) breaks the offline demo silently — flows still run but produce wrong-looking data.
- Safe modification: When editing any file in `server/services/prompts/`, grep for its consumers in `_mock_*` functions.
- Test coverage: M5/M6/M7 tests exercise the mocks, so breakage shows up as test failures at least.

**Report.vue `itemReason` reverse-lookup by std_name:**
- Files: `web/src/views/assessment/Report.vue:313-319`
- Why fragile: Question reviews don't carry `item_id` (documented as a 07-doc contract gap in the comment), so the detail table's reason column does `reviews.find(q => q.std_name === item.std_name)` — a mismatch or duplicate std_name across categories shows the wrong reason or none.
- Safe modification: Include `item_id` in `_load_question_reviews` output (`server/services/report.py:35-69` already joins question_score which has item_id — trivial to add).
- Test coverage: None for this rendering detail.

**`normalize_title` single-pass suffix stripping:**
- Files: `server/services/assign.py:8-18`
- Why fragile: Strips one suffix per call; "高级后端开发工程师" → "高级后端" (removes 开发工程师) but "后端开发工程师（急招）" removes only （急招） and leaves 工程师 — matching depends on suffix list order and single application. Position dedup (the core of JD assignment) varies with these rules.
- Safe modification: Extend `_SUFFIXES`/loop carefully; add table-driven tests.
- Test coverage: None directly (only exercised via pipeline tests).

**Chat.vue `displayContent`/`extractFormId` depend on emoji marker format:**
- Files: `web/src/views/assessment/Chat.vue:155-162`
- Why fragile: Regex `/📎\[form:([^\]]+)\]/` couples the UI to a marker convention that the backend never actually emits (see FormCard gap). Dead-ish code that will surprise whoever wires forms up.
- Safe modification: When implementing the form backend, keep the marker format or replace with a structured message field.
- Test coverage: None.

## Scaling Limits

**SQLite single-writer:**
- Current capacity: Fine for single-instance demo / small team (tens of concurrent users at most, given per-request connections and write-lock contention already observed as "database is locked" — worked around at `server/api/assessment.py:167-168` and `server/services/scoring.py:108-112`).
- Limit: Any two concurrent write transactions collide; `get_conn()` sets no `busy_timeout`, so collisions raise immediately instead of waiting.
- Scaling path: First step: `PRAGMA busy_timeout=5000` + WAL mode (`PRAGMA journal_mode=WAL`) in `get_conn()`. Second: single-process constraint is fine for course-project scale; Postgres migration only if multi-process deployment (multiple uvicorn workers would break background-task and lock assumptions today — everything assumes one process).

**No pagination on admin lists:**
- Current capacity: `GET /api/admin/users`, `GET /api/admin/positions`, `GET /api/admin/feedback/list`, dict list return full tables; trace list has limit/offset (50 default) but `GET /api/admin/trace/by-session/{id}` is unbounded.
- Limit: Thousands of rows → slow responses and heavy JSON payloads.
- Scaling path: Add limit/offset params consistent with the trace list pattern.

**question_bank generation is serial per item with LLM per difficulty tier:**
- Current capacity: A confirmed model with 15 items triggers ~15-30 sequential LLM calls in one background task.
- Limit: With real LLM latency (~2-5s each), confirming a model takes 1-2.5 minutes during which the position has no assessable questions (candidate hitting it mid-generation gets fewer or zero questions — `select_questions_for_session` silently returns a short/empty list; `create_session` does not error on zero questions).
- Scaling path: Parallelize with a bounded pool; or make `create_session` fail gracefully when question count < minimum.

**eval_results `running` rows have no timeout/reconciliation:**
- Current capacity: Polling UI (TestCenter) stops after any error but backend row stays `running` forever if process died mid-run.
- Limit: Stale rows accumulate; history list shows perpetual running tasks.
- Scaling path: Timestamp-based reconciliation on `GET /history` (mark `running` older than X as failed).

## Dependencies at Risk

**bcrypt version pin:**
- Risk: `requirements.txt` pins `bcrypt<4.1` with a comment that passlib 1.7.4 crashes with bcrypt 5.x. passlib is effectively unmaintained (last release 2020); this pin will keep colliding with newer environments.
- Impact: Fresh installs on Python 3.13+ environments may pick bcrypt versions that break `hash_password` at runtime (hashing works, but the incompatibility manifests as `AttributeError` in some passlib/bcrypt combos).
- Migration plan: Move to `bcrypt` directly (its API is simple: `bcrypt.hashpw`/`checkpw`), drop passlib — touches `server/core/security.py`, `scripts/seed_admin.py`, and test seeders (`server/test_m7_backend.py:34-36`).

**No lockfiles for Python:**
- Risk: `requirements.txt` uses floor-only constraints (`>=`); no `requirements.lock` / `uv.lock` / `pip-tools` output. Builds are not reproducible; the bcrypt pin is the only ceiling anywhere.
- Impact: "Works on my machine" drift; the committed `.baseline` test results may not reproduce later.
- Migration plan: Generate a lock (e.g., `pip freeze > requirements.lock` from the working env, or adopt `uv`).

**Vite 5 / Element Plus / echarts majors:**
- Risk: Unpinned caret ranges in `web/package.json` (e.g., `"echarts": "^6.1.0"`, `"element-plus": "^2.8.4"`); `package-lock.json` exists so builds are reproducible, but `npm update` can jump minors/majors.
- Impact: Element Plus and echarts both have breaking-change history across majors.
- Migration plan: Keep relying on the lockfile; run `npm audit`/`npm outdated` in a maintenance pass.

## Missing Critical Features

**Session abandonment flow:**
- Problem: `assessment_session.status` CHECK includes `'abandoned'` (`server/db.py:110`) but no code path ever sets it. Sessions abandoned mid-way stay `in_progress` forever; candidates see them as resumable indefinitely.
- Blocks: Any stale-session analytics or cleanup; the state machine is defined but incomplete.

**Question bank re-generation after model edit:**
- Problem: `PUT /api/admin/models/{model_id}` (edit draft) and confirm trigger `generate_question_bank` only on confirm; but if an admin edits and re-confirms a *new version* of the model, the idempotency check in `server/services/question_bank.py:89-101` skips generation for any std_name that already has an active question — including ones whose required_level changed. Old questions tied to outdated levels persist.
- Blocks: Model version evolution producing assessments aligned to the current confirmed model.

**Diff review flow (P4) has no mutation path:**
- Problem: `GET /api/admin/models/{new_id}/diff` exists (`server/api/admin/models.py:143-177`) but the docstring at `run_aggregate` (`server/services/aggregate.py:104`) says "diff 审阅流属 M3" and `confirm_model` blocks editing confirmed models — there is no endpoint to accept/merge a diff between confirmed versions; VersionHistory.vue only lists.
- Blocks: The version-confirmation workflow completing as designed (currently an admin must manually re-edit a draft to match).

**Candidate has no way to view past sessions/reports:**
- Problem: No `GET /api/assessment/sessions` (list mine) or reports list; the only entry to a report is in-app navigation right after finishing. Direct URL works but nothing links a returning user back.
- Blocks: Candidate-side history (the report page is otherwise orphaned after leaving).

**No CI pipeline:**
- Problem: No `.github/workflows` or any CI config; tests run only manually (and one file is broken under pytest, see Known Bugs).
- Blocks: Automated regression checking on commit/PR.

## Test Coverage Gaps

**Auth security edge cases:**
- What's not tested: Expired tokens, tampered tokens, inactive users hitting protected endpoints, candidate hitting admin routes (403 path), session ownership violations (the IDOR issue above — tests currently prove the vulnerable behavior works, not that it's prevented).
- Files: `server/test_m5_backend.py`, `server/test_m7_backend.py` (only happy-path auth)
- Risk: The most security-sensitive logic (ownership) has zero negative tests.
- Priority: High

**`clean_jd` and `normalize_title` rule engines:**
- What's not tested: Noise-header/state-machine edge cases (header with content on same line, multiple noise blocks, empty input), suffix combinations in title normalization.
- Files: `server/services/pipeline.py:24-50`, `server/services/assign.py:8-18`
- Risk: JD cleaning regressions silently change extraction quality.
- Priority: Medium

**`_gate_check` and gate scoring:**
- What's not tested: M6 tests seed form payloads directly; the actual value-matching semantics (`("true","yes","是","本科",...)`), the missing-payload path, and mixed-type years fields have no dedicated tests.
- Files: `server/services/aggregation.py:42-63`
- Risk: Gate logic is high-consequence (zeroes out weights) and brittle.
- Priority: High

**`run_parse_pipeline` failure/retry paths:**
- What's not tested: LLM extract failure → jd_record.status='failed' + error_msg; auto-aggregate failure being swallowed; reparse endpoint flow.
- Files: `server/services/pipeline.py:184-236`
- Risk: Parse failures currently only visible via DB inspection.
- Priority: Medium

**Frontend has zero tests:**
- What's not tested: All of `web/src/` — no unit, component, or E2E tests; no test runner in `web/package.json` (only dev/build/preview scripts).
- Files: `web/package.json`, entire `web/src/`
- Risk: UI regressions (like the Chat.vue contract drift documented above) ship silently.
- Priority: Medium (acknowledged scope decision for a prototype-stage project, but the contract drift proves the cost is real)

**`eval/` suites only meaningfully run in mock mode:**
- What's not tested: Real-LLM consistency (the actual thing the eval is designed to measure); virtual candidates rely on fixture keyword answers matching `answer_key` regexes.
- Files: `eval/consistency_test.py`, `eval/virtual_candidates.py`
- Risk: The test-center feature demonstrates plumbing, not measurement.
- Priority: Low (by design for offline demo)

---

*Concerns audit: 2026-09-02*
