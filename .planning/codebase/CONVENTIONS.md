# Coding Conventions

**Analysis Date:** 2026-09-02

## Project Layout Context

Three code areas with distinct conventions:

- **Backend**: Python 3.11+ / FastAPI / raw SQLite in `server/` (no ORM)
- **Frontend**: Vue 3 + Element Plus + Vite in `web/`
- **Prototypes**: static HTML/CSS in `prototype/` (design artifacts, not production code — do not apply backend/frontend conventions here)

**No linter or formatter configs exist** (no `.eslintrc`, `.prettierrc`, `ruff.toml`, `pyproject.toml`, `setup.cfg`). Conventions below are de facto from existing code. Match them exactly.

## Documentation Language

**All comments, docstrings, error messages, and UI strings are Simplified Chinese.** Git commit messages use Conventional Commits type prefix + Chinese description (e.g., `feat(prototype): 新增...`, `docs: 回写...`, `fix(prototype): ...`).

## Naming Patterns

**Files:**
- Python: `snake_case.py` — e.g., `server/services/question_selection.py`
- JS modules: `camelCase.js` or `index.js` — e.g., `web/src/utils/sse.js`, `web/src/api/index.js`
- Vue components/views: `PascalCase.vue` — e.g., `web/src/components/FormCard.vue`, `web/src/views/admin/TestCenter.vue`
- Test files: `test_*.py` co-located in `server/` (flat, not a `tests/` dir)

**Functions:**
- Python: `snake_case`; private helpers prefixed `_` — e.g., `_score_objective()` in `server/services/scoring.py`
- JS: `camelCase` — e.g., `function load()`, `async function onSubmit()`

**Variables/Constants:**
- Python module constants: `UPPER_SNAKE` — e.g., `NOISE_HEADERS`, `MIN_ANSWER_CHARS`, `CATEGORY_QUOTA`
- JS: `camelCase`; DOM/template refs via `ref()` — e.g., `const formRef = ref()`

**Types (Pydantic):**
- Request/response models: `PascalCase` in `server/schemas.py` — e.g., `ExtractResult`, `JdImportRequest`
- Use `Literal[...]` for enum-like fields, `Field(ge=1, le=5)` for bounds
- Pydantic v2 style: `model_config = {"populate_by_name": True}` (not v1 `class Config`)

## Code Style

**Formatting:**
- No automated formatter. Python: 4-space indent, ~100 col, double-quoted strings. JS/Vue: 2-space indent, single quotes, no semicolons at line ends, trailing commas in multiline.
- Blank-line section separators with `# ---------- 注释 ----------` comment banners inside Python modules (see `server/services/scoring.py`, `server/api/assessment.py`).

**Linting:**
- None configured. Existing code uses `# noqa: E402` after post-env-setup imports and `# noqa: BLE001 - 原因` on broad excepts with a rationale comment. Preserve this pattern.

## The Module Docstring Rule (Critical)

Every Python module starts with a Chinese one-line docstring stating purpose + design-doc section reference:

```python
"""终局逐题评分（07 文档 §10，R1 双分合成）。"""
```

Prompts additionally carry a version line: `"""P-score 终局逐题评分提示词。版本: v1 (2026-08-30)"""` (see `server/services/prompts/score.py`).

The SSOT is `design/final-design/总设计文档.md`. Reference sections (`07 文档 §6.2`, `05 文档 §5`) rather than restating design in code comments.

## Import Organization

**Python order:**
1. stdlib (`import json`, `import re`, `from datetime import datetime, timezone`)
2. third-party (`from fastapi import APIRouter, Depends, HTTPException, status`)
3. local relative (`from ..db import get_conn`, `from .llm import call_llm_json`)

- Deferred (function-body) imports are used deliberately to break circular deps and defer heavy deps: `server/services/pipeline.py` imports `call_llm_json` inside `extract_items()`; `scripts/seed_admin.py` imports `passlib.context` inside `main()`. Follow suit when adding cross-service imports.
- In `server/main.py`, `.env` is loaded by `_load_env()` BEFORE importing `server.db` — all subsequent imports carry `# noqa: E402`. Any new router import must be added after `_load_env()` in this style.

**JS order:**
1. vue/vue-router/pinia/element-plus
2. local modules (`import api from '../api'`, `import { assessment } from '../../api'`)

**Path aliases:**
- None. JS uses relative paths only (`../../components/FormCard.vue`). Backend tests self-insert repo root: `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` then `from server.db import ...`.

## Error Handling

**Backend pattern — raise HTTPException with status constants and Chinese detail:**

```python
raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
raise HTTPException(status.HTTP_409_CONFLICT, "该题已作答")
raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 question_id 或 answer")
```

(from `server/api/assessment.py`)

- Status codes used: 404 not found, 401 auth failed, 403 role denied, 409 state conflict, 422 missing fields.
- `status` module constants (`status.HTTP_404_NOT_FOUND`) in `server/api/assessment.py`, `server/api/auth.py`; bare ints (`raise HTTPException(404, ...)`) in `server/api/admin/eval.py` — prefer the constant form.
- Service layer raises `ValueError(f"会话不存在: {session_id}")` for precondition failures (`server/services/scoring.py`).
- Pipeline failures are swallowed and recorded, not propagated: `run_parse_pipeline` in `server/services/pipeline.py` catches `Exception` (`# noqa: BLE001 - 单 JD 失败不阻塞其他`), writes `status='failed', error_msg=?` to `jd_record`. Background tasks (`_generate_report_task`, `run_aggregate`) fail silently with a comment noting the admin-side fallback.
- LLM retry: never call LLM SDK directly. Use `call_llm_json()` from `server/services/llm.py` which retries `config.LLM_RETRY` times, writes `llm_trace` rows, and raises `RuntimeError` after exhausting retries.

**Frontend pattern — try/catch + ElMessage with server detail:**

```js
} catch (e) {
  ElMessage.error(e.response?.data?.detail || '表单提交失败')
}
```

- Global 401 handling in the axios response interceptor (`web/src/api/index.js`): clears localStorage, redirects to `/login`.
- Status-code-specific branches: `if (err.response?.status === 409) { ... }` (see `web/src/views/admin/Dict.vue`).
- `streamAnswer` in `web/src/utils/sse.js` normalizes fetch errors to match axios shape (`throw new Error(body?.detail)`).
- Abort on unmount: `onBeforeUnmount(() => abortStream?.())` in `web/src/views/assessment/Chat.vue`.

## LLM Integration Pattern (Critical)

All LLM calls follow one shape — a system prompt constant + builder function in `server/services/prompts/<call_type>.py`, and a call through `call_llm_json` with an offline mock:

```python
# server/services/prompts/score.py
SCORE_SYSTEM = """你是一名公正的评估官。 ... """   # Chinese system prompt, JSON output contract stated

def score_prompt(question: dict, answer: str, position_context: str) -> str:
    return f"""岗位：{position_context}
题目：{question['stem']}
..."""
```

```python
# caller, e.g. server/services/scoring.py
def _mock_score(system_prompt: str, user_prompt: str) -> dict:
    return {"score": 3, "evidence_quote": "mock quote", "reason": "mock reason"}

result = call_llm_json(
    "score", question_id, SCORE_SYSTEM,
    score_prompt(q, answer_text, q["position_name"]),
    mock_fn=_mock_score,
)
```

Rules:
- Every new LLM call_type must be added to the `llm_trace.call_type` CHECK constraint in `server/db.py` `_DDL` (and the `_migrate_llm_trace` rebuild if pre-existing DBs need it).
- Mocks must be deterministic (same input → same output) so offline tests and consistency evals pass.
- Validate LLM output against a Pydantic model in `server/schemas.py` (e.g., `ExtractResult(**result).model_dump()`), or index keys defensively with `.get()`.
- Prompts must state the JSON output contract explicitly and instruct "只输出一个 JSON 对象".

## Database Access Pattern (Critical)

Raw SQLite, no ORM. Connection per operation via `get_conn()` from `server/db.py` (Row factory + `PRAGMA foreign_keys = ON`):

```python
conn = get_conn()
row = conn.execute(
    "SELECT user_id, username, role FROM user WHERE username=?",
    (body.username,),
).fetchone()
if row is None:
    raise HTTPException(status.HTTP_404_NOT_FOUND, "...")
conn.execute(
    "UPDATE jd_record SET status='parsing' WHERE jd_id=?", (jd_id,),
)
conn.commit()
```

Rules:
- Always `?` placeholders with a params tuple; dynamic IN-clauses build placeholders: `",".join("?" * len(ids))` (see `server/services/pipeline.py`, `server/api/admin/trace.py`).
- SQL keywords UPPERCASE, string split across lines with implicit concatenation.
- Write then `conn.commit()`; connections opened by `get_conn()` in API handlers are not explicitly closed (GC'd); test-side read helpers DO close (see TESTING.md).
- `llm_trace` writes open their own connection — therefore commit the outer connection BEFORE any LLM call to avoid `database is locked` (documented in `server/api/assessment.py` and `server/services/scoring.py`). Compute in memory first, write in a single transaction at the end.
- Schema changes go in `_DDL` in `server/db.py` with a matching idempotent migration function (`_migrate_*`) when an old DB needs a CHECK rebuild. Comment each table block with the design-doc reference.
- Timestamps: always `now_iso()` from `server/services/pipeline.py` (UTC ISO string). IDs: always `new_id("prefix")` from the same module — `f"{prefix}_{uuid4().hex[:12]}"`. Prefix conventions in use: `u_` user, `pos` position, `jd`, `cm` model, `c` item, `t` trace, `sess` session, `aq`, `msg`, `qb`/`q` question, `qs` score, `fb` feedback, `ev` eval task, `raw`, `form`, `rp` report.

## ID/Env/Config Conventions

- Config is read ONCE at import time in `server/config.py` via `os.environ.get("NAME", default)`; group constants under `# ---- 分组 ----` banners. Add new env-configurable constants there, never read `os.environ` elsewhere in `server/`.
- `.env` loading is the minimal hand-rolled parser in `server/main.py` (`_load_env()`, `os.environ.setdefault`). No python-dotenv dependency.
- Secrets: `.env` gitignored; `.env.example` documents keys. Never commit real keys.

## API Layer Conventions

- Router per area: `router = APIRouter(prefix="/api/admin", tags=["admin-xxx"], dependencies=[Depends(require_admin)])` at top of each file in `server/api/` and `server/api/admin/`.
- Admin routers put `dependencies=[Depends(require_admin)]` on the router; assessment router uses `dependencies=[Depends(require_login)]` (see `server/api/assessment.py`).
- Auth dependencies: `require_login`, `require_admin` from `server/core/security.py`. Handler needing user data takes `user: dict = Depends(require_login)`.
- New routers must be registered in `server/main.py` after `_load_env()` (with `# noqa: E402`).
- Request bodies: either a Pydantic model from `server/schemas.py` (auth, JD import) or `body: dict` with `body.get(...)` + explicit 422 validation (most admin/assessment endpoints). Prefer `body: dict` for internal admin endpoints to stay consistent with existing code.
- Responses: plain `dict` or `list[dict]` (convert rows with `[dict(r) for r in rows]`); `response_model` only used on `/api/auth/login`.
- Async pattern: heavy work via `BackgroundTasks` (report generation, aggregation, eval runs) + frontend polls a GET endpoint. 202 status on trigger endpoints.
- Success creates return `status_code=status.HTTP_201_CREATED`.
- URL paths: kebab/lowercase segments, resource-oriented (`/api/assessment/sessions/{session_id}/answer`).

## Frontend Conventions

**Vue SFC structure (fixed order):**
1. `<template>` (Element Plus components + scoped template markup)
2. `<script setup>` (imports, then `const route = useRoute()` etc., refs/reactive, functions, lifecycle hooks at bottom: `onMounted(load)`)
3. `<style scoped>`

**Script setup essentials:**
- `<script setup>` always (no Options API) — see `web/src/views/admin/Dict.vue`, `web/src/views/assessment/Chat.vue`
- State: `ref()` for scalars/objects, `reactive({})` for form objects (`const filters = reactive({ category: '', ... })`)
- Props/emits: `defineProps({...})` / `defineEmits([...])` — see `web/src/components/FormCard.vue`
- Domain maps as small function lookup: `function categoryLabel(v) { return { hard_skill: '硬技能', ... }[v] || v }` (see `web/src/components/ItemTable.vue`)
- Computed for derived state; optional chaining `?.` and nullish `??` throughout

**Routing (`web/src/router/index.js`):**
- Lazy routes: `component: () => import('../views/admin/Dict.vue')`
- Route meta: `{ public: true }` (login/register), `{ role: 'admin' }` (admin pages), `{ role: 'candidate' }` (chat/report), `{ requiresAuth: true }`
- Guard in `router.beforeEach`: unauthenticated → `/login?redirect=...`; role mismatch → `auth.homePath`
- Path params use snake_case matching backend: `/assessment/session/:session_id`

**API layer (`web/src/api/index.js`):**
- Single axios instance `baseURL: '/api'`, timeout 15000, request interceptor injects `Bearer` token from localStorage (not Pinia — initialization-order comment)
- Domain-grouped exports: `assessment = { listPositions, createSession, ... }`, `admin = { eval, trace, feedback }` with methods mirroring backend routes. Add new endpoints to the matching domain object; create a new domain object for new areas.
- Streaming must NOT use axios: use `streamAnswer()` in `web/src/utils/sse.js` (fetch + ReadableStream; tolerates both SSE and single-JSON responses; returns `abort()`)

**State (Pinia):**
- Options-API style store: `defineStore('auth', { state, getters, actions })` in `web/src/stores/auth.js`
- Token/user persisted to localStorage keys `token` / `user`; `homePath` getter maps role → landing page

**Styling:**
- Design tokens in `web/src/assets/grail-notion.css` (Grail × Notion palette: `--deck`, `--panel`, `--ink-1/2/3`, pastel status colors). Admin pages follow this system; page-specific styles scoped in the SFC.
- BEM-ish classes in bespoke pages: `.chat-hybrid__message--user` (`web/src/views/assessment/Chat.vue`)
- CSS variables for theming; dark mode via `html[data-theme="dark"]` and `:global()` selectors
- Element Plus for tables/forms/tabs/messages (`el-table`, `el-form`, `el-tabs`, `ElMessage`, `ElMessageBox`); zh-cn locale set in `web/src/main.js`

**Vue file placement:**
- Reusable UI: `web/src/components/` (AdminNav, CandidateNav, FormCard, ItemTable)
- Route pages: `web/src/views/admin/` (admin), `web/src/views/assessment/` (candidate), `web/src/views/` root (Login/Register)

## Comments

**When to Comment:**
- Explain WHY (design-doc refs, SQLite locking rationale, mock determinism guarantees), not what. Existing comments carry rationale like `# 先提交用户消息再调 LLM：llm_trace 用新连接写库，本连接持写事务会 database is locked`.
- Mark deliberate catch-alls: `except Exception:  # noqa: BLE001 - 评测失败也要留痕`.
- JS section banners: `// ---- 新增 ----`, `// callbacks: {onDecision, onReply, onDone, onError}`.

**Docstrings:**
- Every module: single-line Chinese summary with design-doc ref.
- Public service functions: one-line Chinese summary describing return shape: `"""长输入精炼。返回 (refined_text, raw_hash|None)；未触发阈值时原样返回 (text, None)。"""`

## Function Design

**Size:** Small, single-purpose; private helpers extracted aggressively (e.g., `server/services/interview.py` has `_load_session_question`, `_count_followups`, `_build_user_prompt`, `_mock_interview` around one public `decide_next_action`).

**Parameters:** Keyword-only where many optional params (see `_insert_question(conn, *, scope, position_id, item, ...)` in `server/services/question_bank.py`).

**Type hints:** Modern Python 3.10+ syntax throughout — `str | None`, `list[dict]`, `tuple[int, str]`, `dict[str, Any]`. Always annotate returns on service functions.

**Return values:** dicts with documented shape; tuples where 2-valued; never `None` silently for missing DB rows — raise or 404.

## Module Design

**Exports:** One public entry point per service module (e.g., `generate_question_bank`, `select_questions_for_session`, `refine_user_input`), everything else `_`-private. API modules export only `router`.

**Barrel Files:** Only `__init__.py` package markers (empty). No index barrels in JS — import directly from module paths.

**Anti-patterns to avoid:**
- Calling OpenAI SDK directly instead of `call_llm_json` (breaks tracing, retry, mock mode)
- Writing SQL with f-string interpolation of values (breaks placeholder convention; f-strings only for placeholder counts / WHERE-clause assembly with `?` params)
- Returning SQLAlchemy/ORM models — this project has no ORM; return `dict(row)`
- Adding env reads outside `server/config.py`
- Creating Vue pages without route registration in `web/src/router/index.js`
- Skipping the Chinese module docstring and design-doc reference

---

*Convention analysis: 2026-09-02*
