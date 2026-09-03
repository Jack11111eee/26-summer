# External Integrations

**Analysis Date:** 2026-09-02

## APIs & External Services

**LLM (the single external API dependency of this system):**
- DeepSeek Chat API - all AI functionality: JD extraction, disambiguation, level aggregation, question generation, interview decisions, input refinement, scoring, report generation
  - SDK/Client: `openai` Python package, used OpenAI-compatible mode — `OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)` in `server/services/llm.py:28`
  - Auth: `LLM_API_KEY` env var
  - Endpoint: `LLM_BASE_URL` (default `https://api.deepseek.com`), model `LLM_MODEL` (default `deepseek-chat`)
  - Call style: JSON mode (`response_format={"type": "json_object"}`), `temperature=0`, system+user two-message prompt (`server/services/llm.py:_chat`)
  - **Provider switch:** `LLM_PROVIDER=mock` (default) bypasses the real API entirely — each caller supplies a rule-based `mock_fn`, so the full product runs offline. Real mode requires `LLM_PROVIDER=deepseek` + `LLM_API_KEY`
  - **Retry/trace:** failures retried `LLM_RETRY` (2) extra times; every attempt (prompt, response, success, error) persisted to `llm_trace` table via `server/services/llm.py:_record_trace` — this is the prompt-engineering evidence chain for the course deliverable
  - 8 call types (CHECK constraint in `server/db.py` llm_trace DDL): `extract`, `disambiguate`, `aggregate_level`, `question_gen`, `interviewer`, `refine`, `score`, `report`
  - Prompt definitions per call type: `server/services/prompts/{extract,disambiguate,aggregate_level,question_gen,interviewer,refine,score,report}.py`

No other outbound APIs exist. No payment, email, SMS, search, map, or analytics SDK is used anywhere.

## Data Storage

**Databases:**
- SQLite (file-based, single file)
  - Connection: `DB_PATH` env var, default `data/app.db` (gitignored)
  - Client: Python stdlib `sqlite3` directly — **no ORM**. `server/db.py:get_conn()` returns a connection with `row_factory=sqlite3.Row` and `PRAGMA foreign_keys = ON`
  - Schema: 19 tables defined in `server/db.py` `_DDL` string — auth (user), modeling (position, position_alias, jd_record, competency_model, competency_item, competency_dict), assessment (assessment_session, question_bank, assessment_question, assessment_message, context_raw, form_submission, question_score), reporting (report, feedback), and infra (llm_trace, eval_results)
  - Migrations: hand-rolled, idempotent table-rebuild functions `_migrate_llm_trace` and `_migrate_feedback_status` in `server/db.py`, run at startup by `init_db()` (triggered by FastAPI startup event in `server/main.py`)
  - JSON-in-TEXT pattern: structured payloads (model_json, payload_json, std_items_json, report_json, etc.) stored as serialized JSON strings; a few queries use SQLite `json_extract`/`json_array_length` (`server/api/assessment.py:24`)
  - Long user inputs are SHA256-hashed and archived in `context_raw` for traceability (`server/services/refine.py`)

**File Storage:**
- Local filesystem only
- JD import accepts file upload (`/api/admin/jds/import-file`, JSONL format) — read into memory, parsed, stored in DB; file itself not persisted (`server/api/admin/jds.py:47`)
- Frontend build output `web/dist/` served as static files by FastAPI in demo mode (`server/main.py:75-77`)

**Caching:**
- None (no Redis/memcached/in-memory cache layer)

## Authentication & Identity

**Auth Provider:**
- Custom, self-hosted implementation — no third-party identity provider (no OAuth/SAML/SSO)
  - Implementation: JWT Bearer tokens
    - Token creation/verification: `server/core/security.py` (python-jose, HS256, 12h expiry, `JWT_SECRET` env var)
    - Password hashing: passlib bcrypt (`server/core/security.py:12`)
    - Role model: two roles `admin` / `candidate`, enforced by FastAPI dependencies `require_login` / `require_admin` (`server/core/security.py:50-57`)
    - Login/register endpoints: `server/api/auth.py` (open registration is hard-coded to `candidate` role — cannot register an admin)
    - First admin seeded via CLI script `scripts/seed_admin.py` (reads `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars, idempotent)
    - Token validation re-checks user existence and `is_active` in DB on every request (`server/core/security.py:_current_user`)
  - Frontend session: token + user JSON in `localStorage`, Pinia store `web/src/stores/auth.js`, axios request interceptor injects `Authorization: Bearer` header (`web/src/api/index.js:12-18`), 401 response interceptor clears storage and redirects to `/login`

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry or similar)

**Logs:**
- No structured logging framework; uvicorn default access logs only
- Observability is **database-first**: `llm_trace` table (all LLM prompts/responses/errors, admin-viewable via `/api/admin/trace/*` → `server/api/admin/trace.py`), pipeline status fields on `jd_record`, eval task results in `eval_results` table

## CI/CD & Deployment

**Hosting:**
- Local/demo only. Single uvicorn process serves API + built frontend. No cloud, container, or PaaS configuration.

**CI Pipeline:**
- None. No `.github/workflows`, no Dockerfile, no docker-compose, no deploy scripts.
- `.baseline/` directory contains manually captured snapshots (test output, build output, file inventory, base commit `41270042c05badd0e3dd6fa524fb05fe799a6c71`) used as pre-refactor regression reference, not CI.

## Environment Configuration

**Required env vars (see `.env.example`):**
- `LLM_PROVIDER` — `mock` (offline default) or `deepseek` (real API)
- `LLM_API_KEY` — DeepSeek API key (only needed for real mode)
- `LLM_MODEL`, `LLM_BASE_URL` — model/endpoint overrides
- `JWT_SECRET` — token signing secret (default `change-me-in-.env` is insecure placeholder)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` — consumed by `scripts/seed_admin.py`
- `DB_PATH` — SQLite location (default `data/app.db`)
- `REFINE_MIN_TOKENS` (500), `FOLLOWUP_MAX` (2) — assessment tuning

**Secrets location:**
- `.env` at repo root (gitignored, currently absent); template `.env.example` committed
- Loaded by custom parser `server/main.py:_load_env()` using `os.environ.setdefault` — pre-existing real env vars take precedence

## Webhooks & Callbacks

**Incoming:**
- None. The `jd_record.source_type` CHECK constraint allows `'plugin'` (browser-extension JD push per design docs) but no plugin endpoint is implemented — only `paste` and `file` import paths exist (`server/api/admin/jds.py`).

**Outgoing:**
- None.

## Internal Integration Points (for context)

These are not external, but define the system boundary seams planners should know:

- **Frontend ↔ Backend:** REST over `/api/*`. Dev: Vite proxy (`web/vite.config.js`). Demo: same origin via FastAPI static mount. CORS restricted to `http://localhost:5173` only (`server/main.py:44-50`).
- **Answer submission transport:** `POST /api/assessment/sessions/{id}/answer` currently returns a single JSON response (`server/api/assessment.py:129-206`). Frontend `web/src/utils/sse.js:streamAnswer` auto-detects SSE stream vs single JSON (SSE is the designed target form, JSON is current backend reality) — implemented with `fetch` + ReadableStream (not EventSource, to support POST + Bearer header).
- **Async task pattern:** JD parsing, report generation, and eval runs use FastAPI `BackgroundTasks` with frontend polling (`server/api/admin/jds.py`, `server/api/assessment.py:260-268`, `server/api/admin/eval.py`).
- **Eval harness coupling:** `server/api/admin/eval.py` reaches outside the `server` package to import `eval/` scripts (`eval/consistency_test.py`, `eval/virtual_candidates.py`) via `sys.path` manipulation — the repo root must be importable.

---

*Integration audit: 2026-09-02*
