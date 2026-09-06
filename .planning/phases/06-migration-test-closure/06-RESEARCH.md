# Phase 6: 迁移体系与测试闭环收口 - Research

**Researched:** 2026-09-05
**Domain:** SQLite schema migration registry + pytest test-unification/CI + E2E + eval isolation + security hardening
**Confidence:** HIGH

## Summary

Phase 6 closes the loop from "功能已重构、验证未闭环" to SSOT §27 `verified` (M5–M7) / `contract_complete` (M1). All five plan areas are fully mapped to concrete file:line evidence because the phase is **refactor-and-harden existing code, not greenfield** — nearly every mechanism already exists in some ad-hoc form and needs consolidation, not invention.

The single most important architectural insight: **`server/config.py:21` reads `DB_PATH` once at import time** (`DB_PATH = os.environ.get("DB_PATH", "data/app.db")`), and every test file sets `os.environ["DB_PATH"]` at its own module top. This one import-time-read is the root cause of *three* distinct Phase-6 problems at once: (1) the "同一进程不得导入两测试模块" pytest-collection blocker (D-69), (2) eval scripts writing straight to `data/app.db` (D-74/REF-8.8), and (3) the migration-replay-on-temp-DB requirement (D-68). The planner should treat this as the linchpin: solving DB-path isolation once (conftest.py for tests + a `set_db_path()` override or lazy read for eval) unlocks 06-01, 06-02, and 06-05 simultaneously.

**Primary recommendation:** Implement a `schema_version` registry table + ordered `MIGRATIONS` list in `server/db.py` (replacing the hardcoded 13-call list at `init_db`), add a `server/conftest.py` session-scoped temp-DB fixture to enable one-shot pytest collection, give eval a DB_PATH override + seed-to-temp-DB, and wire a GitHub Actions CI as the acceptance gate. Do **not** introduce new third-party packages — the phase runs on pytest (already installed, v9.1.1, but **missing from `requirements.txt`**) + FastAPI TestClient + stdlib `sqlite3` backup.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REF-2.1 | 全局 21 张表对齐（收口清点） | §Architecture Patterns "schema_version registry" — 21 tables already in `_DDL` (db.py:9-409); migration test asserts table inventory |
| REF-2.11 | schema_version 迁移体系替换 DDL 字符串嗅探 | §Pattern 1: replace `_migrate_llm_trace`/`_migrate_feedback_status` DDL-sniff with registry (db.py:420-469) |
| REF-5.11 | score_live/score_final 双分背离 ≥ 阈值 → bad_case_candidate | §Plan 5: detection point in `scoring.py` `score_session` / `report.py`; threshold = open param (§31) |
| REF-6.1 | JWT HttpOnly cookie 方向（关口包 D-76） | §Plan 5 security: Bearer (`security.py:13`) vs cookie; change surface enumerated |
| REF-6.2 | 生产 secret 启动校验 | §Plan 5 security: **already partially done** `main.py:59-67` (CR-05, fail-closed always); D-77 relaxes mock-mode |
| REF-6.3 | 输入限额按类型配置 | §Plan 5 security: constants in `config.py` + API-layer validation; values = open param (§31) |
| REF-7.4 | 测试统一 pytest 收集 + CI | §Plan 2: conftest.py session-DB fixture; script→pytest conversion; `.github/workflows/ci.yml` |
| REF-7.5 | M1 回归清单八项 | §Plan 3: `test_m1_regression.py` locking `_compute_weights`/`clean_jd`/`normalize_title`/`_gate_check`/confirm/version |
| REF-7.6 | 候选人端完整 E2E（刷新/断线/超时/越权） | §Plan 4: pytest+TestClient full-chain file; `get_session` contract fix |
| REF-8.6 | mock interviewer 固定 3 分处置 | §Plan 3: keep deterministic (`scoring.py:80-81`), document; do NOT break `test_m6` numeric asserts |
| REF-8.8 | eval 独立/临时数据库 | §Plan 5: DB_PATH override + seed-to-temp; `eval/*.py` currently read `data/app.db` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| schema_version 迁移登记簿 + 重放/备份/回滚 | Database/Storage | — | DDL + migration runs inside `server/db.py init_db`; SQLite backup via `conn.backup()` |
| pytest 统一收集 + CI | CI/CD (external) | API/Backend | collection fix is backend code (`conftest.py`, script→pytest); CI is `.github/workflows` |
| M1 回归八项 | API/Backend | — | pure services (`pipeline.py`, `assign.py`, `aggregate.py`, `aggregation.py`, `core/security.py`) |
| 候选人端完整 E2E | API/Backend (service-layer) | Browser/Client (contract fix only) | E2E is scripted against FastAPI TestClient (no Playwright); frontend is limited to contract-repair so the main chain renders |
| eval 隔离 + b/c 评测 + bad case | API/Backend | Database/Storage | eval fns run server-side; isolation = temp-DB seed + `eval_results` write-back |
| 安全收尾三项 (JWT cookie / secret / limits) | API/Backend | Browser/Client (cookie) | `security.py`/`auth.py`/`config.py` backend; frontend api layer for cookie |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.13.2 (verified) | runtime | existing project runtime (PROJECT.md D-005) |
| pytest | 9.1.1 (installed) | unified test collection | already the pytest-style runner for M5/M7 |
| FastAPI `TestClient` (starlette) | via fastapi>=0.110 | API-layer E2E without browser | established pattern in `test_m5/m7_backend.py` |
| SQLite (stdlib `sqlite3`) | bundled | migration registry + backup (`conn.backup()`) | raw-SQL + no-ORM is the project convention (PROJECT.md) |
| GitHub Actions | N/A (YAML) | CI acceptance gate | gh CLI 2.73.0 available; no CI exists today |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | >=0.27 (in requirements.txt) | TestClient transport | already present; no action |
| python-jose / passlib / bcrypt<4.1 | existing | auth helpers reused by test seeders | already present; no new deps |

**No new third-party packages are required for this phase.** CI needs `pytest` installable — **`pytest` is currently NOT in `server/requirements.txt`** (verified: file lists fastapi/uvicorn/openai/python-jose/passlib/bcrypt/pydantic/pypinyin/python-multipart/httpx only). Recommended: add `pytest>=8` to `requirements.txt` so CI and local share one install surface.

**Version verification (run locally, all confirmed present):**
```bash
python3 --version     # 3.13.2
python3 -m pytest --version   # 9.1.1
node --version        # v24.13.0
npm --version         # 11.6.2
gh --version          # 2.73.0
```

## Package Legitimacy Audit

This phase introduces **zero new installable packages**. All tooling (pytest, httpx, FastAPI TestClient, stdlib sqlite3) is already in the environment or the codebase. GitHub Actions is a YAML config file, not a registry package. slopcheck is therefore not applicable; no `[ASSUMED]` package claims are made. The one ecosystem note is that `pytest` must be added to `server/requirements.txt` (verified absent) for CI reproducibility — pytest is a mature, universally-trusted package, not a slop risk.

| Package | Registry | Disposition |
|---------|----------|-------------|
| pytest | PyPI (already installed 9.1.1) | Already-present; add to requirements.txt |
| (none new) | — | — |

## Architecture Patterns

### System Architecture Diagram

```
                       ┌─────────────────────────────────────────────────────────┐
                       │                 GitHub Actions CI (.github/workflows)   │
                       │   push/PR → pip install + pytest server/  +  npm build │
                       └──────────────────────────┬──────────────────────────────┘
                                                  │ green = acceptance bar
┌──────────────┐   HTTP/SSE   ┌──────────────────▼───────────────────┐
│  web/ (Vue3) │─────────────▶│  server/ FastAPI (TestClient in tests)│
│ Chat/FormCard│  Bearer or   │   api/assessment.py  api/admin/*.py   │
│ contract fix │  HttpOnly    │   core/security.py  services/*.py     │
└──────────────┘  cookie (D76)└──────────────┬─────────────────────────┘
                                             │ get_conn() / init_db()
                          ┌──────────────────▼───────────────────┐
                          │  server/db.py — schema_version registry│
                          │  MIGRATIONS[(v,name,fn)] + backup      │
                          │  DB_PATH ← env (import-time today)     │
                          └──────────────┬─────────────────────────┘
                                         │
              ┌──────────────────────────┼───────────────────────────┐
              ▼                          ▼                           ▼
   ┌─────────────────┐     ┌───────────────────────┐     ┌────────────────────┐
   │ data/app.db     │     │ temp DB (pytest session)│    │ temp DB (eval run) │
   │ business (demo) │     │ conftest.py fixture     │     │ eval/*.py + write  │
   └─────────────────┘     └───────────────────────┘     │ back eval_results  │
                                                         └────────────────────┘
```

Data flow for the primary acceptance path: **CI runs `pytest server/`** → conftest sets a single session temp `DB_PATH` before any `server.*` import → `init_db()` builds the full 21-table schema through the `schema_version` registry → each test file (script-style converted to pytest) seeds unique-ID rows and exercises the real routes/services → a dedicated E2E file walks register→…→feedback; a migration-test file replays the registry on a fresh temp DB and asserts parity with `_DDL`.

### Recommended Project Structure

```
server/
├── conftest.py              # NEW: session temp-DB fixture + env (D-69 linchpin)
├── db.py                    # EDIT: schema_version table + MIGRATIONS list + backup
├── config.py                # EDIT: input-limit constants (D-78); optional lazy DB_PATH
├── main.py                  # EDIT: adjust CR-05 secret validation per D-77 (gate)
├── test_m6_backend.py       # EDIT: _test_* → test_* (keep _seed_full_chain)
├── test_question_bank.py    # EDIT: test_*(pid,mid) → check_*(pid,mid) + __main__
├── test_m1_regression.py    # NEW: module-1 eight-item regression locks
├── test_e2e_full_chain.py   # NEW: candidate full-chain E2E (pytest+TestClient)
├── test_migration.py        # NEW: registry replay + old-DB replay + idempotency
└── (13 session-test files)  # EDIT: add model_id/model_version to direct qb INSERTs
eval/
├── consistency_test.py      # EDIT: accept db_path / use override; no business DB
├── virtual_candidates.py    # EDIT: same isolation
└── assertions.py            # REUSE: assert_score_consistency / assert_tier_ordering
.github/workflows/
└── ci.yml                   # NEW: backend pytest + frontend npm build
```

### Pattern 1: schema_version ordered migration registry (06-01)

**What:** Replace the hardcoded 13-call list in `init_db` (db.py:853-876) with a `schema_version` table + an ordered `MIGRATIONS` list. The two DDL-string-sniffing migrations (`_migrate_llm_trace` db.py:420-445 checks `"'report'" in row[0]`; `_migrate_feedback_status` db.py:448-469 checks `"'bad_case'" in row[0]`) get their primary "already applied" decision moved from DDL-text sniffing to registry lookup. The 11 column-sniffing migrations (db.py:472-851) keep their `PRAGMA table_info` idempotency as a secondary safety net.

**When to use:** Every `init_db()` call; both fresh and legacy `data/app.db` paths.

**Bootstrap semantics (critical correctness detail):** The existing `data/app.db` has **no** `schema_version` table (it was migrated by the old hardcoded list). On first run of the new registry, `schema_version` is empty → all 13 migrations run. This is **safe** because every migration is idempotent: the two DDL-rebuild migrations no-op when their CHECK already contains the new enum value, and the 11 column migrations no-op when their columns exist. First run therefore "backfills" the registry to current state. Fresh DBs: migrations no-op (tables don't exist yet) then base `_DDL` (db.py:9-409) creates the full latest schema; registry records all 13.

**Example (shape, not verbatim):**
```python
# server/db.py
_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);
"""
MIGRATIONS: list[tuple[int, str, Callable]] = [
    (1,  "llm_trace_report_type",  _migrate_llm_trace),
    (2,  "feedback_bad_case_status", _migrate_feedback_status),
    (3,  "question_bank_v2",        _migrate_question_bank_v2),
    (4,  "assessment_question_v2",  _migrate_assessment_question_v2),
    (5,  "question_score_v2",       _migrate_question_score_v2),
    (6,  "question_score_phase3",   _migrate_question_score_phase3),
    (7,  "form_instance",           _migrate_form_instance),
    (8,  "idempotency_record",      _migrate_idempotency_record),
    (9,  "session_phase3",          _migrate_session_phase3),
    (10, "trace_link",              _migrate_trace_link),
    (11, "question_score_phase5",   _migrate_question_score_phase5),
    (12, "report_phase5",           _migrate_report_phase5),
    (13, "feedback_phase5",         _migrate_feedback_phase5),
]

def init_db() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_SCHEMA_VERSION_DDL)          # bootstrap registry
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
        for version, name, fn in MIGRATIONS:
            if version in applied:
                continue
            _backup_before_migration(conn, version)      # conn.backup() -> backups/
            fn(conn)
            conn.execute("INSERT INTO schema_version(version,name,applied_at) VALUES(?,?,?)",
                         (version, name, now_iso()))
            conn.commit()                                # per-migration commit
        conn.executescript(_DDL)                         # base latest schema (idempotent)
        conn.commit()
    finally:
        conn.close()
```

**Backup/rollback:** `_backup_before_migration` uses stdlib `sqlite3.Connection.backup()` (or `VACUUM INTO`) into `backups/app-{now}.db` before the first not-yet-applied migration. Rollback = restore the backup file over `DB_PATH` (documented, not automated — §28-6 "不作为上线硬门槛").

**Migration test (temp-DB replay, D-68 §24 必测项):**
```python
def test_fresh_replay():
    init_db()  # empty temp DB via conftest
    rows = _q("SELECT version FROM schema_version ORDER BY version")
    assert [r["version"] for r in rows] == list(range(1, 14))
    # table inventory parity (REF-2.1): 21 tables
    n = _q("SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")[0]["c"]
    assert n == 21

def test_idempotent():
    init_db(); init_db()  # second run no-op, registry unchanged

def test_old_db_migration():
    # hand-create OLD llm_trace (no 'report') + feedback (no 'bad_case') + qb (no v2 cols)
    # then init_db(); assert CHECK widened + registry populated
```

### Pattern 2: conftest.py session temp-DB fixture (06-02 linchpin)

**What:** A single `server/conftest.py` sets `DB_PATH`/`LLM_PROVIDER=mock`/`JWT_SECRET=test-secret` **at its own module import** (before any test module imports `server.*`), so `config.DB_PATH` is read once with the temp value and every collected file shares one isolated DB.

**Why this fixes the collision:** pytest imports `conftest.py` before collecting test modules. Because `config.py:21` reads the env var at import time, the conftest-set value wins; the per-file `os.environ["DB_PATH"] = ...` lines in `test_m5/m6/m7/question_bank` become no-ops (config already imported) and should be removed for clarity.

```python
# server/conftest.py
import os, sys, tempfile
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))                     # so `import server.*` works
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="pytest_"), "test.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"
import pytest
from server.db import init_db

@pytest.fixture(scope="session", autouse=True)
def _session_db():
    init_db()          # once per session; explicit because TestClient skips startup
    yield
```

Session-scope (one shared DB) is viable because every seed uses `new_id()` UUID-prefixed IDs (no cross-file row collisions). If state bleed is ever observed, the fallback is a per-test fixture that deletes rows between tests — not a new DB (lazy-DB would be required for per-test DBs).

**Script-style conversion:**
- `test_question_bank.py`: rename `test_generation(pid, mid)` / `test_idempotent(pid, mid)` / `test_selection(pid, mid, model)` → `check_generation` / `check_idempotent` / `check_selection` (pytest stops treating `pid`/`mid` as fixtures → the 3 collection errors vanish); keep the `__main__` runner calling them. `test_prompts()` has no args, keep as-is.
- `test_m6_backend.py`: rename `_test_dual_scoring` / `_test_aggregation` / `_test_report` / `_test_feedback_api` → `test_*` functions; hoist `_seed_full_chain()` into a module-level or fixture so pytest collects them. Keep the `__main__` runner as a convenience.

### Pattern 3: E2E as pytest+TestClient full-chain (06-04)

**What:** A new `server/test_e2e_full_chain.py` walks the whole candidate chain through `TestClient(app)`, reusing the mock 三件套 (temp DB + `LLM_PROVIDER=mock` + `JWT_SECRET=test-secret`) and the `_stream_answer`/`_auth_headers` helpers from `test_m5_backend.py`. This makes E2E part of the unified collection, so the CI green bar == "E2E passed".

**Chain (endpoints, from `assessment.py`/`auth.py`):**
register (`/api/auth/register`) → login (`/api/auth/login`) → list positions (`GET /assessment/positions`) → create session (`POST /assessment/sessions`) → start (`POST /sessions/{id}/start`) → first question (`GET /sessions/{id}`) → answer loop with followup (`POST /sessions/{id}/answer` SSE) → form (`GET /forms/{id}` + `POST /sessions/{id}/forms/submit-v2`) → finish (pool-exhausted answer) → report (`POST /sessions/{id}/report` → 202) → poll (`GET /reports/by-session/{id}`) → feedback (`POST /reports/{id}/feedback`).

**Scenario coverage (API-testable, re-cover not re-write):**
- 刷新恢复: after `get_session` contract fix, assert returned `messages` array + `position_name`.
- 断线重试: `POST /answer` with same `idempotency_key` twice → second returns 200 JSON snapshot, no duplicate rows (Phase 3 done).
- 超时: manipulate `session_time_intervals`/timestamps to trigger `seal_if_question_timed_out` / `session_active_seconds` (Phase 3 done).
- 越权: candidate A reads candidate B's session → 404 (D-01 uniform-404); candidate hits admin route → 403 (Phase 1 done).
- 报告失败重试: FAILED row → re-`POST /report` → version increments, no re-scoring (Phase 5 D-65 done).

### Pattern 4: eval DB isolation via override + seed-to-temp (06-05)

**What:** `eval/consistency_test.py` (lines 22-24) and `eval/virtual_candidates.py` (lines 22-25) call `get_conn()` which reads the import-time `config.DB_PATH` — so they write `data/app.db` today. Fix: add a `db.set_db_path(path)` override (module-level `_db_path_override` consulted by `get_conn()`), or make `get_conn()` read `os.environ` at call time. The admin trigger (`server/api/admin/eval.py:49-74`) builds a temp DB, copies/re-seeds the target session/position data into it, sets the override, runs the eval fn, writes the result to the **business** `eval_results` table via a separate business-DB connection, then resets the override.

**Why not just change env:** `config.DB_PATH` is frozen at import; mutating `os.environ` post-import has no effect. A `set_db_path()` indirection (or call-time env read in `get_conn`) is the minimal localized change.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DDL-change detection ("has this column/CHECK been added?") | string-match `sqlite_master.sql` | `schema_version` registry table + ordered migrations | substring CHECK misjudgment (CONCERNS: db.py:226-275 fragile) |
| SQLite backup for migration rollback | copy file manually | `sqlite3.Connection.backup()` / `VACUUM INTO` | stdlib, atomic, handles open handles |
| Per-file DB isolation | import-time `os.environ["DB_PATH"]` per file | `conftest.py` session fixture | first-import-wins state bleed |
| Browser E2E | Playwright/Cypress | pytest + TestClient full-chain | D-005 local demo, frontend-zero-tests acknowledged scope |
| eval DB isolation | re-point env after import | `db.set_db_path()` override + seed | import-time freeze |
| Weight drift Σ=1 | re-derive rounding | lock `_compute_weights` (aggregate.py:81-105) with tests | already correct; regression-lock, not rewrite |
| bad-case scoring | auto-change score | `bad_case_candidate` + admin review (no auto-change) | D-031 人工唯一权威 |

**Key insight:** The phase's most deceptively-complex item is the *interaction* between the migration registry and the pre-existing `data/app.db` (no registry yet) — but because every legacy migration is idempotent, the registry backfills safely. The second is `DB_PATH` import-time freeze, which one conftest + one `set_db_path()` solves across three plans.

## Runtime State Inventory

> Included because this is a migration phase (schema_version registry). Categories answered explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **`data/app.db` exists and has NO `schema_version` table** (migrated by old hardcoded list; llm_trace already has `report`, feedback already has `bad_case`) | Code-only: new registry must backfill on first boot (idempotent migrations make this safe). No data migration needed — but the migration test MUST cover the "legacy DB → registry" path |
| Stored data | `eval/*.py` virtual-candidate runs write `eval_seed` question_bank rows + sessions/users directly into `data/app.db` | Move to temp-DB seed (D-74); existing `eval_seed`/`eval_user` rows in business DB are orphaned demo data — optional manual cleanup, not a migration |
| Live service config | None (no external services, no n8n/Datadog/Tailscale equivalents) | None |
| OS-registered state | None (no Task Scheduler/launchd/systemd/pm2 in scope) | None |
| Secrets/env vars | `JWT_SECRET` defaults to `change-me-in-.env` (config.py:16); `main.py:59-67` already fail-closes at startup | D-77 adjusts: mock-mode warn vs real-mode fail (gate). No secret rename — key stays `JWT_SECRET` |
| Build artifacts | `web/dist/` (stale after frontend contract fix); `server/__pycache__`, `eval/__pycache__` (stale after refactor) | Re-run `npm run build` for E2E; pycache self-heals on re-import |

**Nothing found in category (Live service config / OS-registered state):** None — verified by codebase audit (no service-config or OS-registration files referenced anywhere in `.planning/` or `server/`).

## Common Pitfalls

### Pitfall 1: DB_PATH import-time freeze defeats "temp DB" everywhere
**What goes wrong:** Setting `os.environ["DB_PATH"]` after `import server.config` (or `server.db`) has zero effect — `config.py:21` reads it once.
**Why it happens:** Module-level constant read at import.
**How to avoid:** conftest sets env at its own import (before test modules import `server.*`); eval uses a `set_db_path()` override consulted at `get_conn()` call time.
**Warning signs:** A "temp DB" test that actually reads/writes `data/app.db`; two test files sharing one DB.

### Pitfall 2: pytest misreads argument-bearing `test_*` functions as fixtures
**What goes wrong:** `test_question_bank.py` `test_generation(pid, mid)` → 3 "fixture 'pid' not found" errors; `test_m6` `_test_*` never collected.
**Why it happens:** pytest collects any `test_*` name and injects args as fixtures.
**How to avoid:** rename arg-bearing functions to `check_*` (keep `__main__`), rename `_test_*` to `test_*`; no parameters on pytest test functions (TESTING.md checklist item 2).

### Pitfall 3: breaking mock-fixed-3 numerical assertions
**What goes wrong:** "Enhancing" the mock interviewer to return variable scores will cascade-break `test_m6_backend.py` numeric asserts.
**Why it happens:** `_mock_score` (scoring.py:80-81) returns a constant 3; `test_m6` asserts `total_score == 24.5`, `Python == 9.5` (0.19*(3-1)/4*100). **Note:** CONTEXT.md D-72 and TESTING.md cite stale `31.4`/`15.2` — the actual current file asserts `24.5`/`9.5` (test_m6_backend.py:200,217). Trust the file.
**How to avoid:** keep mock deterministic (D-72), document b-consistency variance=0 and c-tier-separation-via-objective-answer_key as known mock limitations.

### Pitfall 4: migration registry must not re-run destructive table rebuilds
**What goes wrong:** On the legacy `data/app.db` (no registry), `_migrate_llm_trace`/`_migrate_feedback_status` rebuild the table (`DROP` + `RENAME`). If their DDL-sniff guard is removed *and* the registry is empty, a fresh mechanism re-runs the rebuild unnecessarily (data-risk + perf).
**How to avoid:** keep the internal idempotency sniff as a belt-and-suspenders, but make the *primary* skip-decision the registry lookup; ensure the two guards still short-circuit on an already-migrated DB.

### Pitfall 5: eval_results written to the temp DB instead of business DB
**What goes wrong:** If eval runs entirely in a temp DB, its results never reach the admin TestCenter polling UI.
**Why it happens:** `_save_result` (admin/eval.py:21-32) writes to whatever `get_conn()` points at.
**How to avoid:** eval computation reads the temp DB; result writing uses a business-DB connection explicitly (`_save_result` keeps its own business-DB handle, not the overridden one).

## Code Examples

### Migration registry bootstrap + backup (06-01)
```python
# server/db.py — backup before applying a not-yet-recorded migration
def _backup_before_migration(conn, version: int) -> None:
    if conn.execute("SELECT 1 FROM schema_version WHERE version=?", (version,)).fetchone():
        return
    bdir = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
    os.makedirs(bdir, exist_ok=True)
    target = sqlite3.connect(os.path.join(bdir, f"app-{now_iso()}-pre-{version}.db"))
    try:
        conn.backup(target)
    finally:
        target.close()
```

### conftest.py session fixture (06-02)
```python
# server/conftest.py  (see Pattern 2 above for the full header)
@pytest.fixture(scope="session", autouse=True)
def _session_db():
    init_db()
    yield
```

### eval DB override (06-05)
```python
# server/db.py — minimal indirection
_DB_PATH_OVERRIDE: str | None = None

def set_db_path(path: str | None) -> None:
    global _DB_PATH_OVERRIDE
    _DB_PATH_OVERRIDE = path

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH_OVERRIDE or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```
```python
# server/api/admin/eval.py — isolated run
from ..db import set_db_path
def _run(task_id, test_name, fn, *args):
    tmp = _build_temp_db()          # copy/seed target session/position into temp DB
    set_db_path(tmp)
    try:
        result = fn(*args)
    finally:
        set_db_path(None)
    _save_result(task_id, test_name, "completed" if result else "failed", result)
```

### get_session contract fix (06-04, D-79)
```python
# server/api/assessment.py get_session — add JOIN + messages
row = conn.execute(
    "SELECT s.*, p.name AS position_name FROM assessment_session s"
    " JOIN position p ON p.position_id=s.position_id WHERE s.session_id=?",
    (session_id,),
).fetchone()
msgs = [dict(r) for r in conn.execute(
    "SELECT role, content, created_at FROM assessment_message"
    " WHERE session_id=? ORDER BY sequence_no, created_at", (session_id,))]
return {**existing, "position_name": row["position_name"], "messages": msgs}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| DDL-string sniffing (`"'report'" in row[0]`) | `schema_version` registry + ordered migrations | Phase 6 (this) | robust, replayable, backfill-safe |
| Script-style tests + per-file DB_PATH | conftest session temp-DB + pytest collection | Phase 6 (this) | single `pytest server/` green bar |
| No CI | GitHub Actions (pytest + npm build) | Phase 6 (this) | automated acceptance gate |
| eval writes business DB | temp-DB seed + override | Phase 6 (this) | REF-8.8 closed |
| Bearer token in localStorage | HttpOnly cookie (gate D-76) | Phase 6 (decision) | XSS token-theft surface removed |

**Deprecated/outdated:**
- `@app.on_event("startup")` (main.py:59) — deprecated FastAPI API; leave unless D-77 touches main.py (surgical).
- `pypinyin` in requirements.txt — unused; unrelated to this phase, do not touch (surgical changes).
- CONCERNS.md "FormCard references nonexistent endpoint" is now **stale**: `GET /api/assessment/forms/{form_instance_id}` exists (assessment.py:906-921) and `📎[form:id]` is emitted (assessment.py:386). The remaining real gap is the frontend calling the **old** `POST /forms/submit` (api/index.js:47-48) instead of `submit-v2` (assessment.py:924).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Session-scoped single temp DB is safe under unique-ID seeds | Plan 2 | cross-file state bleed → switch to per-test cleanup |
| A2 | The 13 legacy migrations are all idempotent, so registry backfill on `data/app.db` is safe | Plan 1 | destructive re-run → backup needed first (mitigated by Pattern-1 backup) |
| A3 | `_gate_check` lives in `services/aggregation.py` (not `aggregate.py`) per CONCERNS:42-63 | Plan 3 | wrong file targeted → verify at plan time |
| A4 | CI runner is GitHub Actions (gh 2.73.0 available) and repo is GitHub-hosted | Plan 2 | if repo not on GitHub, CI choice changes |
| A5 | `pytest` should be added to requirements.txt (not a separate CI-only install) | Standard Stack | CI/local drift |
| A6 | E2E via pytest+TestClient (not standalone script) satisfies "完整 E2E" acceptance | Plan 4 | user may insist on browser automation — D-73 leaves carrier to planner |

## Open Questions (ROUTED TO GATE-PACKAGE)

> All three below are routed (not unresolved). Routing: Q1 → 06-05 Task 0 checkpoint (D-76 JWT cookie); Q2 → config.py gate-package placeholders (§31-4/5/6, REF-5.11 threshold, REF-6.3 limits); Q3 → 06-05 Task 0 checkpoint (REF-6.2 secret strictness).

1. **JWT cookie direction (D-76, 关口包)** — migrate to HttpOnly cookie vs keep Bearer?
   - What we know: current = Bearer (security.py:13, auth.py:48, api/index.js:11-18 localStorage). Cookie migration touches `_current_user`, login response, ALL test `_auth_headers`/`_auth` helpers, and the frontend axios interceptor + `sse.js` fetch. SameSite=Lax mitigates CSRF for local demo.
   - Recommendation: adopt HttpOnly cookie (SSOT direction), but this is a user-confirmed gate; the plan should branch. **ROUTED: 06-05 Task 0 checkpoint (D-76).**

2. **Open-param numeric values (§31-4/5/6, REF-5.11 threshold, REF-6.3 limits)** — do not fabricate.
   - What we know: §31-4 dict top-10 match threshold + cleaning wordlist; §31-5 trace retention/desensitization; §31-6 idempotency cleanup threshold; REF-5.11 bad-case |live−final| threshold; REF-6.3 input-limit values.
   - Recommendation: emit config constants as placeholders with "实施期校准" comments; gate-package for user decision. **ROUTED: config.py gate-package placeholders (§31-4/5/6, REF-5.11, REF-6.3).**

3. **REF-6.2 secret validation is already stricter than D-77** — `main.py:59-67` fail-closes on ANY default secret (mock or real); D-77 proposes warn-in-mock / fail-in-real.
   - What we know: current code blocks `LLM_PROVIDER=mock` demo without a real secret; tests bypass it (TestClient skips startup, tests call `init_db()` directly).
   - Recommendation: flag at the gate — either keep fail-closed-always (simplest, safest) or implement D-77's warn-in-mock (requires a real secret for demo). Clarify which. **ROUTED: 06-05 Task 0 checkpoint (REF-6.2 secret strictness).**

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | migration/test/CI | ✓ | 3.13.2 | — |
| pytest | unified collection | ✓ | 9.1.1 (NOT in requirements.txt) | add `pytest>=8` to requirements.txt |
| sqlite3 stdlib | registry + backup | ✓ | bundled | — |
| Node + npm | frontend build (CI) | ✓ | v24.13.0 / 11.6.2 | — |
| gh CLI | GitHub Actions | ✓ | 2.73.0 | — |
| GitHub-hosted repo | CI | assumed (A4) | — | verify `gh repo view` |

**Missing dependencies with no fallback:** none (all required tooling present locally; CI is GitHub-hosted-assumed).
**Missing dependencies with fallback:** `pytest` absent from requirements.txt → add it (fallback: `pip install pytest` in CI step).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 |
| Config file | none today → add `server/conftest.py` + optional `pytest.ini` (`testpaths = server`) |
| Quick run command | `python -m pytest server/test_m1_regression.py -x -q` (targeted) |
| Full suite command | `python -m pytest server/ -q` (from repo root) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REF-2.11 | registry replay parity + idempotency + old-DB migration | unit/integration | `python -m pytest server/test_migration.py -q` | ❌ Wave 0 |
| REF-7.4 | full collection green (no fixture errors) | collection | `python -m pytest server/ -q` | ❌ (3 errors today) |
| REF-7.5 | M1 eight-item regression locks | unit | `python -m pytest server/test_m1_regression.py -q` | ❌ Wave 0 |
| REF-7.6 | candidate full-chain E2E + refresh/retry/timeout/authz | integration | `python -m pytest server/test_e2e_full_chain.py -q` | ❌ Wave 0 |
| REF-5.11 | bad-case candidate created on divergence, never auto-score | unit | `python -m pytest server/test_bad_case.py -q` | ❌ Wave 0 |
| REF-6.2 | startup secret validation behavior | unit | `python -m pytest server/test_secret_gate.py -q` | ❌ Wave 0 |
| REF-6.3 | input-limit enforcement per type | unit/integration | `python -m pytest server/test_input_limits.py -q` | ❌ Wave 0 |
| REF-8.8 | eval uses temp DB, business DB untouched | integration | `python -m pytest server/test_eval_isolation.py -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** targeted `python -m pytest server/test_<area>.py -q` for the touched file
- **Per wave merge:** `python -m pytest server/ -q` (full collection must stay green as files are converted)
- **Phase gate:** full suite green + `npm run build` (web/) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `server/conftest.py` — session temp-DB fixture (blocking prerequisite for ALL collection work)
- [ ] `pytest` added to `server/requirements.txt` (CI reproducibility)
- [ ] `server/test_migration.py` — registry replay / idempotency / legacy-DB path
- [ ] `server/test_m1_regression.py` — eight-item locks
- [ ] `server/test_e2e_full_chain.py` — full candidate chain
- [ ] `server/test_bad_case.py` / `test_secret_gate.py` / `test_input_limits.py` / `test_eval_isolation.py`
- [ ] Fix 13 session-test files' direct `question_bank` INSERTs to write `model_id`/`model_version` (grep evidence: test_p0_security, test_phase2_interview/scoring, test_phase3_forms/sse/idempotency/misc, test_m5, test_m6, test_m7 all show `model_version` refs = 0)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | JWT HS256 (python-jose); password bcrypt; secret validation (D-77) |
| V3 Session Management | yes | JWT HttpOnly cookie direction (D-76); 12h expiry (`JWT_EXPIRE_HOURS=12`) |
| V4 Access Control | yes | `require_admin`/`load_owned_session` (security.py:57-99) — already enforced, E2E re-covers |
| V5 Input Validation | yes | `MAX_ANSWER_LEN` (scoring.py:39) exists; add per-type limits in `config.py` (D-78) |
| V6 Cryptography | yes | HS256 JWT + bcrypt — never hand-roll; secret must not be default (D-77) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| JWT forgery via default secret | Spoofing | startup fail-closed (main.py:59-67, D-77) |
| XSS token theft (localStorage Bearer) | Information disclosure | HttpOnly cookie (D-76, gate) |
| IDOR session/report access | Elevation of privilege | `load_owned_session`/`load_owned_report` (Phase 1, E2E re-covers) |
| SQL injection via f-string clauses | Tampering | bound params only; audit admin/dict.py, trace.py, feedback.py (CONCERNS) |
| Catastrophic regex (answer_key) | DoS | WR-14 `_MAX_KEY_LEN`/`MAX_ANSWER_LEN` (scoring.py:38-40) |
| Prompt injection | Tampering | `INJECTION_DETECTED` event (assessment.py:617-621, Phase 3) |
| eval writing business DB | Integrity | temp-DB isolation (D-74) |

## Sources

### Primary (HIGH confidence — direct codebase read)
- `server/db.py` (migrations 420-851, `init_db` 853-876, `get_conn` 412-417, `_DDL` 9-409)
- `server/config.py` (JWT_SECRET:16, DB_PATH:21, constants)
- `server/main.py` (CR-05 secret fail-closed 59-67, CORS)
- `server/test_question_bank.py`, `test_m6_backend.py`, `test_m5_backend.py`, `test_m7_backend.py`
- `eval/consistency_test.py`, `eval/virtual_candidates.py`, `eval/assertions.py`
- `server/api/admin/eval.py`, `server/api/assessment.py`, `server/api/auth.py`
- `server/services/scoring.py`, `server/services/aggregate.py`, `server/services/report.py`
- `server/core/security.py`
- `web/src/api/index.js`, `web/package.json`
- `server/requirements.txt` (pytest absent — verified)

### Secondary (MEDIUM — authoritative planning docs, cross-referenced)
- `.planning/phases/06-migration-test-closure/06-CONTEXT.md` (D-68~D-79 decisions)
- `.planning/REQUIREMENTS.md`, `.planning/PROJECT.md`, `.planning/STATE.md`
- `.planning/codebase/TESTING.md`, `.planning/codebase/CONCERNS.md`
- `design/final-design/模块四设计-测试闭环.md` (§2.3 bad case, §2.4 isolation, §3 E2E/CI)

### Tertiary (LOW — flagged for validation)
- CONCERNS.md "FormCard endpoint nonexistent" — stale, contradicted by assessment.py:906-921 (verified directly)
- CONTEXT.md/TESTING.md numeric `31.4`/`15.2` — stale, actual test_m6 asserts `24.5`/`9.5` (verified directly)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all versions probed locally.
- Architecture: HIGH — every mechanism traced to file:line in the live codebase.
- Pitfalls: HIGH — grounded in CONCERNS.md + direct code reading; two doc/code staleness flags surfaced.

**Research date:** 2026-09-05
**Valid until:** 2026-09-19 (30 days; stable codebase, no fast-moving external deps)
