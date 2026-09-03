# Codebase Structure

**Analysis Date:** 2026-09-02

## Directory Layout

```
26-summer-sem/                      # repo root (git)
├── server/                         # FastAPI backend (Python package)
│   ├── main.py                     # app entry: env, CORS, routers, static mount
│   ├── config.py                   # env-driven constants (LLM/JWT/DB/quotas)
│   ├── db.py                       # sqlite3 conn factory + 18-table DDL + migrations
│   ├── schemas.py                  # Pydantic v2 request/LLM-output models
│   ├── api/                        # HTTP routers
│   │   ├── auth.py                 # /api/auth/* (public)
│   │   ├── assessment.py           # /api/assessment/* (candidate, require_login)
│   │   └── admin/                  # /api/admin/* (require_admin), one file per resource
│   │       ├── jds.py  models.py  positions.py  dict.py  users.py  trace.py
│   │       ├── feedback.py  eval.py
│   │       └── __init__.py
│   ├── core/
│   │   └── security.py             # JWT + bcrypt + role dependencies
│   ├── services/                   # business logic + LLM orchestration
│   │   ├── pipeline.py             # module-1 parse chain + new_id/now_iso helpers
│   │   ├── aggregate.py            # model aggregation (module 1)
│   │   ├── assign.py               # job title normalization
│   │   ├── llm.py                  # LLM gateway (trace/retry/mock)
│   │   ├── question_bank.py        # bank generation (module 2)
│   │   ├── question_selection.py   # per-session selection
│   │   ├── interview.py            # interviewer decision
│   │   ├── refine.py               # long-input refinement
│   │   ├── scoring.py              # final scoring
│   │   ├── aggregation.py          # session score aggregation
│   │   ├── report.py               # report generation (module 3)
│   │   └── prompts/                # LLM prompt templates, one per call type
│   │       ├── extract.py  disambiguate.py  aggregate_level.py  question_gen.py
│   │       ├── interviewer.py  refine.py  score.py  report.py
│   │       └── __init__.py
│   ├── test_m5_backend.py          # pytest suite (session/answer/score)
│   ├── test_m6_backend.py          # standalone runner (score/report)
│   ├── test_m7_backend.py          # standalone runner (test-loop)
│   ├── test_question_bank.py       # standalone runner (bank gen; known broken)
│   └── requirements.txt           # backend deps
├── web/                            # Vue 3 + Vite frontend
│   ├── package.json                # vue/element-plus/pinia/router/axios/echarts
│   ├── vite.config.js             # :5173 dev, /api proxy → :8000
│   ├── index.html
│   ├── dist/                       # build output (gitignored; served by FastAPI)
│   ├── node_modules/
│   └── src/
│       ├── main.js                 # bootstrap (Pinia/Router/ElementPlus zh-CN)
│       ├── App.vue                 # bare router outlet
│       ├── api/index.js            # axios instance + assessment/admin collections
│       ├── stores/auth.js          # only Pinia store
│       ├── router/index.js         # role-guarded routes
│       ├── utils/sse.js            # fetch answer transport (SSE/JSON adaptive)
│       ├── assets/grail-notion.css # global design tokens
│       ├── components/             # AdminNav, CandidateNav, FormCard, ItemTable
│       └── views/
│           ├── Login.vue  Register.vue
│           ├── admin/              # Positions, PositionDetail, ModelReview,
│           │                      # VersionHistory, Dict, Users, TestCenter
│           └── assessment/        # Positions, PositionAssess, Chat, Report
├── eval/                           # test harness (outside server package)
│   ├── consistency_test.py         # scoring consistency (re-run, delta ≤ 1)
│   ├── virtual_candidates.py       # strong/medium/weak tier ordering test
│   ├── assertions.py               # assert_score_consistency / assert_tier_ordering
│   ├── fixtures/                   # (empty)
│   └── results/                    # (empty)
├── scripts/
│   └── seed_admin.py               # python -m scripts.seed_admin
├── design/                         # documents (not code)
│   ├── final-design/               # SSOT + module excerpts + 历史档案/
│   │   ├── 总设计文档.md            # THE SSOT (v2.0)
│   │   ├── 模块一~四设计-*.md        # module excerpts (subordinate)
│   │   └── 历史档案/                # archived prior versions
│   ├── 需求文档-*.md / 技术方案概述.md  # upstream requirements
│   ├── 临时讨论稿-*.md (×10)       # interim discussion drafts (not authoritative)
│   └── checkpoint-*.md             # snapshots (context only)
├── prototype/                      # static HTML design prototypes
│   ├── final/                      # 6-page admin "grail-notion" definitive set
│   ├── redesign/                   # design exploration dirs (01-linear … 11-chat-styles,
│   │                               #  candidate-material, final-admin)
│   └── *.html / *.css              # earlier single-page prototypes
├── research/
│   ├── gsd-core-operating-guide.md # how to refactor this repo toward SSOT v2.0
│   └── ai-devtools-research-report.md
├── data/
│   └── app.db                      # SQLite DB (gitignored; created on first run)
├── .baseline/                      # recorded pre-refactor test/build results (untracked)
├── .planning/                      # GSD planning docs (this file's home)
├── .env / .env.example             # env vars (gitignored / template)
├── CLAUDE.md / PRODUCT.md          # agent guidelines / product context
└── .gitignore
```

## Directory Purposes

**`server/`:**
- Purpose: entire backend; a single Python package importable as `server.*` from repo root
- Contains: FastAPI app, routers, services, prompts, core security, DB layer, tests
- Key files: `main.py` (entry), `db.py` (schema), `config.py` (all tunables), `services/pipeline.py` (`new_id`/`now_iso` live here and are imported everywhere)

**`server/api/`:**
- Purpose: HTTP layer only — parse request, call service, shape response
- Contains: `auth.py`, `assessment.py`, `admin/` (8 routers, one per admin resource)
- Convention: admin routers use prefix `/api/admin[/resource]` and `dependencies=[Depends(require_admin)]`; never put SQL beyond trivial reads or business logic here that belongs in `services/`

**`server/services/`:**
- Purpose: business logic, LLM orchestration, all state-machine transitions
- Contains: 11 service modules + `prompts/` subpackage
- Note: `pipeline.py` exports shared helpers `new_id(prefix)` / `now_iso()` used across all modules; import them from there (`from .pipeline import new_id, now_iso`)

**`server/services/prompts/`:**
- Purpose: LLM prompt constants and user-prompt builder functions
- Contains: 8 modules, one per LLM call type; each docstring carries a version stamp (e.g. "版本: v1 (2026-08-30)")
- Naming: `EXTRACT_SYSTEM`, `DISAMBIGUATE_SYSTEM`, `AGGREGATE_LEVEL_SYSTEM`, `QUESTION_GEN_SYSTEM`, `INTERVIEWER_SYSTEM`, `REFINE_SYSTEM`, `SCORE_SYSTEM`, `REPORT_SYSTEM` + `build_*_user` / `*_prompt` builders

**`web/src/`:**
- Purpose: entire SPA; flat feature layout (no per-module folders beyond `views/admin` vs `views/assessment`)
- Contains: `api/`, `stores/`, `router/`, `utils/`, `components/`, `views/`, `assets/`

**`web/src/views/`:**
- Purpose: page components mapped 1:1 to routes in `web/src/router/index.js`
- Split: `admin/` (7 pages) and `assessment/` (4 pages), plus `Login.vue`/`Register.vue`

**`eval/`:**
- Purpose: module-4 test harness; runs both standalone (CLI) and embedded (imported by `server/api/admin/eval.py` via sys.path hack)
- Contains: two test runners + shared assertions
- Constraint: imports `server.*` with repo-root `sys.path.insert`; keep importable without a running app

**`scripts/`:**
- Purpose: operational utilities run as `python -m scripts.<name>`
- Contains: `seed_admin.py` (idempotent first-admin creation)

**`design/`:**
- Purpose: documentation only — the SSOT and its subordinate/archived docs
- Contains: `final-design/总设计文档.md` (唯一权威), module excerpts, discussion drafts, archived versions
- Rule: never treat drafts or archives as implementation basis; code changes must trace to the SSOT

**`prototype/`:**
- Purpose: static HTML/CSS visual prototypes used as the design reference for the Vue app (e.g. `prototype/final/grail-notion.css` tokens are mirrored in `web/src/assets/grail-notion.css`)
- Not part of the deployed application

**`data/`:**
- Purpose: runtime SQLite database location (default `DB_PATH=data/app.db`)
- Generated: yes (created by `init_db()`); committed: no (gitignored)

**`.planning/`:**
- Purpose: GSD workflow documents (codebase maps, phases, milestones)
- Generated: by GSD commands; committed with the repo

**`.baseline/`:**
- Purpose: pre-refactor recorded test/build outputs used by the SSOT v2.0 alignment work (see `research/gsd-core-operating-guide.md`)
- Untracked reference data

## Key File Locations

**Entry Points:**
- `server/main.py`: FastAPI app — dev `uvicorn server.main:app --reload --port 8000`; serves `web/dist` at `/` when built
- `web/src/main.js`: SPA bootstrap — `npm run dev` (port 5173, `/api` proxied)
- `scripts/seed_admin.py`: first admin — `python -m scripts.seed_admin` (needs `ADMIN_USERNAME`/`ADMIN_PASSWORD`)
- `eval/consistency_test.py`, `eval/virtual_candidates.py`: eval CLI

**Configuration:**
- `server/config.py`: all env-driven constants (`LLM_PROVIDER/LLM_MODEL/LLM_BASE_URL/LLM_API_KEY`, `JWT_SECRET`, `DB_PATH`, `CATEGORY_RATIO`, `IMPORTANCE_COEF`, thresholds, `REFINE_MIN_TOKENS`, `FOLLOWUP_MAX`) — read at import time
- `.env.example`: template for root `.env` (hand-parsed by `server/main.py`)
- `web/vite.config.js`: dev proxy
- `server/requirements.txt`: backend dependencies (note `bcrypt<4.1` pin for passlib compat)

**Core Logic:**
- `server/db.py`: DDL for all 18 tables + two inline migrations
- `server/services/pipeline.py`: module-1 parse chain
- `server/services/aggregate.py`: model aggregation + weight computation
- `server/services/interview.py` / `scoring.py` / `aggregation.py` / `report.py`: modules 2–3 core
- `server/services/llm.py`: the single LLM gateway
- `server/core/security.py`: auth dependencies

**Testing:**
- `server/test_m5_backend.py` (pytest), `server/test_m6_backend.py`, `server/test_m7_backend.py`, `server/test_question_bank.py` (standalone runners)
- `eval/assertions.py`: shared eval assertions

**Design reference:**
- `design/final-design/总设计文档.md`: SSOT — §28 is the authoritative gap/backlog list
- `research/gsd-core-operating-guide.md`: how this repo is being refactored toward the SSOT

## Naming Conventions

**Files:**
- Python: `snake_case.py`, one module per concern (`question_selection.py`, `aggregate_level.py`)
- Vue views: `PascalCase.vue` matching route names (`ModelReview.vue`, `PositionDetail.vue`); auth pages at views root (`Login.vue`)
- Vue components: `PascalCase.vue` (`FormCard.vue`, `AdminNav.vue`)
- Prompts: named for their LLM call type (`extract.py`, `interviewer.py`)
- Tests: `test_<milestone>_backend.py` in `server/` root (M5=pytest style; M6/M7/question_bank=script style)

**Directories:**
- Python packages: lowercase singular/plural as-is (`api`, `services`, `core`, `prompts`, `admin`)
- Frontend: lowercase singular (`views`, `components`, `stores`, `router`, `api`, `utils`)
- Chinese-named docs in `design/` (e.g. `临时讨论稿-*.md`)

**Symbols:**
- Services export `verb_noun` functions: `run_parse_pipeline`, `generate_question_bank`, `select_questions_for_session`, `decide_next_action`, `refine_user_input`, `score_session`, `generate_report`, `run_aggregate`
- Private helpers `_leading_underscore`; mocks named `_mock_<calltype>`
- Prompt constants `SCREAMING_SNAKE` ending in `_SYSTEM`; builders `build_*_user` or `<noun>_prompt`
- IDs `new_id("<prefix>_<hex12>")` — prefixes: `u_`, `pos_`, `jd_`, `cm_`, `c_`, `sess_`, `q_`, `aq_`, `msg_`, `raw_`, `form_`, `qs_`, `rpt_`, `fb_`, `ev_`, `t_`
- DB columns `snake_case` with `_json` suffix for JSON-text columns (`model_json`, `payload_json`)
- Frontend api collections grouped by consumer (`assessment.*`, `admin.eval.*`, `admin.trace.*`, `admin.feedback.*`)

**Routes:**
- Backend: `/api/<area>/<resource>` RESTful-ish; admin nested under `/api/admin`; polls/status via GET; long ops POST + 202/201 then GET polling
- Frontend: `/admin/<page>`, `/assessment/<page>`, params `snake_case` (`:session_id`, `:position_id`)

**Language:** all user-facing strings, docstrings, and comments are Chinese; identifiers and code are English. Keep this split.

## Where to Add New Code

**New backend endpoint:**
1. Choose the router file by area (`server/api/assessment.py` for candidate, `server/api/admin/<resource>.py` for admin, new file in `server/api/admin/` + register in `server/main.py` for a new admin resource)
2. Write the handler as a thin wrapper: parse body → call service → return dict
3. Add ownership filter (`user_id`) for candidate resources — the SSOT makes this mandatory (§7 P0), even though older code lacks it

**New service/business rule:**
- Module 1 logic → `server/services/pipeline.py` or `aggregate.py`
- Module 2/3 runtime → new file in `server/services/` following the `verb_noun` pattern
- Shared helpers → `server/services/pipeline.py` (`new_id`, `now_iso`) — do not duplicate these

**New LLM call type:**
1. Create `server/services/prompts/<calltype>.py` with `<CALLTYPE>_SYSTEM` + builder
2. Add a Pydantic output model in `server/schemas.py`
3. Add the call_type to the `llm_trace` CHECK constraint in `server/db.py` **and** `_migrate_llm_trace` (legacy DBs)
4. Call `call_llm_json("<calltype>", ref_id, system, user, mock_fn=_mock_<calltype>)` with a deterministic mock beside the real call

**New DB table/column:**
- Edit `_DDL` in `server/db.py`; for constraint changes on existing tables, add a `_migrate_*` rebuild function called from `init_db()` (follow `_migrate_llm_trace` as the template)
- Avoid CHECK constraints that will need widening (SSOT N11 prefers code-side enum validation for new tables)

**New frontend page:**
1. Create `web/src/views/<area>/<Page>.vue`
2. Register route in `web/src/router/index.js` with proper `meta` (`role: 'admin'` / `requiresAuth: true` / `public: true`)
3. Add api methods to the matching collection in `web/src/api/index.js` (verify the backend route exists)
4. Reusable UI → `web/src/components/`; page-specific markup stays in the view

**New frontend shared component:**
- `web/src/components/<Component>.vue`, PascalCase, props via `defineProps`

**New eval script:**
- `eval/<name>.py` with repo-root sys.path bootstrap (copy the header from `eval/consistency_test.py`), shared assertions in `eval/assertions.py`

**Tests:**
- Backend: new `server/test_<feature>.py`; set `DB_PATH` + `LLM_PROVIDER=mock` env BEFORE importing `server.*` (see `server/test_m5_backend.py:13-17`)
- Follow the existing mock-provider, temp-DB isolation pattern

**Utilities:**
- Operational scripts → `scripts/` as `python -m scripts.<name>`

**Do NOT add:**
- ORM models/migrations frameworks (raw SQL + `server/db.py` is the convention)
- A second auth mechanism (everything goes through `server/core/security.py` dependencies)
- Direct `OpenAI` calls outside `server/services/llm.py`
- New Pinia stores for domain data (state lives in views; only auth is stored)
- Chinese filenames for code files (docs in `design/` are the exception)

## Special Directories

**`server/services/prompts/`:**
- Purpose: prompt templates for all 8 LLM call types, version-stamped in docstrings
- Generated: no
- Committed: yes

**`data/`:**
- Purpose: SQLite database (`app.db`)
- Generated: yes (`init_db()` on startup)
- Committed: no (`.gitignore`: `data/`, `*.db`)

**`web/dist/`:**
- Purpose: Vite build output served by FastAPI when present
- Generated: yes (`npm run build` in `web/`)
- Committed: no

**`prototype/`:**
- Purpose: static HTML design prototypes; visual source of truth for Vue styling
- Generated: no (hand-authored)
- Committed: yes

**`design/final-design/历史档案/`:**
- Purpose: archived superseded design docs (prior SSOT versions, old module docs)
- Committed: yes; read-only reference, never an implementation basis

**`.claude/worktrees/`:**
- Purpose: Claude agent git worktrees (full repo copies)
- Generated: yes
- Committed: no — exclude from any repo-wide search/grep

**`.baseline/`:**
- Purpose: recorded pre-refactor backend-test and web-build outputs
- Generated: yes (by the GSD refactor workflow)
- Committed: no (untracked)

**`.planning/`:**
- Purpose: GSD workflow documents (this map, phases, milestones)
- Generated: by GSD commands
- Committed: yes

---

*Structure analysis: 2026-09-02*
