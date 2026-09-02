# Technology Stack

**Analysis Date:** 2026-09-02

## Languages

**Primary:**
- Python 3.13 (3.13.2 on dev machine) - Backend API, services, DB layer, eval scripts (`server/`, `eval/`, `scripts/`)
- JavaScript (ES modules) - Vue 3 SPA frontend (`web/src/`)
- SQL (SQLite dialect) - Schema DDL and all queries inline in Python (`server/db.py`, services)

**Secondary:**
- HTML/CSS - Static design prototypes, no framework, plain hand-written CSS (`prototype/`)
- Markdown - Design docs, SSOT (`design/final-design/`), research notes (`research/`)

## Runtime

**Environment:**
- Python 3.13 (no `.python-version` / `.nvmrc` pin files; system interpreter used)
- Node.js v24.13.0 for frontend build

**Package Manager:**
- pip (backend) — no lockfile; constraints only in `server/requirements.txt` (floor versions, plus `bcrypt<4.1` pin with comment: passlib 1.7.4 incompatible with bcrypt 5.x)
- npm 11.6.2 (frontend) — lockfile present: `web/package-lock.json`

## Frameworks

**Core:**
- FastAPI (declared `>=0.110`, installed 0.141.1) - REST API, background tasks, static file serving. Entry: `server/main.py`
- Vue 3 (`^3.5.10`) - SPA frontend, Options-API style components in `web/src/views/`, `web/src/components/`
- Vite (`^5.4.8`) - Dev server + build (`web/vite.config.js`)

**Testing:**
- pytest (installed 9.1.1, NOT listed in `server/requirements.txt` — must be installed separately)
- FastAPI TestClient (via `httpx`) — used in `server/test_m5_backend.py`, `server/test_m6_backend.py`, `server/test_m7_backend.py`, `server/test_question_bank.py`

**Build/Dev:**
- uvicorn (`[standard]>=0.29`, installed 0.52.4) - ASGI server: `uvicorn server.main:app --reload --port 8000`
- `npm run dev` (Vite, port 5173, proxies `/api` → `http://localhost:8000`)

## Key Dependencies

**Backend (`server/requirements.txt`):**

| Package | Version constraint | Purpose |
|---------|------------------|---------|
| fastapi | >=0.110 | Web framework |
| uvicorn[standard] | >=0.29 | ASGI server |
| openai | >=1.30 | DeepSeek LLM client (OpenAI-compatible API) — imported lazily inside `server/services/llm.py:_chat` |
| python-jose[cryptography] | >=3.3 | JWT encode/decode (HS256) in `server/core/security.py` |
| passlib[bcrypt] | >=1.7.4 | Password hashing (bcrypt scheme) |
| bcrypt | <4.1 | Hard pin — bcrypt 5.x crashes passlib 1.7.4 hashing |
| pydantic | >=2.6 (installed 2.10.3) | Request/response schemas, LLM output validation (`server/schemas.py`) |
| pypinyin | >=0.50 | **Declared but no usage found in any `.py` file** — candidate for removal |
| python-multipart | >=0.0.9 | File upload for `/api/admin/jds/import-file` (`server/api/admin/jds.py`) |
| httpx | >=0.27 | Transitive via FastAPI TestClient; no direct usage in server code |

**Frontend (`web/package.json`):**

| Package | Version | Purpose |
|---------|---------|---------|
| vue | ^3.5.10 | UI framework |
| element-plus | ^2.8.4 | UI component library (zh-CN locale set in `web/src/main.js`) |
| @element-plus/icons-vue | ^2.3.1 | Icon set |
| pinia | ^2.2.2 | State management (`web/src/stores/auth.js` is the only store) |
| vue-router | ^4.4.5 | Client routing, `createWebHistory` (`web/src/router/index.js`) |
| axios | ^1.7.7 | HTTP client with token/401 interceptors (`web/src/api/index.js`) |
| echarts | ^6.1.0 | Radar chart in report page (`web/src/views/assessment/Report.vue`) |

## Architecture Summary (tech view)

- **Monorepo, two apps:** Python package `server/` + Vite SPA `web/`, no root package manifest. `prototype/` is static HTML/CSS design mockups only (no build tooling, no framework).
- **Single process:** FastAPI serves both API and, in demo mode, the built frontend (`web/dist` mounted at `/` in `server/main.py`). API routes registered before static mount so they take precedence.
- **DB access:** raw `sqlite3` stdlib, no ORM. Every call site opens/closes its own connection via `server/db.py:get_conn()`. JSON stored as TEXT columns, parsed with `json.loads` in Python; some SQLite JSON functions used (`json_array_length`, `json_extract` in `server/api/assessment.py:24`).
- **LLM abstraction:** all LLM calls go through `server/services/llm.py:call_llm_json` with `LLM_PROVIDER=mock` (rule-based offline mode, default) or `deepseek` (real API). Every attempt is recorded to `llm_trace` table. Retry count from `config.LLM_RETRY` (2).
- **Async work:** FastAPI `BackgroundTasks` only (JD parse pipeline, report generation, eval runs). No Celery/Redis/job queue.

## Configuration

**Environment:**
- `.env` file at repo root, loaded by a hand-rolled parser in `server/main.py:_load_env()` (KEY=VALUE lines, comments ignored, `os.environ.setdefault` — real env vars win). No python-dotenv dependency.
- `.env.example` committed as template. No `.env` file currently present on disk.
- All config constants centralized in `server/config.py` (read once at import time — tests set `DB_PATH`/`LLM_PROVIDER`/`JWT_SECRET` env vars **before** importing `server`).

**Key env vars:**

| Var | Default | Used for |
|-----|---------|----------|
| `LLM_PROVIDER` | `mock` | `mock` \| `deepseek` switch |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | (empty) | DeepSeek API key |
| `JWT_SECRET` | `change-me-in-.env` | HS256 signing key |
| `DB_PATH` | `data/app.db` | SQLite file path (relative to cwd) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | — | Seed admin (`scripts/seed_admin.py`) |
| `REFINE_MIN_TOKENS` | `500` | Long-input refine threshold |
| `FOLLOWUP_MAX` | `2` | Follow-up question cap per question |

**Hardcoded business constants** (`server/config.py`, not env-driven): `CATEGORY_RATIO` (hard:soft:experience:qualification = 5.5:2.0:2.0:0.5), `IMPORTANCE_COEF`, `REQ_THRESHOLD`/`R_THRESHOLD` (0.5), `LLM_RETRY` (2), `CLEAN_MIN_REQ_LEN` (30).

**Build:**
- `web/vite.config.js` — Vue plugin, port 5173, `/api` proxy to `:8000`
- `server/requirements.txt` — pip constraints
- No tsconfig, no linter/formatter config files (no ESLint/Prettier/Ruff/Black) detected anywhere

## Platform Requirements

**Development:**
- Python 3.13+ with pip; pytest installed separately (not in requirements.txt)
- Node 24 + npm for `web/`
- Run backend from repo root (module path `server.main`): `uvicorn server.main:app --reload --port 8000`
- Run frontend: `cd web && npm run dev`
- Seed admin: `python -m scripts.seed_admin` with `ADMIN_USERNAME`/`ADMIN_PASSWORD` env vars
- Backend tests: `cd server && python -m pytest test_m5_backend.py -v` (tests are self-contained: temp DB, mock LLM)

**Production/Demo:**
- Single-process demo deploy: `cd web && npm run build`, then `uvicorn server.main:app --port 8000` — FastAPI serves `web/dist` as static site
- No Dockerfile, no CI pipeline, no deployment config anywhere in the repo
- CORS allows only `http://localhost:5173` (`server/main.py:46`) — demo/local oriented

## Version Notes / Gotchas

- `bcrypt` must stay `<4.1` — passlib 1.7.4 + bcrypt 5.x crashes on hash (documented in `server/requirements.txt:6`)
- Installed versions exceed declared floors (e.g., FastAPI 0.141 vs `>=0.110`); floors are minimums, not pins
- `openai` SDK is imported inside function body (`server/services/llm.py:26`) so mock mode works without the package installed
- `pypinyin` and `httpx` are declared in requirements but have no direct import in server code
- `web/dist/` is committed-ignored (`.gitignore`) but exists locally; gitignored too: `data/`, `*.db`, `.env`

---

*Stack analysis: 2026-09-02*
