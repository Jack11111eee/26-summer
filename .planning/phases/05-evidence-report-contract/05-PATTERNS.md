# Phase 5: 证据链与报告契约 - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 12（9 改造/新建源文件 + 3 新建测试文件；另有 1 既有测试断言改写）
**Analogs found:** 12 / 12（全部命中——本 phase 是对既有文件的演进改造，analog 多为文件自身现有代码）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/db.py` | config/migration | file-I/O (DDL + data migration) | `server/db.py` `_migrate_question_score_phase3` + `_migrate_form_instance` + `_migrate_llm_trace` | exact (self) |
| `server/services/scoring.py` | service | CRUD (read msg → LLM → write score) | `server/services/scoring.py` `score_question`/`score_session`/`_fetch_answer_text` | exact (self) |
| `server/services/aggregation.py` | service | transform (read score → compute → dict) | `server/services/aggregation.py` `aggregate_session_scores` | exact (self) |
| `server/services/report.py` | service | CRUD + transform (aggregate → LLM → INSERT row) | `server/services/report.py` `generate_report` | exact (self) |
| `server/services/state_events.py` | utility/service | event-driven (append-only) | `server/services/state_events.py` `append_event` | exact (self) |
| `server/services/trace_link.py` **[新]** | service | CRUD (weak-assoc audit link write + import) | `server/services/state_events.py` `append_event` + `server/services/llm.py` `_record_trace` | role-match |
| `server/api/assessment.py` | controller | request-response + event-driven (BackgroundTasks) | `server/api/assessment.py` `request_report`/`_generate_report_task`/`submit_feedback` | exact (self) |
| `server/api/admin/reports.py` **[新]** | controller | request-response (state transition) | `server/api/admin/models.py` `confirm_model` + `server/api/admin/feedback.py` `review_feedback` | role-match |
| `server/api/admin/feedback.py` | controller | CRUD (UPDATE feedback) | `server/api/admin/feedback.py` + `server/api/admin/models.py` `confirm_model` | exact (self) |
| `server/api/admin/trace.py` | controller | CRUD (read) | `server/api/admin/trace.py` `get_session_traces` | exact (self) |
| `server/test_phase5_evidence.py` **[新]** | test | request-response + unit | `server/test_m5_backend.py`（候选侧 helpers） | exact |
| `server/test_phase5_report.py` **[新]** | test | request-response + unit | `server/test_m7_backend.py`（admin 侧 helpers）+ `test_m5_backend.py` | exact |
| `server/test_phase5_feedback.py` **[新]** | test | request-response + unit | `server/test_m7_backend.py` `test_feedback_lifecycle` | exact |
| `server/test_m6_backend.py` **[改]** | test | direct service call | `server/test_m6_backend.py:258`（幂等断言重写） | exact (self) |

---

## Pattern Assignments

### `server/db.py`（config/migration，file-I/O）

**Analog:** 自身既有迁移函数族。四个迁移形态全部有先例，逐条照抄：

**形态 1 — ALTER ADD COLUMN + PRAGMA 嗅探（幂等）**：`_migrate_question_bank_v2` lines 443-460 与 `_migrate_question_score_phase3` lines 553-568。question_score 加 `evidence_spans_json/measurement_target/rubric_version/scorer_version` 照此：
```python
cols = {r[1] for r in conn.execute("PRAGMA table_info(question_score)").fetchall()}
if not cols:
    return  # 表不存在（新建走 _DDL，已含新列）
for name, decl in (
    ("evidence_spans_json", "TEXT"),
    ("measurement_target", "TEXT"),
    ("rubric_version", "TEXT"),
    ("scorer_version", "TEXT"),
):
    if name not in cols:
        conn.execute(f"ALTER TABLE question_score ADD COLUMN {name} {decl}")
```
report/feedback 加列同形态（feedback 加 `user_id/note/reviewer/reviewed_at`；report 加 `report_status/review_status/version` + 发布字段）。N11 纪律：新列一律**无 DB CHECK**（枚举代码校验），NOT NULL 新列必须带常量 DEFAULT（SQLite ADD COLUMN 限制）。

**形态 2 — 新表 CREATE IF NOT EXISTS（存量库补建）**：`_migrate_form_instance` lines 588-607。trace_link 照此：
```python
def _migrate_trace_link(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS trace_link (
      id          TEXT PRIMARY KEY,
      trace_id    TEXT NOT NULL,
      entity_type TEXT NOT NULL,
      entity_id   TEXT NOT NULL,
      link_role   TEXT NOT NULL,
      created_at  TEXT NOT NULL,
      UNIQUE(trace_id, entity_type, entity_id, link_role)
    );
    """)
```
**注意**：trace_link 表必须同时在 `_DDL` 字符串（`server/db.py:9-370`）与 `_migrate_trace_link` 双轨定义（同 `_migrate_form_instance`/`_migrate_idempotency_record` 的双轨纪律——新库走 `_DDL`，存量库走迁移函数）。

**形态 3 — 表重建放宽 CHECK（不可 ALTER 时）**：`_migrate_llm_trace` lines 381-406 / `_migrate_feedback_status` lines 409-430（`SELECT sql FROM sqlite_master` 嗅探 → `executescript` 建 `_new` 表 → `INSERT SELECT` → `DROP` → `RENAME`）。本 phase 的 report/feedback 加列**不需要**重建表（加列用形态 1），但旧 `ref_id` 导入 trace_link 的**数据迁移**照此「迁移函数内嵌 executescript」的形态写。

**形态 4 — 旧 ref_id 导入 trace_link（数据迁移，D-57）**：无现成同构先例（新逻辑），但**迁移函数骨架**照 `_migrate_session_phase3`（lines 631-677——先嗅探列，再逐列 ALTER，再 executescript 建表/索引）。导入规则（RESEARCH 锁定）：逐实体表 `SELECT 1 FROM <table> WHERE <pk>=ref_id`，命中即定 `entity_type`；命不中保留 `ref_id` 原值不拆。`call_type → 实体表` 映射照 RESEARCH Pattern 1。

**注册点**：`init_db` lines 680-699。新迁移函数加在 `_migrate_session_phase3` 之后、`conn.executescript(_DDL)` 之前，与既有迁移同顺序调用：
```python
_migrate_session_phase3(conn)
_migrate_trace_link(conn)      # [新] 建表 + 旧 ref_id 导入
_migrate_question_score_phase5(conn)  # [新] question_score +4 列
_migrate_report_phase5(conn)          # [新] report 状态机列
_migrate_feedback_phase5(conn)        # [新] feedback 审计列
conn.executescript(_DDL)
conn.commit()
```

**get_conn 形态**（所有服务层/API 层写点的连接获取）：`server/db.py:373-378`（`row_factory = sqlite3.Row` + `PRAGMA foreign_keys = ON`）。trace_link 是弱关联（无 FK），但 `feedback.report_id` 已有 `REFERENCES report`（db.py:285）——版本化不再 DELETE report 行后 FK 不悬空。

---

### `server/services/scoring.py`（service，CRUD）

**Analog:** 自身。两个关键改造点：

**改造点 1 — evidence_spans 定位（score_question 内，D-55）**：`score_question` lines 102-148 是证据 quote 的生产点（主观题 `result["evidence_quote"]` line 145；客观题 `answer_text[:60]` line 135）。`_fetch_answer_text` lines 82-99 是现成原文回捞链路（raw_hash → context_raw.full_text），span 定位直接复用：
```python
# scoring.py:82-99 _fetch_answer_text 现成形态（span 定位输入）
conn = get_conn()
rows = conn.execute(
    "SELECT content, raw_hash FROM assessment_message"
    " WHERE session_id=? AND question_id=? AND role='user' ORDER BY created_at, rowid",
    (session_id, question_id),
).fetchall()
parts = []
for r in rows:
    if r["raw_hash"]:
        raw = conn.execute(
            "SELECT full_text FROM context_raw WHERE hash=?", (r["raw_hash"],)
        ).fetchone()
        parts.append(raw["full_text"] if raw else r["content"])
    else:
        parts.append(r["content"])
return "\n".join(parts)
```
`_locate_span`（新建纯函数）用 `answer_text.find(quote)`（Python str 索引天然 code point）+ `hashlib.sha256(quote.encode("utf-8")).hexdigest()`，定位失败返回 None → 降级 `quote_hash` only + `source_message_id=None`。**imports 补 `import hashlib`**（scoring.py 现有 imports 见 lines 14-20：`json`/`re` + `from ..db import get_conn` + `from .llm import call_llm_json`）。

**改造点 2 — score_session 补列（单事务落库，D-55 + 审计快照列）**：`score_session` lines 174-255。改造在「单事务写库」段 lines 243-254——INSERT 列清单加 `evidence_spans_json/rubric_version/scorer_version/measurement_target`（测量结果行才填；gate 行这些列 NULL）。**不动**「内存算完单事务落库」结构（这是 SQLite 单写者第二模式的权威先例）：
```python
# scoring.py:208-254 现有结构（勿改骨架，只扩 INSERT 列）
# 1) 内存计算（含 LLM 调用，此时本 conn 未持写事务）
pending_rows: list[tuple] = []
for q in answered:
    ...
    r = score_question(session_id, q["question_id"])
    ...
    pending_rows.append((new_id("qs"), session_id, q["question_id"], item_id,
                         score_live, r["score_final"], r["score_state"],
                         r["evidence_quote"], r["reason"], now_iso()))
# 2) 单事务写库
conn.execute("DELETE FROM question_score WHERE session_id=? AND gate_result IS NULL", (session_id,))
conn.executemany(
    "INSERT INTO question_score(score_id, session_id, question_id, item_id,"
    " score_live, score_final, score_state, evidence_quote, reason, created_at)"
    " VALUES(?,?,?,?,?,?,?,?,?,?)", pending_rows)
conn.commit()
```
**关键纪律（D-003「LLM 不碰数字」）**：span 定位/quote_hash 是纯代码计算，发生在 `score_question` 返回 `evidence_quote` 之后、`pending_rows.append` 之前——绝不在 LLM 调用期间持有写事务（`score_question` 内部经 `call_llm_json` 用独立连接写 llm_trace，见 llm.py:13-21）。

---

### `server/services/aggregation.py`（service，transform）

**Analog:** 自身。`aggregate_session_scores` lines 90-216 是改造主体：

**改造点 1 — adjudicate 替换 `sum(finals)/len(finals)`（D-58）**：均分在 line 173 `actual = sum(finals) / len(finals)`。替换为内存 `item_measurement` 记录 + `adjudicate(measurements)`。item 分组收分结构照 lines 101-128（三路分流）：
```python
# aggregation.py:110-128 三路分流（IMPUTED 补算插在「缺 finals」分支，不破坏现结构）
_EXCLUDED_STATES = ("INVALIDATED", "INCOMPLETE", "INSUFFICIENT_EVIDENCE", "NOT_ADMINISTERED")
for r in rows:
    std_name = (model_items.get(r["item_id"]) or {}).get("std_name")
    if r["score_state"] == "SCORED":
        item_scores_map.setdefault(r["item_id"], []).append(r["score_final"])
    elif r["score_state"] == "REFUSED":
        refusals.append({...})
    elif r["score_state"] in _EXCLUDED_STATES:
        missing_warnings.append({...})
```

**改造点 2 — IMPUTED 补算（D-59）+ required 缺失 PROVISIONAL（D-60）**：插在 `finals = item_scores_map.get(item_id, [])` 为空的分支（lines 160-171 现在是 `no_data: True`）。`r = Σ w_i·s_i / Σ w_i`（`s_i=(score−1)/4`）纯代码计算，O=∅ → `NO_VALID_OBSERVATION`。required 缺失判定需 `item["importance"] == "required"`（`_load_model_items` lines 18-29 返回 `importance` 键——注意现查询 SELECT 不含 `importance`，需补该列）。

**改造点 3 — 门槛项不动**：`_gate_row` lines 48-63 + `_gate_check` lines 66-87 + `gate` 分支 lines 136-158 保持现状（IMPUTED/裁决只影响非 gate 项）。

**七项校验的「重算分母」复用**（RESEARCH Open Question 3）：提取单一 `_score_state_denominator` 助手，`_EXCLUDED_STATES` 常量（line 110）单源复用——校验函数独立重跑过滤比对，避免逻辑漂移。

---

### `server/services/report.py`（service，CRUD + transform）

**Analog:** 自身。`generate_report` lines 89-153：

**改造点 1 — 版本化 INSERT 替换 DELETE+INSERT（D-61/D-62）**：DELETE 在 lines 144-145（`DELETE FROM report WHERE session_id=?`）。替换为「版本化 INSERT 新行，旧行保留」：
```python
# report.py:144-152 现有覆盖生成（改写对象）
conn.execute("DELETE FROM report WHERE session_id=?", (session_id,))
conn.execute(
    "INSERT INTO report(report_id, session_id, total_score, gate_passed, report_json, created_at)"
    " VALUES(?,?,?,?,?,?)",
    (report_id, session_id, agg["total_score"], int(gate_passed),
     json.dumps(report_data, ensure_ascii=False), report_data["created_at"]),
)
conn.commit()
```
版本化后 INSERT 列加 `report_status/review_status/version` + 发布字段；`version = session 内 MAX(version)+1`（或 created_at 排序，planner 定）。`get_report_by_session` 的 `ORDER BY created_at DESC LIMIT 1`（assessment.py:1095）已满足「读最新」——**读路径不破坏**。

**改造点 2 — 七项一致性校验（D-63）**：插在 `aggregate_session_scores`（line 100）之后、LLM 调用（line 119）与 INSERT 之前。任一失败 → 写 `report_status='FAILED'` 行（report_json 含 error 摘要）后 return，不生成正常报告。

**改造点 3 — 状态机推进 + trace_link 写点**：`generate_report` 返回前写 trace_link（report→session→model/version→question→score→trace 闭合）。`_load_question_reviews` lines 35-69（补 `item_id` 列 + `aq.item_id`）与 `_collect_evidence_quotes` lines 72-86（复用现成）为 question_reviews 补 item_id 的载体。

**imports 形态**（report.py lines 6-12）：`import json` + `from ..db import get_conn` + `from .aggregation import aggregate_session_scores` + `from .llm import call_llm_json` + `from .pipeline import new_id, now_iso`。新增 trace_link 写点若独立服务则 `from .trace_link import link_entity`。

---

### `server/services/state_events.py`（utility/service，event-driven）

**Analog:** 自身 `append_event` lines 14-48（唯一写入入口，**不 commit**，事务边界由调用者持有）。REVIEW_* 事件（`REVIEW_FEEDBACK_RECEIVED` / `REVIEW_REPORT_PUBLISH_CONFIRMED` / `TASK_FAILED`）直接走此入口，**本文件无需改动**——只扩调用点：
```python
# state_events.py:14-48 append_event 签名（调用方形态）
def append_event(conn, *, session_id, event_type, from_state=None, to_state=None,
                 actor_type="system", actor_id=None, assessment_question_id=None,
                 assessment_message_id=None, payload=None) -> None:
    if actor_type not in _VALID_ACTOR_TYPES:  # ("candidate","system","admin")
        raise ValueError(...)
    seq = conn.execute(
        "SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM assessment_state_event WHERE session_id=?",
        (session_id,)).fetchone()[0]
    conn.execute("INSERT INTO assessment_state_event(...) VALUES(...)", ...)
```
**后台任务无外层事务时的包装器**：`server/api/assessment.py:1018-1028` `_append_task_event`（独立小事务写事件：get_conn → append_event → commit → close）——REVIEW_* 在同步端点内与业务行同事务（单 commit），在后台任务内走 `_append_task_event`。

---

### `server/services/trace_link.py` **[新]**（service，CRUD）

**Analog:** `server/services/state_events.py` `append_event`（唯一写入入口形态）+ `server/services/llm.py` `_record_trace` lines 13-21（独立连接写审计行的形态）。

**核心形态**（照 `llm.py:_record_trace` 的独立小事务写 + `state_events.py` 的枚举代码校验）：
```python
# llm.py:13-21 _record_trace（审计行写入形态）
def _record_trace(call_type, ref_id, attempt, prompt, response, success, error):
    conn = get_conn()
    conn.execute(
        "INSERT INTO llm_trace(trace_id, call_type, ref_id, attempt, prompt, response, success, error, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (new_id("t"), call_type, ref_id, attempt, prompt, response, int(success), error, now_iso()))
    conn.commit()
```
trace_link 写点 `link_entity(conn, trace_id, entity_type, entity_id, link_role)`：接调用方 conn（同事务，不 commit——照 append_event）或独立 conn（后台无事务时，照 _record_trace）。`link_role ∈ {input|output|caused_by|scored|reported|source}` 代码校验（照 state_events `_VALID_ACTOR_TYPES` 的 `raise ValueError` 形态，lines 11/34-35）。`imports`：`from ..db import get_conn` + `from .pipeline import new_id, now_iso`。

---

### `server/api/assessment.py`（controller，request-response + event-driven）

**Analog:** 自身。改造点集中在报告/反馈链：

**改造点 1 — request_report 重复生成语义（D-62/Pitfall 7）**：`request_report` lines 1058-1087。现有「已存在 report 行 → 409 REPORT_ALREADY_EXISTS」（lines 1074-1080）改为三分支：
```python
# assessment.py:1067-1087 现有 request_report（409 语义改写对象）
conn = get_conn()
session = load_owned_session(conn, session_id, user)
if session["status"] != "completed":
    raise HTTPException(409, detail={"error_code": "SESSION_NOT_COMPLETED", ...})
report_row = conn.execute("SELECT 1 FROM report WHERE session_id=?", (session_id,)).fetchone()
if report_row is not None:
    raise HTTPException(409, detail={"error_code": "REPORT_ALREADY_EXISTS", ...})
append_event(conn, session_id=session_id, event_type="TASK_QUEUED", actor_type="system")
conn.commit()
background.add_task(_generate_report_task, session_id)
return {"session_id": session_id, "status": "generating"}
```
改写后：非 completed → 409 SESSION_NOT_COMPLETED；completed 且存在 `report_status='GENERATING'` 行 → 409 REPORT_GENERATING（防并发重入）；其余（无行 / 已有 FAILED/READY/PUBLISHED 行）→ 202 入队新版本。`report_status='GENERATING'` 行在入队前写入（照 TASK_QUEUED 先落库后 add_task 的形态，lines 1081-1086）。

**改造点 2 — `_generate_report_task` FAILED 可见（D-65）**：lines 1031-1055。`except Exception` 分支（lines 1051-1055）现在只发 TASK_FAILED 事件 + 静默。改写：捕获后写 `report_status='FAILED'` 行（report_json 含 `{"error": str(e)[:200]}`）+ TASK_FAILED 事件保留。`str(e)[:200]` 截断照 line 1053 现有形态。GENERATING 行由 request_report 或任务启动时先写。

**改造点 3 — submit_feedback 补 user_id + REVIEW 事件（D-66/D-67）**：lines 1114-1141。INSERT 加 `user_id`（从 `require_login` 的 `user["user_id"]`），item 归属校验（lines 1125-1133，JOIN report→session→competency_item）**保留不动**。补 `append_event(conn, session_id=..., event_type="REVIEW_FEEDBACK_RECEIVED", actor_type="candidate", actor_id=user["user_id"], payload={"feedback_id":..., "item_id":...})`——**注意 report 行需反查 session_id**（feedback→report→session JOIN）。append_event 不 commit，submit_feedback 既有 `conn.commit()`（line 1140）覆盖同事务。

**改造点 4 — get_report_by_session 版本取最新**：lines 1090-1103 已 `ORDER BY created_at DESC LIMIT 1`，版本化后**无需改**（只确保 FAILED 行也能被前端读到 report_status）。

**auth 形态**：`load_owned_report` / `load_owned_session`（core/security.py:63-99）+ `Depends(require_login)`（router 级 line 39）。发布端点不在此文件（走 admin）。

---

### `server/api/admin/reports.py` **[新]**（controller，request-response）

**Analog:** `server/api/admin/models.py` `confirm_model` lines 126-159（require_admin + 状态迁移 + 事件/审计字段 + commit 的权威形态）+ `server/api/admin/feedback.py` `review_feedback`（POST + Pydantic body + UPDATE + rowcount 404 判定）。

**核心形态**（照 confirm_model 的状态迁移 + 审计字段 + 同事务事件）：
```python
# admin/models.py:126-159 confirm_model（发布端点照此骨架）
@router.post("/models/{model_id}/confirm")
def confirm_model(model_id: str, background: BackgroundTasks, admin: dict = Depends(require_admin)) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT ... FROM competency_model WHERE model_id=?", (model_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "模型不存在")
    if row["status"] == "confirmed":
        raise HTTPException(409, "模型已确认")
    conn.execute("UPDATE ... SET status='confirmed', confirmed_by=?, confirmed_at=? WHERE model_id=?",
                 (admin["user_id"], now_iso(), model_id))
    conn.commit()
    ...
    return {"model_id": model_id, "status": "confirmed", ...}
```
publish 端点（`POST /api/admin/reports/{report_id}/publish`）：
- **router 声明**照 admin/models.py:13：`router = APIRouter(prefix="/api/admin", tags=["admin-reports"], dependencies=[Depends(require_admin)])`（注意 feedback.py 用 `/api/admin/feedback` prefix，reports 用 `/api/admin` 前缀以承载 `/reports/{report_id}/publish` 路径）。
- **Pydantic body** 照 `_ReviewBody`（admin/feedback.py:30-31 `class _ReviewBody(BaseModel): note: str = ""`）。
- **校验 review_status 满足**（required 缺失需 CONFIRMED）→ `report_status=PUBLISHED` + `publish_confirmed_by=admin["user_id"]` + `published_at` + `REVIEW_REPORT_PUBLISH_CONFIRMED` 事件（同事务 append_event，照 assessment.py 端点形态）。
- **rowcount 0 → 404** 照 feedback.py:42-43（`if cur.rowcount == 0: raise HTTPException(404, ...)`）。
- **imports** 照 admin/models.py:5-11：`from fastapi import APIRouter, Depends, HTTPException` + `from pydantic import BaseModel` + `from ...core.security import require_admin` + `from ...db import get_conn` + `from ...services.pipeline import now_iso`。**注意**：admin 路由用 `...`（三层相对导入，`admin/` 在 `api/` 下一层），assessment.py 用 `..`（两层）。

---

### `server/api/admin/feedback.py`（controller，CRUD）

**Analog:** 自身 `review_feedback` lines 34-44 / `mark_bad_case` lines 47-57。

**改造点 — note/reviewer/reviewed_at 持久化（D-66）**：现有 `body: _ReviewBody` 的 `note` 入参被丢弃（UPDATE 只写 status）。改写：
```python
# admin/feedback.py:34-44 review_feedback（改造对象——note 被丢弃）
@router.post("/{feedback_id}/review")
def review_feedback(feedback_id: str, body: _ReviewBody) -> dict:
    conn = get_conn()
    cur = conn.execute(
        "UPDATE feedback SET status='reviewed' WHERE feedback_id=?", (feedback_id,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "反馈不存在")
    return {"feedback_id": feedback_id, "status": "reviewed"}
```
UPDATE 加 `note=?, reviewer=?, reviewed_at=?`。`reviewer` 从 `Depends(require_admin)` 的 `admin["user_id"]` 取（router 级 `dependencies=[Depends(require_admin)]` 在 line 9，但需在函数签名加 `admin: dict = Depends(require_admin)` 才能拿到 user_id——照 admin/models.py confirm_model 的 `admin: dict = Depends(require_admin)` 形态）。

---

### `server/api/admin/trace.py`（controller，CRUD read）

**Analog:** 自身 `get_session_traces` lines 48-65（ref_id IN (...) 弱关联 → trace_link 消费升级）。

**改造点 — trace_link 审计链查询（D-56/D-57）**：`get_session_traces` 现有「ref_id IN (session_id + question_ids)」并集（lines 52-61）为弱关联消费。升级：从 trace_link 表按 `entity_type='session' AND entity_id=session_id` 反查 trace_id 集合，再 JOIN llm_trace。列表/详情端点（lines 12-77）不破坏，`llm_trace.ref_id` 列保留。**imports** 现有形态 lines 1-7（`from ...core.security import require_admin` + `from ...db import get_conn`），新增 trace_link 服务 import 若需。

---

## Shared Patterns

### 1. SQLite 单写者两模式（全 phase 不变式）

**模式 A「先 commit 再调 LLM」** — `server/api/assessment.py:582-586`（submit_answer 提交用户消息后调 decide_next_action）与 `700-705`（先 commit 再选题）：
```python
# assessment.py:582-586
# 先提交用户消息再调 LLM：llm_trace 用新连接写库，本连接持写事务会 database is locked
conn.commit()
decision = decide_next_action(session_id, question_id, refined)
```
**适用**：request_report / _generate_report_task / submit_feedback 等「落库后需跨 LLM 调用」的写点。

**模式 B「内存算完单事务落库」** — `server/services/scoring.py:208-254`（`score_session`：内存循环含 LLM 调用，最后一次写库）：
```python
# scoring.py:187-189 注释（权威判据）
# 实现注意：先在内存里算完全部行（含 LLM 调用），最后一次写库——避免外层
# conn 持写事务时 LLM trace 用新连接写库导致 database is locked。
```
**适用**：evidence_spans 定位、item_measurement 裁决、IMPUTED 补算、七项校验——全在「内存算完单事务落库」模式内，绝不持有写事务跨 LLM。

**归类**（planner 每个新写点对号入座）：
- trace_link 写点、evidence_spans 生成、adjudicate/IMPUTED、七项校验、版本化 INSERT → **模式 B**（内存算完/同步算完单事务落库）。
- request_report 入队、submit_feedback、publish、review note → **模式 A**（同步端点落库 + commit，LLM 调用在后/独立）。

### 2. append_event 唯一入口 + 不 commit
**Source:** `server/services/state_events.py:14-48`；后台任务包装器 `server/api/assessment.py:1018-1028`。
**Apply to:** 所有 REVIEW_* / TASK_FAILED / TASK_QUEUED 事件写点。同步端点与业务行同事务（单 commit），后台任务走 `_append_task_event` 独立小事务。

### 3. 枚举代码校验（N11，无 DB CHECK）
**Source:** `server/services/scoring.py:23-30` `SCORE_STATES` 常量 + `state_events.py:11,34-35` `_VALID_ACTOR_TYPES` raise。
**Apply to:** `report_status`（GENERATING/PROVISIONAL/READY/PUBLISHED/FAILED）、`review_status`（NONE/REQUIRED/IN_PROGRESS/CONFIRMED/CLOSED）、`link_role`（input/output/caused_by/scored/reported/source）。全部常量集中 + `raise ValueError(f"非法 ...")` 形态，**不建 DB CHECK**。

### 4. 鉴权与所有权
**Source:** `server/core/security.py:53-99`。
- 候选人端点：`Depends(require_login)`（router 级）+ `load_owned_session`/`load_owned_report`（404 统一不存在语义）。
- 管理端点：`Depends(require_admin)`（router 级 `dependencies=[...]`）+ 需要 user_id 时函数签名 `admin: dict = Depends(require_admin)`。
- publish 端点（admin）route 级 `Depends(require_admin)`，越权 → 403（require_admin lines 57-60）。

### 5. 错误响应 WR-01 三态
**Source:** `server/api/assessment.py:1069-1073`（409 detail `{error_code, message}`）。
**Apply to:** request_report 新 409 分支（REPORT_GENERATING）、publish 端点 409（review 未满足）。404 文案统一「不存在」语义（load_owned_* 与 admin feedback rowcount==0）。

### 6. Pydantic body 校验（admin 端点）
**Source:** `server/api/admin/feedback.py:30-31`（`_ReviewBody`）+ `server/api/admin/models.py:16-33`（Field 约束）。
**Apply to:** publish 端点 request body（review_outcome/review_note）。

### 7. 测试三件套纪律（单文件单进程 + tempfile + mock）
**Source:** `server/test_m5_backend.py`（候选侧）与 `server/test_m7_backend.py`（admin 侧）。
```python
# test_m5_backend.py:11-29 头部（每个 test_phase5_* 文件照抄）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase5_xxx.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from server.db import init_db, get_conn
from server.main import app
init_db()          # TestClient 不触发 startup，显式建表
client = TestClient(app)
```
```python
# test_m5_backend.py:32-38 _q 只读助手（避免持锁阻塞 API 写入）
def _q(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```
- **候选侧 helpers**：`_auth_headers`（test_m5:130-135，register+login 取 token）、`_seed_position_with_confirmed_model`（43-73）、`_seed_question_bank`（76-127）。
- **admin 侧 helpers**：`_ensure_admin`（test_m7:28-46）、`_admin_token`/`_auth`（49-56）、`_seed_report_and_item`（59-99，直接插库造外键全链）。
- **测试执行纪律（RESEARCH 锁定）**：逐文件跑 `python -m pytest test_phase5_evidence.py -v`，**禁止单进程同跑多文件**（DB_PATH import 冲突）。

### 8. 现有 test_m6 断言改写（Pitfall 1）
**Source:** `server/test_m6_backend.py:256-259`：
```python
n = conn.execute("SELECT COUNT(*) c FROM report WHERE session_id=?", (session_id,)).fetchone()["c"]
check("重复生成幂等（同会话仅 1 行 report）", n == 1, f"实际 {n}")
```
**改写**：断言重复生成后 `COUNT(*)==2`、最新行 version=2、旧行 version=1 保留、`get_report_by_session` 取 version=2。

---

## No Analog Found

无。本 phase 全部 12 个文件均有现成 analog（自身既有代码或同角色文件）。唯一「无同构先例」的逻辑是：
- `trace_link` 旧 ref_id 导入的「逐实体表命中探测」算法（D-57）——但迁移函数**骨架**照 `_migrate_session_phase3`；
- `_locate_span` / `_impute_r` / `adjudicate` / 七项校验——纯函数新逻辑，但**所在文件的既有结构**（`_fetch_answer_text`/`_EXCLUDED_STATES` 分流/`aggregate_session_scores`）就是载体。

planner 可完全依赖上述 analog，无需回落 RESEARCH 的 pseudocode（RESEARCH 的 Pattern 1-7 pseudocode 已与上述源码 excerpt 对齐）。

## Metadata

**Analog search scope:** `server/db.py`, `server/services/*.py`, `server/api/*.py`, `server/api/admin/*.py`, `server/core/security.py`, `server/test_m5_backend.py`, `server/test_m7_backend.py`, `server/test_m6_backend.py`
**Files scanned:** 18（含 4 个测试文件）
**Pattern extraction date:** 2026-09-05
