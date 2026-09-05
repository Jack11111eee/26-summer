# Phase 4: 题库版本绑定与模块一收口 - Research

**Researched:** 2026-09-05
**Domain:** SQLite raw-SQL 数据绑定（question_bank model/version 强绑定）+ FastAPI 路由顺序 + Pydantic v2 字段校验
**Confidence:** HIGH（全部改造对象已逐行核对源码 + SSOT §9.2/§10.4/§28 原文 + gap-matrix 交叉核验）

## Summary

Phase 4 是「既有列填充 + 消费侧收紧」而非表结构演进：`question_bank` 的 `model_id/model_version/item_id/rubric_version` 列已在 Phase 2 `_migrate_question_bank_v2`（`server/db.py:433`）落位，本 phase **零新增迁移**。主体工作是三处「同源过滤口径」的收紧——落库侧 `generate_question_bank` 写版本绑定、消费侧 `readiness` 与 `selection` 把 Phase 2 的「版本近似放行」升级为「强制 model_id + model_version 匹配」——以及一处 FAILED 可见性、一处 orphan 路由顺序、一处 Pydantic 校验强化。

**Primary recommendation:** 本 phase 纯 Python 代码改造，不装任何新包、不改表结构、不碰 SSOT；按「落库填充 → readiness 收紧 + FAILED 明细 → selection 收紧 → orphan 路由 → update_model 校验 → todos 明细」六个触点推进，每触点用 `test_phase4_*.py` 单文件单进程回归，消费侧 WHERE 口径与 Phase 2 的 WR-15 教训（防 readiness/selection 两处公式漂移）对齐。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| question_bank 行写 model_id/model_version/item_id | API/Backend（service 落库） | — | `generate_question_bank` 是唯一落库点，绑定列在服务层写入 |
| 升版后旧题库失效（消费侧过滤） | API/Backend（service 查询） | — | `readiness` + `selection` 的 WHERE 加 model_version 过滤，不改旧行 status |
| 开考阻止（升版须重建） | API/Backend（readiness 前置） | Frontend（仅展示 409 detail） | `check_session_readiness` 已在 `create_session` 的 INSERT 前预检 |
| 生成失败可见 | API/Backend（readiness + todos） | Frontend（零改动） | 后端 detail 带 error_msg；Vue 对未知键安全 |
| orphan 路由 | API/Backend（FastAPI 路由声明序） | — | 纯路由顺序修复，无 DB 层改动 |
| 模型编辑字段校验 | API/Backend（Pydantic 边界校验） | — | 服务端拒绝非法值，`competency_item` 重建前拦截 |

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REF-2.5 | question_bank 演进（model/version 绑定、question_type、measurement_stage、rubric_version、锚点） | 列已落（`db.py:141-151`）；本 phase 只填 model_id/model_version/item_id/rubric_version="v1"，equivalence_group_id/integrated_bindings_json 延后 |
| REF-3.4 | 题库绑定 model/version；升版须重建否则阻止开考 | D-48 升版语义 + readiness/selection 收紧（`readiness.py:95-141`、`question_selection.py:219-244`） |
| REF-7.1 | /jds/orphan 路由顺序修复 | `main.py:75/77` 注册序致 `jds.py:79` `/jds/{jd_id}` 吞 `/jds/orphan`；`positions.py:87-95` 已有被遮蔽的路由 |
| REF-7.2 | 模型编辑字段校验（NaN/范围/类别/重复 std_name） | `models.py:15-28` ModelItem 强化 + `update_model` 重复校验；NaN 已验证会静默绕过 Σ=100% |
| REF-8.4 | 题库生成失败静默 → 可见 | `readiness.py:95-105` FAILED 分支加 error_msg + `positions.py:25-27` todos 扩展明细 |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.110（已装） | 路由声明序匹配 + Pydantic 校验 | 项目既有栈，路由顺序修复即用 FastAPI 声明序语义 |
| pydantic | 2.10.3（已装） | ModelItem 字段级校验（allow_inf_nan/le/ge/Literal） | 项目既有栈；`allow_inf_nan=False` 是 v2 拒绝 NaN/∞ 的正解 |
| sqlite3（stdlib） | 内置 | raw SQL + get_conn() per-call | 项目强制「raw SQL no ORM」纪律 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| typing.Literal | stdlib | importance 枚举 `{required, preferred, plus}` | D-53 类别越界拒绝 |
| math | stdlib | `math.isfinite` 备选（若不用 allow_inf_nan） | 备用路径，推荐 allow_inf_nan=False 为主 |

**Installation:** 无新增包。全部改造复用现有依赖（fastapi/pydantic/sqlite3/typing）。

**Version verification:** pydantic 2.10.3 已在本机 `python3 -c "import pydantic; print(pydantic.VERSION)"` 确认；fastapi/sqlite3 由项目 requirements.txt 固定，无需 npm/pip 安装。

## Package Legitimacy Audit

本 phase **不安装任何外部包**（纯 Python 代码改造，复用既有 fastapi/pydantic/sqlite3/typing.Literal/math 等 stdlib 与已装依赖）。Package Legitimacy Gate 不适用——无 npm/pypi 新增依赖。

## Architecture Patterns

### System Architecture Diagram

```text
confirm(v2) [models.py:113]
   └─ INSERT question_bank_task(QUEUED, model_id, model_version=v2) [models.py:136]
   └─ background generate_question_bank(position_id, model_id)
        │  fetch version FROM competency_model WHERE model_id=?
        │  fetch items WHERE model_id=?
        └─ per item 判重(model_id, model_version, std_name, category, difficulty)
           └─ call_llm_json(question_gen)  →  _insert_question(+model_id/+model_version/+item_id/+rubric_version)
              └─ conn.commit()  (逐 item commit，先 commit 再调 LLM 模式保持)

create_session(position_id) [assessment.py:99]
   └─ _latest_confirmed_model → model{model_id, version}
   └─ check_session_readiness(position_id, model) [readiness.py:40]
        │  task(status, error_msg) WHERE position_id/model_id/model_version → GENERATING/FAILED
        │  _question_count_by_category(+model_id/+model_version)
        │  _covered_std_names(+model_id/+model_version)
        └─ tier LEFT JOIN(+qb.model_id/qb.model_version) → plan_quotas → INCOMPLETE | None

select_next_question(session_id) [question_selection.py:266]
   └─ session{model_id, model_version} [line 284 已取]
   └─ _load_candidate_rows(conn, position_id, model_id, model_version)
        └─ WHERE b.model_id=? AND b.model_version=?（收紧，去 NULL 放行）
```

### Recommended Project Structure（本 phase 无新文件结构，仅改既有文件 + 新增测试）

```
server/
├── db.py                        # 无改动（v2 列已落，_migrate_question_bank_v2 已存在）
├── services/
│   ├── question_bank.py         # 落库填充 + 判重键升级
│   ├── readiness.py             # 三处 WHERE + tier JOIN + FAILED 明细
│   └── question_selection.py    # _load_candidate_rows 签名 + WHERE 收紧
├── api/admin/
│   ├── models.py                # ModelItem 校验 + update_model 重复 std_name
│   ├── jds.py                   # 新增 /jds/orphan（置于 /jds/{jd_id} 前）
│   └── positions.py             # get_todos 明细扩展；list_orphan_jds 移除（迁入 jds.py）
└── test_phase4_*.py             # 新增，单文件单进程 + tempfile + mock 三件套
```

### Pattern 1: 消费侧过滤同源纪律（WR-15 防漂移）

**What:** readiness 与 selection 的题库 WHERE 口径必须一致——两处都按「status='active' AND (scope='general' OR scope='position' AND position_id=?) AND model_id=? AND model_version=?」过滤。Phase 2 已把配额公式抽成 `plan_quotas` 纯函数共享，本 phase 的 model_version 谓词同样必须在两处同步加，且落点同源（`readiness.py` 的 `_question_count_by_category`/`_covered_std_names`/tier LEFT JOIN 与 `question_selection.py` 的 `_load_candidate_rows`）。

**When to use:** 任何「题库行有效性」判定。不要在某处用 model_id 过滤、另一处只用 model_version——D-50 锁定两列都要 `AND b.model_id=? AND b.model_version=?`。

### Pattern 2: 先 commit 再调 LLM（SQLite 单写者）

**What:** `generate_question_bank` 逐 item `conn.commit()` 后才进入下一 item 的 `call_llm_json`。Phase 4 的 model_id/model_version/item_id 填充全在 `_insert_question` 的 INSERT 内（内存参数，非新事务），**不破坏**该模式——不需要新增 commit 点。

**When to use:** 混 DB 写与 LLM 调用的任何新代码；本 phase 只改 INSERT 列与 WHERE，不引入新 LLM 调用点，天然合规。

### Anti-Patterns to Avoid

- **在 readiness 里改旧题 status 实现「升版失效」:** D-48 锁定旧题 status 保持 active，靠消费侧 model_version 过滤失效——标 inactive 会破坏审计/历史与 §9.2「有效题目 = active 且 model/version 匹配」字面。**做**：只加 WHERE 过滤。
- **只加 model_id 过滤不加 model_version:** model_id 与 version 是 1:1（每次 confirm 新 model_id + 递增 version），但 §9.2 明文「model/version 匹配」，且 question_bank_task 按 `model_id + model_version` 双键。**做**：两列都过滤。
- **在 orphan 修复时保留 positions.py 的重复路由:** `positions.py:87` 已有 `list_orphan_jds`，若在 `jds.py` 新增同路径路由而不移除原函数，会产生两个同名路由（首个声明生效，positions 版成死代码）。**做**：把函数整体迁到 jds.py，positions.py 只留 `get_todos` 里的 orphan_jds 计数。
- **用 `sum()` 做 Σ=100% 却先不拦 NaN:** 已验证 `sum([nan, 0.3, 0.7])` → nan，`abs(nan-1.0) > 0.005` → False，NaN 静默通过现有校验（`models.py:85-88`）污染 `competency_item`。**做**：weight 字段级 `allow_inf_nan=False`，让 Pydantic 在校验入口就 422 掉。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| NaN/∞ 权重拒绝 | 手写 `math.isnan()` 逐项扫 | Pydantic v2 `Field(ge=0, le=1, allow_inf_nan=False)` | v2 原生 `allow_inf_nan=False` 在解析期拒绝 NaN/±inf，边界一致、错误信息结构化（422） |
| importance 类别枚举 | `str` + 手写 if 白名单 | `Literal["required","preferred","plus"] \| None` | 与 `competency_item.importance` CHECK 口径对齐，Pydantic 自动 422 |
| orphan 路由优先级 | 自定义 URL 前缀正则/中间件 | FastAPI 声明序（`@router.get("/jds/orphan")` 置于 `/jds/{jd_id}` 前） | FastAPI 按声明序匹配，纯顺序修复即可，零自研路由逻辑 |
| 失败明细截断 | 手写字符串切片到处散 | 复用 `generate_question_bank` 已有的 `str(e)[:200]` 口径 | readiness detail 附 `error_msg[:200]`，避免注入敏感堆栈 |

**Key insight:** 本 phase 的「复杂问题」全部有既有标准解（Pydantic 约束、FastAPI 声明序、幂等嗅探迁移），无需任何手写框架。唯一要自研的是「重复 std_name 校验」——用 `ModelUpdateBody` 的 `@model_validator` 或 `update_model` 内一个 `seen` 集合按 `(std_name, category)` 判重（D-53 锁定，无第三方库需求）。

## Common Pitfalls

### Pitfall 1: orphan 路由「已存在」却仍 404（声明序 vs 位置）
**What goes wrong:** `positions.py:87` 已有 `@router.get("/jds/orphan")`，但 `main.py:75` 先注册 `admin_jds.router`、`main.py:77` 后注册 `admin_positions.router`，FastAPI 按注册序匹配，`/jds/{jd_id}`（`jds.py:79`）把 `jd_id="orphan"` 吞掉 → 恒 404。gap-matrix 第 115 行已实测确认此行为。
**Why it happens:** 路由声明在 A 文件、顺序由 B 文件（main.py）决定，跨文件声明的顺序隐患。
**How to avoid:** 把 orphan 路由迁入 `jds.py`，置于 `jd_detail` 之前（同文件内声明序可控），并移除 `positions.py` 的 `list_orphan_jds`。
**Warning signs:** `GET /api/admin/jds/orphan` 返回 404「JD 不存在」而非列表。

### Pitfall 2: 判重键不含 model_version → v2 生成整链跳过
**What goes wrong:** 现状 WR-03 判重按 `(std_name, category, difficulty)`（`question_bank.py:122-149`），升版后 v2 生成时发现 v1 已 active 同 std_name 行 → `exists` 命中 → 整 item 跳过，v2 题库空 → readiness 永久 INCOMPLETE。
**Why it happens:** 判重键的「代际」维度缺失，v1/v2 的 position_id 相同无法区分。
**How to avoid:** D-49 判重键升级为 `(model_id, model_version, std_name, category, difficulty)`；general 题（无 difficulty）同加 model_id + model_version。
**Warning signs:** 升版后 `question_bank` 无新增行、readiness 报「题库不完整」但 v1 题库明明满。

### Pitfall 3: FAILED 分支落空（当前落下看题量）
**What goes wrong:** `readiness.py:104-105` 注释「FAILED → INCOMPLETE（Phase 4 再做）」——现状 FAILED 行不显式拦，落下到「看实际可选题量」，若旧版题量恰好够，升版失败会被放行开考。
**Why it happens:** 过渡态设计只处理了 QUEUED/RUNNING，FAILED 依赖题量兜底。
**How to avoid:** D-51 显式 FAILED 分支——task status=FAILED 时直接返回 `QUESTION_BANK_INCOMPLETE` + 最新 FAILED 行 `error_msg[:200]`，不依赖题量。
**Warning signs:** 升版 confirm 后生成失败但 create_session 仍成功。

### Pitfall 4: selection/readiness 口径漂移（WR-15 重演）
**What goes wrong:** readiness 加了 model_version 过滤而 selection 没加（或反之），导致 readiness 判定「足量可开考」但 selection 实际选不到题（或选到旧版题）。
**Why it happens:** 两处 WHERE 独立维护，Phase 2 已为配额公式抽纯函数防漂移，model_version 谓词是新的漂移面。
**How to avoid:** D-50 锁定三处（readiness 两个 count + tier LEFT JOIN）与 selection 一处，四地全部 `AND model_id=? AND model_version=?`，落点同源、参数同源（都从 `model["model_id"]`/`model["version"]` 或 `session["model_version"]` 取）。

### Pitfall 5: NaN 权重静默污染（见 Anti-Patterns）
**What goes wrong:** `sum()` 遇 NaN 返回 NaN，`abs(NaN-1.0) > 0.005` 恒 False，Σ=100% 校验被绕过，NaN weight 写入 `competency_item`。
**Why it happens:** 字段级未拦 NaN/∞，聚合级比较对 NaN 不敏感。
**How to avoid:** `weight: float = Field(ge=0, le=1, allow_inf_nan=False)`——Pydantic v2 在解析期 422。
**Warning signs:** `competency_item.weight` 出现 NaN、报告聚合 total 变 NaN。

## Code Examples

### 1. 落库填充（question_bank.py `_insert_question` + `generate_question_bank`）

```python
# generate_question_bank 顶部补取 version（签名保持 (position_id, model_id) 不动）
model_row = conn.execute(
    "SELECT version FROM competency_model WHERE model_id=?", (model_id,)
).fetchone()
model_version = model_row["version"] if model_row else None

# _insert_question 签名加 model_id/model_version/item_id，INSERT 加四列
def _insert_question(conn, *, scope, position_id, model_id, model_version,
                     item, difficulty, qtype, stem, answer_key, rubric,
                     chain_key, chain_seq):
    conn.execute(
        "INSERT INTO question_bank(question_id, scope, position_id, model_id,"
        " model_version, item_id, std_name, category, difficulty, qtype, stem,"
        " answer_key, rubric, rubric_version, chain_key, chain_seq, source, status, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_id("q"), scope, position_id, model_id, model_version, item["item_id"],
         item["std_name"], item["category"], difficulty, qtype, stem,
         answer_key, rubric, "v1", chain_key, chain_seq, "llm_seed", "active", now_iso()),
    )
```

### 2. 判重键升级（question_bank.py 4 处 exists 查询）

```python
# scope='position' 且 difficulty 非 None：
"SELECT 1 FROM question_bank WHERE scope='position' AND model_id=? AND model_version=?"
" AND std_name=? AND category=? AND difficulty=? AND status='active' LIMIT 1"
# scope='general'（无难度维度，同加版本）：
"SELECT 1 FROM question_bank WHERE scope='general' AND model_id=? AND model_version=?"
" AND std_name=? AND category=? AND status='active' LIMIT 1"
```

### 3. readiness 收紧（readiness.py 三处 + FAILED 明细）

```python
# _question_count_by_category / _covered_std_names 签名加 model_id/model_version
" ... WHERE status='active' AND model_id=? AND model_version=?"
" AND (scope='general' OR (scope='position' AND position_id=?))"

# tier LEFT JOIN 加谓词（ci.model_id=? 邻位）：
" WHERE qb.status='active' AND qb.model_id=? AND qb.model_version=?"
" AND qb.category=? AND (qb.scope='general' OR (qb.scope='position' AND qb.position_id=?))"

# task 查询加取 error_msg + FAILED 分支（替换 line 104-105 注释）：
task = conn.execute(
    "SELECT status, error_msg FROM question_bank_task"
    " WHERE position_id=? AND model_id=? AND model_version=?"
    " ORDER BY created_at DESC LIMIT 1",
    (position_id, model["model_id"], model["version"]),
).fetchone()
if task is not None and task["status"] in ("QUEUED", "RUNNING"):
    return {"error_code": "QUESTION_BANK_GENERATING", "detail": "该岗位题库正在生成中，请稍后开考"}
if task is not None and task["status"] == "FAILED":
    detail = "该岗位题库生成失败，不可开考"
    if task["error_msg"]:
        detail += f"（{task['error_msg'][:200]}）"
    return {"error_code": "QUESTION_BANK_INCOMPLETE", "detail": detail}
```

### 4. selection 收紧（question_selection.py `_load_candidate_rows`）

```python
def _load_candidate_rows(conn, position_id, model_id, model_version):
    rows = conn.execute(
        "SELECT b.*, ci.weight AS item_weight, ci.importance AS item_importance,"
        " ci.item_id AS model_item_id"
        " FROM question_bank b"
        " LEFT JOIN competency_item ci ON ci.std_name=b.std_name AND ci.category=b.category"
        " AND ci.model_id=?"
        " WHERE b.status='active' AND b.category IN ('hard_skill','soft_skill')"
        " AND (b.scope='general' OR (b.scope='position' AND b.position_id=?))"
        " AND b.model_id=? AND b.model_version=?",  # 去 NULL 放行
        (model_id, position_id, model_id, model_version),
    ).fetchall()
    # 调用点（_select_next_question_locked line 299）传 session["model_version"]
```

### 5. orphan 路由（jds.py，置于 jd_detail 前）

```python
@router.get("/jds/orphan")
def list_orphan_jds() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT jd_id, job_title, company, source_type, status, created_at"
        " FROM jd_record WHERE position_id IS NULL ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]

@router.get("/jds/{jd_id}")  # 必须在本函数之后声明
def jd_detail(jd_id: str) -> dict: ...
```

### 6. update_model 校验（models.py）

```python
from typing import Literal

class ModelItem(BaseModel):
    std_name: str = Field(min_length=1)
    category: str = Field(pattern="^(hard_skill|soft_skill|experience|qualification)$")
    weight: float = Field(ge=0, le=1, allow_inf_nan=False)          # 拦 NaN/∞ + 单 item 越界
    required_level: int | None = Field(default=None, ge=1, le=5)
    importance: Literal["required", "preferred", "plus"] | None = None
    years: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    ...

# update_model 内（Σ=100% 之后）加重复 std_name 校验（D-53）：
seen: set[tuple[str, str]] = set()
for it in items:
    key = (it.std_name, it.category)
    if key in seen:
        raise HTTPException(400, f"同一类目内能力项重复：{it.std_name}({it.category})")
    seen.add(key)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| question_bank 无模型绑定（scope+position_id 复用） | model_id/model_version 强绑定 | Phase 2 已落列，Phase 4 填充+消费 | 升版后旧题自然失效（消费侧过滤） |
| 版本近似放行 `(model_id IS NULL OR ? IS NULL OR model_id=?)` | 强制 `model_id=? AND model_version=?` | Phase 4 | 存量 NULL 行不再命中，需配合 v2 题已绑定的落库 |
| 判重键 (position_id, std_name, category, difficulty) | (model_id, model_version, std_name, category, difficulty) | Phase 4 | v2 生成 v2 题，不再因 v1 题跳过 |
| 生成失败静默（FAILED 落表但 readiness 不显式拦） | FAILED → INCOMPLETE + error_msg | Phase 4 | 管理员可查失败原因 |

**Deprecated/outdated:**
- `_load_candidate_rows` 的「版本近似」子句（`question_selection.py:233`）——Phase 2 过渡态设计者已注释「Phase 4 REF-3.4 收紧为强制绑定」，本 phase 移除 NULL 放行。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `model_id` 与 `model_version` 是 1:1（每次 confirm 新 model_id + 递增 version），故 `generate_question_bank` 顶部 `SELECT version FROM competency_model WHERE model_id=?` 能唯一取到 version | 落库填充 | 低——若未来 model_id 复用，需改从 task 行取 version；当前 confirm/retry 都锚定单一 model_id |
| A2 | orphan 迁移后 `get_todos` 的 orphan_jds 计数（`positions.py:21-23`，含 `status != 'failed'`）与 `/jds/orphan` 列表口径是否统一，属 Claude's Discretion；D-52 字面「WHERE position_id IS NULL」（无 status 过滤）与现有实现「AND status != 'failed'」不一致 | orphan 路由 | 中——若两者口径漂移，待办计数与列表条数对不上；需规划时敲定统一口径 |
| A3 | `generate_question_bank` 签名保持 `(position_id, model_id)` 不变、内部自取 version（两个调用点 confirm_model/retry_question_bank_task 都只传这两参） | 落库填充 | 低——若改为传 version 需同步改两处调用点，纯内部选择 |

**注：** 除上表外，其余技术断言（列已落、路由顺序、Pydantic v2 `allow_inf_nan`、NaN 绕过 Σ 校验）均已逐行源码/实测核验，非假设。

## Open Questions（已裁定 2026-09-05 [04-009]/[04-010]）

1. **orphan 列表字段口径与 status 过滤**
   - What we know: 现有 `positions.py:87` 的 `list_orphan_jds` 字段为 `jd_id/job_title/company/source_type/status/created_at`，查询含 `AND status != 'failed'`；D-52 说「字段同 list_jds」（即含 low_confidence/error_msg）且「WHERE position_id IS NULL」（无 status 过滤）。`get_todos` 的 orphan 计数含 `status != 'failed'`。
   - What's unclear: 迁入 jds.py 时字段集与 status 过滤取哪套。
   - Recommendation（已裁定 [04-009]）: 选项 B（现有 `positions.py` 实现：字段子集 + `status != 'failed'`，与 `get_todos` 计数口径一致、前端已只消费 job_title/company/source_type/created_at/jd_id）。

2. **admin todos 失败明细的字段结构**
   - What we know: D-51 说 `question_bank_not_ready` 从计数扩展为「计数 + 明细」，Claude's Discretion 允许 `question_bank_failed` 新键 vs `question_bank_not_ready` 内嵌。前端 `Positions.vue` 当前**未展示** `question_bank_not_ready`（只展示 pending/stalled/orphan 三卡）。
   - What's unclear: 是否要在前端新增「题库失败」展示卡（D-13 预留「admin 页展示留 Phase 4」）。
   - Recommendation: 后端做「计数 + 失败明细」（`question_bank_not_ready` 保持 int，新增 `question_bank_failed` 明细列表）——已在 04-01 计划落定。前端展示卡：【已裁定 [04-010] 选项 A 前端零破坏】——本 phase 不做前端改动。

## Environment Availability

本 phase 无新增外部依赖（纯代码改造）。Step 2.6 结论：SKIPPED（无外部依赖）。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest（无 pytest.ini/conftest.py/pyproject.toml，默认收集） |
| Config file | 无 —— 沿用「单文件单进程」纪律（每文件顶部 tempfile + env + init_db） |
| Quick run command | `cd server && python -m pytest test_phase4_<area>.py -v` |
| Full suite command | 逐文件串行（禁止一次 pytest 收集多个 server/test_*.py——DB_PATH import 时互踩） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REF-2.5 | generate_question_bank 落库写 model_id/model_version/item_id/rubric_version="v1" | unit/integration | `python -m pytest server/test_phase4_binding.py -v` | ❌ Wave 0 |
| REF-3.4 | 升版后 readiness 对旧版题返回 INCOMPLETE（v2 未生成时开考被拦）；selection 只取 v2 题 | integration | `python -m pytest server/test_phase4_binding.py -v` | ❌ Wave 0 |
| REF-7.1 | `GET /api/admin/jds/orphan` 返回列表（非 404），且顺序先于 `/jds/{jd_id}` | integration | `python -m pytest server/test_phase4_orphan.py -v` | ❌ Wave 0 |
| REF-7.2 | update_model 拒绝 NaN weight / required_level=6 / importance=bad / 重复 std_name（保留 Σ=100%） | integration | `python -m pytest server/test_phase4_model_edit.py -v` | ❌ Wave 0 |
| REF-8.4 | 生成失败 → readiness 返回 INCOMPLETE + error_msg；get_todos 含失败明细 | integration | `python -m pytest server/test_phase4_fail_visible.py -v` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd server && python -m pytest test_phase4_<area>.py -v`（对应文件，< 30s）
- **Per wave merge:** 单文件逐个 `python -m pytest server/test_phase4_*.py -v`（不合并收集）
- **Phase gate:** 新增 test_phase4_* 全绿 + 既有 test_phase2_selection/test_question_bank 不回归（升版判重改动会触碰旧断言，需复核）

### Wave 0 Gaps
- [ ] `server/test_phase4_binding.py` — 覆盖 REF-2.5/REF-3.4（落库绑定 + 消费侧过滤 + 判重升级）
- [ ] `server/test_phase4_orphan.py` — 覆盖 REF-7.1（路由顺序回归）
- [ ] `server/test_phase4_model_edit.py` — 覆盖 REF-7.2（NaN/范围/枚举/重复）
- [ ] `server/test_phase4_fail_visible.py` — 覆盖 REF-8.4（FAILED 明细 + todos）
- [ ] 既有 `server/test_question_bank.py`（脚本式）与 `test_phase2_selection.py` 的判重/候选断言需复核是否因 model_version 过滤改动而需同步（判重键、`_load_candidate_rows` 签名变更会波及）

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | 否 | 无新增认证面（沿用 require_admin） |
| V3 Session Management | 否 | 无会话管理改动 |
| V4 Access Control | 是 | orphan/todos/update_model 均在 `dependencies=[Depends(require_admin)]` 的 admin router 下，已有角色限制；本 phase 不新增候选端入口 |
| V5 Input Validation | 是 | Pydantic v2 字段校验（weight allow_inf_nan/le/ge、required_level 1-5、importance Literal、years ge=0、重复 std_name）；error_msg 截断 [:200] 防堆栈/敏感信息注入 |
| V6 Cryptography | 否 | 无加密改动 |

### Known Threat Patterns for 本 phase 栈
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| NaN/∞ 权重绕过 Σ=100% 校验污染 competency_item | Tampering | `Field(ge=0, le=1, allow_inf_nan=False)` 解析期 422 |
| error_msg 携带 LLM 堆栈/敏感信息泄漏到 readiness detail | Information Disclosure | 复用 `str(e)[:200]` 截断，detail 不附原始异常对象 |
| 越权访问 orphan/todos 端点 | Elevation of Privilege | 已在 `require_admin` 依赖下，无需新加（本 phase 不改权限模型） |

## Sources

### Primary (HIGH confidence — 逐行源码 + SSOT 原文)
- `server/db.py:125-152`（question_bank DDL v2 列）、`:433-467`（`_migrate_question_bank_v2`）、`:680-699`（init_db 迁移调用序）
- `server/services/question_bank.py:56-67`（`_insert_question`）、`:88-181`（`generate_question_bank`）、`:122-149`（幂等判重）
- `server/services/readiness.py:16-37`（两 count）、`:95-105`（task/FAILED）、`:132-141`（tier LEFT JOIN）
- `server/services/question_selection.py:219-244`（`_load_candidate_rows` 版本近似）、`:284/299`（session model_version / 调用点）
- `server/api/admin/models.py:15-28`（ModelItem）、`:67-110`（update_model + Σ=100%）、`:113-146`（confirm_model task 行）
- `server/api/admin/jds.py:79-90`（jd_detail `/jds/{jd_id}`）
- `server/api/admin/positions.py:11-33`（get_todos）、`:87-95`（list_orphan_jds 被遮蔽）
- `server/main.py:75/77`（router 注册序：jds 先于 positions）
- `design/final-design/总设计文档.md` §9.2（question_bank 演进）、§10.4（开考检查三态）、§28 第 4 项（题库绑定/失败可见/orphan/模型校验）
- `research/ssot-code-gap-matrix.md` 第 34/49/114/115/116/130 行（2.5/3.4/7.1/7.2/8.4 契约核对）

### Secondary (MEDIUM confidence — 交叉核验)
- `server/api/assessment.py:99-139`（create_session → check_session_readiness 调用链）、`:42-54`（`_latest_confirmed_model` 单源）
- `web/src/views/admin/Positions.vue:13-32/153-186`（todos 三卡展示 + orphan 列表字段消费）
- `server/test_phase2_migration.py:141`（v2 列名清单佐证）、`server/test_question_bank.py`（既有判重断言位置）
- `.planning/codebase/ARCHITECTURE.md`（分层/SQLite 单写者/raw SQL 纪律）、`TESTING.md`（单文件单进程三件套，注：文件清单已过时——现新增 test_p0_*/test_phase2_*/test_phase3_*）

### Tertiary (LOW confidence — 需规划时确认)
- 无（本 phase 全部关键断言均达源码级 HIGH/交叉核验 MEDIUM）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部复用既有 fastapi/pydantic 2.10.3/sqlite3，本机已实测 pydantic 版本
- Architecture: HIGH — 六触点逐行定位，SSOT §9.2/§10.4 目标态已核对
- Pitfalls: HIGH — NaN 绕过 Σ 校验已本机实测；orphan 遮蔽已由 gap-matrix 实测 + main.py 注册序双重确认

**Research date:** 2026-09-05
**Valid until:** 2026-09-19（慢速域；DB/校验语义稳定，唯一易变项为 Pydantic 版本——若未来升级 pydantic ≥3 需复核 `allow_inf_nan` 语义）

---

## RESEARCH COMPLETE
