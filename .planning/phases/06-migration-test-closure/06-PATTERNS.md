# Phase 6: 迁移体系与测试闭环收口 - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 27 (modified + new)
**Analogs found:** 26 / 27

> Note on one orchestrator-listed file: `server/api/index.js` **does not exist** — `server/` is Python-only. The frontend contract fix (D-79) lives solely in `web/src/api/index.js` (line 47-48). No backend `.js` analog is required.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/db.py` (EDIT) | model/migration | file-I/O (SQLite DDL) | itself — `_migrate_*` 420-851, `init_db` 853-876, `get_conn` 412-417 | exact (self) |
| `server/config.py` (EDIT) | config | transform (env→const) | itself — `DB_PATH` 21, `JWT_SECRET` 16 | exact (self) |
| `server/main.py` (EDIT) | config/entrypoint | request-response (bootstrap) | itself — CR-05 fail-closed 59-67 | exact (self) |
| `server/conftest.py` (NEW) | config/test-fixture | transform (env, import-time) | `server/test_m5_backend.py` 12-28 (module-top env) | role-match |
| `server/test_m6_backend.py` (EDIT) | test | batch (script→pytest) | `server/test_m5_backend.py` (pytest) | exact |
| `server/test_question_bank.py` (EDIT) | test | batch (script→pytest) | `server/test_m5_backend.py` | exact |
| 13 session-test files (EDIT) | test | CRUD (seed → route) | `server/test_m5_backend.py` `_seed_position_with_confirmed_model` 43-73 | role-match |
| `server/requirements.txt` (EDIT) | config | — (dependency list) | itself | exact (self) |
| `.github/workflows/ci.yml` (NEW) | config (CI) | batch | none in repo → RESEARCH Standard Stack | no-analog |
| `server/test_migration.py` (NEW) | test | batch (DDL replay) | `server/db.py` `_DDL` 9-409 + `init_db` | role-match |
| `server/test_m1_regression.py` (NEW) | test | transform (pure-service) | `server/test_m5_backend.py` `test_objective_scoring` 216-223 (pure-fn) | role-match |
| `server/test_e2e_full_chain.py` (NEW) | test | request-response (full chain) | `server/test_p0_security.py` `_seed_a_full_chain` 203-222 | exact |
| `server/api/assessment.py` (EDIT) | controller | request-response | itself — `get_session` 143-205, `submit_form_v2` 924-991 | exact (self) |
| `server/test_bad_case.py` (NEW) | test | CRUD | `server/test_phase5_feedback.py` + `report.py` `generate_report` | role-match |
| `server/test_secret_gate.py` (NEW) | test | transform (config gate) | `server/main.py` 59-67 + `server/test_p0_security.py` | role-match |
| `server/test_input_limits.py` (NEW) | test | request-response (validation) | `server/services/scoring.py` `MAX_ANSWER_LEN` 38-40 | role-match |
| `server/test_eval_isolation.py` (NEW) | test | batch (eval run) | `server/test_m7_backend.py` eval-runner section | role-match |
| `eval/consistency_test.py` (EDIT) | utility/service | batch (CLI) | itself — `get_conn()` 16-30 | exact (self) |
| `eval/virtual_candidates.py` (EDIT) | utility/service | batch (CLI) | itself — `get_conn()` 22-25 | exact (self) |
| `server/api/admin/eval.py` (EDIT) | controller | request-response (BackgroundTasks) | itself — `_save_result` 21-32, `_run` 35-42 | exact (self) |
| `server/services/scoring.py` (EDIT) | service | CRUD (score write) | itself — `score_session` 240-324 | exact (self) |
| `server/services/report.py` (EDIT) | service | CRUD (report write) | itself — `generate_report` 160-243 | exact (self) |
| `web/src/api/index.js` (EDIT) | utility (frontend api client) | request-response | itself — `submitForm` 47-48, interceptor 11-18 | exact (self) |
| `web/src/views/assessment/Chat.vue` (EDIT) | component | event-driven (SSE) | itself — `load()` 172-195 | exact (self) |
| `web/src/components/FormCard.vue` (EDIT) | component | request-response | itself — `onSubmit` 101-118 | exact (self) |
| `web/src/utils/sse.js` (EDIT, gate D-76 only) | utility | streaming | itself — fetch 21-28 | exact (self) |
| `server/core/security.py` + `server/api/auth.py` (EDIT, gate D-76 only) | middleware/controller | request-response | themselves — `_current_user` 33-50, `login` 36-48 | exact (self) |

---

## Pattern Assignments

### 06-01 — Migration registry (`server/db.py` EDIT, `server/test_migration.py` NEW)

#### `server/db.py` (model/migration, file-I/O)

**Analog:** itself. The 13-migration hardcoded list + DDL-sniff pattern is the exact object D-68 replaces. Copy the *existing* per-migration idempotency structure and re-register it.

**`get_conn` pattern** (db.py:412-417) — the target of the `set_db_path()` override (D-74):
```python
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```
Change to consult a module-level `_DB_PATH_OVERRIDE or DB_PATH` (RESEARCH Pattern 4 / Pitfall 5) so eval can point at a temp DB without touching `config.DB_PATH` (import-time frozen).

**DDL-sniff guard to preserve as belt-and-suspenders** (db.py:420-426) — keep inside `_migrate_llm_trace`:
```python
row = conn.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='llm_trace'"
).fetchone()
if row is None or "'report'" in (row[0] or ""):
    return
```

**`init_db` hardcoded list to convert into `MIGRATIONS`** (db.py:853-876):
```python
def init_db() -> None:
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        _migrate_llm_trace(conn)
        _migrate_feedback_status(conn)
        _migrate_question_bank_v2(conn)
        ...
        _migrate_feedback_phase5(conn)
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
```
New shape (RESEARCH Pattern 1): bootstrap `schema_version` DDL first, read `applied = {version ...}`, loop `MIGRATIONS [(v,name,fn), ...]`, skip if applied, `_backup_before_migration(conn, version)` then `fn(conn)` then `INSERT INTO schema_version` + per-migration `conn.commit()`, then `conn.executescript(_DDL)` + final commit. The 13 names/order must match the existing list exactly (llm_trace, feedback_status, question_bank_v2, assessment_question_v2, question_score_v2, question_score_phase3, form_instance, idempotency_record, session_phase3, trace_link, question_score_phase5, report_phase5, feedback_phase5).

**`_DDL` table inventory** (db.py:9-409) — 21 tables + triggers + indexes; the migration test asserts `COUNT(*) FROM sqlite_master` parity against this. Do NOT touch `_DDL` content (surgical).

#### `server/test_migration.py` (test, batch DDL replay)

**Analog:** `server/db.py` `_DDL` + `init_db`. No existing migration test. Use the `_q()` read-only helper pattern from `server/test_m5_backend.py:32-38`:
```python
def _q(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```
Test shape (RESEARCH Pattern 1): `test_fresh_replay` calls `init_db()` then asserts `[r["version"] for r in _q("SELECT version FROM schema_version ORDER BY version")] == list(range(1,14))` and table count `== 21`; `test_idempotent` calls `init_db()` twice; `test_old_db_migration` hand-creates the old `llm_trace` (no `report`) + `feedback` (no `bad_case`) then asserts CHECK widened + registry populated.

---

### 06-02 — pytest unification + CI (`conftest.py` NEW, test conversions EDIT, 13 session files EDIT, `requirements.txt` EDIT, `ci.yml` NEW)

#### `server/conftest.py` (config/test-fixture, transform)

**Analog:** `server/test_m5_backend.py:11-28` module-top env block — the mock 三件套 that every test file repeats. conftest is this block hoisted once, before any `server.*` import:
```python
# server/test_m5_backend.py:11-18 (the pattern to centralize)
import tempfile
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_m5.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```
conftest does this **at its own module import** (pytest imports conftest before test modules), then a session-scoped autouse fixture calls `init_db()` (RESEARCH Pattern 2). This replaces the per-file `os.environ["DB_PATH"]` lines which become no-ops and must be removed for clarity.

#### `server/test_m6_backend.py` (test, batch → pytest)

**Analog:** `server/test_m5_backend.py` full pytest structure (its own `test_*` functions + `_q` + `_seed_*`).

Conversion (RESEARCH Pattern 2 / Pitfall 2):
- Rename `_test_dual_scoring` / `_test_aggregation` / `_test_report` / `_test_feedback_api` (lines 148, 190, 228, 269) → `test_*` (pytest collects only `test_*`, and functions with params get misread as fixtures).
- Keep `_seed_full_chain()` (lines 35-145) verbatim as a module helper (or wrap in a fixture) — pytest test functions take no params.
- Keep the `check(name, cond, detail)` helper but note it is print-based; the pytest conversion should also add `assert`-style bodies (or keep `check` — planner's call, but numeric asserts at lines 200/217 (`abs(py["score"] - 9.5)`, `abs(agg["total_score"] - 24.5)`) MUST NOT change — D-72 keeps mock=3 deterministic).

#### `server/test_question_bank.py` (test, batch → pytest)

**Analog:** `server/test_m5_backend.py`.

Conversion (RESEARCH Pattern 2): rename arg-bearing `test_generation(pid, mid)` / `test_idempotent(pid, mid)` / `test_selection(pid, mid, model)` (lines 71, 117, 125) → `check_generation` / `check_idempotent` / `check_selection` (eliminates the 3 "fixture 'pid' not found" collection errors). Keep `test_prompts()` (line 181, no args) as-is. Keep the `__main__` runner (lines 229-237) calling the renamed `check_*` fns.

#### 13 session-test files (test, CRUD seed)

**Analog:** `server/test_m5_backend.py:43-73` `_seed_position_with_confirmed_model()` which returns `(pid, mid)` — thread that `mid` into the `question_bank` INSERT.

The gap (D-71): `grep -n "INSERT INTO question_bank"` shows `server/test_p0_chain.py`, `test_phase2_interview.py`, `test_phase2_scoring.py`, `test_phase2_migration.py`, `test_phase3_sse.py`, `test_phase3_idempotency.py`, `test_phase3_misc.py`, `test_phase3_forms.py`, `test_phase3_timer.py`, `test_phase4_binding.py`, `test_phase4_fail_visible.py`, `test_phase4_model_edit.py`, `test_phase4_orphan.py`, `test_phase5_evidence.py`, `test_phase5_report.py`, `test_phase5_feedback.py` all INSERT `question_bank` columns **without** `model_id`/`model_version`. The columns exist in `_DDL` (db.py:142-143):
```sql
model_id             TEXT,
model_version       INTEGER,
```
Fix = add `model_id, model_version` to the INSERT column list + `(mid, 1)` to values. Reference the question_bank v2 column DDL above; the model_id comes from the seed helper's returned `mid`.

#### `server/requirements.txt` (config)

**Analog:** itself (read: `fastapi>=0.110`, `httpx>=0.27` present; `pytest` absent). Add `pytest>=8` (RESEARCH Standard Stack / A5).

#### `.github/workflows/ci.yml` (config, batch)

**Analog:** none in repo (`ls .github` → no such dir). Use RESEARCH Standard Stack. Shape:
- `on: push / pull_request`
- steps: `actions/checkout`, `actions/setup-python@3.13`, `pip install -r server/requirements.txt`, `python -m pytest server/ -q`, `actions/setup-node`, `npm ci --prefix web`, `npm run build --prefix web`.
- `web/package.json:8` build script = `vite build` (verified).

---

### 06-03 — M1 regression (`server/test_m1_regression.py` NEW)

#### `server/test_m1_regression.py` (test, transform — pure service fns)

**Analog:** `server/test_m5_backend.py:216-223` `test_objective_scoring` (direct pure-function call + assert), and `test_refine_threshold` (202-213).

Targets to lock (all verified line refs):
- `_compute_weights` (`server/services/aggregate.py:81-105`) — lock Σ=1 exactly (generator path) vs ±0.005 tolerance (editor path); extract the drift-absorption block at 100-105:
```python
if items:
    drift = round(1.0 - sum(it["weight"] for it in items), 4)
    if drift:
        max(items, key=lambda x: x["weight"])["weight"] = round(
            max(items, key=lambda x: x["weight"])["weight"] + drift, 4)
```
- `_gate_check` (`server/services/aggregation.py:139-160`) — NOT `aggregate.py` (assumption A3; verified `_gate_check` lives in `aggregation.py`).
- `clean_jd` / `normalize_title` / `_gate_check` / confirm-not-silently-overwrite / version-diff / admin-permission — locate via `server/services/pipeline.py`, `assign.py`, `aggregation.py` at plan time (CONCERNS recorded these have no direct test yet).
- Note: `_compute_weights` and `_gate_check` are in different modules (`aggregate.py` vs `aggregation.py`) — do not confuse them (Pitfall A3).

---

### 06-04 — E2E full chain + frontend contract (D-73/D-79)

#### `server/test_e2e_full_chain.py` (test, request-response full chain)

**Analog:** `server/test_p0_security.py:203-222` `_seed_a_full_chain()` — the most complete chain walker (register→session→answer whole session→report→return sid/rid/headers):
```python
def _seed_a_full_chain() -> tuple[str, str, dict]:
    pid, _mid = _seed_position_with_confirmed_model()
    _seed_question_bank(pid)
    headers = _auth_headers("p0_candidate_a")
    r = client.post("/api/assessment/sessions", json={"position_id": pid}, headers=headers)
    sid = r.json()["session_id"]
    _answer_whole_session(sid, headers)
    r = client.post(f"/api/assessment/sessions/{sid}/report", headers=headers)
    assert r.status_code == 202
    rows = _q("SELECT report_id FROM report WHERE session_id=?", (sid,))
    return sid, rows[0]["report_id"], headers
```
Reuse the helper set from `test_m5_backend.py`: `_q` (32-38), `_auth_headers` (130-135), `_start` (138-141), `_stream_answer` (144-158). The E2E chain endpoints (RESEARCH Pattern 3): register → login → `GET /assessment/positions` → `POST /assessment/sessions` → `POST /sessions/{id}/start` → `GET /sessions/{id}` → `POST /sessions/{id}/answer` (SSE) → `GET /forms/{id}` + `POST /sessions/{id}/forms/submit-v2` → finish → `POST /sessions/{id}/report` (202) → poll `GET /reports/by-session/{id}` → `POST /reports/{id}/feedback`.

#### `server/api/assessment.py` `get_session` (controller, request-response)

**Analog:** itself, lines 143-205. Add `position_name` + `messages` to the return dict. The `position` join pattern already exists in `score_question` (scoring.py:164-169) and `generate_report` (report.py:168-171):
```python
# report.py:168-171 — position_name JOIN pattern to copy
s = conn.execute(
    "SELECT s.session_id, p.name AS position_name FROM assessment_session s"
    " JOIN position p ON p.position_id=s.position_id WHERE s.session_id=?",
    (session_id,),
).fetchone()
```
Append `position_name` from that join, and `messages` from `SELECT role, content, created_at FROM assessment_message WHERE session_id=? ORDER BY sequence_no, created_at` (RESEARCH Code Example). Do not disturb the existing `current_question`/`open_form`/`total_count` logic (surgical).

#### `web/src/api/index.js` (utility, request-response)

**Analog:** itself, `submitForm` (47-48) calls the OLD endpoint; `submit_form_v2` is the real endpoint (assessment.py:924). Fix:
```js
// web/src/api/index.js:47-48 — current (wrong) target
submitForm: (sessionId, formType, payload) =>
  api.post(`/assessment/sessions/${sessionId}/forms/submit`, { form_type: formType, payload }),
```
`submit-v2` needs `form_instance_id` + `payload` + optional `expected_revision`/`idempotency_key` (see `submit_form_v2` body, assessment.py:924-991) — the planner wires the exact contract; the getter `getForm` (line 46, `GET /assessment/forms/{form_instance_id}`) already exists and returns the render whitelist.

#### `web/src/views/assessment/Chat.vue` (component, event-driven)

**Analog:** itself, `load()` 172-195 already consumes `data.messages` (178-183) and `session.position_name` (line 9). The backend contract fix makes these fields actually present; Chat.vue logic is mostly ready. Remaining D-79 work: `missing_reasons score_state` code→中文 mapping + report-failure-retry UI — mirror the existing `statusText`/`ElMessage` error-handling shape (176-195).

#### `web/src/components/FormCard.vue` (component, request-response)

**Analog:** itself, `onSubmit` 101-118 currently calls `assessment.submitForm(sessionId, form_type, {...model})`. Change to the `submit-v2` signature (needs `form_instance_id` from `props.formId`). The render path `assessment.getForm(props.formId)` (line 91) is already correct.

---

### 06-05 — eval isolation + b/c + bad case + security (D-74/75/76/77/78)

#### `eval/consistency_test.py` + `eval/virtual_candidates.py` (service, batch CLI)

**Analog:** themselves — both import `get_conn` and read the business DB (consistency_test.py:16-30, virtual_candidates.py:22-25):
```python
# eval/consistency_test.py:16-23 — direct get_conn() (the object D-74 fixes)
from server.db import get_conn
def _load_answered_questions(session_id: str) -> list[dict]:
    conn = get_conn()
    ...
```
Fix = rely on `db.set_db_path()` (added to db.py, see 06-01) so these functions operate on whatever DB the caller overrides. Do NOT change `eval/assertions.py` (pure predicates, reuse as-is — verified lines 7-27).

#### `server/api/admin/eval.py` (controller, BackgroundTasks)

**Analog:** itself — `_save_result` (21-32) and `_run` (35-42):
```python
def _run(task_id: str, test_name: str, fn, *args) -> None:
    try:
        result = fn(*args)
        _save_result(task_id, test_name, "completed", result)
    except Exception as e:
        _save_result(task_id, test_name, "failed", {"error": str(e)})
```
Isolation fix (RESEARCH Pattern 4 / Pitfall 5): build temp DB, `set_db_path(tmp)`, `try: result = fn(*args) finally: set_db_path(None)`, then write `eval_results` via a **business-DB connection** (so admin poll UI sees results — Pitfall 5). The `eval_results` table DDL is db.py:318-325.

#### `server/test_eval_isolation.py` (test, batch)

**Analog:** `server/test_m7_backend.py` eval-runner section + `server/api/admin/eval.py` routes (`/api/admin/eval/consistency` 49-58, `/virtual-candidates` 65-74, `/results/{task_id}` 77-90). Assert business DB untouched (`data/app.db` row count unchanged) after a run.

#### `server/services/scoring.py` + `server/services/report.py` (service, CRUD) + `server/test_bad_case.py` (test)

**Analog:** `scoring.py` `score_session` (240-324) writes `score_live`/`score_final` into `question_score`; `report.py` `generate_report` (160-243) is where report-final scoring surfaces. `feedback` table already has `status='bad_case'` (db.py:307).

D-75 divergence detection (`|score_live - score_final| >= threshold` → `bad_case_candidate`): the comparable pair already lives in `question_score` (columns `score_live`, `score_final` at db.py:233-234). Detection point = `generate_report` (after `aggregate_session_scores`) or `score_session` — planner's discretion. Threshold = open param (§2.3) → config placeholder + gate. The mock note: `_mock_score` returns constant 3 (scoring.py:80-81), so `score_live == score_final == 3` under mock → divergence is always 0 (document, don't fabricate — D-72). `test_bad_case.py` must seed a hand-divergent `question_score` row (INSERT with `score_live=5, score_final=1`) to exercise the detector.

#### `server/config.py` (config) + `server/test_input_limits.py` (test)

**Analog:** `server/services/scoring.py:38-40` — existing per-type limit constant precedent:
```python
_MAX_KEY_LEN = 512
MAX_ANSWER_LEN = 64 * 1024
```
D-78 = add named constants in `config.py` (JD length / file lines / answer length / prompt max_tokens / pagination limit) following the `config.py` §8.4 constant style (see `REFINE_MIN_TOKENS` 49, `FOLLOWUP_MAX` 51). Values = open params (§31-6) → placeholder + "实施期校准" comment (do NOT fabricate numbers). `test_input_limits.py` hits the routes with oversized inputs and asserts 4xx.

#### `server/main.py` (config/entrypoint) + `server/test_secret_gate.py` (test)

**Analog:** itself, CR-05 fail-closed (59-67):
```python
if config.JWT_SECRET in _INSECURE_JWT_DEFAULTS:
    raise RuntimeError("JWT_SECRET 未配置或为公开默认值：拒绝启动 ...")
```
D-77 (gate): current code already fail-closes ALWAYS (stricter than D-77). `test_secret_gate.py` imports `main`/`config` and asserts the reject/warn behavior; note TestClient skips startup (so `init_db()` is called directly in tests — the startup guard is only exercised by direct `_startup()` invocation). JWT default literal is `config.py:16` (`"change-me-in-.env"`); `_INSECURE_JWT_DEFAULTS` is `main.py:16`.

---

### Gate D-76 — JWT HttpOnly cookie (only if user confirms)

**Analogs (all "self", role-match):**
- `server/core/security.py:33-50` `_current_user` (Bearer `HTTPBearer` + `jwt.decode`) → cookie variant reads token from request cookie instead.
- `server/api/auth.py:36-48` `login` → add `Set-Cookie: HttpOnly + SameSite=Lax` response.
- `web/src/api/index.js:11-18` axios interceptor + `web/src/utils/sse.js:21-28` fetch — remove `Authorization: Bearer localStorage` header, switch `credentials: 'include'`.
- `server/main.py:50-56` CORS already has `allow_credentials=True` (needed for cookie).

This is a **关口包 (D-76)** — the plan should branch; the above are the enumerated change surface (RESEARCH Open Question 1).

---

## Shared Patterns

### Mock 三件套 (temp DB + `LLM_PROVIDER=mock` + `JWT_SECRET=test-secret`)
**Source:** `server/test_m5_backend.py:11-15` (replicated in `test_m7_backend.py:11-14`, `test_p0_security.py:16-19`, and 24 other test files)
**Apply to:** ALL test files (conftest.py centralizes it in 06-02)
```python
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"
```

### `_q()` read-only helper (avoids SQLite single-writer lock)
**Source:** `server/test_m5_backend.py:32-38`
**Apply to:** ALL new test files (migration, m1_regression, e2e, bad_case, input_limits, eval_isolation)
```python
def _q(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```

### Auth header helper (register→login→Bearer)
**Source:** `server/test_m5_backend.py:130-135` (`_auth_headers`), `server/test_p0_security.py:132-155` (`_ensure_admin`/`_admin_headers`)
**Apply to:** E2E + bad_case + input_limits + eval_isolation (any test hitting protected routes)
```python
def _auth_headers(username: str = "candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409)
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}
```

### SSE answer consumption
**Source:** `server/test_m5_backend.py:144-158` `_stream_answer`
**Apply to:** E2E (answer loop), any test driving `POST /answer`
```python
with client.stream("POST", f"/api/assessment/sessions/{sid}/answer",
                   json={"question_id": question_id, "answer": answer}, headers=headers) as r:
    assert r.status_code == 200
    lines = [ln for ln in r.iter_lines() if ln.startswith("data: ")]
events = [json.loads(ln[6:]) for ln in lines]
decision = next(e for e in events if e["type"] == "decision")
done = next(e for e in events if e["type"] == "done")
```

### Ownership/越权 (404 uniform-absence, D-01)
**Source:** `server/core/security.py:63-99` `load_owned_session` / `load_owned_report`
**Apply to:** E2E 越权 re-cover (assert 404, not 403); all new controller-facing tests.

### Seed helper (position + confirmed model → `(pid, mid)`)
**Source:** `server/test_m5_backend.py:43-73` `_seed_position_with_confirmed_model`
**Apply to:** E2E + m1_regression + any test needing a confirmed model.

### raw SQL + `get_conn()` per-call + explicit commit
**Source:** `server/db.py` `get_conn` (412-417), all services (`scoring.py`, `aggregate.py`, `report.py`) — project convention (no ORM).
**Apply to:** ALL new service/controller code in this phase (bad_case detection, eval isolation, get_session fix).

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `.github/workflows/ci.yml` | config (CI) | batch | No CI infra exists in repo (`ls .github` → absent). Use RESEARCH Standard Stack + `web/package.json:8` build script. |

*(All other files have a self-analog or an exact pytest/seed analog — this is a refactor-and-harden phase, not greenfield.)*

## Metadata

**Analog search scope:** `server/` (db, config, main, api/, core/, services/, test_*), `eval/`, `web/src/`
**Files scanned:** ~40 (24 test files + db/config/main/security/auth/assessment/eval/admin-eval/scoring/aggregate/aggregation/report + web api/sse/Chat/FormCard + requirements/package.json)
**Pattern extraction date:** 2026-09-05
**Staleness flags surfaced:** (1) orchestrator listed `server/api/index.js` — does not exist (frontend-only fix in `web/src/api/index.js`). (2) CONTEXT/TESTING numeric `31.4`/`15.2` are stale — actual `test_m6_backend.py:200/217` assert `9.5`/`24.5` (trust the file). (3) `_gate_check` is in `services/aggregation.py`, NOT `aggregate.py`.
