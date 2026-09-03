# Testing Patterns

**Analysis Date:** 2026-09-02

## Test Framework

**Runner:**
- pytest (via TestClient for API tests) + plain Python scripts
- Config: none (no `pytest.ini`, `conftest.py`, `pyproject.toml` — defaults only)
- httpx is required by `fastapi.testclient` (in `server/requirements.txt`)

**Assertion Library:**
- pytest `assert` for pytest-collected tests
- Custom `check()` helper for script-style tests (see below)

**Run Commands:**
```bash
# pytest-collected backend tests (API-level, M5/M7)
cd server && python -m pytest test_m5_backend.py -v

# Script-style tests (run directly, exit code = pass/fail)
cd server && python test_m6_backend.py
cd server && python test_question_bank.py

# Whole suite via repo root
python -m pytest server/test_m5_backend.py server/test_m7_backend.py -q

# Eval harness (against live/dev DB, needs seeded data)
python eval/consistency_test.py --session-id <sid> --runs 3
python eval/virtual_candidates.py --position-id <pid>
```

**IMPORTANT — two test styles coexist:**

| Style | Files | Runner | Status |
|-------|-------|--------|--------|
| pytest + TestClient | `server/test_m5_backend.py`, `server/test_m7_backend.py` | `python -m pytest` | Clean |
| Script with `check()` + `__main__` | `server/test_m6_backend.py`, `server/test_question_bank.py` | direct `python` execution | **NOT pytest-collectible** |

The script-style files break under pytest: `test_question_bank.py` defines `test_generation(pid: str, mid: str)` — pytest mistakes `pid`/`mid` for missing fixtures (3 ERRORS: `fixture 'pid' not found`). `test_m6_backend.py`'s `_test_*` functions only run inside `if __name__ == "__main__"`. The module-4 design doc (`design/final-design/模块四设计-测试闭环.md` line 49) records this as known debt: "统一 pytest 收集 ... 需重构为可收集 pytest 或明确独立命令". **New tests must be pytest-collectible (M5/M7 style).**

**NEVER run all four server test files in one pytest invocation** — each sets `os.environ["DB_PATH"]` at import time to its own temp dir; the first import wins, later files silently share the first file's DB (state bleed between suites).

## Test File Organization

**Location:**
- Backend tests co-located flat in `server/` (no `tests/` dir), prefixed `test_`
- Eval harness in `eval/` at repo root (deliberately outside `server/` — "可迁移，与具体岗位/模型解耦")
- No frontend tests (no vitest/jest config, no `*.spec.js` files)

**Naming:**
- Files: `test_<milestone>_backend.py` by milestone (M5 = assessment core, M6 = scoring/report, M7 = test-loop admin API)
- Functions: `test_<behavior>` for pytest style; `_test_<area>` helpers + `check()` for script style

**Structure:**
```
server/
├── test_m5_backend.py      # pytest + TestClient: sessions, answers, scoring, forms
├── test_m6_backend.py      # script: dual scoring, aggregation, report, feedback
├── test_m7_backend.py      # pytest + TestClient: trace viewer, feedback, eval runner
└── test_question_bank.py   # script: question gen, selection, prompts
eval/
├── assertions.py           # reusable assertion predicates -> (passed, message)
├── consistency_test.py     # b: re-run scoring N times, variance <= 1
├── virtual_candidates.py   # c: strong/medium/weak candidate tiers
├── fixtures/               # empty
└── results/                # empty (results persist to eval_results table instead)
```

## Test Structure

**Suite Organization (pytest style, from `server/test_m5_backend.py`):**

```python
"""M5 测评核心后端测试：会话创建/选题、答题（精炼+决策）、打分（客观+主观）。

全程 LLM_PROVIDER=mock 离线运行；DB 用临时文件，不碰 data/app.db。
运行：cd server && python -m pytest test_m5_backend.py -v
"""
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_m5.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)
```

**Patterns:**
- Setup: env vars at module top BEFORE importing `server.*` (config reads env at import time — comment this ordering requirement)
- Setup: `init_db()` called explicitly at module level because TestClient does not fire startup events
- Teardown: none — temp DB in `tempfile.mkdtemp()` is abandoned (never deleted)
- Assertion: bare `assert cond, detail` with response text: `assert r.status_code == 201, r.text`

**Script style (`server/test_m6_backend.py`):**

```python
PASS, FAIL = 0, 0

def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")

if __name__ == "__main__":
    init_db()
    ctx = _seed_full_chain()
    _test_dual_scoring(ctx)
    _test_aggregation(ctx)
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    sys.exit(1 if FAIL else 0)
```

## Test Database Isolation (Critical)

Every test file sets up its own temp DB before imports:

```python
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_m5.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"       # offline, deterministic
os.environ["JWT_SECRET"] = "test-secret"   # (m5/m7 only)
```

Rules:
- `LLM_PROVIDER=mock` is mandatory — the whole suite runs offline with deterministic mock LLM outputs (see CONVENTIONS.md mock pattern)
- Never point `DB_PATH` at `data/app.db` (the live DB); each file's docstring states this: "DB 用临时文件，不碰 data/app.db"
- `sys.path.insert` of repo root enables `from server.db import ...` imports
- Because isolation is import-order-dependent, run one file per pytest invocation

**Test-side read helper** (`server/test_m5_backend.py`) — opens, reads, closes to avoid holding a write lock:

```python
def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```

## Mocking

**Framework:** No mocking library (no unittest.mock / no monkeypatch usage). All isolation is architectural:

**Patterns:**

1. **Mock LLM provider** — the `mock_fn` parameter of `call_llm_json`:

```python
# server/services/scoring.py
def _mock_score(system_prompt: str, user_prompt: str) -> dict:
    return {"score": 3, "evidence_quote": "mock quote", "reason": "mock reason"}
```

When `LLM_PROVIDER=mock`, `call_llm_json` short-circuits real HTTP and calls `mock_fn`. Mocks parse the user prompt to derive deterministic output (e.g., `server/services/question_bank.py` `_mock_question_gen` extracts ability name from prompt lines; `server/services/aggregate.py` `_mock_aggregate_level` takes the mode of `Lv\d` tokens). Mocks are co-located with the caller service, not in the test file.

2. **Password hashing inline** — tests needing seeded users hash directly with passlib rather than importing the app's context:

```python
# server/test_m7_backend.py
from passlib.context import CryptContext
pwd_ctx = CryptContext(schemes=["bcrypt"])
conn.execute("INSERT INTO user(...)", (new_id("u"), "admin", pwd_ctx.hash("admin"), "admin", ...))
```

3. **Direct DB seeding** — test fixtures insert rows with raw SQL through `get_conn()` (no factories/builders), see Fixtures below.

**What to Mock:**
- All LLM calls (via `LLM_PROVIDER=mock` + `mock_fn`) — required for offline determinism

**What NOT to Mock:**
- The database (use a temp file DB instead)
- The FastAPI app (tests hit real routes through `TestClient(app)`)
- Business services (tests call them directly: `refine_user_input`, `_score_objective`, `score_question`, `generate_report`)
- Time (timestamps via `now_iso()` are real; ordering assertions use rowid/seq, not clock)

## Fixtures and Factories

**Test Data:** hand-seeded SQL per test, idempotent:

```python
# server/test_m5_backend.py
def _seed_position_with_confirmed_model() -> tuple[str, str]:
    """建 active 岗位 + confirmed 模型 + competency_item（hard/soft/experience 各若干）。"""
    conn = get_conn()
    pid = new_id("pos")
    mid = new_id("cm")
    now = now_iso()
    conn.execute(
        "INSERT INTO position(position_id, name, status, created_at) VALUES(?,?,?,?)",
        (pid, "后端开发工程师", "active", now),
    )
    items = [
        {"std_name": "Python", "category": "hard_skill", "importance": "required", "weight": 0.3},
        ...
    ]
    conn.commit()
    conn.close()
    return pid, mid
```

`_seed_full_chain()` in `server/test_m6_backend.py` builds the complete dependency chain (position → user → model → items → question_bank → session → assessment_question → messages → score_live → form_submission) and returns a `ctx: dict` threaded through test functions.

**Auth helper:**

```python
# server/test_m5_backend.py
def _auth_headers(username: str = "m5_candidate") -> dict:
    r = client.post("/api/auth/register", json={"username": username, "password": "pw123456"})
    assert r.status_code in (200, 201, 409), r.text   # 409 tolerated: idempotent re-register
    r = client.post("/api/auth/login", json={"username": username, "password": "pw123456"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}
```

Admin variant `_auth()` in `server/test_m7_backend.py` logs in as a pre-seeded `admin`/`admin` user (`_ensure_admin()` creates it idempotently on first run).

**Fixture data conventions:**
- Data is realistic Chinese domain content (岗位 "后端开发工程师", stems like "MySQL 默认事务隔离级别是？")
- Seed helpers are idempotent or tolerate 409s so tests are re-runnable
- Each test creates its own entities with `new_id()` prefixes — tests never share rows across files
- `server/test_m5_backend.py` seeds a full difficulty chain to verify selection order: Python easy→medium→hard with `chain_key`/`chain_seq`
- Deliberate test answers are tuned to mock behavior: answers > 20 chars avoid followup; "我会 Python。" (short) triggers it

**Location:** seed helpers live at the top of each test file (`_seed_*` prefix). `eval/fixtures/` is empty; eval data is generated at runtime (`virtual_candidates.py` creates 3 objective questions keyed to `_KEYWORDS = ["索引", "事务", "缓存"]`).

## Coverage

**Requirements:** None enforced (no coverage config, no CI, no thresholds)

**View Coverage:**
```bash
cd server && python -m pytest test_m5_backend.py --cov=server  # requires pytest-cov (not installed)
```

**De facto coverage** (what the existing suite exercises):
- `server/api/`: auth, assessment, admin/{positions, jds, models, dict, users, trace, feedback, eval} — most routes hit at least once
- `server/services/`: refine, scoring, question_selection, question_bank, interview (via API), aggregation, report
- Frontend: zero test coverage
- `server/api/admin/users.py`, `server/api/admin/feedback.py` partially covered via `test_m7_backend.py`

## Test Types

**Unit Tests:**
- Pure function tests: `test_objective_scoring` calls `_score_objective(answer_key, answer)` directly (`server/test_m5_backend.py`)
- Prompt builders: `server/test_question_bank.py` `test_prompts` asserts prompt content contains stems/rubrics/answers
- Config: `test_config_refine_min_tokens` pins `config.REFINE_MIN_TOKENS == 500`

**Integration Tests (dominant style):**
- Full API flows through `TestClient`: register → login → create session → answer loop (followup → next → ... → finish) → score → verify DB state
- Service-level integration: `server/test_m6_backend.py` calls `score_question` → `score_session` → `aggregate_session_scores` → `generate_report` in sequence, asserting the persisted rows and report JSON shape at each stage
- DB-state assertions made directly with `_q()` SQL after API calls — tests verify persistence, not just HTTP responses

**E2E Tests:** Not used for the web app. The eval harness (`eval/`) is the backend E2E substitute — it drives full sessions through the service layer against a real DB.

**Eval harness (project-specific):**
- `eval/assertions.py` — reusable predicates returning `(passed, message)`: `assert_score_consistency(scores, max_variance=1)`, `assert_tier_ordering(strong, medium, weak)`, `assert_weakness_identified(report, expected)`
- `eval/consistency_test.py` — design-doc requirement "固定 transcript 复跑断言 score_final 分差≤1（temperature=0）"; returns `{test_name, session_id, runs, passed, details}`
- `eval/virtual_candidates.py` — strong/medium/weak tiers, asserts `strong > medium > weak` on total_score
- Both are wired to the admin UI through `server/api/admin/eval.py` (BackgroundTasks + `eval_results` table + polling); test functions are imported and run server-side: `from eval.consistency_test import test_scoring_consistency`

## Common Patterns

**Async Testing:**
- No async tests. BackgroundTasks execute synchronously inside TestClient responses, so reports/evals are ready immediately after the triggering POST. Where true async polling exists (admin UI), tests avoid it (see `server/test_m7_backend.py`: "这里绕过 API 直接插库，专注测 admin 侧闭环").

**Error Testing:**

```python
# 404 for missing resources
r = client.get("/api/admin/eval/results/not-exist", headers=headers)
assert r.status_code == 404

# 409 state conflict (re-answer an already-answered question)
r = client.post(f"/api/assessment/sessions/{sid}/answer",
                json={"question_id": q1, "answer": long_answer}, headers=headers)
assert r.status_code == 409

# Login failures via service (m6 script style, calling handler function directly)
result = submit_feedback(rpt_row["report_id"],
    {"item_id": ctx["items"][0]["item_id"], "feedback_text": "Python 分给低了"})
check("status=pending", result["status"] == "pending")
```

**Idempotency testing (recurring theme):**

```python
# server/test_m6_backend.py — regenerating a report must not duplicate rows
rpt2 = generate_report(ctx["session_id"])
n = conn.execute("SELECT COUNT(*) c FROM report WHERE session_id=?", ...).fetchone()["c"]
check("重复生成幂等（同会话仅 1 行 report）", n == 1)
```

**Numerical tolerance:**

```python
check("total_score 一致", abs(rpt["total_score"] - 31.4) < 0.01)
check("Python score = 0.19 * 4/5 * 100 = 15.2", abs(py["score"] - 15.2) < 0.01)
```

**Writing new tests — checklist:**
1. Create `server/test_<area>.py` with the standard header: temp `DB_PATH`, `LLM_PROVIDER=mock`, `sys.path.insert`, `# noqa: E402` imports, `init_db()`, `client = TestClient(app)`
2. Use pytest function style with descriptive `test_*` names (no parameters — pytest will treat them as fixtures)
3. Seed with `_seed_*` helpers returning IDs/ctx dicts; use `_auth_headers()`/`_auth()` for auth
4. Assert both HTTP response AND DB state (`_q()` helper)
5. Keep mock-mode determinism in mind: subjective scores are always 3, objective is regex hit = 5 / miss = 1, followup triggers under 20 chars
6. Run `python -m pytest server/test_<area>.py -v` from repo root (or `cd server` first) — single file per invocation
7. Never import two test modules in one process (DB_PATH collision)

---

*Testing analysis: 2026-09-02*
