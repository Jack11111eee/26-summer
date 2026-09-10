# AI-Driven Job Competency Assessment & Talent Profile System

Transforms unstructured **job descriptions (JDs)** into measurable **competency models** (the "ruler"), runs **bounded dynamic assessments** against those models, produces **talent profiles (scores & reports)**, and closes the loop with a **test/audit framework** that keeps the entire chain auditable, traceable, and measurable.

```
JD text ──► Competency Model (Module 1) ──► Bounded Dynamic Assessment (Module 2) ──► Talent Profile / Scoring (Module 3)
                                                                                                  │
                                                 Test Closed Loop (Module 4) ◄─────────────────────┘
                                              auditable / traceable feedback / measurable criteria
```

> All technical and design documents in this repository are authored in Chinese; the Chinese README is authoritative. English readers may find the primary references under `design/`.

## Feature Overview

The system is organized around four design modules (see `design/final-design/总设计文档.md` for the authoritative spec):

**Module 1 · JD Parsing & Competency Model Building**
- Six-stage pipeline: ① ingest (paste / JSONL upload) → ② cleaning (pure rules) → ③ extraction (LLM) → ④ normalization & disambiguation (competency dictionary + LLM) → ⑤ aggregation (code-based statistics + LLM adjudication + code-computed weights) → ⑥ human review (confirm & bump version).
- The LLM only **classifies and adjudicates**; all arithmetic — statistics, weights, quotas — is done in code (hard constraint ① "LLM never touches numbers"); aggregation frequency dilutes per-call LLM noise.
- Competency dictionary (canonical names / aliases / exclusions), position alias table, and per-stage intermediate artifacts are persisted.
- A `confirmed` model is the **single authority** for downstream question generation and scoring; it is never silently overwritten — edits go through a diff-review flow that bumps `v{n+1}`.

**Module 2 · Bounded Dynamic Assessment**
- Bounded loop: `Observation → Policy/Plan → Act → Evaluation → Persist`; **code is the only state machine** (question count, follow-up cap, difficulty transitions, finish, etc. are decided by code — the LLM supplies structured observations and suggestions only).
- Question bank + position-level quota formula (7:3 category ratio + largest-remainder + tier quotas), per-question dynamic instantiation, four-layer selection, difficulty-path state machine.
- Session state machine, real SSE chat, follow-up questions / form-based fact verification (gate items), timing with pause & resume, idempotency; answers are archived immutably and state events are **append-only**.

**Module 3 · Scoring, Aggregation & Talent Profile**
- Scoring chain: `score_live` is used for navigation only and never enters the final score; refusal (REFUSED), missing-data (IMPUTED imputation), multi-question item merging, and synthesis-question adjudication are all handled.
- **Five-section report**: ① total score + gate tags ② radar chart ③ per-item detail (gap coloring / rationale / disagreements) ④ strengths · gaps · suggestions (code-ordered; gap = required level − actual level, gap>0 means below requirement) ⑤ per-question review (evidence quotes + source traceability).
- Reports require **code-side pre-release consistency checks + an explicit human "publish" click**; a duplicate-trigger guardrail returns 409; candidates may file per-score disagreements (feedback), which **never auto-change scores**.

**Module 4 · Test Closed Loop**
- End-to-end auditability: `report → session → model/version → question → message → score → trace` closes via `trace_link`.
- Consistency eval (re-running a fixed transcript with bounded score drift) plus **virtual candidates** (strong / medium / weak end-to-end); `eval/` runs against an isolated temporary DB and never touches business data.
- Security: JWT auth + resource-level ownership checks (a candidate can only access their own resources), input limits, prompt-injection event logging, and trace access auditing.

**Explicitly out of scope**: final hiring decisions / ranking / automatic pass-fail. Reports express measurement results only — no "hire/no-hire" or ranking language.

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ · FastAPI · Uvicorn (single process) |
| LLM client | `openai` SDK (base_url swappable to OpenAI-compatible endpoints such as DeepSeek); `mock` provider simulates the LLM with rules — **the full flow runs offline** |
| Storage | Single-file SQLite (default `data/app.db`); DDL + migrations embedded in `server/db.py` (`schema_version` based) |
| Auth | JWT (HS256) + bcrypt; roles `admin` / `candidate` |
| Frontend | Vue 3 · Vite · Vue Router · Pinia · axios (active frontend: `web-next/`; the UI kit and radar chart are hand-rolled — no Element Plus / ECharts; the legacy `web/` is retired) |
| Deployment shape | Vite build output (`web-next/dist`) is served statically by FastAPI; single-process uvicorn demo deploy |

## Repository Layout

```
.
├── server/                 # FastAPI backend
│   ├── main.py             # App entry: loads .env / creates tables / registers routes / serves web-next/dist
│   ├── config.py           # Env vars & tunables (weighting scheme, assessment quotas, open-parameter placeholders)
│   ├── db.py               # SQLite DDL + migrations (schema_version) + init (20+ tables)
│   ├── schemas.py          # Pydantic request / response models
│   ├── core/               # Low-level security (password hashing, JWT)
│   ├── api/                # Routes: auth, assessment, admin/{jds,models,positions,dict,users,trace,feedback,forms,eval,reports}
│   ├── services/           # Business logic: pipeline / question bank / selection / difficulty state machine / forms / idempotency / timing / scoring / aggregation / reports / events
│   └── test_*.py           # pytest: P0 security / Modules 2–4 / migrations / E2E / eval isolation
├── web-next/               # Frontend (the only active one): Vue 3 + Vite, hand-rolled ui/ components and SVG radar
│   └── src/views/          # admin/ (management) + assessment/ (candidate) + Login / Register
├── web/                    # Frontend (retired, kept for history — do not modify): the old Element Plus + ECharts implementation
├── design/                 # Design & requirements docs (see "Authoritative Documents")
├── data/                   # Runtime data (git-ignored): app.db, jd_corpus, backups
├── eval/                   # Independent Module-4 eval: consistency (b) + virtual candidates (c) + fixtures
├── scripts/                # One-off/ops scripts: seed_admin (bootstrap admin), jd_corpus_normalize, backfill_jd_source_title, dict_governance, review_gate_positions, etc.
├── prototype/              # High-fidelity static prototypes (visual reference only — not a functional acceptance basis)
├── research/               # Research notes / gap registers / reference docs
├── .planning/              # GSD progress records: ROADMAP / STATE / PROJECT / decisions / requirements
├── .github/workflows/      # CI: backend pytest + frontend build
├── .baseline/              # Pre-refactor baseline snapshots (history)
└── CLAUDE.md               # Agent behavior conventions (incl. document-governance summary)
```

## Authoritative Documents & Governance

- **Single Source of Truth (SSOT)**: `design/final-design/总设计文档.md` (v2.0). The sole authority for system design, scope, interfaces, and acceptance. Any change updates the SSOT **first (body + §14 changelog), then the code**.
- **Per-module excerpts**: `design/final-design/模块一~四设计*.md` are excerpts of the SSOT; on conflict the SSOT wins.
- **Upstream requirements**: `design/需求文档-胜任力测评与人才画像系统.md` and `design/技术方案概述.md`.
- **Historical archives** (`design/final-design/历史档案/`, legacy 04/05/06 under `design/`) and **working drafts** (`design/临时讨论稿-*`) are for traceability only — they are **not** implementation authority.
- Modifying the SSOT requires explicit user authorization; checkpoint snapshots and working drafts under `design/` are context only and grant no authority to change docs or code.

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20 (frontend build / dev)
- Optional: a DeepSeek (or other OpenAI-compatible) API key — otherwise run in `mock` mode

### 1) Backend

Run from the **repository root**:

```bash
python -m venv .venv && source .venv/bin/activate   # optional virtualenv
pip install -r server/requirements.txt
cp .env.example .env          # edit as needed — see "Configuration"
```

Initialize and start:

```bash
ADMIN_USERNAME=admin ADMIN_PASSWORD=admin123 python -m scripts.seed_admin   # idempotent
uvicorn server.main:app --reload --port 8000
```

- Health check: `curl http://localhost:8000/api/health` → `{"status":"ok"}`
- On startup the app **refuses to run** with a missing or publicly-defaulted `JWT_SECRET` (fail-closed).
- The DB is auto-created on first run at `data/app.db` (override with `DB_PATH`).

### 2) Frontend (dev mode, hot reload)

```bash
cd web-next
npm install
npm run dev          # http://localhost:5174 — /api is proxied to :8000
```

### 3) Single-process demo (build, then served by the backend)

```bash
cd web-next && npm run build
# Back at the repo root, start uvicorn again and open http://localhost:8000
uvicorn server.main:app --port 8000
```

### Accounts

- **Admin**: created by `scripts/seed_admin.py` (default `admin / admin123` — local demo only; change it).
- **Candidates**: open self-registration at `/register`; the role is forced to `candidate`, so no one can self-register as admin.

### Configuration (`.env`)

| Variable | Description |
|---|---|
| `LLM_PROVIDER` | `mock` (default, offline rule-based simulation) or `deepseek` |
| `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | Real-LLM integration (OpenAI-compatible endpoint) |
| `JWT_SECRET` | **Must** be a strong random secret, or startup is refused |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Bootstrap admin credentials (read by `seed_admin` only) |
| `DB_PATH` | Database file path (default `data/app.db`) |

## Tests & CI

```bash
# Backend regression (conftest injects mock LLM / test JWT / an isolated temp DB — never touches data/app.db)
cd server && python -m pytest . -q

# Frontend build check
cd web-next && npm ci && npm run build

# Independent eval (eval/ uses an isolated temp DB — see eval/ for details)
```

CI lives in `.github/workflows/ci.yml` and runs the backend tests plus the frontend build on every push / PR.

## Current Status

- All six phases of milestone v2.0 are closed: P0 security & main chain → dynamic selection & bounded loop → forms/SSE/idempotency/timing → question-bank version binding & Module-1 closure → evidence-chain & report contract → migration & test-loop closure.
- The backend regression suite is fully green — **544 passed** (measured on the current branch, 2026-09-10). Progress records live in `.planning/STATE.md`. Open parameters are tracked in SSOT §31 — they **await user calibration; no invented defaults**.
- Target shape is a **demo deployment**: single machine, single instance, single process. Evaluation relies on `mock` regression plus the independent `eval/`; it does not substitute for real-LLM quality validation.

## Conventions

- Commit messages are written in Chinese; each commit is one logical unit; SSOT-affecting changes require prior user authorization and are committed atomically.
- Runtime artifacts (`.env`, `data/`, `web-next/node_modules/`, `web-next/dist/`) are git-ignored and never committed.
- Frontend baseline (2026-09-08): `web-next/` is the only active frontend; `web/` is retired and kept for history — no further changes, and CI no longer builds it.

## Server Deployment (Demo)

Single-machine, single-process demo shape (per the SSOT deployment convention): the `npm run build` output `web-next/dist` is served statically by FastAPI; run uvicorn without `--reload` and without multi-process workers (SQLite single-writer + in-memory background tasks are design assumptions). Example below uses Linux + systemd + Nginx; Node is only needed at build time — the running server needs no Node.

### 1) Prerequisites

| Item | Requirement |
|---|---|
| Python | 3.11+ (required at runtime) |
| Node.js | 20 (build time only; can be removed afterwards) |
| Ports | uvicorn listens on `127.0.0.1:8000`; Nginx exposes 80/443 |
| Real LLM | Optional — `LLM_PROVIDER=mock` runs the full flow offline; for DeepSeek etc. set `LLM_API_KEY` |

### 2) Build

```bash
git clone <this repo> && cd 26-summer             # or, on an existing deploy, git pull
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt

cd web-next && npm ci && npm run build          # produces web-next/dist (served by the backend)
cd ..
```

### 3) Configure `.env` (repo root; git-ignored)

```bash
cp .env.example .env
# REQUIRED: set JWT_SECRET to a strong random value (public defaults are rejected fail-closed at startup)
python3 -c "import secrets; print(secrets.token_hex(32))"   # generate one and paste it in
# Optional: LLM_PROVIDER=deepseek + LLM_API_KEY; DB_PATH is best as an absolute path (guards against systemd cwd drift)
```

```bash
# Bootstrap the seed admin (idempotent; use a non-default password in production)
ADMIN_USERNAME=admin ADMIN_PASSWORD=<strong-password> .venv/bin/python -m scripts.seed_admin
```

> **Mind the cwd**: `DB_PATH` defaults to the relative path `data/app.db` — **always start from the repo root**, otherwise an empty DB is silently created in the wrong directory (the symptom is every login returning 401). The systemd unit pins this with `WorkingDirectory`; keep it in mind for manual restarts too.

### 4) systemd service

`/etc/systemd/system/competency.service`:

```ini
[Unit]
Description=Competency assessment system (FastAPI, single process)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/26-summer          # repo root — pins the cwd that DB_PATH resolves against
EnvironmentFile=/opt/26-summer/.env
ExecStart=/opt/26-summer/.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /opt/26-summer/data     # SQLite write permission (tables are auto-created on first start)
sudo systemctl daemon-reload && sudo systemctl enable --now competency
curl http://127.0.0.1:8000/api/health                    # {"status":"ok"} means ready
```

### 5) Nginx reverse proxy (SSE matters)

`/etc/nginx/sites-available/competency`:

```nginx
server {
    listen 80;
    server_name your.domain.or.ip;

    client_max_body_size 4m;              # JD JSONL uploads (backend caps at 500 lines; this is the byte-level backstop)

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;           # assessment chat SSE long connections
        proxy_buffering off;               # MUST be off for SSE — otherwise the proxy buffers and the chat stream stalls
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/competency /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

- The backend's SSE responses already send `X-Accel-Buffering: no`; `proxy_buffering off` is belt-and-suspenders. Deep links such as `/login`, `/assessment/**` are handled by the backend's SPA fallback (returns index.html — built in, no Nginx rewrite needed).
- HTTPS (optional): run `certbot --nginx` and follow the wizard to add 443.

### 6) Backup & Upgrade

- **Backup**: cold-copy the whole `data/` directory (`app.db` + `jd_corpus/`); a cron job is recommended (e.g. daily `sqlite3 app.db ".backup data/backup-$(date +%F).db"`).
- **Upgrade**: `git pull` → (if the frontend changed) `cd web-next && npm ci && npm run build` → `sudo systemctl restart competency`. Migrations run automatically at startup (`schema_version` registry, with an automatic pre-migration backup).
- **Rollback**: `git checkout <old tag>` and restart; for data, restore `app.db` from the backup directory and restart.
