# Phase 3: 表单/SSE/幂等/计时 - Pattern Map

**Mapped:** 2026-09-05
**Codebase:** @ HEAD 6b24d97（feature/m5-assessment）
**Files analyzed:** 21（16 新建/修改 + 1 回归改断言 + 4 复用核对）
**Analogs found:** 21 / 21（全部有代码基线锚点；6 个具体技法无库内先例——RESEARCH 11 项实验已验证，见 No Analog Found）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/db.py`（form_instance/idempotency_record/session_time_intervals 三新表 + assessment_session 6 列 + assessment_message 3 列 + assessment_question.revision + question_score gate 5+4 列） | config/migration | file-I/O（DDL 演进） | `server/db.py:281-291` question_bank_task（上一代新表先例）+ `:355-433` _migrate_*_v2（PRAGMA 嗅探）+ `:303-328` _migrate_llm_trace（约束放宽重建） | exact（同文件扩展） |
| `server/config.py`（SESSION_TOTAL_MINUTES=40 / QUESTION_TIMEOUT_MINUTES=20 / ABANDON_HOURS=6 / MAX_CONTEXT_TOKENS 占位） | config | — | `server/config.py:44-49` ORDINARY_PLAN_N（纯 code 常量 + 决议注释）+ REFINE_MIN_TOKENS | exact（同区追加） |
| `server/schemas.py`（AnswerRequest / FormSubmitRequest，D-46） | model | request-response | `server/schemas.py:30-33` JdImportRequest + `:36-42` ExtractItem | exact（同文件同模式） |
| 新 `server/services/forms.py`（schema 常量 + render/六维校验/gate 判定，名 plan 可改） | service | CRUD + transform | `server/services/question_selection.py:524-607` _instantiate（INSERT+事件+commit 形态）+ `server/services/aggregation.py:48-70` _gate_check（字段消费口径） | role-match（无表单服务先例，双风格锚定） |
| 新 `server/services/idempotency.py`（三键检查 + 快照写入 + request_hash，名 plan 可改） | service | request-response | `server/services/refine.py:25-44`（sha256 + 短服务）+ `server/api/admin/feedback.py:33-40`（UPDATE rowcount 检查） | role-match |
| 新 `server/services/timer.py`（区间闭/开 + Σ重叠 + 超时判定，若 planner 拆出） | service/utility | transform（纯函数）+ CRUD | `server/services/difficulty.py:46-142`（纯函数区）+ `:145-231` update_path_state（接 conn 不 commit，事务归调用者） | role-match |
| `server/services/interview.py`（_build_user_prompt 滑窗截断） | service | transform | 自身 `interview.py:75-90`（history 循环落点）+ `:135`（纯函数区惯例）+ `refine.py:15-16` _approx_tokens | exact（同文件加截断） |
| `server/services/aggregation.py`（_gate_check 迁移为结构化结果消费） | service | batch | 自身 `aggregation.py:48-70`（迁移对象）+ `:32-45` _load_form_payload（双源兜底形态）+ `db.py:454-455`（COALESCE 双源语义先例） | exact（同文件改取数点） |
| `server/api/assessment.py` submit_answer（SSE 化 + 幂等/计时/revision 四合一改造） | controller | request-response → streaming | 自身三相 commit 链（`:170-367` 时序重排，不改链条本身） | exact（同文件内部时序重排） |
| `server/api/assessment.py` 新端点组（start/pause/resume/GET forms/submit-v2） | controller | request-response | `server/api/assessment.py:469-486` forms/submit（旧链骨架）+ `:79-117` create_session（状态转换+事件同事务）+ `:188-202` 409 三态 | exact |
| 新 `server/api/admin/forms.py`（gate 人工覆盖端点） | controller | request-response | `server/api/admin/feedback.py:11-40`（require_admin 路由 + Pydantic body + rowcount 404） | exact |
| `server/main.py`（admin forms 路由注册 2 行） | route | — | `server/main.py:43-44` import + `:79-80` include_router | exact |
| 新 `server/test_phase3_forms.py` | test | integration | `server/test_p0_chain.py:30-57`（三件套头）+ `:59-143`（种子含 gate=1 :76-78）+ `:456-471`（事件断言） | exact |
| 新 `server/test_phase3_sse.py` | test | integration（streaming） | 三件套头 exact；流式消费面**无库内先例**（RESEARCH 实验 3 `client.stream` 骨架） | partial（头 exact + 消费面 No Analog） |
| 新 `server/test_phase3_idempotency.py` | test | integration | `server/test_p0_chain.py:30-57` + `:188` _seed_completed_session_direct（直插时间旅行风格） | exact |
| 新 `server/test_phase3_timer.py` | test | unit + integration | `server/test_phase2_difficulty.py:40-66`（纯函数直测 + _make_snap fixture）+ `test_p0_chain.py:456-471`（事件序断言） | exact |
| 新 `server/test_phase3_misc.py`（分列/滑窗/INJECTION/start，名可改） | test | mixed | 同三件套头 | exact |
| `server/test_m5_backend.py`（answer 断言 SSE 流式适配） | test | regression | 自身 `:226-246` 旧 `r.json()["action"]` 断言行（只改断言形态不重构，D-09 同纪律） | exact |
| `web/src/**`（sse.js/FormCard.vue/api/index.js/Chat.vue） | — | — | **零改动**——核对锚点见 Pattern Assignments 末条 | read-only |
| `eval/virtual_candidates.py` | — | — | **零改动**——grep 已核无 answer API 面（直插链 `:123+`） | read-only |
| `server/services/state_events.py` / `refine.py` / `question_selection.py` | service | — | **不动**——append_event / (refined, raw_hash) / 池耗尽 None 语义原样复用 | read-only |

---

## Pattern Assignments

### 计划 03-01（表单链）

---

#### `server/db.py`（migration，file-I/O——本条为全 phase 三新表/ALTER 的工具箱，03-03/03-04 段照此惯例）

**Analog:** `server/db.py:281-291` question_bank_task（Phase 1「新表」先例）+ `:355-433` _migrate_*_v2（PRAGMA 嗅探）+ `:303-328` _migrate_llm_trace（约束放宽）

**新表 DDL 惯例**（`db.py:276-291`——form_instance/idempotency_record/session_time_intervals 全照）：
```python
# ============ 题库生成任务表（SSOT §10.4/D-12 题库 readiness 载体）============
# 状态枚举 QUEUED/RUNNING/SUCCEEDED/FAILED 代码校验、无 DB CHECK（N11）；
# confirm 触发生成时插 QUEUED，generate_question_bank 开始/结束更新自身行；
# 开考检查（services/readiness.py）按最新行判定生成中/不完整/就绪。

CREATE TABLE IF NOT EXISTS question_bank_task (
  task_id      TEXT PRIMARY KEY,
  ...
  status      TEXT NOT NULL,
```
照抄惯例：分节注释块（四行：来源 § 号 + 枚举代码校验 + 写入时机 + 消费面）+ 新列/新表一律无 DB CHECK（N11）+ TEXT PRIMARY KEY + now_iso 字符串时间列。form_instance 的 included_at/submitted_at、idempotency_record 的 created_at 同形态。

**组合唯一索引先例**（idempotency_record 的 UNIQUE(session_id, endpoint, idempotency_key)）：
- `db.py:57` `UNIQUE(position_id, version)`（competency_model 在 CREATE 内声明组合唯一）
- `db.py:267` `UNIQUE(session_id, sequence_no)`（assessment_state_event）
- `db.py:167` `CREATE UNIQUE INDEX IF NOT EXISTS uq_aq_session_seq ...`（独立索引语句形态——session_time_intervals 部分唯一索引走此语句形态，`WHERE ended_at IS NULL` 子句无库内先例，见 No Analog Found）

**存量表 ALTER 段惯例**（`db.py:365-382`——assessment_session 6 列 / assessment_message 3 列 / assessment_question.revision / question_score gate 列全照）：
```python
    cols = {r[1] for r in conn.execute("PRAGMA table_info(question_bank)").fetchall()}
    if not cols:
        return  # 表不存在（新建走 _DDL）
    new_cols = [
        ("model_id", "TEXT"),
        ("question_type", "TEXT NOT NULL DEFAULT 'ordinary'"),
        ...
    ]
    for name, decl in new_cols:
        if name not in cols:
            conn.execute(f"ALTER TABLE question_bank ADD COLUMN {name} {decl}")
```
照抄惯例：PRAGMA table_info 取列名集合（不逐列 sqlite_master 字符串嗅探）→ 列表驱动 → if-not-in-ALTER → NOT NULL 新列必须带常量 DEFAULT。02-01 已验证。**双轨纪律**：`_DDL` 内对应 CREATE 同步加列（新库直建）——`question_bank` 的 `:132-142` v2 列注释块 `============ Phase 2 v2 新列（SSOT §9.2；无 DB CHECK——N11）============` 是分波列注释模板。

**register 点**（`db.py:462-477` init_db）：新迁移函数按序追加在 `:472-473` _migrate_assessment_question_v2 / _migrate_question_score_v2 之后；`assessment_question` 加 revision 列直接并入既有 `_migrate_assessment_question_v2` 的 new_cols（`db.py:404-417`）或新函数（plan 定，偏好并入——同表不拆两条函数不合 02 先例的「一表一函数」实态）。

**question_score gate 列 + NOT NULL 放宽**（`db.py:436-459` _migrate_question_score_v2 是 ADD/DROP 节奏先例；`:454-455` 是 COALESCE 双源合并语义先例——gate 双源读（gate 行优先→form_submission 兜底）的 D-31 过渡期在应用层做同语义）：
- gate 五+四列 ADD：照 `:448-451` if-not-in-ADD，DEFAULT 取 NULL 可空（无 NOT NULL 需要）
- question_id/score_state NOT NULL 放宽（RESEARCH A2 四步法：ADD copy→UPDATE 拷→DROP 原列→RENAME）：**RENAME COLUMN 无库内先例**，最近似是 `:303-328` _migrate_llm_trace 的「CREATE 新表 + INSERT SELECT + DROP + RENAME」重建（sqlite_master.sql 嗅探 + executescript + BEGIN/COMMIT）——若 plan 选重建形态照此；四步部分放宽法已由 RESEARCH 实验 9/10 本地验证可行。

**保留不动**：`form_submission`（`db.py:190-197`——旧 UI 直提链，D-29 保留兼容不改列）；`assessment_state_event` 的 `:258-259` request_id/idempotency_key 列已存在——SSOT §13.1 全列本 phase 无需 ALTER。

---

#### 新 `server/services/forms.py`（service，CRUD + transform）

**Analog（双风格锚）:** `server/services/question_selection.py:524-607` `_instantiate`（写库型服务）+ `server/services/aggregation.py:48-70` `_gate_check`（消费口径）+ `server/services/scoring.py:23-30`（枚举 tuple）

**schema 常量区**（照 `scoring.py:23-30` SCORE_STATES 与 `question_selection.py:38` ORDINARY_CATEGORIES 的模块级常量惯例）：
```python
# score_state 六态（D-28；N11 代码校验惯例——Phase 2 生产前三态，枚举位供 Phase 5）
SCORE_STATES = (
    "SCORED",
    ...
)
```
FORM_SCHEMA_VERSION = "v1"（字符串版本，D-29）+ FORM_STATUS 三态 tuple + schema dict 常量（形态参照 `config.py:28-33` CATEGORY_RATIO 的内联 dict + 注释出处）。**字段名就近设计**（CONTEXT Claude's Discretion 明文）：experience 用 `years_of_experience`、qualification 用 std_name 字段——直接照 `aggregation.py:56-69` _gate_check 的现行消费口径写 schema，保证表单采集字段与 gate 判定字段零翻译层。

**render（写库段）形态**：两种在库先例，按调用点选——
- 被调于 submit_answer 池耗尽分支（API 层 conn 已持有、主事务进行中）→ **接 conn 不 commit**（难度状态机先例 `difficulty.py:27-28` 模块 docstring「事务边界（D-06/T-02-13）：update_path_state 接 conn 但不 commit——snapshot UPDATE 与事件在调用者持有的同一事务内落库」）；
- 写库 + 事件同事务 + commit + return dict 的完整形态参照 `question_selection.py:576-599`（INSERT 列名清单一行写全 + append_event ×2 + conn.commit() + 返回含主键的 dict）。

**不可变 revision（D-29/Pitfall 3）**：修订 = INSERT 新行（revision+1，instance_id 不变）+ 旧行仅 UPDATE status='superseded'——形态参照 `assessment_state_event` append-only 理念（`db.py:242-245` 注释 + `:270-274` 触发器）但**用代码纪律不用触发器**；active 查询 `ORDER BY revision DESC LIMIT 1` 照 `question_selection.py:544-547` 最新实例查询形态。

**六维校验（纯函数段）**：①所有权/②状态/③revision 需查库（接 conn 形态照 `_count_followups` interview.py:55-61 的单行读）；④必填/⑤枚举/⑥长度不持 conn——照 `difficulty.py` 纯函数区惯例（`difficulty.py:135` 分区注释「---------- 裁决层纯函数（不持 conn——Simplicity 边界） ----------」照写一个校验纯函数分区）。错误返回照 `readiness.py` 三态 dict `{"error_code", "detail"}` → API 层转 409（既有消费链 `assessment.py:96-99`）。

**渲染字段白名单分栏**（CONTEXT specifics：GET 不暴露内部阈值）：渲染列 = schema 的 fields/label/type/options；内部判分列（years 门槛/required_level）不出 GET 响应——分栏 dict 组装照 `report.py` / `aggregation.py:175-191` 的「响应 dict 键白名单」惯例。

---

#### `server/api/assessment.py` render 插入点 + forms 新端点（03-01 段）

**Analog:** 自身 `assessment.py:469-486`（forms/submit 旧链骨架）+ `:323-334`（池耗尽 finish 分支——render 插入锚）+ `:55-74` get_confirmed_model（GET 只读形态）

**render_form 插入锚两处对称**（`assessment.py:323-334` 主链 picked-None 分支 + `:343-353` legacy 对称分支）：
```python
        picked = select_next_question(session_id)
        _is_legacy_session = bool(picked and picked.get("legacy"))
        if picked is None:
            # 可选池耗尽（普通计划 + required 例外全完成）→ finish 收尾
            conn.execute(
                "UPDATE assessment_session SET status='completed', ended_at=? WHERE session_id=?",
                (now_iso(), session_id),
            )
```
改造形态：`picked is None` 后先查 gate 采集（`competency_item` gate=1 行 + form_instance 提交状态 JOIN 形态照 `_uncovered_required_items` question_selection.py:350-361 的「item 覆盖判定」）→ 未采集走 render_form_instance + assistant 消息含 `📎[form:{instance_id}]` 标记 + 事件同事务 + conn.commit() + 返回 action='form'；gate 全采集保持原 finish 路径逐字不动（D-30 扩展不改 02-02 口径）。assistant 消息 INSERT 照 `assessment.py:229-236` 现行列清单加 action='form'。

**GET /forms/{id} 只读端点**：骨架照 `:55-74` get_confirmed_model（双 404 拦截 + dict 组装）；权属前置 `load_owned_session`（`security.py:63-81`——form_instance 必须经 session 归属核验，session_id 从 form_instance 行反查，与 D-01 统一不存在语义一致）。**响应 = 渲染白名单**（见 forms.py 条目）。

**表单提交新端点（submit-v2）**：骨架照 `:469-486`（422 手检 → load_owned_session → INSERT → commit → return dict——本端点改 Pydantic body + 六维校验调用 + gate 行写 question_score + GATE_EVALUATED 事件，`session_time_intervals` 闭旧开新见 03-04 接入）。gate 行 INSERT 列清单形态照 `scoring.py:244-251`（十列参数化 executemany/单条 INSERT 均可——gate 单行用单条）。

**gate 结构化结果消费（`server/services/aggregation.py` 迁移）**：
- 迁移对象：`aggregation.py:48-70` `_gate_check(item, form_payload)` 摸底段整函数读——判定逻辑（years 比较/真值表）保留为新源判定，只换数据来源；
- 双源读：gate 行（question_score gate_result 列）优先 → 无行回退 `_load_form_payload`（`:32-45` 现行保留为旧链兜底——`json.loads + try/except JSONDecodeError: continue` 的解析防御照抄）；
- `:116-134` gate 消费段（`contribution = weight * 100.0 if passed else 0.0` + gate_items/gate_passed/gate_reason 七键）**结构不动**（D-31 不动 weight 公式）；gate 名称 detail 串格式（"工作年限 {x} 年 ≥ 要求 {y} 年"）保持——report 消费面 `aggregation.py:175-191` 键结构不破。

---

#### 新 `server/api/admin/forms.py` + `server/main.py`（gate 人工覆盖写入口，03-01 收尾段）

**Analog:** `server/api/admin/feedback.py:11-40` + `server/main.py:43-44/79-80`

**admin 路由 + Pydantic body + rowcount 检查全套先例**（`feedback.py`）：
```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ...core.security import require_admin
router = APIRouter(prefix="/api/admin/feedback", tags=["feedback"], dependencies=[Depends(require_admin)])

class _ReviewBody(BaseModel):
    note: str = ""
```
覆盖端点照此：文件头中文 docstring + prefix="/api/admin/forms" + Depends(require_admin) 路由级挂载（非函数级）+ **request 体走 Pydantic BaseModel 而非 body: dict**（admin 侧已先走 Pydantic——D-46 双重满足）；`override_reason` 强制非空用 `Field(min_length=1)`（`schemas.py:30-31` 先例）。UPDATE 未命中行 → 404 照 `feedback.py` `cur.rowcount == 0` 检查。reviewer_id 取 `user["user_id"]`（require_admin 返回 dict 含 user_id/role，`security.py:44-50`）。`automated_gate_result` 复制 + 二次确认语义（无 override_reason 拒绝 409/422）落在端点校验第一层。

**main.py 注册**（`:43-44` import + `:79-80` include）：两行照抄 `admin_feedback` 邻位。

---

#### `server/schemas.py`（03-01 + 03-02 合用）

**Analog:** `server/schemas.py:29-48`

**请求体 Field 形态先例**（`:30-33`）：
```python
class JdImportRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    company: Optional[str] = None
```
AnswerRequest 照此：question_id/answer `Field(min_length=1)`、idempotency_key/expected_revision/client_attempt_id `Optional`（幂等键可选——D-36 缺省不启用）；**`.strip()` 语义保留**（WR-02：纯空格串 422——用 Pydantic validator 保持 `assessment.py:175-176` 现行 strip 后校验语义，RESEARCH State of the Art 明示此迁移点）。FormSubmitRequest 照 `:36-42` ExtractItem（Literal 枚举 + Field(ge/le) + Optional[float]）。分节注释 `# ---- ... ----`（`:29/:35` 等惯例）+ 中文单行出处注释。

---

#### `server/test_phase3_forms.py`（03-01 测试）

**Analog:** `server/test_p0_chain.py:30-57`（三件套头——全 phase 5 个 test_phase3_* 文件统一模板，见 Shared Patterns 文件头纪律全引）+ `:59-143` 种子 + `:456-471` 事件断言

- 种子：`_seed_position_with_confirmed_model` 直复制，**gate=1 种子先例已存在**（`test_p0_chain.py:76-78` 后端开发经验 gate=1 行——form 链测试种子照此加 qualification gate 项）；
- 全链断言形态：render 触发（答题至池耗尽 → `_q` 查 form_instance 行 status='rendered' + assistant 消息含 `📎[form:` 标记）→ GET（白名单分栏断言：响应键不含 years 门槛值）→ submit（六维各错误码一行 + 成功路径）→ gate 行落 question_score 五列（`_q` 直查照 `test_m5_backend.py:249-252` 三表 JOIN 手法）→ GATE_EVALUATED 事件（`test_p0_chain.py:456-471` SELECT event_type ORDER BY sequence_no + types 断言）。revision 不可变断言：修订后旧行 status='superseded' 且新行 revision=2（双行查询）。admin 覆盖：register admin 账号 → require_admin 路由调用 + 无 override_reason 422/409（注册 admin 照 `users` 表 role 字段直插或注册后 UPDATE）。

### 计划 03-02（SSE）

---

#### `server/api/assessment.py` submit_answer SSE 化（:170-367 时序重排）

**Analog:** 自身——决策事务链条整段是「先落库再推流」的既有解法（改造 = return 换 StreamingResponse + 前置检查插入，链条本身不动）

**三相 commit 锚（generator 启动前必须全部完成——Pattern 4）**：
- `:217-218` 「先提交用户消息再调 LLM」——模式 A 原文注释与 conn.commit()；SSE 决策落库在前推流在后的形态学基础；
- `:311/:316` followup/confirm 与 next/finish 决策后 commit；`:331/:350` finish 收尾 commit；`:357` 终态 commit；
- 改造后：幂等快照 INSERT（COMMITTED 态）追加在 `:357` 后、StreamingResponse 返回前（RESEARCH 架构图 step 9）。

**改造段清单**（其余段 :173-218/:221/:229-250 原样保留）：
- 返回体替换点：`:332-334`（finish 提前 return dict）、`:351-353`（legacy finish return）、`:365-367`（主 return dict）→ 三处 return 统一改为 `StreamingResponse(_event_stream(...), media_type="text/event-stream", headers={...})`；幂等命中路径保持 200 JSON dict 直返（sse.js 形态 B :47 自动消费——A1）；
- import 块（`:2-17`）追加 `from fastapi.responses import StreamingResponse`（既有 fastapi import 行 `:4` 之外的独立行——按现行 from-import 分组惯例放 `:4` 邻位）；
- 前置检查插入区间：`:185-204`（load_owned_session 之后、消息 INSERT 之前）——6h 惰性 ABANDONED（03-04）/暂停 409（03-04）/幂等三键（03-03）/单题超时点检（03-04）按序插入，各自条目见对应计划段。

**generator 纪律**（库内无先例，Anti-pattern 1 判据写进 plan）：generator 函数体内零 `get_conn()`——静态断言可 grep generator 源码；事件序列 decision→reply×N→done（帧格式 `data: {json}\n\n` + `json.dumps(..., ensure_ascii=False)`——中文 reply 保样，`state_events.py:47` 同款 ensure_ascii=False 惯例）。decision 事件键 = `:365-367` 现行返回 dict 的键 + D-34 扩展键（answer_state/evidence_sufficient——`:241-243` OBSERVATION_CLASSIFIED payload 同键透传）。

**错误路径不动**：LLM 失败降级已在 `interview.py:216-230`（RuntimeError/ValidationError → MODEL_UNCERTAIN）——决策在 endpoint body 内完成，流无 error 事件主路径（Pitfall 2）。

---

#### `server/test_phase3_sse.py`（03-02 测试）+ 回归 `test_m5_backend.py`

**Analog:** 三件套头（test_p0_chain.py:30-57）；流式消费断言无库内先例（RESEARCH 实验 3：`with client.stream("POST", ...) as r: r.iter_lines()`）

- 断言面四项：Content-Type == text/event-stream、事件序 decision→reply(N)→done、reply 块拼接 == decision.reply 完整、done.next_question_id 与 `_q` 落库一致；
- mock 假流分块断言（reply N 条计数可断言——分块只影响传输）；
- abort 语义：AbortController/断流后 `_q` 断言用户消息与决策已落库（「先落库再推流」的直接验证）；
- 回归适配：`test_m5_backend.py:226-246` 的 `r.json()["action"]`（:229/:233/:234/:245 共 6 处）与 `test_m5_backend.py` 其余 answer 响应断言 → 改流式解析 helper（`for line in r.iter_lines(): 解析 data: 行` → 组回 dict 的本地 helper，写一次复用）；`test_p0_chain.py:182` `assert r.json()["action"] in (...)` 同步适配。只改断言形态不改测试结构（D-09 纪律）。

### 计划 03-03（幂等）

---

#### `server/db.py` idempotency_record 段（03-01 条目工具箱复用）

- 新表 DDL + UNIQUE 三键（`UNIQUE(session_id, endpoint, idempotency_key)`——组合唯一声明放 CREATE 表尾，照 `db.py:57` competency_model 形态）+ request_hash TEXT + response_snapshot TEXT + status TEXT（PENDING/COMMITTED 代码校验 tuple）+ created_at（D-38：索引留 `CREATE INDEX IF NOT EXISTS ... ON (created_at)`，普通索引照 `db.py:167` 语句形态去掉 UNIQUE）。
- `assessment_question` 加 `revision INTEGER NOT NULL DEFAULT 1`：并入 `_migrate_assessment_question_v2` new_cols（`db.py:404-417`）+ `_DDL` `:145-166` 的 v2 列区同步 + `_instantiate` INSERT `:576-583` 补列（新实例 revision=1）。

#### 新 `server/services/idempotency.py`（03-03 服务）

**Analog:** `server/services/refine.py:25-44`（短服务形态）+ `refine.py:30`（sha256 先例）+ `server/api/admin/feedback.py:33-40`（UPDATE rowcount 检查）

**hash 先例**（`refine.py:30`）：
```python
    raw_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
```
request_hash_of 照此（json.dumps sort_keys=True 规范化后 sha256——规范化层是新代码，hashlib 用法逐字照抄）。INSERT PENDING / UPDATE COMMITTED 两阶段 + IntegrityError 捕获（except sqlite3.IntegrityError——`db.py` 导入 sqlite3 惯例）；重复命中 COMMITTED → 返回 `json.loads(response_snapshot)`（解析防御照 `aggregation.py:41-44` try/except JSONDecodeError: continue 形态）；PENDING → 409 REQUEST_IN_PROGRESS（detail 结构 WR-01，`assessment.py:188-191` 模板）。开头/结尾握手走接 conn 不 commit（difficulty 契约——由 submit_answer 主事务统一）。409 三态 error_code 清单（QUESTION_REVISION_CONFLICT/REQUEST_IN_PROGRESS/SESSION_PAUSED）全 phase 统一此形态（RESEARCH Q3）。

#### submit_answer 接入点（03-03 API 段）

- 幂等检查插入 `:185` load_owned_session 之后（三键 body 参数经 AnswerRequest 可选字段 API 层取）；重复请求 200 JSON 快照直返（SSE 不启动——Anti-pattern 2：幂等命中在 StreamingResponse 之前，A1 裁量）；
- revision 乐观锁：UPDATE 扩展 `WHERE question_id=? AND revision=?`——落点即可接入 `:213-216` asked_at COALESCE UPDATE 或独立语句（plan 定）；rowcount==0 → 409 QUESTION_REVISION_CONFLICT（WR-01 detail）；
- 测试 `test_phase3_idempotency.py`：三件套头 + 同 key 重发断言（消息表无第二行 `_q` COUNT）+ revision 冲突 409 + 无 key 请求不受影响 + 时间旅行直插（旧行形态直插照 `test_p0_chain.py:188+` _seed_completed_session_direct——插 PENDING 态记录测回放路径）。

### 计划 03-04（计时区间 + 消息分列 + 滑窗）

---

#### `server/db.py` 计时段（03-01 条目工具箱复用）

- session_time_intervals 新表（interval_id/session_id/interval_type/reason/started_at/ended_at——D-39 §15 列名照 SSOT）+ **部分唯一索引** `CREATE UNIQUE INDEX IF NOT EXISTS uq_sti_open ON session_time_intervals(session_id) WHERE ended_at IS NULL`（语句形态照 `db.py:167`，WHERE 子句无先例见 No Analog Found；`_DDL` 与迁移两轨同步——02-01 Pitfall 2 纪律继承）；
- assessment_session 6 新列 ALTER（phase/active_elapsed_seconds/last_activity_at/abandoned_at/policy_version/session_time_intervals_json——SSOT §12.1 列名）照 PRAGMA 嗅探段；**旧行 phase 回填 'PENDING_START'** 用 UPDATE ... WHERE phase IS NULL（幂等条件照 `db.py:389` 锚点回填 WHERE IS NULL 形态）；**status 列 CHECK 不动**（`db.py:110`——Anti-pattern 4 双轨并存是唯一形态）；
- assessment_message 3 新列（refined_content/client_request_id/sequence_no——D-43 列名照 §12.3）可空 ALTER；写入点 = `assessment.py:207-211` 用户消息 INSERT 与 `:229-236` assistant INSERT 列清单扩展（refine_user_input 返回双值 `:205-206` 现成——refined_content 取 refined、原文经 raw_hash→context_raw 既有链）。

#### 新 `server/services/timer.py`（若 planner 拆出——不拆则并入 03-04 服务组）

**Analog:** `server/services/difficulty.py`（纯函数 + caller 持事务全套）

**「接 conn 不 commit」契约先例**（`difficulty.py:27-28` 模块 docstring 原文 + `:145-152` update_path_state 函数 docstring 重申）：
```python
事务边界（D-06/T-02-13）：update_path_state 接 conn 但不 commit——snapshot UPDATE
与 DIFFICULTY_* 事件在调用者持有的同一事务内落库（§13.1 快照与事件同事务）。
```
close_open_interval/open_interval/paused_overlap_seconds 全照此写模块 docstring（中文 + § 号出处 + 事务归调用者声明）。纯函数（区间 merge/Σ重叠）照 `advance_snapshot :114-142`（输入 dict → 新 dict 零副作用 + 判据 docstring 逐条）；now_iso 解析 `_ts = datetime.fromisoformat`（`pipeline.py:14-16` now_iso 是产生方——兼容性 RESEARCH 实验 8 已证）；IntegrityError 捕获重试环（open_interval）except sqlite3.IntegrityError。6h 判定挂 `load_owned_session` 相邻（每次会话访问点——提交函数接 conn 形态同款）。

#### `server/config.py`（03-04 常量）

**Analog:** `server/config.py:44-49`

**纯 code 常量 + 决议注释先例**（`:44-47`）：
```python
# 岗位级普通题计划数 N（SSOT §10.1/§31-1）：普通主问题配额的基数，
# 与 7:3 最大余数 + tier 公式共同决定每次会话的选题目标。
ORDINARY_PLAN_N = 10  # 生产默认值——2026-09-04 关口 A 用户裁决（02-DECISIONS [02-007]）
```
SESSION_TOTAL_MINUTES=40 / QUESTION_TIMEOUT_MINUTES=20 / ABANDON_HOURS=6 照此（SSOT §15 硬编码非开放参数）；MAX_CONTEXT_TOKENS 照注释结构但写「**实施期校准，关口包呈报项**（SSOT §31-2 开放参数——数值不代决）」。**注意**：不抄 FOLLOWUP_MAX 的 `int(os.environ.get(...))` env 可覆盖形态（`config.py:51`）——RESEARCH Runtime State 已定「全部 code 常量不引 env 新名」（对齐 ORDINARY_PLAN_N 先例）。分节：并入 `# ---- 模块二：测评 ----`（`config.py:44`）或新分节注释。

#### `server/services/interview.py`（滑窗截断，03-04/05 侧带）

**Analog:** 自身 `interview.py:75-90`（落点）+ `:135`（纯函数区惯例）+ `server/services/refine.py:15-16`（token 近似）

**截断落点**（`interview.py:84-87` 现行 history 循环 + 当前题最新回答追加）：
```python
    for m in history:
        role = {"user": "候选人", "assistant": "面试官", "system": "系统"}[m["role"]}
        lines.append(f"{role}：{m['content']}")
    lines.append(f"候选人：{user_message}")
```
接入形态：decide_next_action `:200-205` history 加载后、`:213` _build_user_prompt 调用前插截断调用；**当前题 stem 与候选人回答永不进截断面**（§14——Pitfall 7）。`_truncate_history` 落纯函数区——`interview.py:135` 分区注释「---------- 裁决层纯函数（不持 conn——Simplicity 边界） ----------」邻位新起或复用该区；token 近似 `len(content) // 2` 与 `refine.py:15-16` _approx_tokens 同款口径（同库同近似，防两处公式漂移——WR-15 教训）。mock 全量直通的 provider 判断：RESEARCH Pitfall 9 裁量推荐「纯函数不看 provider、调用方传全量」——调用点 `decide_next_action :211-215` 的 call_llm_json mock_fn 双轨相邻位。

---

#### `server/test_phase3_timer.py`（03-04 测试）

**Analog:** `server/test_phase2_difficulty.py:40-66`（纯函数直测 + _make_snap fixture 构造）+ `test_p0_chain.py:456-471`（事件序断言 + sequence_no 顺序）

- 回归 merge/纯函数直测：构造重叠区间列表断言 Σ（表驱动照 `_make_snap` 局部 fixture 风格）；
- 闭旧开新：请求前后 `_q` 查区间行（ended_at 闭合 + 无双 open 行断言——部分唯一索引的 DB 层断言）；
- 单题超时：时间旅行直插 activated_at（UPDATE 直插照 `_seed_completed_session_direct` 直插手法）→ answer 请求触发封存 seal_reason='timeout'（第四路断言 + QUESTION_SEALED payload）;
- 全场超时事件序：GLOBAL_TIMEOUT sequence_no < SESSION_ENTERED_SCORING（`ORDER BY sequence_no` 双行比较——`test_p0_chain.py:456-459` 查询形态）；
- 6h ABANDONED：时间旅行 last_activity_at 直插 → 任意会话访问触发 SESSION_ABANDONED + status='abandoned';
- 消息分列：answer 后 `_q` 查三新列落值（refined_content/client_request_id/sequence_no）。

### 计划 03-05（入场确认 + Injection 留痕 + misc）

---

#### `server/api/assessment.py` start/pause/resume 端点组

**Analog:** `server/api/assessment.py:79-117` create_session（状态转换三步）+ `:609-636` submit_feedback（带护栏 POST 形态）+ `:188-202`（409 三态）

**状态转换三步先例**（`assessment.py:103-115`）：INSERT/UPDATE + append_event（与写同事务）+ conn.commit() + return dict——start 端点照此（UPDATE phase='ACTIVE' + SESSION_STARTED + open 第一个 active 区间三动作同事务）。pause/resume 照 submit_feedback 骨架（load_owned → 状态 409 护栏 → 写 + 事件 + commit → dict），pause 期间 answer 被 409 SESSION_PAUSED 的插入点在 `:186-202` 护栏区（与 SESSION_NOT_IN_PROGRESS 相邻新增分支）。get_session 派发分支 `:135-137` 加 `phase == 'ACTIVE'` 条件（Pitfall 12——防未确认先计时）。`estimated_duration_minutes`（`:117`）改 SESSION_TOTAL_MINUTES 派生（A5：前端无消费 grep 已核）。

#### INJECTION_DETECTED 落点（03-05）

**Analog:** `assessment.py:238-243` OBSERVATION_CLASSIFIED 事件段（相邻位 + payload 白名单纪律）

```python
    append_event(conn, session_id=session_id, event_type="OBSERVATION_CLASSIFIED",
                 actor_type="system", assessment_question_id=question_id,
                 payload={"answer_state": decision["answer_state"], ...})
```
INJECTION_DETECTED 照此相邻追加：`decision["answer_state"] == "PROMPT_INJECTION"` 判定（`_EXCLUDED_FAILURE_STATES` 已含该枚举 `:436`——分类驱动即检测 D-45）；payload 白名单 `{answer_state, stability}` **不含输入原文**（同 OBSERVATION_CLASSIFIED 的白名单纪律——payload 只放分类结论键）。候选人输入以数据身份进 prompt 的既有包裹形态保持（_build_user_prompt `:87` 候选人行格式）。

#### `server/test_phase3_misc.py`（03-05 测试，名可改）

三件套头 + 分列断言 + `_truncate_history` 纯函数两分支直测（非 mock 条件构造——Pitfall 9）+ mock 词表注入词（mock 分类器 `_DECLINE_WORDS` 邻位新增注入词表，`interview.py:26` 模块级元组惯例）→ answer_state=PROMPT_INJECTION → 事件行存在 + payload 无原文字段（断言键集合）+ start 端点状态机（PENDING_START→ACTIVE→SESSION_STARTED 事件序 + get_session 派发时序）。

---

#### `web/src/**`（零改动——核对锚点，不落任何 plan 的 Files 清单）

| 文件:行 | 核对锚点 | 对后端的约束 |
|---------|----------|--------------|
| `web/src/utils/sse.js:3-10` | 形态 A/B 契约注释 | 事件名/键名以此为准（decision/action/reply.content/done.next_question_id） |
| `web/src/utils/sse.js:47` | `contentType.includes('application/json')` 形态 B 分支 | 幂等快照 200 JSON 直返即被消费（sse.js 形态 B 分支） |
| `web/src/utils/sse.js:69-72` | `data: ` 前缀 + JSON.parse | 帧 `data: {json}\n\n` + ensure_ascii=False 兼容（中文 reply） |
| `web/src/utils/sse.js:76-78` | type 三分发 + `data.content` | reply 事件键名必须 content |
| `web/src/api/index.js:46-48` | `getForm` → GET `/api/assessment/forms/{formId}` | **GET /forms 路由 URL 以此锁定**（不带 /sessions 前缀）；submitForm 走旧链不动 |
| `web/src/components/FormCard.vue:81` | 契约注释 `{form_type, title?, fields:[{name,label,type,required?,options?,placeholder?}]}` | GET /forms/{id} 响应形态以此单源锁定（渲染白名单字段集） |
| `web/src/components/FormCard.vue:109` | `submitForm(sessionId, schema.form_type, {...model})` | 提交体 = {form_type, payload dict}——六维校验输入形态 |
| `web/src/views/assessment/Chat.vue:159-160` | `extractFormId` 正则 `/📎\[form:([^\]]+)\]/` | 标记格式 `📎[form:{form_instance_id}]` 逐字对齐；instance_id 引用稳定性（revision 换行不换 id） |
| `eval/virtual_candidates.py:102+` | 直插链（无 answer API 调用） | reply/SSE 化零影响（grep 已核） |

---

## Shared Patterns

### 测试文件头三件套（全 phase test_phase3_* 统一模板）

**Source:** `server/test_p0_chain.py:30-57`（最新同款：`server/test_phase2_selection.py:25-46`）
**Apply to:** 全部 5 个 test_phase3_* 文件

```python
import json
import os
import sys
import tempfile

# 必须在 import server 之前设环境变量（config 在 import 时读取）
_tmp_db = os.path.join(tempfile.mkdtemp(), "test_phase3_<name>.db")
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
另有模块 docstring（文件用途 + REF 号 + 「单文件单进程/不碰 data/app.db/运行命令」三行——`test_p0_chain.py:1-24` 模板）；`_q` 只读 helper（`test_p0_chain.py:48-54`——开→读→关，不持锁阻塞 API 写）；种子 fixtures 不 import 其他测试模块（:57 注释）。旧库迁移路径变体（question_score 放宽/gate 列 ALTER 测试需要）：`test_phase2_migration.py:12-60` 的 `_OLD_DDL` 先建旧表插旧行再 init_db 的双路径形态。

### append_event 唯一事件入口（SESSION_* 组 + FORM_*/GATE_*/INJECTION_DETECTED 全部走此）

**Source:** `server/services/state_events.py:14-48`
**Apply to:** 03-01 FORM_RENDERED/FORM_SUBMITTED/GATE_EVALUATED、03-04 SESSION_PAUSED/RESUMED/GLOBAL_TIMEOUT/ABANDONED、03-05 SESSION_STARTED/INJECTION_DETECTED
参照 `assessment.py:112-114`（SESSION_CREATED 与写同事务调用形态）与 `assessment.py:239-243`（payload dict 传入形态）。sequence_no 取号单点封装（`state_events.py:36-38`）——**禁止手拼 INSERT INTO assessment_state_event**。

### raw SQL + get_conn() 惯例

**Source:** `server/db.py:295-300`（Row 工厂 + PRAGMA foreign_keys + 每调用新连接）
**Apply to:** 全部新服务与端点。`?` 参数化、dict(r) 转换、服务自取连接 try/finally close（`question_selection.py:275-279`）、WR-01 同事务读写接主 conn（`assessment.py:415-423` _question_item_id 的 docstring 注记——03-03 乐观锁/03-04 区间操作同纪律消双连接交错窗口）。

### SQLite 写锁两模式（SSE「先落库再推流」= 模式 A 的传输层副本）

**Source:** `server/api/assessment.py:217-218`（模式 A：先 commit 再调 LLM——注释原文「本连接持写事务会 database is locked」）+ `server/services/scoring.py:243-251`（模式 B：内存算完单事务落库）
**Apply to:** 03-02 generator 零连接（决策全 commit 后 yield——abort 落链条之外）；03-04 区间闭开在主事务内（append_event 同款单事务多写合并）。

### N11 枚举代码校验（无 DB CHECK）

**Source:** `server/services/state_events.py:11`（`_VALID_ACTOR_TYPES = ("candidate", "system", "admin")`）+ `server/services/scoring.py:23-30`（SCORE_STATES）+ `server/db.py:162`（seal_reason 枚举位注释——timeout 位已预留：`seal_reason TEXT, -- answered/refused/timeout 枚举位，代码校验`）
**Apply to:** form_status/interval_type/gate_status/idempotency status/SESSION_* 事件名 全部模块级 tuple + 入口校验；seal_reason='timeout' 第四路**枚举位已在 D-25 预留无需改 DDL 注释**。

### 409 detail 三态结构（WR-01）

**Source:** `server/api/assessment.py:188-191`
```python
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"error_code": "SESSION_NOT_IN_PROGRESS",
                                    "message": f"会话已结束（{s['status']}）"})
```
**Apply to:** SESSION_PAUSED / QUESTION_REVISION_CONFLICT / REQUEST_IN_PROGRESS / FORM_ALREADY_SUBMITTED / 幂等版本冲突——全部新增 409 逐字照此结构。

### mock 双轨（假流分块 = 假流不假语义）

**Source:** `server/services/interview.py:93-132` _mock_interview（`_mock_*` 相邻 + 词表模块级元组 :26-27）+ `server/services/llm.py` call_llm_json mock_fn 分派（消费形态 `interview.py:211-215`）
**Apply to:** 03-02 reply 假流分块（mock/真实同构 decision dict，只切分传输）；03-05 注入词表（`_INJECTION_WORDS` 元组照 `_DECLINE_WORDS` 邻位）。mock 分类器输出与 InterviewObservation 同构的纪律照抄。

### 中文 docstring + SSOT § 号 + WR/CR/D 缩写注释

**Source:** `difficulty.py:1-29`（模块 docstring 判据逐条 + 事务边界声明）、`assessment.py:443-448`（_advance_difficulty_state 函数 docstring）、`interview.py:207-210`（CR-01 注释留痕）
**Apply to:** 全部新函数（forms/timer/idempotency/新端点/generator）——docstring 首段中文用途 + § 号出处；防回归决策以 WR-xx/CR-xx/D-3x 缩写行内注释；Pitfall 编号引用 03-RESEARCH。

---

## 全局惯例清单（Phase 2 执行已验证——Phase 3 沿用确认）

1. **单文件单进程 pytest**：一次 pytest 只收一个测试文件（DB_PATH 竞态——多文件不得同一次收集）；回归三件（test_m5_backend / test_p0_chain / test_p0_security——p0_security 不涉 answer 面但按 02 验收节奏全跑）+ 5 个 phase3 文件逐个跑。测试库永远 tempfile.mkdtemp()——不碰 data/app.db（红线 2）。
2. **mock 双轨**：LLM_PROVIDER=mock 离线全测；每服务 `_mock_*` 相邻（不集中 mock 模块）；mock 模拟行为节奏而非绕过决策语义（reply 分块同纪律的依据 D-23）。
3. **原子 commit message 格式**（Phase 2 验证形态）：`feat(03-0X): <一行>` / `test(03-0X): <一行，含 (RED) 前缀先行测试>` / review 轮 `fix(03-review): WR-XX — <描述>`——scope 用带波号的 plan 号（02 实例：`feat(02-05): DROP final_score column — A8 order-contract closure`、`test(02-05): add failing score-chain contract tests (RED)`、`fix(02-review): WR-01 — ...`）。每个工作单元一个 commit；先测试后实现的 RED→GREEN 节奏照 02。
4. **工作树纪律**：不留未 commit 的完成品；自己的改动产生的孤儿 import/变量必须清理；不「顺手改进」相邻代码/注释/格式；匹配既有风格（raw SQL `?` 参数化、`{error_code, message}` 409 detail、`# noqa: E402`、中文 docstring、ensure_ascii=False）。
5. **Conftest 无配置文件**：测试三件套 env 前置 + tempfile 不引 conftest.py（TESTING.md 纪律，Phase 2 五文件全部遵守）。

## No Analog Found

代码库无结构先例（RESEARCH Code Examples + 实验编号已给可转写骨架——planner 直接引用，不推导）：

| 技法 | 落点 | 最近似（形态锚） | RESEARCH 依据 |
|------|------|------------------|---------------|
| StreamingResponse 同步 generator | 03-02 submit_answer | 全库唯一流式端点；starlette iterate_in_threadpool | Code Examples #1 / 实验 1-3 |
| TestClient 流式消费（client.stream + iter_lines） | test_phase3_sse.py + m5 回归 | 现有 `r.json()` 一次性断言（test_m5_backend.py:226-246）测不出流式 | 实验 3/11 / Pitfall 8 |
| 部分唯一索引（CREATE UNIQUE INDEX ... WHERE ended_at IS NULL） | 03-04 session_time_intervals | `db.py:167` 普通 UNIQUE INDEX 语句形态 | 实验 6 / Pattern 3 |
| ALTER ... RENAME COLUMN（question_score question_id/score_state NOT NULL 放宽四步法） | 03-01 gate 行落位 | `db.py:303-328` 重建表法（CREATE new+INSERT SELECT+DROP+RENAME）| 实验 9/10 / Pitfall 4 |
| Python 端区间 merge（Σpaused 重叠） | 03-04 timer.py | `difficulty.py:114-142` advance_snapshot 纯函数风格 | 实验 5（SQL SUM 双计已证不可用） |
| sha256 规范化 JSON request_hash（sort_keys） | 03-03 idempotency.py | `refine.py:30` hashlib.sha256 用法（输入是 json.dumps 产物为新代码） | Code Examples #5 / 实验 4 |

## Metadata

**Analog search scope:** `server/` 全部 .py（db/config/schemas/main、services/ 全 17 模块、api/assessment + api/admin/ 全 9 模块）、`server/services/prompts/`、`web/src/utils/sse.js` + `web/src/components/FormCard.vue` + `web/src/api/index.js` + `web/src/views/assessment/Chat.vue`（定向行号核对）、`eval/virtual_candidates.py`（grep 定向）
**Files scanned:** 35+（12 模块全文读取 + 6 测试文件定向段 + 4 前端文件 grep/定向行核对 + git log 40 条 commit 格式样本）
**未读但被 RESEARCH 覆盖：** `report.py` 大部、`eval/consistency_test.py`、`api/admin/*.py` 其余 6 文件（admin 路由惯例经 feedback.py 单点核实）、`web/src` 其余视图
**Pattern extraction date:** 2026-09-05
