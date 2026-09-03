<!-- refreshed: 2026-09-02 -->
# Architecture

**Analysis Date:** 2026-09-02

**Project:** AI 驱动的岗位胜任力测评与人才画像系统 (AI-driven competency assessment & talent profiling)
**Design SSOT:** `design/final-design/总设计文档.md` (v2.0) — all code is being refactored toward this contract (see `research/gsd-core-operating-guide.md`)

## System Overview

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                    Browser (Vue 3 SPA, Element Plus)                      │
│  管理端 admin views            测评端 assessment views                     │
│  `web/src/views/admin/`       `web/src/views/assessment/`                  │
│  `web/src/views/Login.vue`   `web/src/views/Register.vue`                  │
├───────────────┬──────────────────────────────┬────────────────────────────┤
│  Pinia store  │  axios api client            │  fetch SSE adapter         │
│  `web/src/stores/auth.js`  `web/src/api/index.js`  `web/src/utils/sse.js`   │
└───────┬───────┴───────────────┬──────────────┴─────────────┬──────────────┘
        │  /api (Vite dev proxy → :8000, or FastAPI static mount in prod)
        ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     FastAPI app (single process)                          │
│  Entry: `server/main.py`  (uvicorn server.main:app --port 8000)            │
├──────────────────────────────────────────────────────────────────────────┤
│  API routers                                                              │
│  `server/api/auth.py`         /api/auth/*        (public)                  │
│  `server/api/assessment.py`   /api/assessment/*  (require_login)          │
│  `server/api/admin/*.py`      /api/admin/*       (require_admin)          │
├──────────────────────────────────────────────────────────────────────────┤
│  Services (business logic + LLM orchestration)                            │
│  `server/services/pipeline.py`      JD parse chain (module 1)             │
│  `server/services/aggregate.py`      model aggregation (module 1)         │
│  `server/services/question_bank.py`  bank generation (module 2)           │
│  `server/services/question_selection.py` per-session selection            │
│  `server/services/interview.py`      interviewer decision (module 2)      │
│  `server/services/refine.py`         long-input refinement                │
│  `server/services/scoring.py`        final per-question scoring           │
│  `server/services/aggregation.py`    session score aggregation            │
│  `server/services/report.py`         five-section report (module 3)       │
│  `server/services/llm.py`            LLM gateway (trace/retry/mock)       │
│  `server/services/prompts/*.py`      prompt templates                     │
├──────────────────────────────────────────────────────────────────────────┤
│  Cross-cutting                                                            │
│  `server/core/security.py`   JWT + bcrypt + role dependencies              │
│  `server/schemas.py`         Pydantic v2 request/LLM-output models          │
│  `server/config.py`          env-driven constants                          │
│  `server/db.py`              sqlite3 connections + DDL (18 tables)          │
└───────────────────────────────────┬──────────────────────────────────────┘
                                    ▼
                    ┌───────────────────────────────┐
                    │  SQLite file: data/app.db     │
                    │  (DB_PATH env, raw SQL,      │
                    │   no ORM, per-call conns)    │
                    └───────────────────────────────┘
        External (optional): DeepSeek API (OpenAI-compatible), only when
        LLM_PROVIDER != "mock"; `server/services/llm.py` via `openai` SDK
```

Supporting subsystems outside the request path:
- `eval/` — consistency & virtual-candidate test harness, invoked both by CLI and by `server/api/admin/eval.py` (which sys.path-hacks the repo root to import it)
- `scripts/seed_admin.py` — first-admin bootstrap (`python -m scripts.seed_admin`)
- `prototype/` — static HTML design prototypes (not part of the running app; visual reference for the Vue rebuild)

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| App entry / wiring | .env load, CORS (localhost:5173), startup init_db, router registration, static mount of `web/dist` | `server/main.py` |
| Auth endpoints | register (candidate only), login, me | `server/api/auth.py` |
| Assessment endpoints | sessions, answers, forms, scoring, reports, feedback | `server/api/assessment.py` |
| Admin JD endpoints | JD import (paste/JSONL), reparse, JD detail | `server/api/admin/jds.py` |
| Admin model endpoints | aggregate trigger, model get/edit/confirm, stalled retry, versions, diff | `server/api/admin/models.py` |
| Admin position endpoints | todos stats, position review, orphan JDs, JD reassign | `server/api/admin/positions.py` |
| Admin dict endpoints | competency dictionary CRUD/merge/disable | `server/api/admin/dict.py` |
| Admin user endpoints | user list/create/enable-disable/reset password | `server/api/admin/users.py` |
| Admin trace endpoints | llm_trace search/detail | `server/api/admin/trace.py` |
| Admin feedback endpoints | candidate feedback review/bad-case | `server/api/admin/feedback.py` |
| Admin eval endpoints | trigger consistency/virtual-candidate tests, poll results | `server/api/admin/eval.py` |
| JD parse pipeline | clean → LLM#1 extract → position assign → LLM#2 disambiguate → persist | `server/services/pipeline.py` |
| Model aggregation | frequency stats → importance thresholds → LLM#3 level adjudication → code-computed weights | `server/services/aggregate.py` |
| Position matching | job title normalization + alias match | `server/services/assign.py` |
| LLM gateway | JSON-mode call, retry ×2, llm_trace persistence, mock fallback | `server/services/llm.py` |
| Question bank gen | per-item difficulty plan → LLM question generation → idempotent insert | `server/services/question_bank.py` |
| Question selection | per-session quota-based selection with chains | `server/services/question_selection.py` |
| Interviewer decision | followup/next/finish decision with rule guardrails | `server/services/interview.py` |
| Input refine | SHA256 archive of raw long answers + LLM refinement | `server/services/refine.py` |
| Scoring | objective regex scoring + subjective LLM scoring, live/final blend | `server/services/scoring.py` |
| Score aggregation | item scores, gate checks (form payload), total, strengths/weaknesses | `server/services/aggregation.py` |
| Report generation | five-section report JSON (radar data, details, LLM strengths/weaknesses text) | `server/services/report.py` |
| Security | JWT HS256 sign/verify, bcrypt hash/verify, role dependencies | `server/core/security.py` |
| DB | 18-table DDL, `get_conn()`, inline table migrations | `server/db.py` |
| Frontend bootstrap | Pinia + Router + Element Plus (zh-CN locale) | `web/src/main.js` |
| Frontend routing | role-guarded routes, login redirect | `web/src/router/index.js` |
| Auth store | token/user persistence in localStorage, fetchMe restore | `web/src/stores/auth.js` |
| API client | axios instance, Bearer injection, 401 auto-logout; assessment/admin method collections | `web/src/api/index.js` |
| Answer transport | fetch-based submit-answer; adapts to SSE stream OR plain JSON response | `web/src/utils/sse.js` |
| Eval harness | scoring consistency test, virtual-candidate tier test | `eval/consistency_test.py`, `eval/virtual_candidates.py` |

## Pattern Overview

**Overall:** Layered monolith (router → service → raw SQL) with a "code computes, LLM only observes" doctrine. Frontend is a classic Vue 3 SPA.

**Key Characteristics:**
- **LLM/计算分离 (LLM never touches numbers):** all arithmetic (weights, scores, quotas) is computed in Python code; LLM calls only produce structured JSON observations. Enforced everywhere (`server/services/aggregate.py` `_compute_weights`, `server/services/aggregation.py`, `server/services/question_selection.py`).
- **Single LLM gateway:** every LLM call goes through `call_llm_json(call_type, ref_id, system, user, mock_fn)` in `server/services/llm.py` — retry, trace persistence, and mock fallback in one place. Call types: `extract`, `disambiguate`, `aggregate_level`, `question_gen`, `interviewer`, `refine`, `score`, `report`.
- **Offline-first mock mode:** `LLM_PROVIDER=mock` (default in `server/config.py`) substitutes deterministic `_mock_*` functions per call site so the entire flow runs with no network. Every service defines its own mock next to the real call.
- **Async = BackgroundTasks + polling:** long work (JD parse, aggregation, question bank gen, report gen, eval runs) is scheduled via FastAPI `BackgroundTasks` and the frontend polls GET endpoints for results. No queue, no persistence across restarts (accepted per SSOT §5).
- **Rule guardrails over LLM output:** e.g., `server/services/interview.py` forces `finish` on last question and caps followups at `FOLLOWUP_MAX` regardless of what the LLM returns.
- **JSON-blob persistence:** complex documents stored as JSON text columns (`model_json`, `report_json`, `payload_json`, `*_items_json`, `evidence_json`) alongside relational rows. Human editing replaces whole JSON.
- **No ORM:** hand-written SQL with parameterized queries via `conn.execute(...)`; every handler opens its own connection through `get_conn()` and must `conn.commit()`.

## Layers

**API layer (routers):**
- Purpose: HTTP contract, validation (light), auth dependency wiring, status codes
- Location: `server/api/`
- Contains: one `APIRouter` per resource; admin routers under `server/api/admin/`
- Depends on: `server/core/security.py` (auth deps), `server/db.py`, `server/services/*`
- Used by: frontend axios calls and `eval/` TestClient
- Convention: router-level `dependencies=[Depends(require_admin)]` or `Depends(require_login)`; handlers return plain dicts (not Pydantic response models, except auth)

**Service layer:**
- Purpose: all business logic, LLM orchestration, state machine transitions, persistence
- Location: `server/services/`
- Contains: pipeline/aggregate (module 1), question bank/selection/interview/refine/scoring/aggregation/report (modules 2–3), shared `new_id`/`now_iso` helpers in `pipeline.py`
- Depends on: `server/db.py`, `server/config.py`, `server/schemas.py` (LLM output validation), `server/services/prompts/*`
- Used by: API layer, background tasks, `eval/` harness, tests

**Prompt layer:**
- Purpose: LLM system prompts and user-prompt builders, versioned in docstrings
- Location: `server/services/prompts/` (one module per call type: `extract.py`, `disambiguate.py`, `aggregate_level.py`, `question_gen.py`, `interviewer.py`, `refine.py`, `score.py`, `report.py`)
- Depends on: nothing (pure constants/functions)
- Used by: services only

**Core layer:**
- Purpose: auth primitives shared by all routers
- Location: `server/core/security.py`
- Contains: `hash_password`/`verify_password` (passlib bcrypt), `create_token`/`_current_user` (python-jose JWT), `require_login`/`require_admin` FastAPI dependencies

**Data layer:**
- Purpose: schema + connections + migrations
- Location: `server/db.py`, `server/schemas.py` (Pydantic), `server/config.py`
- Contains: `_DDL` (18 tables), `get_conn()` (Row factory + `PRAGMA foreign_keys=ON`), `init_db()` with idempotent CREATE IF NOT EXISTS + `_migrate_llm_trace`/`_migrate_feedback_status` table-rebuild migrations
- Note: migrations are hand-rolled "rebuild table if CHECK constraint outdated" — no schema_version table yet (SSOT §28 item 6)

**Frontend layers:**
- Views (`web/src/views/`) — page components, call api collections directly
- Components (`web/src/components/`) — shared: `AdminNav.vue`, `CandidateNav.vue`, `FormCard.vue` (schema-driven form), `ItemTable.vue`
- Store (`web/src/stores/auth.js`) — only auth; no other Pinia stores
- Transport (`web/src/api/index.js`, `web/src/utils/sse.js`) — all backend calls funnel through these two files

## Data Flow

### Primary Flow 1: JD import → confirmed model (module 1)

1. `POST /api/admin/jds/import` (`server/api/admin/jds.py:38`) — inserts `jd_record` row with status `imported`, schedules `run_parse_pipeline` via BackgroundTasks, returns immediately
2. `run_parse_pipeline` (`server/services/pipeline.py:184`) — sets status `parsing`; each stage persists its artifact before the next (`cleaned_text` → `raw_items_json` → `position_id` → `std_items_json`); on exception sets `failed` + `error_msg`
3. `clean_jd` (`server/services/pipeline.py:24`) — pure-rule noise/requirement section filtering; short result sets `low_confidence=1`
4. `extract_items` → `call_llm_json("extract", ...)` — LLM#1; output validated against `ExtractResult` (`server/schemas.py:45`)
5. `assign_position` (`server/services/pipeline.py:94`) — normalized title → exact match → alias table → else create `pending_review` position
6. `disambiguate_items` (`server/services/pipeline.py:135`) — LLM#2 merges (skipped if dictionary empty); new std names passively inserted into `competency_dict` with `created_by='llm_pending'`
7. Auto-aggregate hook (`server/services/pipeline.py:229`) — if position `active`, runs `run_aggregate` (`server/services/aggregate.py`) in background; failure silent
8. `run_aggregate` — groups items across parsed JDs by `(std_name, category)`, computes r/req frequencies → importance thresholds → LLM#3 level adjudication only on conflict (failure → model `stalled`) → `_compute_weights` (category ratio × importance coef, Σ=1 with largest-item drift absorption) → inserts `competency_model` (draft/stalled) + `competency_item` rows
9. Human review: `GET /api/admin/positions/{id}/model` → `PUT /api/admin/models/{id}` (whole-JSON replace, Σ=100% server-side check, rebuilds `competency_item`) → `POST /api/admin/models/{id}/confirm` (`server/api/admin/models.py:86`) — sets `confirmed`, records confirm by/at, background-triggers `generate_question_bank` (`server/services/question_bank.py`)

### Primary Flow 2: candidate assessment session (modules 2–3)

1. `GET /api/assessment/positions` (`server/api/assessment.py:19`) — only positions with `active` status + a `confirmed` model (latest version deduped)
2. `POST /api/assessment/sessions` (`server/api/assessment.py:59`) — anchors `model_id`/`model_version`, runs `select_questions_for_session` (`server/services/question_selection.py:58`) — category quotas (hard 6 / soft 2 / exp 2), required-first, weight-desc, easy→hard chains via `chain_key`/`chain_seq` — inserts `assessment_question` rows with seq
3. `POST /api/assessment/sessions/{id}/answer` (`server/api/assessment.py:129`) — the hot path:
   - `refine_user_input` (`server/services/refine.py:25`) — if approx tokens > `REFINE_MIN_TOKENS` (default 500), SHA256-archives original into `context_raw` and stores refined text + `raw_hash`
   - user message inserted, `asked_at` set, **connection committed before LLM call** (comment at `server/api/assessment.py:167`: llm_trace writes on a second connection; holding a write transaction causes "database is locked")
   - `decide_next_action` (`server/services/interview.py:83`) — LLM `interviewer` call with full history; rule guardrails then cap followups / force finish; subjective questions get `score_live`
   - assistant message inserted with action/reason/score_live (audit-first)
   - `answered_at` set on next/finish; session `completed` + `ended_at` on finish
   - Returns single JSON `{action, reply, question_id, next_question_id, score_live}` (no SSE yet — frontend `streamAnswer` adapts, see `web/src/utils/sse.js`)
4. `POST /api/assessment/sessions/{id}/forms/submit` — raw payload into `form_submission` (gate checks consume this later)
5. `POST /api/assessment/sessions/{id}/score` → `score_session` (`server/services/scoring.py:107`) — per answered question: objective = regex/substring match against `answer_key` (5/1); subjective = LLM `score` call on raw text recovered via `raw_hash`; final = `round(score_live*0.5 + score_final*0.5)`; computes all rows in memory first, then deletes+inserts `question_score` in one transaction (same lock-avoidance pattern)
6. `POST /api/assessment/sessions/{id}/report` (202) → background `generate_report` (`server/services/report.py:89`) — `aggregate_session_scores` (`server/services/aggregation.py:66`) computes item scores (gate items binary via form payload), total = Σ(weight × actual/5) × 100, top-3 strengths/weaknesses; radar data for ECharts; LLM `report` call for strengths/weaknesses text bound to evidence quotes; whole JSON into `report` table (idempotent: deletes prior rows for session)
7. Frontend `Report.vue` polls `GET /api/assessment/reports/by-session/{session_id}` every 3s (`web/src/views/assessment/Report.vue:402`)
8. Candidate objection: `POST /api/assessment/reports/{report_id}/feedback` → `feedback` table (status `pending`), reviewed in admin Test Center

### Admin supporting flow

- Todos dashboard: `GET /api/admin/todos` (`server/api/admin/positions.py:11`) — pending positions / stalled models / orphan JD counts
- Test center: `POST /api/admin/eval/consistency` and `/virtual-candidates` (`server/api/admin/eval.py`) — sys.path-insert repo root, import `eval/*.py`, run in background, persist to `eval_results`, poll via `GET /results/{task_id}`

**State Management (frontend):**
- Auth only: Pinia store persisted to localStorage (`token`, `user`); router guard reads `auth.isLoggedIn` / `auth.user.role` and redirects (`web/src/router/index.js:72`)
- All other state is per-view refs/reactives; no shared domain stores
- 401 responses globally intercepted in `web/src/api/index.js:21` — clears localStorage and hard-redirects to `/login`

## Key Abstractions

**LLM gateway `call_llm_json`:**
- Purpose: the only way to reach an LLM; unifies tracing, retry, JSON mode, and mock
- Location: `server/services/llm.py:41`
- Pattern: `call_llm_json(call_type, ref_id, system_prompt, user_prompt, mock_fn)`; every attempt (success or failure) recorded in `llm_trace`; `LLM_PROVIDER=mock` calls `mock_fn` instead of the network; real mode uses `openai` SDK with `response_format={"type":"json_object"}`, `temperature=0`
- All 8 call sites: `pipeline.py` (extract, disambiguate), `aggregate.py` (aggregate_level), `question_bank.py` (question_gen), `interview.py` (interviewer), `refine.py` (refine), `scoring.py` (score), `report.py` (report)

**Status machines (code-driven, persisted as TEXT columns with CHECK constraints):**
- JD: `imported → parsing → parsed | failed` (`server/db.py:43`, transitions in `server/services/pipeline.py:184`)
- Model: `draft | stalled | confirmed` — confirmed is terminal; stalled models must be retried or edited back to draft (`server/api/admin/models.py`)
- Session: `in_progress → completed | abandoned` (`server/db.py:110`)

**ID/time helpers:**
- `new_id(prefix)` → `f"{prefix}_{uuid4().hex[:12]}"` and `now_iso()` → UTC ISO string, both in `server/services/pipeline.py:14-19`; imported by nearly every other module. Prefixes: `u_`, `pos_`, `jd_`, `cm_`, `c_`, `sess_`, `q_`, `aq_`, `msg_`, `raw_`, `form_`, `qs_`, `rpt_`, `fb_`, `ev_`, `t_`

**Raw-answer immutability:**
- Original long answers archived by SHA256 in `context_raw`; scoring and report review recover originals via `raw_hash` (`server/services/scoring.py:31`, `server/services/report.py:35`)

**Mock-mode local convention:**
- Every service defines `_mock_<calltype>(system_prompt, user_prompt) -> dict` adjacent to the real call; mocks parse the user prompt text to produce deterministic outputs. When adding an LLM call, provide a mock with this signature or the mock provider returns `{}`.

**Frontend dual-protocol answer transport:**
- `streamAnswer` (`web/src/utils/sse.js:17`) detects `Content-Type: application/json` (current backend) vs `text/event-stream` (target SSE) and normalizes both into `{onDecision, onReply, onDone, onError}` callbacks; returns `abort()` for component unmount

**Schema-driven form card:**
- `web/src/components/FormCard.vue` renders text/number/textarea/select/date fields from a fetched schema; note the fetch target `GET /api/assessment/forms/{form_id}` has no backend route (see Anti-Patterns)

## Entry Points

**Backend server:**
- Location: `server/main.py`
- Triggers: `uvicorn server.main:app --reload --port 8000` (dev, from repo root); production serves `web/dist` statically at `/`
- Responsibilities: env load → router registration → `init_db()` on startup → health check at `/api/health`

**Frontend dev:**
- Location: `web/src/main.js` via `npm run dev` in `web/` (Vite on :5173, proxies `/api` → localhost:8000 per `web/vite.config.js`)

**CLI tools:**
- `python -m scripts.seed_admin` — creates first admin from `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars
- `python eval/consistency_test.py --session-id <sid> --runs 3`
- `python eval/virtual_candidates.py --position-id <pid>`

**Tests:**
- `cd server && python -m pytest test_m5_backend.py -v` (pytest), plus standalone runners `server/test_m6_backend.py`, `server/test_m7_backend.py` (check/pass counters)
- Tests set `DB_PATH`/`LLM_PROVIDER`/`JWT_SECRET` env **before** importing `server.*` (config reads env at import time)

## Architectural Constraints

- **Threading:** single-process uvicorn, async endpoints only where file upload is involved; background work runs in-process via `BackgroundTasks` (Starlette threadpool). No job persistence — restart loses in-flight tasks (accepted by SSOT §5 for this demo phase).
- **SQLite single-writer:** every `get_conn()` is a fresh connection; concurrent write + a second connection writing trace rows raises `database is locked`. Mitigated by two conventions you MUST follow when adding code that calls LLM/services during a write:
  - commit the outer connection before invoking anything that opens its own connection (`server/api/assessment.py:167-168`)
  - compute everything (including LLM calls) in memory first, write in one transaction at the end (`server/services/scoring.py:107-154`)
- **Config read at import time:** `server/config.py` evaluates `os.environ.get(...)` at module import; env must be set before any `server.*` import (this is why `server/main.py` loads `.env` before importing `server.db`, and why tests set env first).
- **Global state:** module-level constants only (`_DDL` in `server/db.py`, prompt strings, `CATEGORY_QUOTA`); no mutable global singletons.
- **Circular imports (managed):** `server/services/llm.py` imports `now_iso, new_id` from `pipeline.py` while `pipeline.py`, `aggregate.py`, and others lazily import `call_llm_json` from `llm.py` inside functions (e.g. `server/services/pipeline.py:81`). When adding imports between services, defer them into function bodies if a cycle appears.
- **Cross-tree import hack:** `server/api/admin/eval.py:14` inserts the repo root into `sys.path` to import `eval/` (which lives outside the `server` package). Same hack appears in `eval/*.py` and `scripts/seed_admin.py` to import `server.*`. Keep new top-level runnable code following this pattern or place shared code in `server/`.
- **Declarative response models unused:** handlers return raw dicts; only `schemas.TokenResponse` and the two eval request bodies use Pydantic at the boundary. LLM outputs ARE validated via `server/schemas.py` (`ExtractResult`, `DisambiguateResult`, `AggregateLevelResult`).
- **Ownership checks pending (known gap, SSOT §7 P0):** `server/api/assessment.py` endpoints check session existence but not `user_id == current_user` — a candidate can currently read/score/submit-feedback on another candidate's session. Treat as debt, not convention; new endpoints must add `WHERE user_id=?` checks.

## Anti-Patterns

### Blocking SQLite transactions across LLM calls

**What happens:** holding an open write transaction on `conn` while `call_llm_json` writes `llm_trace` on a *new* connection → `sqlite3.OperationalError: database is locked`.
**Why it's wrong:** SQLite allows one writer; nested independent connections deadlock.
**Do this instead:** commit before the LLM call (`server/api/assessment.py:167`) or buffer all writes in memory and commit once after all LLM work (`server/services/scoring.py`). Copy one of these two patterns whenever mixing DB writes with LLM calls.

### Letting the LLM decide control flow or numbers

**What happens:** prompts like `INTERVIEWER_SYSTEM` ask the model to choose followup/next/finish; scoring prompts ask for a score.
**Why it's wrong:** SSOT constraint ①/④ — LLM output is an *observation*; arithmetic and state transitions belong to code.
**Do this instead:** follow `server/services/interview.py:100-107` — take the LLM's structured suggestion, then apply rule guardrails (followup cap, forced finish). Weights/scores/totals are always computed in Python (`server/services/aggregate.py::_compute_weights`, `server/services/aggregation.py`).

### Skipping the LLM gateway

**What happens:** calling `OpenAI` directly or building prompts inline in a router.
**Why it's wrong:** bypasses `llm_trace` audit trail, retry, and mock mode — breaking offline demo and auditability (SSOT constraint ③).
**Do this instead:** route every call through `call_llm_json` in `server/services/llm.py`, with prompt constants in `server/services/prompts/<calltype>.py` and output validated against a model in `server/schemas.py`. Register new `call_type` values in the `llm_trace` CHECK constraint (`server/db.py:91`) and in `_migrate_llm_trace`.

### Calling nonexistent endpoints from the frontend

**What happens:** `web/src/components/FormCard.vue` fetches `assessment.getForm(formId)` → `GET /api/assessment/forms/{form_id}`, but no such route exists in `server/api/assessment.py` (only `POST .../forms/submit`); `web/src/api/index.js` also declares `admin.trace.getBySession` matching a real route, but form GET does not exist.
**Why it's wrong:** the form card renders only after a form_id is embedded in an assistant reply; the GET 404s and the card shows a load error.
**Do this instead:** when adding frontend api methods, verify the backend route exists (grep `@router.` in `server/api/`); if a route is genuinely planned, mark it clearly as pending rather than wiring it into components.

### Whole-JSON model edits without field-level validation

**What happens:** `PUT /api/admin/models/{id}` (`server/api/admin/models.py:42`) accepts `body: dict`, checks only that `items` is a non-empty list and Σweight ≈ 1.
**Why it's wrong:** NaN/illegal categories/duplicate std_names pass server-side and corrupt `competency_item` on rebuild (SSOT §28 item 4 flags exactly this).
**Do this instead:** for new admin edit endpoints, validate per-field types/ranges/enums explicitly or via Pydantic before writing; keep the Σ=100% server-side check.

## Error Handling

**Strategy:** optimistic per-stage persistence with explicit status columns; failures are recorded, not raised to users where avoidable.

**Patterns:**
- JD pipeline catches all exceptions per JD, marks `jd_record.status='failed', error_msg=<msg>`, continues other JDs (`server/services/pipeline.py:219`)
- Aggregation LLM#3 failure → model `stalled` with `stall_reason` embedded in `model_json` for the todos dashboard (`server/services/aggregate.py`)
- LLM gateway retries `LLM_RETRY` (2) times with trace per attempt, then raises `RuntimeError` (`server/services/llm.py:48`)
- Report background task swallows exceptions — frontend polling infers failure from persistent 404 (`server/api/assessment.py:251`)
- HTTP semantics: 404 not-found, 409 conflict (already answered/confirmed), 422 missing fields, 401/403 from `server/core/security.py`; Chinese-language `detail` messages consumed directly by the frontend (`web/src/utils/sse.js:36` reads `body.detail`)
- Frontend: global 401 interceptor; per-view `ElMessage.error` for others; polling with `MAX_POLLS` timeout in `Report.vue`

## Cross-Cutting Concerns

**Logging:** none (no logger anywhere); observability is DB-based — `llm_trace` for LLM calls, status/`error_msg` columns for pipeline state. Do not add console/print logging as a substitute for trace persistence.
**Validation:** request bodies are mostly raw `dict` checked with `body.get(...)` + manual 422s; Pydantic used for auth requests and LLM output schemas (`server/schemas.py`). New LLM outputs should get a Pydantic model there.
**Authentication:** JWT HS256 Bearer; `require_login` (any role) / `require_admin` dependencies on routers (`server/core/security.py:50-57`); registration hardcodes `role='candidate'`; frontend mirrors with route meta `role`/`requiresAuth` (`web/src/router/index.js`). Backend role checks are authoritative; frontend guard is UX only — but resource-level ownership is not yet enforced (see constraints).
**Secrets:** `.env` at repo root loaded by hand-rolled parser in `server/main.py:16` (no python-dotenv); template at `.env.example` (existence noted only, contents not read).

---

*Architecture analysis: 2026-09-02*
