# Phase 1: P0 安全与主链修复 - Pattern Map

**Mapped:** 2026-09-02
**Files analyzed:** 16（新建 5 / 修改 11）
**Analogs found:** 14 / 16（2 项无代码库先例，用 RESEARCH.md 已实测样例代替）

> 本文件回答"新文件该抄谁的代码"。所有行号以当前 `feature/m5-assessment` 工作树为准。
> RESEARCH.md（01-RESEARCH.md）中的 [VERIFIED] 代码样例（触发器 DDL、append_event 形状、helper 形状）已在本机实测，可视为"可抄样例"，本文件在对应位置引用不重复全文。

## File Classification

| 新建/修改文件 | 角色 | 数据流 | 最近模拟（Analog） | 匹配度 |
|---|---|---|---|---|
| `server/core/security.py` 顶部（或 `server/api/assessment.py` 顶部）—— 新增 `load_owned_session` / `load_owned_report` | middleware（鉴权 helper） | request-response | `server/core/security.py:33-57`（`_current_user` / `require_admin`） | exact |
| `server/api/assessment.py`（修改：8 路由接 helper、create_session 前插检查、request_report 改串行链、409 转换） | controller | request-response | 自身现状 + `server/api/admin/positions.py:43-65`（404/409 判定风格） | exact |
| `server/db.py`（修改：`_DDL` 追加 assessment_state_event + 触发器、question_bank_task） | config（schema） | — | `server/db.py:189-196`（report 表）与 `:207-214`（eval_results 时间戳对） | exact |
| `server/services/state_events.py`（新建，名可 plan 定）—— `append_event()` | service / utility | 事件追加（只写） | `server/services/scoring.py:146-154`（单事务落库）+ `pipeline.py:14-19` | role-match |
| `server/services/readiness.py`（新建，名可 plan 定）—— `check_session_readiness()` | service | 只读预检（request-response 前置） | `server/services/question_selection.py`（同款 conn + CATEGORY_QUOTA 口径） | role-match |
| `server/services/scoring.py`（修改：score_session 入口护栏 + docstring 同步） | service | batch（内存算完单事务落库） | 自身 `:107-155` | exact |
| `server/services/question_bank.py`（修改：task 行 RUNNING/SUCCEEDED/FAILED 维护） | service | batch | 自身 `:70-120` | exact |
| `server/api/admin/positions.py`（修改：todos 扩展新键） | controller | request-response | 自身 `:11-28`（get_todos 聚合） | exact |
| `server/api/admin/models.py`（修改：confirm 插 question_bank_task QUEUED 行） | controller | request-response + background | 自身 `:85-107`（confirm_model） | exact |
| `server/test_p0_security.py`（新建） | test | request-response | `server/test_m5_backend.py:6-38`（头部模板）+ `test_m7_backend.py:28-46`（admin 种子） | exact |
| `server/test_p0_chain.py`（新建） | test | request-response | `server/test_m5_backend.py:213-287`（答题闭环主链测试） | exact |
| `server/test_m5_backend.py`（修改 :257-258 断言 → 期望 409） | test | request-response | 自身 | exact |
| `server/test_m6_backend.py`（修改：逐条过直调断言） | test | 脚本式 | 自身（`:22-32` check() 风格**不得**改成 pytest——D-09 锁定） | exact |
| `eval/virtual_candidates.py`（修改 :131-136 顺序一行调整） | 测试资产 | batch | 自身 | exact |
| `web/src/router/index.js`（修改 :49-60 两条路由 meta） | route（前端） | request-response | 自身 `:37-42`（`requiresAuth: true` 既有写法） | exact |
| `web/src/views/assessment/PositionAssess.vue`（修改 :128-143 catch 409 提示） | component | request-response | 自身 catch + `web/src/utils/sse.js:33-40`（detail 提取惯例） | exact |

> **CONTEXT 集成点勘误（RESEARCH Pattern 5 已核实，本文件再次确认）：** `assessment.createSession` 的实际调用点在 **`web/src/views/assessment/PositionAssess.vue:131`**（onStart），`Positions.vue:76-78` 只做 `router.push` 跳转、不调 API。409 提示改动应落在 PositionAssess.vue 的 catch 分支（plan 可决定是否两文件皆轻触，但主落点必须是 PositionAssess.vue，否则提示永远不会出现）。

---

## Pattern Assignments

### 01-01 越权 helper：`load_owned_session` / `load_owned_report`（新建 helper）

**放置（Claude's Discretion，两处皆可行，无循环导入风险）：**
- 放 `server/core/security.py` 顶部：该文件已 import `get_conn`（security.py:10），helper 查 assessment_session/report 无需新增依赖；api/assessment.py 已 import security（assessment.py:6）。
- 放 `server/api/assessment.py` 顶部：该文件已 import `get_conn`（assessment.py:7）与 `HTTPException`（:4）。
- 判定依据：若希望"鉴权语义集中在 core"，放 security.py；若希望"测评资源语义靠近路由"，放 assessment.py 顶部。plan 阶段二选一。

**Analog：`server/core/security.py:33-47`**（`_current_user` 的"查行→dict(row)→无行抛 HTTPException"三段式，与 helper 的 404 语义同构）：

```python
def _current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    ...
    conn = get_conn()
    row = conn.execute(
        "SELECT user_id, username, role, is_active FROM user WHERE user_id=?",
        (payload["sub"],),
    ).fetchone()
    if row is None or not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return dict(row)
```

**Helper 形状**（D-01/D-02/D-03 已锁定，RESEARCH.md Pattern 1 有完整 [VERIFIED] 样例，关键点摘录）：
- 单查询 `WHERE session_id=? AND user_id=?`（admin 读豁免用 OR）；无行统一 `HTTPException(404, "会话不存在")`，不引入 403。
- admin 边界只读：读路由传 `allow_admin_read=True`，写路由不传（owner-only）。
- **判定顺序（Pitfall 10）：** `user_id == current` 恒通过（admin 访问自己的资源必须走通），仅非 owner 时才看 admin 读豁免。
- report 侧用 join：`SELECT r.* FROM report r JOIN assessment_session s ON s.session_id=r.session_id WHERE r.report_id=? AND s.user_id=?`；`get_report_by_session` 用 `WHERE r.session_id=? AND s.user_id=?`；`submit_feedback` 经 `load_owned_report`（写，owner-only）——**Pitfall 5：最容易漏接的一条**。

---

### 01-01 路由接入：`server/api/assessment.py`（修改）

**Analog：自身现状 + admin/positions.py 的 404/409 风格。**

**关键前置改动——路由需注入 user：** 现文件 :15 的 router 级依赖只做 401 拦截，**不注入 user 对象**；8 条目标路由中目前只有 `create_session`（:60）与 `submit_form`（:210）带 `user: dict = Depends(require_login)` 参数。其余 6 条（get_session :98、submit_answer :130、score_session_endpoint :234、request_report :260、get_report_by_session :273、get_report :286、submit_feedback :298——共 7 条需补）必须逐条加 `user: dict = Depends(require_login)`，helper 才有 `user_id/role` 可用。`submit_form` 是"路由签名 + 所有权检查"的现成参照（它已取 `user["user_id"]` 落库，assessment.py:226）。

**替换目标——现状"只查存在不查归属"（以 get_session 为例，:97-107）：**

```python
@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    """会话状态：当前题 = 第一个未作答（answered_at IS NULL）的题。"""
    conn = get_conn()
    s = conn.execute(
        "SELECT session_id, status, position_id, model_version FROM assessment_session"
        " WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
```

改后：路由首调 `load_owned_session(get_conn(), session_id, user, allow_admin_read=True)`，删掉原"只查 id"的 SELECT/404 块（原 404 分支由 helper 接管，语义不变）。

**8 条路由 × 读写 × admin 豁免矩阵（覆盖清单，逐条对账用）：**

| 路由（现行号） | 方法 | helper | allow_admin_read |
|---|---|---|---|
| get_session (:97) | GET | load_owned_session | 是 |
| submit_answer (:129) | POST | load_owned_session | 否（写） |
| submit_form (:209) | POST | load_owned_session | 否 |
| score_session_endpoint (:233) | POST | load_owned_session | 否 |
| request_report (:259) | POST | load_owned_session | 否 |
| get_report_by_session (:272) | GET | load_owned_report（按 session_id） | 是 |
| get_report (:285) | GET | load_owned_report（按 report_id） | 是 |
| submit_feedback (:297) | POST | load_owned_report（按 report_id，写） | 否 |

`POST /sessions`（create_session :59）与 `GET /positions`（:18）不涉他人资源，无需 helper。

**409 判定风格 analog：`server/api/admin/positions.py:48-52`**（先 404 再 409 的顺序，helper 接管 404 后保留状态类 409）：

```python
    pos = conn.execute("SELECT status FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "岗位不存在")
    if pos["status"] != "pending_review":
        raise HTTPException(status.HTTP_409_CONFLICT, "仅 pending_review 岗位可审核")
```

`submit_answer` 自身 :143-144 已有同款（`s["status"] != "in_progress"` → 409），保持不动。

---

### 01-02 DDL 追加：`server/db.py`（修改）

**Analog：`_DDL` 内既有表块。**

**新表列型惯例（analog：report 表，db.py:189-196；时间戳对 analog：eval_results，db.py:207-214）：**

```sql
CREATE TABLE IF NOT EXISTS report (
  report_id   TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES assessment_session,
  total_score REAL NOT NULL,
  gate_passed INTEGER NOT NULL,
  report_json TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_results (
  task_id      TEXT PRIMARY KEY,
  ...
  created_at   TEXT NOT NULL,
  completed_at TEXT
);
```

惯例要点（两新表照抄）：TEXT 主键 + `REFERENCES` 外键 + `created_at TEXT NOT NULL` + 可空结束时间列；**不写 CHECK**（N11——注意这与库内旧表大量 CHECK 不同，新表是刻意例外，actor_type/status 走 helper 代码校验）。

**追加位置：** `_DDL` 字符串末尾（:215 `"""` 之前），带分节注释（既有 `-- ============ 模块三新增…` 风格，:187）。`init_db()` 的 `conn.executescript(_DDL)`（:287）幂等建表，无需改 init_db。

**表结构权威：** SSOT `design/final-design/总设计文档.md` §13.1（:390-400，全文 19 列 + `UNIQUE(session_id, sequence_no)`）。触发器 DDL（`CREATE TRIGGER IF NOT EXISTS … RAISE(ABORT)`）在 RESEARCH.md Pattern 2 有已实测全文，直接照抄；注意 RESEARCH Pitfall 2：触发器必须 `IF NOT EXISTS`，且事件表永不做重建式迁移（`DROP TABLE` 连带删触发器）。

**反面教材（勿模仿）：** `_migrate_llm_trace`（db.py:226-251）的嗅探式表重建是脆弱区（D-10 反模式清单明示新表不走此路），新表只走 `_DDL` 追加。

---

### 01-02 事件写入：`server/services/state_events.py`（新建，名可 plan 定）

**无代码库先例（库内无任何事件写入代码）。** 组合两个既有部件：

**ID/时间 analog：`server/services/pipeline.py:14-19`（直接 import 复用）：**

```python
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"
```

**单事务落库 analog：`server/services/scoring.py:146-154`**（append_event 的"同事务取号+插入"照此节奏——先 SELECT 取号，再 INSERT，显式 commit 由调用者事务决定）：

```python
    # 2) 单事务写库
    conn.execute("DELETE FROM question_score WHERE session_id=?", (session_id,))
    conn.executemany(
        "INSERT INTO question_score(score_id, session_id, question_id, item_id,"
        ...
    )
    conn.commit()
```

`append_event` 完整签名与 MAX+1 取号 SQL 见 RESEARCH.md Pattern 2 的 [VERIFIED] 样例（`SELECT COALESCE(MAX(sequence_no), 0) + 1 …` + `UNIQUE(session_id, sequence_no)` 兜底）。参数形状按 SSOT §13.1 逐列对齐，Phase 1 未用列（idempotency_key/policy_version/correlation_id 等）不写即默认 NULL。

**迁移点接入位置（api/assessment.py 内，事件行与快照 UPDATE 同事务）：**
- `create_session`：INSERT 会话（:79-84）后、`conn.commit()`（:92）前 → `SESSION_CREATED`（candidate）。
- `submit_answer`：`answered_at` UPDATE（:186-189）与 finish 的 `status='completed'`（:190-194）处 → QUESTION_ANSWERED（candidate）/ SESSION_COMPLETED（system），与 :202 的 `conn.commit()` 同事务。
- `submit_answer` 的 commit-before-LLM 纪律（:167-169，本阶段**不得破坏**）：

```python
    # 先提交用户消息再调 LLM：llm_trace 用新连接写库，本连接持写事务会 database is locked
    conn.commit()
```

- `request_report` → TASK_QUEUED；`_generate_report_task` 链入口/成功/失败 → TASK_STARTED + SESSION_ENTERED_SCORING / TASK_SUCCEEDED / TASK_FAILED（均 system）。后台链事件遵守 scoring.py:107 模式：LLM 调用前不持写事务，事件行与最终落库同事务或紧随其后独立小事务。

---

### 01-03 串行链 + 护栏：`server/services/scoring.py`（修改）

**Analog：自身 `score_session`，:107-155（整段保留"内存算完单事务落库"骨架，只在入口加护栏）。**

**入口现状（:113-118，护栏插点）：**

```python
    conn = get_conn()
    session = conn.execute(
        "SELECT model_id FROM assessment_session WHERE session_id=?", (session_id,)
    ).fetchone()
    if session is None:
        raise ValueError(f"会话不存在: {session_id}")
```

改法：SELECT 加 `status` 列；沿用 `ValueError` 作服务层护栏载体（现状 :118 已用，API 层捕获转 `HTTPException(409, str(e))` 最贴合）。

**伴生小改（Pitfall 9）：** docstring `:108` 的"幂等：重打先删旧行"须同步收窄语义，且 :147 的 `DELETE FROM question_score` 在护栏生效后的行为需 plan 明确（completed 已不可达该行；in_progress 内重复调用是否保留删旧行为）。

**⚠ 关键张力（planner 必须裁决，四处证据互相牵制）：**

D-09 字面 = "completed 再调→409；in_progress 调评分属非法前置→409"，但 RESEARCH.md 自身的四条测试证据要求更细的语义：

| 证据（RESEARCH.md 出处） | 要求的行为 |
|---|---|
| m5 :257-258 断言重写（Pitfall 4） | POST /score 在 completed 会话 → **409** |
| m6 `_seed_full_chain` 直调（:164） | score_session 直调 **in_progress** 会话 → 通过（"m6 不受影响，已核对"） |
| eval 顺序调整（A4/Pitfall 4） | score_session 直调 **completed** 会话 → 被拒（故需先 score 后置 completed） |
| e2e 串行断言（Code Examples） | 后台链对 **completed** 会话 score_session → **必须成功**（question_score>0 是成功标准 2） |

后两条同状态不同结果 → **护栏必须区分调用方**。与全部四条证据一致的唯一形态：`score_session` 服务层拒绝 completed（护 API 与直调双路径），**串行链（`_generate_report_task`）经内部参数/内部函数豁免**——这正是 D-03"串行化后评分/报告由服务端内部链触发，不经候选人端点"的实现面。D-09 后半句（"in_progress 调评分属非法前置"）与 m6-unaffected 证据冲突，planner 须按上表裁决（推荐读法：该句指 **request_report** 对 in_progress 会话 → 409 非法前置，score 层 in_progress 放行）。

**串行链落点（api/assessment.py :251-269，改动极小）：**

现状（:251-269）：

```python
def _generate_report_task(session_id: str) -> None:
    """后台任务：生成报告。异常静默（前端轮询 report 表为空即判失败/未完成）。"""
    try:
        generate_report(session_id)
    except Exception:  # noqa: BLE001
        pass


@router.post("/sessions/{session_id}/report", status_code=status.HTTP_202_ACCEPTED)
def request_report(session_id: str, background: BackgroundTasks) -> dict:
    ...
    background.add_task(_generate_report_task, session_id)
    return {"session_id": session_id, "status": "generating"}
```

改法（D-08 方案 B）：`_generate_report_task` 内在 `generate_report(session_id)` 前加 `score_session(...)`（带链内豁免）；202 响应体、BackgroundTasks、前端 Report.vue 轮询全部不动。`score_session_endpoint`（:233-246）保留，只加 user 参数 + helper + 服务层 ValueError→409 转换。

---

### 01-04 readiness：`server/services/readiness.py`（新建，名可 plan 定）

**Analog（配额口径 + 查询形态）：`server/services/question_selection.py`。**

```python
# 各类目选题配额（07 §6.2 题量分配）
CATEGORY_QUOTA = {"hard_skill": 6, "soft_skill": 2, "experience": 2}
```

（question_selection.py:9；D-11 锁定"配额可行"必须用此现行口径，勿用 config.CATEGORY_RATIO）

**题库可选题量查询 analog（question_selection.py:23-27，readiness 的"实际可选题量"判定照抄此 WHERE 口径——Pitfall 3：先看实际题量，task 行仅区分 GENERATING/INCOMPLETE，"无 task 行 + 题库足量"→就绪）：**

```python
    rows = conn.execute(
        "SELECT * FROM question_bank WHERE status='active' AND category=?"
        " AND (scope='general' OR (scope='position' AND position_id=?))"
        " ORDER BY CASE difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 WHEN 'hard' THEN 2 ELSE 3 END",
        (category, position_id),
    ).fetchall()
```

**confirmed 模型 + items 数查询 analog：`api/assessment.py:69-75`（create_session 已有同款）与 `:22-28`（list_positions 的 `json_array_length(json_extract(...))` 写法——REF-8.5 模型 items 空判定直接复用）：**

```python
        " json_array_length(json_extract(m.model_json,'$.items')) AS item_count"
```

**函数形态：** 模块级函数 + `conn = get_conn()` per-call（全 services 惯例，见 question_selection.py:58-60、scoring.py:113）；返回 `None | {"error_code": ..., "detail": ...}`（RESEARCH Pattern 5 骨架）。三个失败状态名（QUESTION_BANK_GENERATING / QUESTION_BANK_INCOMPLETE / MODEL_NOT_MEASURABLE）在检查函数一处统一返回；no-op 检查位（综合槽位/表单 schema/新配额）只留函数体占位。

**接入点：`create_session`（api/assessment.py:59-94）。** 检查插在 :67 的 422 校验之后、:69 模型查询之前（或紧随模型查询——plan 定，但必须在 :77 INSERT 会话之前，硬性口径"失败绝不创建会话"）。409 返回形态见 RESEARCH Pattern 5（dict detail `{error_code, message}`，本机实测可序列化进 `r.json()["detail"]`）。

---

### 01-04 question_bank_task 维护：`server/services/question_bank.py`（修改）

**Analog：自身 `generate_question_bank`，:70-120。**

```python
def generate_question_bank(position_id: str, model_id: str) -> None:
    """为 confirmed 模型生成题库（异步任务调用）。失败不抛，仅静默（可手动重触发）。"""
    conn = get_conn()
    pos = conn.execute("SELECT name FROM position WHERE position_id=?", (position_id,)).fetchone()
    if pos is None:
        return
```

改动锚点：
- **开头置 RUNNING**：函数取 conn 后（:72 之后）；注意 :73-75 的 `pos is None: return` 早退分支——该分支 task 行如何处置（置 FAILED 或保持 QUEUED）plan 须明确，勿静默漏更。
- **结尾置 SUCCEEDED**：循环结束处（:120 最后一次 `conn.commit()` 之后）。
- **异常置 FAILED + error_msg**：现状全函数**无 try/except**（docstring "失败不抛，仅静默"）——需包一层 try/except 落 FAILED 再静默退出（"现状失败静默改为至少落表"，D-12）。签名不变（confirm 的 `background.add_task(generate_question_bank, ...)` models.py:105 依赖此签名）。

**QUEUED 插行点 analog：`server/api/admin/models.py:98-105`（confirm_model）**——插在 `conn.commit()`（:102）之后、`background.add_task`（:105）之前：

```python
    conn.execute(
        "UPDATE competency_model SET status='confirmed', confirmed_by=?, confirmed_at=? WHERE model_id=?",
        (admin["user_id"], now_iso(), model_id),
    )
    conn.commit()

    from ...services.question_bank import generate_question_bank
    background.add_task(generate_question_bank, row["position_id"], model_id)
```

新 INSERT 紧跟 :102 的 commit（自身小事务，`new_id("qbt")` + `now_iso()` + row["position_id"] + model_id + row["version"] + "QUEUED"）。**导入惯例注意：** models.py 顶部只 import 了 `now_iso`（:9），文件内已有"函数内局部 import new_id"先例（:70），confirm 加 new_id 可走顶部补 import 或局部 import，二选一与现文件任一风格一致即可。

**todos 扩展 analog：`server/api/admin/positions.py:11-28`（get_todos）**——在返回 dict 追加 `question_bank_not_ready` 键即可，前端零破坏（Vue 对未知键安全）：

```python
    return {
        "pending_positions": pending_positions,
        "stalled_models": stalled,
        "orphan_jds": orphan_jds,
    }
```

计数查询照抄同函数的 `SELECT COUNT(*) c FROM … WHERE …` 三连风格；按 position 去重聚合的具体 SQL plan 定。

---

### 新测试文件：`server/test_p0_security.py` / `server/test_p0_chain.py`（新建）

**头部模板 analog：`server/test_m5_backend.py:6-38`（必须原样照抄的骨架——env 先于 import、`init_db()`、TestClient）：**

```python
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

（新文件注意：`# noqa: E402` 与中文 docstring 均为项目惯例，照抄；`test_p0_chain.py` 若也要造 admin，补 `test_m7_backend.py:28-46` 的 `_ensure_admin` + `CryptContext(schemes=["bcrypt"])` 直插 user 行模式）

**只读断言 helper analog：`test_m5_backend.py:32-38`（`_q()`——测试侧不持锁）：**

```python
def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```

**种子与登录 analog：**
- 岗位+confirmed 模型+题库种子：`test_m5_backend.py:43-127`（`_seed_position_with_confirmed_model` + `_seed_question_bank`）——p0 测试直接复用/改造（注意 Pitfall 3：这些种子直插 question_bank 无 task 行，readiness 必须放行）。
- 候选人登录：`test_m5_backend.py:130-135`（`_auth_headers`，register+login 取 Bearer）。
- admin 种子：`test_m7_backend.py:28-46`（`_ensure_admin`）。
- 主链答题闭环（p0_chain 的底座）：`test_m5_backend.py:213-246`（followup→next→finish 推进循环）。

**断言要点（RESEARCH Code Examples 三段骨架已给全）：** 越权矩阵 12 用例、append-only 触发器拒绝（`sqlite3.IntegrityError`）、串行链（TestClient 下 background 同步执行，**断言里不得出现 time.sleep**）、completed 护栏 409、readiness 三态 409 + 不建会话 + todos 新键。测试函数一律无参（防被当 fixture）。

---

### 修改现有测试：`test_m5_backend.py` / `test_m6_backend.py` / `eval/virtual_candidates.py`

**`test_m5_backend.py:256-258`（断言重写，只改断言不重构）：**

现状：

```python
    # 终局打分
    r = client.post(f"/api/assessment/sessions/{sid}/score", headers=headers)
    assert r.status_code == 200, r.text
```

此处 finish 已置 completed（:246-249 断言过 `sess["status"] == "completed"`）→ 护栏生效后必 409。改为期望 409 后，紧随其后的 question_score 落库断言（:259-287）数据来源需同步调整（改为经 POST /report 串行链或 Python 直调豁免路径产生 score 行——plan 定，参考 RESEARCH 成功标准 2"不得再用 Python 层直调掩盖"，优先走 API 链）。

**`test_m6_backend.py`（脚本式风格锁定，逐条核对两处）：**
1. `_test_dual_scoring:164` 直调 `score_session(sid)`：seed 为 in_progress（:100-102 `"in_progress"`），在推荐护栏语义下不受影响；若 plan 采纳"in_progress 也拒"的 D-09 字面读法，则此处必挂——**这是护栏语义裁决的直接试金石**。
2. `_test_feedback_api:263-270` 直调 `submit_feedback(rpt_row["report_id"], {...})`：**该函数签名在 01-01 后将新增 `user` 参数 + helper 首调**，此直调必挂——需补传种子用户 dict（或改走 TestClient API 路径），只改调用与断言，不动 `check()` 脚本骨架（:22-32）。

**`eval/virtual_candidates.py:131-136`（一行顺序调整）：**

```python
    conn.execute(
        "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
        (now_iso(), session_id),
    )
    conn.commit()

    score_session(session_id)
```

顺序对调（先 score 后置 completed），仅此一行级调整，不改脚本结构（A4：测试资产适配，非业务改动）。

---

### 前端：`web/src/router/index.js`（修改）+ `PositionAssess.vue`（修改）

**route meta 目标形态 analog：`router/index.js:37-42`（`/assessment/positions` 的既有写法）：**

```js
  {
    path: '/assessment/positions',
    name: 'AssessmentPositions',
    component: () => import('../views/assessment/Positions.vue'),
    meta: { requiresAuth: true }
  },
```

改动点（:49-60）：`AssessmentChat` 与 `AssessmentReport` 两条的 `meta: { role: 'candidate' }` → `meta: { requiresAuth: true }`。守卫逻辑（:72-90）无需动——`to.meta.role` 为空即放行，登录态由 `auth.isLoggedIn` 兜底。

**409 提示展示 analog（改动落点 `PositionAssess.vue:134-139`）：**

```js
  } catch (e) {
    if (e.response?.status === 501) {
      ElMessage.warning('测评功能尚未上线（模块二）')
    } else {
      ElMessage.error(e.response?.data?.detail || '创建测评会话失败')
    }
  }
```

加 409 分支取可读信息；detail 为 dict 形态（Pitfall 7，勿直接展示否则 `[object Object]`）：

```js
e.response?.data?.detail?.message || e.response?.data?.detail
```

detail 提取惯例参照 `web/src/utils/sse.js:33-40`（`body?.detail` 前端消费既有写法）。

---

## Shared Patterns（全阶段通用）

### 1. 连接与 SQL（全后端文件）
**Source：** `server/db.py:218-223`（get_conn）+ 任一 service/route
每次调用 `conn = get_conn()`（per-call connection）+ raw SQL `?` 参数化 + 显式 `conn.commit()`；无 ORM、无连接池、无全局事务。新 helper/检查函数/插行一律照此，禁止值插值（SQL 注入面）。

### 2. ID 与时间（全后端新代码）
**Source：** `server/services/pipeline.py:14-19`
`new_id(prefix)`（事件行 `asev_` / task 行 `qbt_` 等前缀照 `sess`/`aq`/`form` 惯例自拟）+ `now_iso()`。不从其他模块复制该函数，直接 import。

### 3. 错误响应（全部 API 层改动）
**Source：** `server/api/admin/models.py:49-57`
`raise HTTPException(status.HTTP_404_NOT_FOUND / HTTP_409_CONFLICT, "中文消息")`——status 常量 + 中文 detail，全库统一。服务层用 `ValueError`，API 层转 409（scoring.py:118 既有先例）。

### 4. LLM 与事务纪律（01-02 事件接入点全适用）
**Source：** `server/services/scoring.py:107-111`（内存算完单事务落库）+ `server/api/assessment.py:167-169`（先 commit 再调 LLM）
二选一，事件行与快照 UPDATE 同事务；违反即 `database is locked`（Pitfall 6）。

### 5. 后台任务（01-03 / 01-04）
**Source：** `server/api/assessment.py:259-269` + `server/api/admin/models.py:104-105`
`BackgroundTasks.add_task(fn, *args)` + 前端轮询 / 状态行；进程重启丢任务本期接受（D-005）。TestClient 下同步执行，测试直接断言落库。

### 6. 测试纪律（两个新测试文件）
**Source：** `server/test_m5_backend.py:6-29`
env 先于 import、`init_db()`、`TestClient`、`_q()` 只读即关、测试函数无参、**单文件单进程**（不得一次 pytest 收多文件）；m6 保持 `python server/test_m6_backend.py` 脚本式运行。

---

## No Analog Found（无代码库先例，以 RESEARCH.md [VERIFIED] 样例为准）

| 文件/部件 | 角色 | 数据流 | 说明 |
|---|---|---|---|
| `server/db.py` 触发器 DDL（BEFORE UPDATE/DELETE + RAISE(ABORT)） | config | — | 库内无任何 SQLite 触发器先例；RESEARCH Pattern 2 的触发器 DDL 已本机实测（UPDATE/DELETE 均抛 IntegrityError），照抄即可 |
| `server/services/state_events.py` `append_event()` | service | 事件追加 | 库内无事件写入代码；RESEARCH Pattern 2 的函数体（MAX+1 取号 + actor_type 校验）已实测，配合上文 pipeline/scoring 两个部件 analog 组装 |
| `server/services/readiness.py` 整体 | service | 只读预检 | 无同职责先例；最接近的是 question_selection.py（配额口径 + 查询形态，已列为 analog），骨架按 RESEARCH Pattern 5 |

## Metadata

**Analog search scope:** `server/`（api、api/admin、core、services、根级 test_*）、`web/src/`（router、views/assessment、utils）、`eval/`、`design/final-design/总设计文档.md` §13、`.planning/phases/01-p0/`（CONTEXT/RESEARCH）
**Files scanned:** 16 个目标文件全部直读（api/assessment.py 318 行全文、db.py 290 行全文、scoring.py 155 行全文、question_bank.py 120 行全文、admin/positions.py 92 行全文、admin/models.py 177 行全文、test_m5 307 行全文、test_m6 287 行全文、test_m7 头部+种子段、core/security.py 57 行全文、pipeline.py 头部、question_selection.py 66 行全文、router/index.js 92 行全文、Positions.vue 128 行全文、PositionAssess.vue 关键段、eval 关键段、sse.js 关键段）
**Pattern extraction date:** 2026-09-02
