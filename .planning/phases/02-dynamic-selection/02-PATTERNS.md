# Phase 2: 动态选题与有界循环 - Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 20 (15 新建/修改 + 3 回归改断言 + 2 复用核对)
**Analogs found:** 20 / 20（全部有代码基线；2 个新服务函数为「规格代码化」无直接结构先例，用最近似纯函数风格锚定）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/db.py`（_DDL 三表加列 + `_migrate_question_*` ALTER） | config/migration | file-I/O（DDL 演进） | `server/db.py:277-341` 既有 `_migrate_llm_trace`/`_migrate_feedback_status`/`init_db` | exact（同文件扩展） |
| `server/config.py`（CATEGORY_RATIO 7:3 + ORDINARY_PLAN_N） | config | — | `server/config.py:23-45` 自身既有常量区 | exact（同文件追加） |
| `server/services/question_selection.py`（全量重写 select_next_question） | service | CRUD（读 question_bank 写 assessment_question，纯函数配额） | 自身旧版（重写基线）+ `server/services/readiness.py`（纯函数风格 + 共享口径教训） | partial（结构全新，风格锚定） |
| 新 `server/services/difficulty.py`（路径状态机纯函数，文件名 plan 可改） | service | transform（判定→快照/事件） | `server/services/question_bank.py:15-29` `_question_plan`（纯规则分派函数）+ `server/services/scoring.py:23-58`（代码判分布尔裁决） | partial（无状态机先例） |
| `server/schemas.py`（新增 InterviewObservation/ObservationDims） | model | request-response（LLM 输出 schema） | `server/schemas.py:35-65` ExtractItem/AggregateLevelResult | exact（同文件同模式） |
| `server/services/interview.py`（两层化 + _mock_interview 重写） | service | request-response（LLM 决断） | 自身（decide_next_action 签名保留）+ `server/services/llm.py:41-62` call_llm_json mock 双轨 | exact（同文件内部重构） |
| `server/services/prompts/interviewer.py`（输出契约描述对齐） | config | — | `server/services/prompts/interviewer.py` INTERVIEWER_SYSTEM 自身 | exact |
| `server/services/scoring.py`（删 50/50 + score_state + INVALIDATED） | service | CRUD + LLM 调用 | 自身 `score_session:141-196`（改删除点，不改「内存算完单事务落库」结构） | exact（同文件改造） |
| `server/services/aggregation.py`（实际取 score_final + 分母过滤） | service | batch（session 级聚合） | 自身 `aggregate_session_scores:66-159`（取数点 72-79 改动） | exact（同文件改选列） |
| `server/services/aggregate.py`（7:3 跟随 + 断言锁死） | service | batch（模型权重计算） | 自身 `_compute_weights:81-98`（零逻辑改动，仅回归断言） | exact |
| `server/services/readiness.py`（第 5 步配额公式换新） | service | request-response（开考预检） | 自身 `_check_session_readiness_locked:100-131` 步骤 5 替换 | exact（同函数改公式） |
| `server/api/assessment.py`（create_session 删预选 / get_session 首题派发 / submit_answer 消费两层输出） | controller | request-response | 自身三个端点 + `server/api/assessment.py:283-293` `_append_task_event`（独立小事务模式） | exact（同文件改调用点） |
| `server/services/report.py`（final_score SELECT 切列） | service | batch（报告渲染） | 自身 `_load_question_reviews:35-47` | exact（单行 SELECT 改列） |
| `server/test_phase2_migration.py`（新） | test | file-I/O | `server/test_p0_chain.py:30-57`（环境+建库模板） | exact |
| `server/test_phase2_weights.py`（新） | test | unit | `server/test_m5_backend.py:140-171`（断言组织风格） | role-match |
| `server/test_phase2_selection.py`（新） | test | integration | `server/test_p0_chain.py`（种子+闭链断言全套） | exact |
| `server/test_phase2_difficulty.py`（新） | test | unit（表驱动判据） | `server/test_m5_backend.py:203-211` test_objective_scoring（纯函数直测风格） | role-match |
| `server/test_phase2_interview.py`（新） | test | integration | `server/test_m5_backend.py:213-290` 答题闭环（mock 三向分类断言面） | exact |
| `server/test_phase2_scoring.py`（新） | test | integration | `server/test_m5_backend.py:260-290`（分表断言）；`test_p0_chain.py:312-344`（报告闭环） | exact |
| `server/test_m5_backend.py` / `test_m6_backend.py` / `test_question_bank.py`（回归改断言） | test | regression | 各自身旧断言行（D-09：只改断言不重构） | exact |

复用不改（read-only 核对）：`server/services/state_events.py`（append_event 原样调用）、`server/services/question_bank.py`（02-01 锚点列回填后 CR-01 降级保持）、`eval/virtual_candidates.py`（INSERT 语句列名核对，预检评估见 Shared Patterns 反模式区）。

## Pattern Assignments

### 计划 02-01

---

#### `server/db.py`（migration，file-I/O）

**Analog:** `server/db.py:277-341`（`_migrate_llm_trace` + `_migrate_feedback_status` + `init_db`）

**迁移函数嗅探式惯例**（`server/db.py:277-302`，新 `_migrate_*` 照此骨架）：
```python
def _migrate_llm_trace(conn: sqlite3.Connection) -> None:
    """老库 llm_trace.call_type CHECK 类型不全时，重建表放宽到 _DDL 最新口径（含 report）。"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='llm_trace'"
    ).fetchone()
    if row is None or "'report'" in (row[0] or ""):
        return  # 表不存在（新建走 _DDL）或已是最新约束
```
注意（RESEARCH Pitfall 1/A1）：02-01 是 **ALTER ADD COLUMN** 不是重建表——列存在性嗅探改用 `PRAGMA table_info(表名)` 取列名集合（比 sqlite_master 字符串嗅探更直接，同一「先查再动 + 幂等早退」骨架）。NOT NULL 新列必须带常量 DEFAULT（如 `'ordinary'`/`0`）；锚点列裸 ADD 后用 `UPDATE ... CASE difficulty` 回填。

**init_db 注册点**（`server/db.py:329-341`）——新迁移函数按既有次序追加：
```python
def init_db() -> None:
    """建表（幂等）+ 老库迁移，启动时调用一次。"""
    ...
    conn = sqlite3.connect(DB_PATH)
    try:
        _migrate_llm_trace(conn)
        _migrate_feedback_status(conn)
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
```
**双轨纪律（Pitfall 2）**：`_DDL` 的三个 CREATE 语句（`db.py:116-132` question_bank、`db.py:134-142` assessment_question、`db.py:174-185` question_score）与新 `_migrate_*` 必须同步加列——新库直建含新列、老库走 ALTER。新列一律不带 DB CHECK（N11，参照 `db.py:255-265` question_bank_task 无 CHECK 先例）；旧列已有 CHECK（`db.py:121-123` category/qtype）不改不删。

**question_score 合并迁移两步法**（02-01 只合并不 DROP；DROP 推迟到 02-05，RESEARCH A8）：
```sql
UPDATE question_score SET score_final=COALESCE(final_score, score_final);
-- DROP COLUMN final_score 属 02-05（消费点切完后）
```

**新列的 N11 代码校验参照**（`server/services/state_events.py:11`）：
```python
_VALID_ACTOR_TYPES = ("candidate", "system", "admin")
```
新枚举（answer_state 11 态/score_state 8 态子集/seal_reason/question_type/measurement_stage）用模块级 tuple 常量 + 入口 ValueError，不进 DDL。

---

#### `server/config.py`（config）

**Analog:** `server/config.py:23-45` 自身

**常量声明惯例**（`server/config.py:23-33`）：
```python
# ---- 可配置常量（§8.4）----
# 类间权重配比 hard_skill:soft_skill:experience:qualification
CATEGORY_RATIO = {
    "hard_skill": 5.5,
    ...
}
```
7:3 修正在此处改值（hard 0.7 / soft 0.3 / exp 0.0 / qual 0.0，experience/qualification 保留 0.0 键位——`aggregate.py:87` 的 `sum(config.CATEGORY_RATIO[c] for c in by_cat)` 只对出现类目求和，0.0 键不干扰归一）。`ORDINARY_PLAN_N` 新增同风格 code 常量、**数值占位待关口包**（RESEARCH A5：不做 env 覆盖）。分节注释 `# ---- 模块二：测评 ----`（`config.py:41-45`）是分区惯例，FOLLOWUP_MAX 的 `os.environ.get` 可覆盖写法（`config.py:45`）**不**复制给 ORDINARY_PLAN_N。

---

#### `server/services/aggregate.py`（service，batch）

**Analog:** `server/services/aggregate.py:81-98` `_compute_weights`

**权重归一核心（零逻辑改动，仅回归断言锁死 D-16）**（`aggregate.py:87-98`）：
```python
    total_ratio = sum(config.CATEGORY_RATIO[c] for c in by_cat)  # 仅出现的类目参与配比
    for cat, cat_items in by_cat.items():
        cat_share = config.CATEGORY_RATIO[cat] / total_ratio
        coef_sum = sum(config.IMPORTANCE_COEF[it["importance"]] for it in cat_items)
        for it in cat_items:
            it["weight"] = round(cat_share * config.IMPORTANCE_COEF[it["importance"]] / coef_sum, 4)
    # 四舍五入尾差由权重最大项吸收，保证 Σ 严格 = 1
    if items:
        drift = round(1.0 - sum(it["weight"] for it in items), 4)
        if drift:
            max(items, key=lambda x: x["weight"])["weight"] = round(
                max(items, key=lambda x: x["weight"])["weight"] + drift, 4)
```
**摘要联动点**（`aggregate.py:165`，自动跟随需断言）：
```python
        "category_weights": {c: round(config.CATEGORY_RATIO[c] / sum(config.CATEGORY_RATIO.values()), 4)
                              for c in {i["category"] for i in items}},
```
02-01 改动形态：本文件**不改代码**，只在测试 `test_phase2_weights.py` 加断言（hard+soft 模型 Σhard≈0.7、Σsoft≈0.3；纯 soft 岗归一 1.0；aggregation 总分不二次乘大类比例——即 `aggregation.py:121` 的 `weight * (actual/5.0) * 100.0` 无额外 CATEGORY_RATIO 因子）。gate 项核对见反模式区。

---

#### `server/test_phase2_migration.py`（test，新建）

**Analog:** `server/test_p0_chain.py:30-57` 环境与建库模板

**文件头纪律**（`server/test_p0_chain.py:30-45`，逐行照抄结构）：
```python
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase2_migration.db")
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

**只读查询 helper**（`server/test_p0_chain.py:48-54`）：
```python
def _q(sql: str, params: tuple = ()) -> list[dict]:
    """测试侧只读查询：开连接→读→关，避免持锁阻塞 API 写入（SQLite 单写）。"""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
```
迁移测试特有形态（老库路径）：先用**旧版 DDL 字符串**手工建三张旧结构表 + 插旧行（参照 `test_p0_chain.py:172-230` `_seed_completed_session_direct` 直插风格，含 final_score 双列值）→ 调 `init_db()` → `_q` 断言新列全在、锚点 CASE 回填正确（easy→[2,3]/medium→[3,4]/hard→[4,5]）、`COALESCE(final_score, score_final)` 合并语义。再走全新库路径（`init_db` 直建含新列）双断言（Pitfall 2 双轨检查表）。mock 分类器断言参照 `test_p0_chain.py:438-466`（事件行 `_q` SELECT + json.loads payload 断言）。

---

### 计划 02-02

---

#### `server/services/question_selection.py`（service，CRUD+transform）

**Analog:** 自身旧版（重写基线）+ `server/services/readiness.py:14-36`（口径共享/纯函数风格）

**废除对象（重写时的行为参照，不是复制对象）**：`CATEGORY_QUOTA`（`question_selection.py:9`）、`select_questions_for_session` 一次性预选（`question_selection.py:58-66`）、§10.6 之前的 required-排序模式（`question_selection.py:30-34` sort_key）。

**保留复用的查询口径**（`question_selection.py:23-28`，①合法性过滤层继续用同一 WHERE 形态）：
```python
    rows = conn.execute(
        "SELECT * FROM question_bank WHERE status='active' AND category=?"
        " AND (scope='general' OR (scope='position' AND position_id=?))"
        " ORDER BY CASE difficulty WHEN 'easy' THEN 0 WHEN 'medium' THEN 1 WHEN 'hard' THEN 2 ELSE 3 END",
        (category, position_id),
    ).fetchall()
```
`?` 参数化、字段名只以字面量进 SQL（新动态 WHERE 拼列名时值仍走参数——Research 安全表）。chain 后继判定可参照旧 `question_selection.py:40-46`（chain_key/chain_seq 分组）。

**配额纯函数共享（Pitfall 3/WR-15 防漂移）**——readiness 消费面参照 `server/services/readiness.py:11`（当前 `from .question_selection import CATEGORY_QUOTA` 的单一外部引用模式）：
```python
from .question_selection import CATEGORY_QUOTA
```
新公式落 `plan_quotas(n, ...)` 纯函数于 question_selection.py，readiness 第 5 步同源 import（`readiness.py:119-124` 的循环消费段整体替换）。`test_question_bank.py:128` 经 `select_questions_for_session` 间接消费——重写后该断言同步改（见回归条目）。

**模块 docstring 风格**：中文、首段说明用途+公式出处（§ 号引用），照 `question_selection.py:1-5` 现状。

---

#### `server/services/readiness.py`（service，request-response）

**Analog:** 自身 `_check_session_readiness_locked:60-135`

**步骤 4+5 消费段（替换目标，`readiness.py:100-131`）**：
```python
    counts = _question_count_by_category(conn, position_id)
    covered = _covered_std_names(conn, position_id)
    ...
    gaps: list[str] = []
    for category, quota in CATEGORY_QUOTA.items():
        if category not in needed_categories:
            continue  # 模型不含该类目：不要求配额
        have = counts.get(category, 0)
        if have < quota:
            gaps.append(f"{category} {have}/{quota}")
    if missing_required or gaps:
        ...
        return {"error_code": "QUESTION_BANK_INCOMPLETE", "detail": detail}
```
保留：只对模型实际含类目要求配额（CR-04，`readiness.py:109-117` needed_categories 推导）、失败三态 dict 结构 `{"error_code", "detail"}`（API 层 `assessment.py:92-94` 消费此结构转 409，不改）、6/7 步 no-op 注释位（`readiness.py:133-134`）、docstring 里的步骤清单（`readiness.py:41-49` 第 5 步描述同步改公式口径）。模块 docstring 第 8 行「配额口径用 question_selection.CATEGORY_QUOTA」随替换更新。

**连接生命周期纪律**（`readiness.py:51-57`，WR-11 try/finally close 保持）：
```python
    conn = get_conn()
    try:
        return _check_session_readiness_locked(conn, position_id)
    finally:
        conn.close()
```

---

#### `server/api/assessment.py`（controller，request-response）

**Analog:** 自身三个端点

**create_session 删除对象**（`assessment.py:104-110` INSERT 预选循环）：
```python
    questions = select_questions_for_session(position_id, json.loads(model["model_json"]))
    for i, q in enumerate(questions, start=1):
        conn.execute(
            "INSERT INTO assessment_question(question_id, session_id, bank_question_id, seq, created_at)"
            " VALUES(?,?,?,?,?)",
            (new_id("aq"), session_id, q["question_id"], i, now),
        )
```
保留结构（`assessment.py:96-115`）：readiness 409 拦截 → INSERT session → append_event（SESSION_CREATED 与 INSERT 同事务）→ conn.commit() → 响应 dict。响应 `question_count`/`estimated_duration_minutes` 键处理见 Pitfall 9（前端无消费，仅 test_m5:149 断言要改）。

**get_session 派发点改造对象**（`assessment.py:132-137` 当前题查询）：
```python
    cur = conn.execute(
        "SELECT aq.question_id, aq.seq, b.stem, b.category, b.qtype, b.difficulty"
        " FROM assessment_question aq JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE aq.session_id=? AND aq.answered_at IS NULL ORDER BY aq.seq LIMIT 1",
        (session_id,),
    ).fetchone()
```
改为：无当前实例 → 调 `select_next_question(session_id)` 派发。`total_count` 口径同步换 N+E（`assessment.py:125-131` 两段 COUNT）。

**submit_answer 保留的关键次序**（`assessment.py:191-192`，先 commit 再调 LLM——Anti-pattern 1 的既有解法）：
```python
    # 先提交用户消息再调 LLM：llm_trace 用新连接写库，本连接持写事务会 database is locked
    conn.commit()
```
next 分支的 `ORDER BY seq LIMIT 1` 旧查询（`assessment.py:226-231`）替换为 select_next_question 调用。**事件+快照同事务**段（`assessment.py:207-232`）保持结构：UPDATE 快照列 → append_event（不 commit）→ 尾部统一 conn.commit()。

**409 detail 结构**（`assessment.py:162-165`，WR-01 统一 `{error_code, message}`，所有新增 409 保持）：
```python
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_IN_PROGRESS",
                                    "message": f"会话已结束（{s['status']}）"})
```

**独立小事务事件模式**（`assessment.py:283-293`，如需后台/无外层事务时的事件写入参照）：
```python
def _append_task_event(session_id: str, event_type: str, *, payload: dict | None = None, ...) -> None:
    """独立小事务写串行链事件（后台任务无外层事务；不持事务跨 LLM 调用）。"""
    conn = get_conn()
    try:
        append_event(conn, ...)
        conn.commit()
    finally:
        conn.close()
```

---

#### `server/test_phase2_selection.py`（test，新建）

**Analog:** `server/test_p0_chain.py` 全套（种子 fixtures + 答题闭链 + 计数断言）

**种子 fixtures**（`test_p0_chain.py:59-133`，直接复制形态再按新配额调整题数）：`_seed_position_with_confirmed_model()`（岗位+confirmed 模型+competency_item INSERT，`test_p0_chain.py:59-89`）、`_seed_question_bank(pid)`（`_add` 局部函数逐行 INSERT question_bank，`test_p0_chain.py:97-104` INSERT 列清单照旧 15 列——新列 allow NULL 不必显式写，或按测试需要显式补 item_id/tier 类新列）、`_auth_headers(username)`（`test_p0_chain.py:136-141`）。

**答题闭链 helper**（`test_p0_chain.py:152-169`，改为按「动态实例」逐题取当前题再答）：
```python
def _answer_whole_session(sid: str, headers: dict) -> list[dict]:
    ...
    for i, q in enumerate(questions, start=1):
        r = client.post(..., json={"question_id": q["question_id"], "answer": _LONG_ANSWER}, ...)
        expected = "finish" if i == len(questions) else "next"
        assert r.json()["action"] == expected, ...
```
新调度性断言（Pitfall 9）：建会话后 aq 行=0；第 k 次 answer next 后 aq 行=k；selection_reason JSON 四层记录可 `_q` + json.loads 断言（参照 `test_p0_chain.py:438-466` 事件断言手法）。N=9/10/11/15 四行样例（§10.2）进本文件或 test_phase2_weights 直测纯函数（`test_m5_backend.py:203-211` test_objective_scoring 的直调风格）。

---

### 计划 02-03

---

#### `server/services/difficulty.py`（新 service，transform）

**Analog（结构无直接前例，风格双锚）:** `server/services/question_bank.py:15-29` `_question_plan`（输入 dict→确定输出清单的纯规则分派）+ `server/services/scoring.py:52-58` `_looks_like_regex`（布尔判据函数 + 中文 docstring 逐条说明判据来源）

**纯规则分派风格**（`question_bank.py:15-29`）：
```python
def _question_plan(item: dict) -> list[tuple[str, str]]:
    """按类目与权重规划 (difficulty, qtype) 清单（07 §6.2 + 难度递进 N1）。

    hard_skill：weight>10% → 3 档（easy/medium/hard），否则 2 档（easy/medium）
    ...
    """
    cat = item["category"]
    if cat == "hard_skill":
        ...
```

**布尔判据函数风格**（`scoring.py:52-58`）：
```python
def _looks_like_regex(key: str) -> bool:
    """判定 key 是否显式声明为正则：仅 |（分支）与字符类 [...]{...} 视为正则意图。

    裸量词（+、*、?）跟在普通字符后不视为正则声明——凭其静默改变语义的风险
    大于收益（"C+"、"V*" 这类 key 几乎都是想表达字面文本）。
    """
    return bool(re.search(r"\||\[[^\]]*\]|\([^)]*\)[?*+]", key))
```
difficulty.py 按此写 `next_difficulty(snap, *, evidence_sufficient, stable, is_valid_failure) -> tuple[str|None, str|None]` 纯函数（§11.2 判据逐条中文 docstring），**不持 conn**；持久化（path_state_snapshot UPDATE + DIFFICULTY_* 事件）放在单独函数内走 append_event 契约。三态极小逻辑不引框架（RESEARCH Alternatives）。

**快照 JSON 落库惯例**：字段蛇形命名 + `json.dumps(x, ensure_ascii=False)`（全局惯例，见 `state_events.py:47`、`assessment.py:253`）。

**事件判据摘要进 payload（Pitfall 5）**——调用形态参照 `api/assessment.py:214-217` 现有 QUESTION_ANSWERED 写法扩展：
```python
        append_event(conn, session_id=session_id, event_type="QUESTION_ANSWERED",
                     from_state="active", to_state="answered",
                     actor_type="candidate", actor_id=user["user_id"],
                     assessment_question_id=question_id)
```
DIFFICULTY_* 增加 `from_state=旧难度, to_state=新难度, payload={"criterion": ..., "evidence_counts": {...}}`，事务边界仍由调用者（assessment.py 或 selection 服务）持有。

---

#### `server/test_phase2_difficulty.py`（test，新建）

**Analog:** `server/test_m5_backend.py:203-211`（纯函数直测）+ `test_p0_chain.py:422-466`（事件断言）

**纯函数直测风格**（`test_m5_backend.py:203-211`）：
```python
def test_objective_scoring():
    score, _ = _score_objective("def", "用 def 定义函数")
    assert score == 5
```
表驱动判据测试照此组织（§11.2 每判据一行：升/降/滞回/跳级拒绝/单实例不升降）；事件+快照同事务断言参照 `test_p0_chain.py:438-466`（sequence_no 递增 + payload_json json.loads 内容断言——Pitfall 5 警示：不只断言 event_type 存在）。文件头照 `_test_p0_chain.py:30-57` 模板。

---

### 计划 02-04

---

#### `server/schemas.py`（model，LLM 输出 schema）

**Analog:** `server/schemas.py:35-65`

**文件头与 import**（`schemas.py:3-5`）：
```python
from typing import Literal, Optional

from pydantic import BaseModel, Field
```

**Literal 枚举 + 约束字段先例**（`schemas.py:36-42`）：
```python
class ExtractItem(BaseModel):
    name: str
    category: Literal["hard_skill", "soft_skill", "experience", "qualification"]
    required_level: int = Field(ge=1, le=5)
    importance: Literal["required", "preferred", "plus"]
    evidence: list[str]
    years: Optional[float] = None
```
InterviewObservation 照此加：answer_state 用 `Literal[...]` 11 态、观察维度用 `Field(ge=0, le=3)`/bool/`Optional[bool] = None`，分节注释 `# ---- ... ----`（`schemas.py:8/29/35/50/63` 惯例）+ 中文单行注释说明出处（§11.3/§11.4）。嵌套模型先例：`ObservationDims` 类似 `MergePair`（`schemas.py:51-56`）的独立 BaseModel 组合。

---

#### `server/services/interview.py`（service，request-response）

**Analog:** 自身（签名与调用结构保留）

**签名保留锚点**（`interview.py:83-84`）：
```python
def decide_next_action(session_id: str, question_id: str, user_message: str) -> dict:
    """决策下一步动作。规则优先于 LLM：追问达上限强制 next；最后一题强制 finish。"""
```
**返回 5 键保持**（`interview.py:109-115`，Pitfall 8——只加不减，可加 answer_state/observation 新键）：
```python
    return {
        "action": action,
        "reason": result.get("reason", ""),
        "reply": result.get("reply", ""),
        "score_live": result.get("score_live") if question["qtype"] == "subjective" else None,
        "score_live_reason": result.get("score_live_reason") if question["qtype"] == "subjective" else None,
    }
```
**LLM 调用点结构保留**（`interview.py:94-98`）：
```python
    result = call_llm_json(
        "interviewer", session_id, INTERVIEWER_SYSTEM,
        _build_user_prompt(session, question, history, user_message, is_last),
        mock_fn=_mock_interview,
    )
```
**规则护栏段保留并扩展**（`interview.py:100-107`）：
```python
    # 规则护栏（07 §7.1/§7.2）：finish 由规则触发；追问上限 FOLLOWUP_MAX
    followups = _count_followups(session_id, question_id)
    action = result.get("action", "next")
    if action == "followup" and followups >= config.FOLLOWUP_MAX:
        action = "next"
        result["reason"] = f"追问达上限({config.FOLLOWUP_MAX})，强制 next"
```
两层化改造：LLM 输出先过 `InterviewObservation`（`Parsed = InterviewObservation(**result)`，校验失败降级 MODEL_UNCERTAIN 不卡死，参照 `aggregate.py:77` 的 `AggregateLevelResult(**result)` 消费先例）→ 裁决层纯函数（新代码，布尔判据风格照 02-03 的 `_looks_like_regex` 说明）→ 组装 5 键返回。`_load_session_question`/`_count_followups`/`_build_user_prompt` 的 get_conn + JOIN 查询风格保持（`interview.py:17-45`）；followup 计数迁列（D-25）后 `_count_followups` 改读 assessment_question.followup_count，函数名/调用点不扩散。

**_mock_interview 重写**（D-23，旧版 `interview.py:66-80` 是「直接出 action」要改为「出观察」）——签名与「解析 user_prompt 产确定性输出」惯例保留：
```python
def _mock_interview(system_prompt: str, user_prompt: str) -> dict:
    """离线 mock 规则：回答短→followup；否则 next（最后一题→finish）。主观题固定 score_live=3。"""
    last_user = ""
    for line in reversed(user_prompt.splitlines()):
        if line.startswith("候选人："):
            last_user = line[len("候选人："):]
            break
    is_last = "这是最后一题" in user_prompt
```
重写要点：输出 dict 键改为 `{"answer_state": ..., "observation": {...}, ...}`（与 InterviewObservation 同构），拒答关键词/长度/实义词三向分类（`MIN_ANSWER_CHARS` 常量与模块级位置惯例照 `interview.py:14`），共用同一裁决层。mock 输出解析既有先例的多样性参照：`_mock_score`（`scoring.py:61-62` 固定值）、`_mock_report`（`report.py:15-32` prompt 解析+模板串）、`_mock_aggregate_level`（`aggregate.py:22-26` 正则取众数）——分类器解析法用 `_mock_interview` 现有的「reverse 找 候选人： 前缀行」手法最直接。

---

#### `server/services/prompts/interviewer.py`（轻触）

**Analog:** 自身 `INTERVIEWER_SYSTEM`（`prompts/interviewer.py:8-26`）

仅改「输出格式」JSON 结构描述段（`:13-20`）对齐 InterviewObservation（action 等键从「LLM 输出」移除、观察维度进入）；docstring 版本注释行（`:1`）同步。真实 prompt 重构不做（D-030 留 API 面）。

---

#### `server/test_phase2_interview.py`（test，新建）

**Analog:** `server/test_m5_backend.py:213-290` 答题闭环（mock 行为断言面）

**短答触发 followup / 长答 next 的断言手法**（`test_m5_backend.py:226-237`）：
```python
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": q1, "answer": "不知道"}, headers=headers)
    assert r.json()["action"] == "followup"
    ...
    r = client.post(f"/api/assessment/sessions/{sid}/answer",
                    json={"question_id": q1, "answer": long_answer}, headers=headers)
    assert r.json()["action"] == "next"
```
新分类语义断言覆盖：短（<20 字）→NEED_CLARIFICATION、拒答关键词→DECLINED（含首次 confirm、二次封存 seal_reason='refused'+REFUSED+score_value=0 的 DB 行断言，`_q` 直查 assessment_question/question_score）、实义词→VALID_EVIDENCE。Pydantic 拒绝断言（非法 answer_state 抛 ValidationError + literal_error + loc）在纯函数层直测。followup≤2 护栏断言照 `test_m5_backend.py:240-246` 循环答题形态。

---

### 计划 02-05

---

#### `server/services/scoring.py`（service，batch + LLM）

**Analog:** 自身 `score_session:141-196`

**「内存算完单事务落库」结构（保持不动，只改组行内容）**（`scoring.py:168-195`）：
```python
    # 1) 内存计算（含 LLM 调用，此时本 conn 未持写事务）
    pending_rows: list[tuple] = []
    for q in answered:
        r = score_question(session_id, q["question_id"])
        ...
        pending_rows.append(...)

    # 2) 单事务写库
    conn.execute("DELETE FROM question_score WHERE session_id=?", (session_id,))
    conn.executemany(
        "INSERT INTO question_score(...) VALUES(...)",
        pending_rows,
    )
    conn.commit()
```
**删除对象**（`scoring.py:172-177`）：
```python
        score_live = _latest_score_live(session_id, q["question_id"]) if q["qtype"] == "subjective" else None
        score_final = r["score_final"]
        if score_live is not None:
            final = round(score_live * 0.5 + score_final * 0.5)
        else:
            final = score_final
```
改为：score_final 直接落数（`_latest_score_live:130-138` 保留但只作参考值）；pending_rows 增 score_state 列值；answer_key 空客观题升级 INVALIDATED（替换 `scoring.py:103-105` 客观分支 + WR-14 防护段 `scoring.py:36-37` 的「按最低分记」语义，WR-14 的正则防护逻辑本体保留）。completed 护栏（`scoring.py:156-158`）、`_find_item_id`（`:121-127`）、`_fetch_answer_text`（`:65-82`）、`score_question` 双轨（`:103-116`）结构保持。模块 docstring 的「合成：final = round(...)」行（`:5`）同步删。

---

#### `server/services/aggregation.py`（service，batch）

**Analog:** 自身 `aggregate_session_scores:66-131`

**取数点（改列 + 加分母过滤，`aggregation.py:72-79`）**：
```python
    # 按 item 分组收 final_score
    rows = conn.execute(
        "SELECT item_id, final_score FROM question_score WHERE session_id=?",
        (session_id,),
    ).fetchall()
    item_scores_map: dict[str, list[int]] = {}
    for r in rows:
        item_scores_map.setdefault(r["item_id"], []).append(r["final_score"])
```
改为 `SELECT item_id, score_final, score_state ...` + score_state 过滤（SCORED 进分母；REFUSED 单独列表进行为/完整度聚合；INVALIDATED/INCOMPLETE 排除+警告列表，Pitfall 7 六态子集）。保留：`_load_model_items`/`_load_form_payload`/`_gate_check` 三个 helper（`:12-63`）、gate 项二值判定段（`:87-103`，不乘 actual——weight 变化自动生效且该路径不吃 weight×actual，7:3 只影响非 gate 贡献）、no_data 分支（`:105-115`）、总分公式 `weight * (actual/5.0) * 100.0`（`:118-121`，7:3 不二次乘的断言锚点）、strengths/weaknesses 排序（`:133-142`）、返回 dict 键结构（`:144-158`，report.py 消费面）。模块 docstring `:3` 的「final_score 均分」行同步改。

---

#### `server/services/report.py`（service，batch）

**Analog:** 自身 `_load_question_reviews:35-47`

**隐藏消费点（切列，`report.py:39-41`）**：
```python
    rows = conn.execute(
        "SELECT qs.question_id, qs.score_live, qs.score_final, qs.final_score,"
        " qs.evidence_quote, qs.reason,"
        ...
```
`qs.final_score` 切 `score_final`（与 02-01 不 DROP、02-05 末 DROP 的次序配合，A8）。其余不动。

---

#### `server/test_phase2_scoring.py`（test，新建）

**Analog:** `server/test_m5_backend.py:260-290`（question_score 落库断言手法）

**分表断言手法**（`test_m5_backend.py:267-290`）：
```python
    rows = _q(
        "SELECT qs.*, b.qtype FROM question_score qs"
        " JOIN assessment_question aq ON aq.question_id=qs.question_id"
        " JOIN question_bank b ON b.question_id=aq.bank_question_id"
        " WHERE qs.session_id=?", (sid,),
    )
    ...
    assert all(r["score_live"] == 3 and r["final_score"] == 3 for r in subj)
```
新断言：score_final 独立（mock 3 分直落，无合成）；REFUSED 行 score_value=0 且聚合 actual 不含它；answer_key 空客观题 → score_state=INVALIDATED 不进分母含缺失警告；grep 无 `0.5 +` 合成残留（静态断言或 plan 验收 checklist）。报告闭环断言参照 `test_p0_chain.py:312-344`（POST /report → by-session 轮询）。

---

### 回归改断言（三个既有测试，D-09：只改断言不重构）

---

#### `server/test_m5_backend.py`

**改断言行定位：**
- `test_m5_backend.py:149` `assert body["question_count"] == 10` → 新调度语义断言（aq 行=0 / 字段删除去断言，Pitfall 9）
- `test_m5_backend.py:157-171` 类目配额断言（hard 6/soft 2/exp 2 + required 排序）→ 按 N + 7:3 新口径
- `test_m5_backend.py:290` `assert all(r["score_live"] == 3 and r["final_score"] == 3 for r in subj)` → score_final 独立断言
- `test_m5_backend.py:185` `total_count == 10` → N+E 口径
- 答题闭链 `test_m5_backend.py:220-246` 若消费预选题目列表需改为逐题取当前题（get_session 消费）

#### `server/test_m6_backend.py`

**改断言行定位（脚本式 check 保持）：**
- `test_m6_backend.py:169-182`：`obj["final_score"] == 5`（:177）、`sub1["final_score"] == 3`（:182 `check("主观题 final=round(3*0.5+3*0.5)=3", ...)`）→ score_final 断言 + score_state 断言

#### `server/test_question_bank.py`

**改断言行定位：**
- `test_question_bank.py:128` `qs = select_questions_for_session(pid, model)` 及其后配额断言 → 换 select_next_question 消费或按新公式改期望值（脚本式保持）

## Shared Patterns

### SQLite 写锁规避两模式（全部涉及 LLM 调用的新代码必须二选一）

**模式 A：先 commit 再调 LLM** — `server/api/assessment.py:191-192`：
```python
    # 先提交用户消息再调 LLM：llm_trace 用新连接写库，本连接持写事务会 database is locked
    conn.commit()
```
**Apply to:** submit_answer 的裁决层调用之后、select_next_question 调用之前的次序检查（Anti-pattern 1：选题必须位于 commit 之后的新事务）。

**模式 B：内存算完单事务落库** — `server/services/scoring.py:168-195`（见 02-05 条目全文）。
**Apply to:** scoring.py 改造（结构原样）、02-04 裁决层不在持事务状态下发 LLM 调用。

### append_event 事件契约（DIFFICULTY_*/QUESTION_* 全部走此入口，禁止手拼 INSERT）

**Source:** `server/services/state_events.py:14-48`
**Apply to:** select_next_question 的 QUESTION_SELECTED/ACTIVATED、难度状态机的 DIFFICULTY_RAISED/LOWERED/RESTORED、REQUIRED_EXCEPTION_GRANTED（A6）、拒答封存事件

```python
def append_event(
    conn,
    *,
    session_id: str,
    event_type: str,
    from_state: str | None = None,
    to_state: str | None = None,
    actor_type: str = "system",
    ...
    payload: dict | None = None,
) -> None:
    """在调用者已持有的同一事务内追加一条状态事件（不 commit）。..."""
```
调用者持事务不 commit（`api/assessment.py:207-232` 现行段）：快照 UPDATE → append_event → 统一 commit。payload 用 `json.dumps(..., ensure_ascii=False)`（helper 已封装）。

### call_llm_json + mock 双轨（所有新 LLM 调用面）

**Source:** `server/services/llm.py:41-62`
**Apply to:** interviewer 观察层（既有调用点改 schema，不新增旁路——llm_trace 落库保持）

```python
def call_llm_json(call_type: str, ref_id: str, system_prompt: str, user_prompt: str,
                  mock_fn=None) -> dict[str, Any]:
    """调 LLM 并解析 JSON。失败带错误信息重试 LLM_RETRY 次，全败抛异常。

    mock_fn: provider=mock 时替代真实调用的函数，签名 (system_prompt, user_prompt)->dict。
    """
```
Pydantic 校验消费先例：`server/services/aggregate.py:77` `parsed = AggregateLevelResult(**result)`——InterviewObservation 照此在 interview.py 内消费，非法输出捕获降级 MODEL_UNCERTAIN（不卡死，§11.5）。

### raw SQL + get_conn() 惯例（无 ORM，全部服务保持）

**Source:** `server/db.py:269-274` + 各服务 `conn.execute("... WHERE x=?", (param,))`
**Apply to:** 全部新/改服务与 API 代码

```python
def get_conn() -> sqlite3.Connection:
    """返回开启外键、Row 工厂的数据库连接。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```
`?` 参数化、`sqlite3.Row` → dict(r) 转换（`interview.py:36`）、服务自取连接自 commit（无依赖注入）、测试侧只读用完即关（`test_p0_chain.py:48-54`）。

### 中文 docstring + 判据来源标注 + WR/CR/Pitfall 注释惯例

**Source:** `server/services/scoring.py:23-35`（WR-14 防护注释）、`server/services/readiness.py:60-68`（W-2/WR-15 注释）、`server/services/question_bank.py:73-77`（WR-12 注释）
**Apply to:** 所有新函数——docstring 首段中文说明用途与 SSOT § 号出处，防回归决策以 `WR-xx/CR-xx/D-xx` 缩写行内注释留痕。

### eval 直调链兼容核对（02-04/02-05 验收项，非改码）

`eval/virtual_candidates.py:24-25` 直调 `score_session`/`aggregate_session_scores`、`:131-135` INSERT assessment_message 仅写 role/content 列——**新列不得加 NOT NULL 无默认**（Pitfall 10），02-05 改列名后跑 `--position-id` 冒烟核对。guard：该文件不 import interview 服务，mock 分类器重写不影响其行为断言。

### 反模式警戒（planner 写 action 时核对）

- gate 项权重：`aggregation.py:87-103` gate 项 contribution = `weight * 100.0`（passed 时），不乘 actual/5——7:3 断言时 gate 语义单列（`aggregate.py:134` gate 判定 `category == "qualification" or (experience and years)`），勿把 gate 项算进 Σhard=0.7 断言。
- answer_state 不直接映射分数（§11.4，D-22 裁决层只出 action/布尔）；selection_reason 不拼中文串（D-18）。
- INSUFFICIENT_EVIDENCE / IMPUTED / HUMAN_REVIEW_REQUIRED 只留枚举位不写生产路径（Pitfall 7）。
- 一次 pytest 不得收多文件（单文件单进程）；测试永用 /tmp/ 临时库不碰 data/app.db（红线 2）。

## No Analog Found

代码库中无结构先例、按 SSOT 规格直接代码化（RESEARCH Code Examples #1-#3 已给可直接转写的骨架）：

| File/Function | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `question_selection.plan_quotas`（7:3 最大余数 + tier 0.8/0.6/1.7 纯函数） | utility (纯函数) | transform | 无任何配额公式先例（现有 CATEGORY_QUOTA 是硬编码 dict）；风格锚 `_looks_like_regex` |
| `services/difficulty.py` 状态机整体 | service | event-driven | 全库唯一「多态+计数器」状态机；风格锚 `_question_plan` + `_looks_like_regex` |
| `interview.py` 裁决层纯函数（evidence_sufficient/stable_evidence 布尔） | utility | transform | 无布尔裁决先例（`_gate_check` 是最接近的双返回值分派，`aggregation.py:42-63` 可作次要参照）；stable_evidence 跨实例语义见 Pitfall 6/A2 |
| mock 规则分类器的拒答关键词表 | config | — | 全库无中文关键词分类先例（`_mock_interview` 现有 is_objective 字符串探测 `interview.py:74` 是最近手法）；词表常量模块级元组（照 `_VALID_ACTOR_TYPES`） |

## Metadata

**Analog search scope:** `server/`（全部 .py：db/config/schemas/main、services/ 全 15 模块、api/assessment+auth）、`server/services/prompts/`、`eval/virtual_candidates.py`（定向）、测试六文件（test_p0_chain/test_m5/test_m6/test_question_bank 定向 grep）
**Files scanned:** 30+（15 服务/模块全文读取 + 4 测试全文 + 6 处 grep 定向 consumer 核对：final_score 四消费点、CATEGORY_QUOTA 两消费点、assessment_message INSERT eval 兼容点）
**未读但被 RESEARCH 覆盖：** `server/test_m7_backend.py`、`eval/consistency_test.py`、`web/src/**`（前端消费面已由 RESEARCH grep 核对，Chat.vue 只用 total_count/answered_count/d.action——`api/assessment.py` 响应键改动以此为约束）
**Pattern extraction date:** 2026-09-04
