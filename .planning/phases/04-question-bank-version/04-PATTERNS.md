# Phase 04: 题库版本绑定与模块一收口 - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 8（7 改造 + 1 组新测试）
**Analogs found:** 8 / 8（全部为「修改现有文件」——类比 = 文件自身现状 + 新测试对齐既有三件套）

## 概览

本 phase 是「既有列填充 + 消费侧收紧」，**零新增迁移、零新增包、零新增路由（仅迁移 orphan）**。所有改造对象都是现有文件，故「Closest Analog」= 改造对象自身现状（已逐行读取，下方摘录当前签名/SQL/Pydantic 字段 + 具体改动面）。新测试文件对齐 `test_phase2_selection.py` / `test_phase3_forms.py` 的「单文件单进程 + tempfile + mock」三件套。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/services/question_bank.py` | service（异步后台生成） | batch + CRUD（逐 item 落库 + LLM 调用） | 自身现状（generate_question_bank/_insert_question） | 修改现有（exact 定位） |
| `server/services/readiness.py` | service（开考前预检） | request-response（只读查询判定） | 自身现状（check_session_readiness） | 修改现有（exact 定位） |
| `server/services/question_selection.py` | service（运行时选题） | CRUD 查询（候选池加载） | 自身现状（_load_candidate_rows） | 修改现有（exact 定位） |
| `server/api/admin/models.py` | controller（FastAPI router） | request-response / CRUD（Pydantic 入参校验 + DB 重建） | 自身现状（ModelItem/update_model） | 修改现有（exact 定位） |
| `server/api/admin/jds.py` | controller（FastAPI router） | request-response | 自身现状 + `positions.py:87` list_orphan_jds | 修改现有 + 迁移 |
| `server/api/admin/positions.py` | controller（FastAPI router） | request-response | 自身现状（get_todos / list_orphan_jds） | 修改现有（exact 定位） |
| `server/main.py` | config/bootstrap | 路由注册 | 自身现状（include_router 序） | 修改现有（exact 定位） |
| `server/test_phase4_binding.py` / `_orphan` / `_model_edit` / `_fail_visible.py` | test | — | `server/test_phase2_selection.py`（pytest 三件套）/ `test_phase3_forms.py`（老库迁移双路径） | exact |

---

## Pattern Assignments

### 1. `server/services/question_bank.py`（service，batch + CRUD）

**当前签名（`_insert_question`，lines 56-67）：**
```python
def _insert_question(conn, *, scope: str, position_id: str | None, item: dict,
                     difficulty: str | None, qtype: str, stem: str,
                     answer_key: str | None, rubric: str | None,
                     chain_key: str | None, chain_seq: int | None) -> None:
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, std_name, category,"
        " difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("q"), scope, position_id, item["std_name"], item["category"],
         difficulty, qtype, stem, answer_key, rubric, chain_key, chain_seq,
         "llm_seed", "active", now_iso()),
    )
```

**当前签名（`generate_question_bank`，line 88）：**
```python
def generate_question_bank(position_id: str, model_id: str) -> None:
```
内部 line 96 取岗位、line 104-108 取 items（含 `item_id, std_name, category, required_level, weight, evidence_json`）、line 101-102 置 RUNNING 后 commit。

**幂等判重现状（lines 122-149，WR-03 目标粒度 4 处 exists）：**
```python
if scope == "position":
    if difficulty is None:
        exists = conn.execute(
            "SELECT 1 FROM question_bank WHERE scope='position' AND position_id=?"
            " AND std_name=? AND category=? AND status='active' LIMIT 1",
            (position_id, item["std_name"], item["category"]),
        ).fetchone()
    else:
        exists = conn.execute(
            "SELECT 1 FROM question_bank WHERE scope='position' AND position_id=?"
            " AND std_name=? AND category=? AND difficulty=?"
            " AND status='active' LIMIT 1",
            (position_id, item["std_name"], item["category"], difficulty),
        ).fetchone()
else:  # scope='general'（experience/qualification，无难度维度）
    if difficulty is None:
        exists = conn.execute(
            "SELECT 1 FROM question_bank WHERE scope='general'"
            " AND std_name=? AND category=? AND status='active' LIMIT 1",
            (item["std_name"], item["category"]),
        ).fetchone()
    else:
        exists = conn.execute(
            "SELECT 1 FROM question_bank WHERE scope='general'"
            " AND std_name=? AND category=? AND difficulty=?"
            " AND status='active' LIMIT 1",
            (item["std_name"], item["category"], difficulty),
        ).fetchone()
```

**改动面（D-47/D-49/D-54）：**
1. `generate_question_bank` 顶部（`_update_task_status(...,"RUNNING")` 前后均可）补取 version：
   ```python
   model_row = conn.execute(
       "SELECT version FROM competency_model WHERE model_id=?", (model_id,)
   ).fetchone()
   model_version = model_row["version"] if model_row else None
   ```
   签名保持 `(position_id, model_id)` 不动（A3 假设——两处调用点 `confirm_model`/`retry_question_bank_task` 只传这两参）。
2. `_insert_question` 签名加 `model_id`/`model_version`/`item_id` 三参（keyword-only），INSERT 加 4 列：`model_id, model_version, item_id, rubric_version`，值 `rubric_version="v1"` 常量（`measurement_target`/`evidence_requirement` 留 NULL 不落）。
3. 4 处 exists 判重键升级（D-49）：`scope='position'` 分支把 `position_id=?` **替换**为 `model_id=? AND model_version=?`；`scope='general'` 分支**追加** `model_id=? AND model_version=?`。general 题无难度维度，同加版本。
4. 逐 item `conn.commit()`（line 172）保持不动——「先 commit 再调 LLM」模式不破坏。

**landmine（WR-03 幂等）：** 若只改 INSERT 列不改 exists 键，v2 生成时命中 v1 active 行 → 整链跳过 → v2 题库空 → readiness 永久 INCOMPLETE（RESEARCH Pitfall 2）。

---

### 2. `server/services/readiness.py`（service，request-response）

**当前签名与 SQL（两 count helper，lines 16-37）：**
```python
def _question_count_by_category(conn, position_id: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT category, COUNT(*) c FROM question_bank WHERE status='active'"
        " AND (scope='general' OR (scope='position' AND position_id=?))"
        " GROUP BY category",
        (position_id,),
    ).fetchall()

def _covered_std_names(conn, position_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT std_name FROM question_bank WHERE status='active'"
        " AND (scope='general' OR (scope='position' AND position_id=?))",
        (position_id,),
    ).fetchall()
```

**task 查询 + FAILED 占位（lines 95-105）：**
```python
task = conn.execute(
    "SELECT status FROM question_bank_task"
    " WHERE position_id=? AND model_id=? AND model_version=?"
    " ORDER BY created_at DESC LIMIT 1",
    (position_id, model["model_id"], model["version"]),
).fetchone()
if task is not None and task["status"] in ("QUEUED", "RUNNING"):
    return {"error_code": "QUESTION_BANK_GENERATING",
            "detail": "该岗位题库正在生成中，请稍后开考"}
# FAILED → INCOMPLETE（失败细节 Phase 4 REF-8.4 再做）；
```

**tier LEFT JOIN（lines 132-141）：**
```python
rows = conn.execute(
    "SELECT COALESCE(ci.importance, 'plus') AS tier, COUNT(*) c"
    " FROM question_bank qb"
    " LEFT JOIN competency_item ci ON ci.model_id=?"
    " AND ci.std_name=qb.std_name AND ci.category=qb.category"
    " WHERE qb.status='active' AND qb.category=?"
    " AND (qb.scope='general' OR (qb.scope='position' AND qb.position_id=?))"
    " GROUP BY COALESCE(ci.importance, 'plus')",
    (model["model_id"], category, position_id),
).fetchall()
```

**调用点（lines 108-109）：**
```python
counts = _question_count_by_category(conn, position_id)
covered = _covered_std_names(conn, position_id)
```

**改动面（D-50/D-51）：**
1. 两个 helper 签名加 `model_id`/`model_version`，WHERE 统一加 `AND model_id=? AND model_version=?`（落点在 `status='active'` 邻位）。
2. tier LEFT JOIN 的 WHERE 加 `AND qb.model_id=? AND qb.model_version=?`（`ci.model_id=?` 邻位，参数补 `model["model_id"], model["version"]`）。
3. task 查询 `SELECT status` → `SELECT status, error_msg`，新增 FAILED 显式分支（D-51，替换 line 104-105 注释）：
   ```python
   if task is not None and task["status"] == "FAILED":
       detail = "该岗位题库生成失败，不可开考"
       if task["error_msg"]:
           detail += f"（{task['error_msg'][:200]}）"
       return {"error_code": "QUESTION_BANK_INCOMPLETE", "detail": detail}
   ```
4. 调用点 line 108-109 传 `model["model_id"], model["version"]`（`model` 行已含 `model_id/version`，见 `assessment.py:42-54` `_latest_confirmed_model` 返回 `SELECT model_id, version, model_json`）。

**landmine（WR-15 过滤漂移）：** 三处 WHERE 与 selection 一处必须四地同步加 `AND model_id=? AND model_version=?`，参数同源（都从 `model["model_id"]`/`model["version"]` 或 `session["model_version"]` 取）。只加一处会致 readiness 判「足量」但 selection 选不到（或选到旧版）。

---

### 3. `server/services/question_selection.py`（service，CRUD 查询）

**当前签名 + 版本近似子句（`_load_candidate_rows`，lines 219-244）：**
```python
def _load_candidate_rows(conn, position_id: str, model_id: str | None) -> list[dict]:
    rows = conn.execute(
        "SELECT b.*, ci.weight AS item_weight, ci.importance AS item_importance,"
        " ci.item_id AS model_item_id"
        " FROM question_bank b"
        " LEFT JOIN competency_item ci ON ci.std_name=b.std_name AND ci.category=b.category"
        " AND ci.model_id=?"
        " WHERE b.status='active' AND b.category IN ('hard_skill','soft_skill')"
        " AND (b.scope='general' OR (b.scope='position' AND b.position_id=?))"
        " AND (b.model_id IS NULL OR ? IS NULL OR b.model_id=?)",
        (model_id, position_id, model_id, model_id),
    ).fetchall()
```

**调用点（`_select_next_question_locked`，lines 283-299）：**
```python
session = conn.execute(
    "SELECT session_id, position_id, model_id, model_version, status"
    " FROM assessment_session WHERE session_id=?", (session_id,)
).fetchone()
...
model_id = session["model_id"]
items = _load_model_items(conn, model_id)
candidates = _load_candidate_rows(conn, session["position_id"], model_id)
```

**改动面（D-50）：**
1. 签名 `_load_candidate_rows(conn, position_id, model_id, model_version)`。
2. 行 233 子句收紧：`" AND (b.model_id IS NULL OR ? IS NULL OR b.model_id=?)"` → `" AND b.model_id=? AND b.model_version=?"`，参数去掉 NULL 放行（`(model_id, position_id, model_id, model_version)`）。
3. 调用点 line 299 补 `session["model_version"]`（session 已取 `model_version`，就近传入）。

**landmine（REF-3.4 收紧 + WR-15）：** 去 NULL 放行后，存量 NULL model_id 行（m5/m6 直插种子）不再命中——需配合落库侧已写绑定；且必须与 readiness 三处口径一致。

---

### 4. `server/api/admin/models.py`（controller，Pydantic 校验 + CRUD）

**当前 ModelItem（lines 15-28）：**
```python
from pydantic import BaseModel, Field

class ModelItem(BaseModel):
    std_name: str = Field(min_length=1)
    category: str = Field(pattern="^(hard_skill|soft_skill|experience|qualification)$")
    weight: float = Field(ge=0)
    required_level: int | None = None
    importance: str | None = None
    years: float | None = None
    gate: int = 0
    level_reason: str | None = None
    occurrence: dict = {}
    evidence: list = []
```

**当前 Σ=100% 校验（`update_model`，lines 84-88）：**
```python
total_weight = sum(it.weight for it in items)
if abs(total_weight - 1.0) > 0.005:
    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                        f"权重合计须为 100%（当前 {total_weight * 100:.1f}%）")
```

**改动面（D-53）：**
1. `weight: float = Field(ge=0, le=1, allow_inf_nan=False)` —— `allow_inf_nan=False` 是 Pydantic v2 解析期拒绝 NaN/∞ 的正解（项目 pydantic 2.10.3），`le=1` 拦单 item 越界。
2. `required_level: int | None = Field(default=None, ge=1, le=5)`。
3. `importance: Literal["required", "preferred", "plus"] | None = None`（`from typing import Literal`；与 readiness `COALESCE(ci.importance,'plus')` 口径对齐）。
4. `years: float | None = Field(default=None, ge=0, allow_inf_nan=False)`。
5. `update_model` 内 Σ=100% 校验之后、重建 `competency_item` 之前，加重复 std_name 校验（D-53，自研唯一逻辑）：
   ```python
   seen: set[tuple[str, str]] = set()
   for it in items:
       key = (it.std_name, it.category)
       if key in seen:
           raise HTTPException(status.HTTP_400_BAD_REQUEST,
                               f"同一类目内能力项重复：{it.std_name}({it.category})")
       seen.add(key)
   ```

**landmine（NaN 绕过 Σ 校验）：** `sum([nan, 0.3, 0.7])` → nan，`abs(nan - 1.0) > 0.005` → False，NaN 静默通过 line 85-88 污染 `competency_item.weight`。必须在字段级 `allow_inf_nan=False` 拦住，不能在聚合级补救（RESEARCH Pitfall 5 / Anti-Patterns）。

---

### 5. `server/api/admin/jds.py`（controller，路由迁移）

**当前 `jd_detail`（lines 79-90，参数路由吞掉 orphan 的元凶）：**
```python
@router.get("/jds/{jd_id}")
def jd_detail(jd_id: str) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM jd_record WHERE jd_id=?", (jd_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "JD 不存在")
```

**被遮蔽的现有实现（`positions.py:87-95`，迁入源）：**
```python
@router.get("/jds/orphan")
def list_orphan_jds() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT jd_id, job_title, company, source_type, status, created_at"
        " FROM jd_record WHERE position_id IS NULL AND status != 'failed' ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]
```

**改动面（D-52）：**
1. 把 `list_orphan_jds`（`@router.get("/jds/orphan")`）整体迁到 `jds.py`，声明位置放在 `list_jds`（line 68）之后、`jd_detail`（line 79）**之前**——同文件内声明序可控，`/jds/{jd_id}` 不再吞 `orphan`。
2. 字段/status 口径：**【待硬关口 A 裁定的 pending 决策】**——选项 A（D-52 字面：字段同 list_jds、WHERE position_id IS NULL、无 status 过滤）vs 选项 B（现有 positions.py 实现：字段子集 `jd_id/job_title/company/source_type/status/created_at` + `AND status != 'failed'`，与 `get_todos` 的 orphan 计数口径一致）。默认按选项 B 实现，待用户裁决后锁定（已由 04-02 计划呈报硬关口 A）。

**landmine（orphan 双路由）：** 迁移后必须移除 `positions.py` 的 `list_orphan_jds`，否则两个同路径路由并存（首个声明生效，positions 版成死代码）。

---

### 6. `server/api/admin/positions.py`（controller，明细扩展 + 移除重复路由）

**当前 `get_todos` 的 question_bank_not_ready（lines 24-27）：**
```python
question_bank_not_ready = conn.execute(
    "SELECT COUNT(DISTINCT position_id) c FROM question_bank_task WHERE status != 'SUCCEEDED'"
).fetchone()["c"]
```

**当前 `list_orphan_jds`（lines 87-95）** —— 见上文 jds.py 节，整体迁走。

**改动面（D-51 + D-52）：**
1. 移除 `list_orphan_jds`（lines 87-95），orphan 路由由 jds.py 承接；`get_todos` 里的 `orphan_jds` 计数（lines 21-23）保留。
2. `get_todos` 扩展失败明细：`question_bank_not_ready` 保持 int；新增 `question_bank_failed` 明细列表（Claude's Discretion 字段结构，RESEARCH Open Question 2 推荐方案）：
   ```python
   failed_rows = conn.execute(
       "SELECT position_id, model_id, model_version, error_msg FROM question_bank_task"
       " WHERE status='FAILED'"
   ).fetchall()
   question_bank_failed = [dict(r) for r in failed_rows]
   ```
   返回 dict 加 `"question_bank_failed": question_bank_failed`（前端 `Positions.vue` 对未知键安全，D-51「前端零破坏」）。

**landmine（口径一致性）：** 明细列表是否过滤 error_msg 为空、是否去重 position 由规划时敲定；需与 readiness FAILED 分支的 `error_msg[:200]` 截断口径对齐，避免注入敏感堆栈。

---

### 7. `server/main.py`（config/bootstrap，路由注册序）

**当前注册序（lines 74-84）：**
```python
app.include_router(auth.router)
app.include_router(admin_jds.router)       # line 75 —— 先注册
app.include_router(admin_models.router)
app.include_router(admin_positions.router) # line 77 —— 后注册（含 list_orphan_jds）
```

**改动面：** 本 phase **零改动** main.py。orphan 迁入 `jds.py` 后，`/jds/orphan` 与 `/jds/{jd_id}` 同在 `admin_jds.router` 内，声明序即可控，不再依赖跨文件注册序。main.py 只作为「landmine 佐证」记录——**若迁移后忘了移除 positions.py 的重复路由**，main.py 无需动但会出现双路由（首个声明生效）。

**landmine（注册序）：** RESEARCH Pitfall 1 / gap-matrix 第 115 行实测——`GET /api/admin/jds/orphan` 现状返回 404「JD 不存在」（`jd_detail("orphan")`）。修复点在 jds.py 内声明序，不在 main.py 注册序。

---

### 8. 新测试文件（test，对齐三件套）

**Analog 头（`test_phase2_selection.py` lines 13-52 / `test_phase3_forms.py` lines 13-53）——三件套：**
```python
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase2_selection.db")
os.environ["DB_PATH"] = _tmp_db
os.environ["LLM_PROVIDER"] = "mock"
os.environ["JWT_SECRET"] = "test-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402
from server import config  # noqa: E402
from server.db import init_db, get_conn  # noqa: E402
from server.main import app  # noqa: E402
from server.services.pipeline import new_id, now_iso  # noqa: E402

init_db()  # TestClient 不触发 startup 事件，显式建表
client = TestClient(app)

def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```

**种子模式（`test_phase2_selection.py:57-90`）：** `_seed_position_with_confirmed_model` 直插 active position + confirmed competency_model（`model_json` 含 `{"position_id","version","items"}`）+ competency_item 行；`test_question_bank.py:34-68` 是更贴近 generate_question_bank 的种子（含 experience/qualification + evidence）。老库迁移双路径用 `test_phase3_forms.py:50-86` 的 `_cols`/`_build_old_db`（`PRAGMA table_info` 嗅探 + 直连 `sqlite3.connect` 建旧版 DDL）。

**映射到 4 个新测试文件（RESEARCH Wave 0）：**
| 新文件 | 覆盖 | 对齐既有 |
|--------|------|---------|
| `test_phase4_binding.py` | REF-2.5/REF-3.4（落库写 model_id/model_version/item_id/rubric_version="v1"；升版后 readiness 拦旧版 + selection 只取 v2；判重键升级 v2 不跳过） | `test_question_bank.py` 种子 + `test_phase2_selection.py` 三件套 |
| `test_phase4_orphan.py` | REF-7.1（`GET /api/admin/jds/orphan` 返回列表非 404，顺序先于 `/jds/{jd_id}`） | `test_phase2_selection.py` 三件套 + TestClient |
| `test_phase4_model_edit.py` | REF-7.2（拒绝 NaN weight / required_level=6 / importance=bad / 重复 std_name，保留 Σ=100%） | `test_phase2_selection.py` 三件套 + `PUT /models/{id}` TestClient |
| `test_phase4_fail_visible.py` | REF-8.4（生成失败 → readiness INCOMPLETE + error_msg；get_todos 含失败明细） | `test_phase2_selection.py` 三件套 + `test_phase3_forms.py` mock 路径 |

**运行纪律：** `cd server && python -m pytest test_phase4_<area>.py -v`，单文件单进程（禁止一次 pytest 收集多个 server/test_*.py——DB_PATH import 时互踩）。既有 `test_question_bank.py`（脚本式）与 `test_phase2_selection.py` 的判重/候选断言会因 model_version 过滤改动而触碰，需复核同步（RESEARCH Validation Architecture 末行）。

---

## Shared Patterns

### 消费侧过滤同源纪律（WR-15 防漂移）
**Source:** `readiness.py:16-37/132-141` 与 `question_selection.py:219-244`
**Apply to:** readiness 三处 + selection 一处，四地全部 `AND model_id=? AND model_version=?`，参数同源。禁止某处只加 model_id、另一处只加 model_version。

### raw SQL + get_conn() per-call + 显式 commit（项目既定）
**Source:** 全改造对象（`get_conn()` + `conn.execute` + `conn.commit()`/`conn.close()` try/finally）
**Apply to:** question_bank / readiness / selection 的每处 SQL 改动——不加 ORM、不加连接池、不引入新事务点（question_bank 逐 item commit 保持）。

### Pydantic v2 字段级校验
**Source:** `models.py:15-28`（ModelItem 现状）
**Apply to:** update_model 的 ModelItem 强化——`allow_inf_nan=False`/`le`/`ge`/`Literal` 优先于手写 `math.isfinite` 扫描。

### FastAPI 声明序路由匹配
**Source:** `jds.py:79` + `main.py:75/77`（现状）
**Apply to:** orphan 迁移——`@router.get("/jds/orphan")` 置于 `/jds/{jd_id}` 之前，纯顺序修复，零自研路由逻辑。

### error_msg 截断 `[:200]`
**Source:** `question_bank.py:178`（`str(e)[:200]`）
**Apply to:** readiness FAILED detail 与 todos 失败明细——复用同一截断口径，防注入敏感堆栈。

### 测试三件套（tempfile + env + init_db）
**Source:** `test_phase2_selection.py:13-43` / `test_phase3_forms.py:13-36`
**Apply to:** 4 个新 test_phase4_* 文件——env 必须 import server 之前设；`init_db()` 显式建表；`_q()` 只读查询防 SQLite 单写锁。

---

## No Analog Found

无。本 phase 全部为「修改现有文件」，无新增业务文件（仅新增测试，测试模式有既有 analog）。

唯一「无现成代码类比」的点：**重复 std_name 校验**（D-53）——`update_model` 内一个 `seen: set[tuple[str, str]]` 按 `(std_name, category)` 判重，是自研最小逻辑（无第三方库），非独立文件。

## Landmines 汇总（规划时必查）

| # | Landmine | 位置 | 后果 | 规避 |
|---|----------|------|------|------|
| L1 | NaN 绕过 Σ=100% 校验 | `models.py:21/85-88` | NaN weight 静默写入 competency_item | `weight: Field(ge=0, le=1, allow_inf_nan=False)` |
| L2 | orphan 双路由 | `jds.py:79` + `positions.py:87` + `main.py:75/77` | `/jds/orphan` 恒 404 或双路由死代码 | 迁入 jds.py 置于 jd_detail 前 + 移除 positions.py 函数 |
| L3 | WR-03 幂等键缺版本 | `question_bank.py:122-149` | v2 生成整链跳过 → v2 题库空 → 永久 INCOMPLETE | exists 键加 model_id+model_version |
| L4 | WR-15 过滤漂移 | `readiness.py` 三处 + `question_selection.py:233` | readiness 判足量但 selection 选不到/选旧版 | 四地同步 `AND model_id=? AND model_version=?` |
| L5 | FAILED 分支落空 | `readiness.py:104-105` | 升版生成失败仍开考 | 显式 FAILED → INCOMPLETE + error_msg[:200] |

## Open Questions（已由 04-02 计划呈报硬关口 A 待裁定）

1. **orphan 列表字段/status 口径**：【待硬关口 A 裁定】选项 A（D-52 字面：字段同 list_jds、无 status 过滤）vs 选项 B（现有 `positions.py:87-95` 实现：字段子集 + `AND status != 'failed'`，与 `get_todos` 计数一致）。默认选项 B，待用户裁决后锁定。
2. **todos 失败明细结构**：已落定——`question_bank_not_ready`（int）保持 + 新增 `question_bank_failed`（list）。实现细节（是否去重 position、过滤空 error_msg）由执行时定。
3. **前端是否加「题库失败」卡**：【待硬关口 A 裁定】D-51「前端零破坏」倾向不强制前端改动，但需与「生成失败对管理员可见」验收口径对齐。

## Metadata

**Analog search scope:** `server/services/`、`server/api/admin/`、`server/api/`、`server/main.py`、`server/test_*.py`、`server/db.py`
**Files scanned:** 7 源码 + 3 测试 + db.py（question_bank DDL / _migrate_question_bank_v2）
**Pattern extraction date:** 2026-09-05

---

## PATTERN MAPPING COMPLETE
