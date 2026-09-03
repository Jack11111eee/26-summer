---
phase: 01-p0
reviewed: 2026-09-03T08:05:12Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - eval/virtual_candidates.py
  - server/api/admin/models.py
  - server/api/admin/positions.py
  - server/api/assessment.py
  - server/core/security.py
  - server/db.py
  - server/services/question_bank.py
  - server/services/readiness.py
  - server/services/scoring.py
  - server/services/state_events.py
  - server/test_m5_backend.py
  - server/test_m6_backend.py
  - server/test_p0_chain.py
  - server/test_p0_security.py
  - web/src/router/index.js
  - web/src/views/assessment/PositionAssess.vue
findings:
  critical: 5
  warning: 15
  info: 9
  total: 29
status: issues_found
---

# Phase 01 (p0): Code Review Report

**Reviewed:** 2026-09-03T08:05:12Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

审查了 Phase 01（p0）四个计划的全部交付物：候选人资源所有权检查（IDOR 修复：`load_owned_session`/`load_owned_report`）、`assessment_state_event` append-only 审计链（触发器 + `append_event` 唯一写入口）、score→report 服务端串行链与 completed 护栏（B-1 三分支）、开考前可测量性检查（readiness 三态 + `question_bank_task` 表），以及配套前端路由与开考页、4 个测试文件与 eval 虚拟考生工具。审查跨文件追到了 `question_selection`、`interview`、`refine`、`aggregate`、`aggregation`、`report`、`llm`、`auth`、`admin/eval`、`config` 及前端 `api/index.js`/`stores/auth.js`。

正面结论：IDOR 修复本身质量高——读写路由全覆盖、404 语义统一、admin 读豁免/写拒绝一致、owner 判定优先；串行链事件与快照更新的事务边界（同事务原则、LLM 调用不持写事务）实现严谨；测试矩阵对护栏与越权路径证明充分。

但发现 5 个 Critical：客观题 `answer_key` 为 NULL 时空正则匹配一切、任何回答恒得 5 分（评分正确性缺陷）；题库生成失败后全仓库无任何重触发入口，FAILED+题库不足的岗位被 readiness 永久锁死（契约断裂）；`review_position` reject 在 FK 开启下遇子表数据即未捕获 IntegrityError → 500（且 `trigger_aggregate` 不查岗位状态使其可达）；readiness 配额检查不考虑模型类目构成，某类目全缺的合法模型永久 INCOMPLETE；JWT_SECRET 采用公开默认值且无启动校验，配合 eval 工具写入的固定 `user_id="eval_user"` 可构造已知 sub 的伪造 token。另有 15 个 Warning（错误体契约不一致、输入校验缺口、幂等粒度、非原子任务行、存在性 oracle、前端缺错误处理等）与 9 个 Info。

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: 客观题 answer_key 为 NULL 时空正则匹配一切——任何回答（含乱码）恒得 5 分

**File:** `server/services/scoring.py:69-71, 18-24`（配合 `server/services/question_bank.py:134-141`、`server/db.py:118-132`）
**Issue:** `score_question` 对客观题调用 `_score_objective(q["answer_key"] or "", answer_text)`。当 `answer_key` 为 NULL/空时传入空串，而 Python 中 `re.search("", 任何文本)` **恒返回 match 对象**（已实测验证：`bool(re.search('', 'anything')) == True`）→ `hit = True` → 返回 5 分。即：客观题缺 answer_key 时，任意回答（包括"不知道"）都得满分。

该形态可达：
- `generate_question_bank` 真实 LLM 路径存 `answer_key=q.get("answer_key")`（question_bank.py:139），`call_llm_json` 对 question_gen 输出**无 Pydantic 强校验**（对照 schemas.py 中 extract/disambiguate/aggregate_level 均有强 Schema），LLM 返回 objective 题但漏 answer_key 字段时照常入库；
- `question_bank` DDL 对 qtype='objective' 的 answer_key **无 CHECK 约束**（db.py:118-132），人或导入路径同样可产生 NULL；
- 入库后 status='active'，进入选题池并参与终局评分——污染 `question_score`、聚合分、报告雷达，且无任何告警。

这是核心评分正确性缺陷（测评系统最不能错的地方），mock 模式与测试种子都恰好给了 answer_key，所以现有测试永远打不中它。

**Fix:**
```python
# server/services/scoring.py
def _score_objective(answer_key: str, answer: str) -> tuple[int, str]:
    if not (answer_key or "").strip():
        return 1, "answer_key 缺失（题目配置异常），按最低分记"
    try:
        hit = re.search(answer_key, answer) is not None
    except re.error:
        hit = answer_key.lower() in answer.lower()
    ...
```
并在 `generate_question_bank` 入库前拒绝/跳过无 answer_key 的 objective 题（或降级为 subjective），必要时给 `question_bank` 补 CHECK。

### CR-02: 题库生成失败后无任何重触发入口——FAILED + 题库不足的岗位被 readiness 永久锁死，管理端待办永不归零

**File:** `server/services/question_bank.py:83-151`（配合 `server/api/admin/models.py:93-115`、`server/services/readiness.py:79-91`、`server/api/admin/positions.py:24-27`）
**Issue:** 题库生成唯一入口是 `confirm_model` 插 QUEUED task 行后 `background.add_task(generate_question_bank, ...)`。任务失败置 FAILED 不抛（设计如此）。但失败后的恢复路径不存在：
- 再次 confirm 同一模型 → 409「模型已确认」（models.py:93-94）；
- 全仓库（grep 验证）除 `confirm_model` 与测试外**没有任何路由再次调用 `generate_question_bank` 或插入新 task 行**；
- `_update_task_status` 只 UPDATE 既有行，不新建行。

于是「FAILED + 题库不足」形成死局：readiness 永远返回 QUESTION_BANK_INCOMPLETE → 该岗位 `POST /api/assessment/sessions` 恒 409；`GET /api/admin/todos` 的 `question_bank_not_ready` 按 `status != 'SUCCEEDED'` 计数（positions.py:25-27），FAILED 行永不消除。代码自身注释声称「失败不抛（可手动重触发）」（question_bank.py:84），但重触发入口在交付范围内不存在——实现与自身契约断裂。管理员唯一出路是手工改库。

**Fix:**
```python
# server/api/admin/models.py 追加 retry 路由
@router.post("/question-bank-tasks/{task_id}/retry")
def retry_question_bank_task(task_id: str, background: BackgroundTasks) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT position_id, model_id, model_version, status FROM question_bank_task"
        " WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if row["status"] != "FAILED":
        raise HTTPException(status.HTTP_409_CONFLICT, "仅失败任务可重试")
    from ...services.pipeline import new_id, now_iso
    conn.execute(
        "INSERT INTO question_bank_task(task_id, position_id, model_id, model_version,"
        " status, created_at) VALUES(?,?,?,?,?,?)",
        (new_id("qbt"), row["position_id"], row["model_id"],
         row["model_version"], "QUEUED", now_iso()))
    conn.commit()
    from ...services.question_bank import generate_question_bank
    background.add_task(generate_question_bank, row["position_id"], row["model_id"])
    return {"position_id": row["position_id"], "requeued": True}
```
（同修 WR-12 的 `_update_task_status` 取行 tie-break，见下。）

### CR-03: `review_position` reject 直接 DELETE position——FK 开启下命中 competency_model / question_bank_task / assessment_session 即未捕获 IntegrityError → 500

**File:** `server/api/admin/positions.py:63-69`（配合 `server/db.py:273`、`server/api/admin/models.py:14-22`）
**Issue:** reject 分支清理 jd_record（归 NULL）与 position_alias（删除）后 `DELETE FROM position`。但 `competency_model.position_id`、`question_bank.position_id`、**`question_bank_task.position_id`（01-04 新表）**、`assessment_session.position_id` 均 REFERENCES position，且 `get_conn()` 每连接 `PRAGMA foreign_keys = ON`。真实触发路径存在：`trigger_aggregate`（models.py:14-22）**查询了 position.status 却不检查**，管理员对 pending_review 岗位手动聚合即产生 competency_model 行；01-04 的 question_bank_task 存在任何历史行、或该岗位已有会话，同样命中。sqlite3.IntegrityError 未捕获 → FastAPI 500，无全局兜底转可解释错误（前两个语句未 commit，连接关闭时回滚，数据不坏，但接口崩坏且不可解释）。

**Fix:** reject 前检查子表占用并给出 409；同时 `trigger_aggregate` 补 status 检查（见 WR-08）堵住可达路径：
```python
if action == "reject":
    blocking = conn.execute(
        "SELECT (SELECT COUNT(*) FROM competency_model WHERE position_id=?) m,"
        " (SELECT COUNT(*) FROM question_bank_task WHERE position_id=?) t,"
        " (SELECT COUNT(*) FROM assessment_session WHERE position_id=?) s",
        (position_id, position_id, position_id)).fetchone()
    if blocking["m"] or blocking["t"] or blocking["s"]:
        raise HTTPException(status.HTTP_409_CONFLICT,
            "岗位已产生模型/题库/会话数据，不可撤销（请改用下架处理）")
    # ...原有 jd 归 NULL、alias 删除、position 删除...
```

### CR-04: readiness 配额检查不考虑模型类目构成——任一整类目缺失的合法模型被永久 QUESTION_BANK_INCOMPLETE 锁死

**File:** `server/services/readiness.py:93-105,38-49`（配合 `server/services/question_selection.py:9`、`server/services/question_bank.py:15-29,108`）
**Issue:** 第 5 项配额检查对全局 `CATEGORY_QUOTA = {"hard_skill": 6, "soft_skill": 2, "experience": 2}` **无条件**逐类目比对，不问模型是否含该类目能力项。而题库生成只按本模型 items 产题：hard_skill/soft_skill 一律 `scope='position'` 且仅来自本岗位模型 items。于是：

模型全然没有 hard_skill 项（纯软技能岗位，聚合链完全可产出此形态——`_collect_items` 按 JD 抽取项的实际 category 分组，category ratio 只影响权重）→ 该岗位 position 作用域 hard 题恒为 0，`have 0 < 6` 恒 gap → 永久 QUESTION_BANK_INCOMPLETE → **该岗位永远无法开考**，且没有任何管理端操作能补齐（没有任何路径能往一个不含 hard 项的模型岗位里塞 position 作用域 hard 题）。soft_skill、experience 类目同理（模型无 soft 项的纯硬技能岗位同样锁死）。这是对合法数据形态的功能性死锁。

**Fix:** 配额按模型实际类目需求计算：
```python
needed_categories = {
    r["category"] for r in conn.execute(
        "SELECT DISTINCT category FROM competency_item WHERE model_id=? AND gate=0",
        (model["model_id"],)).fetchall()
}
for category, quota in CATEGORY_QUOTA.items():
    if category not in needed_categories:
        continue  # 模型不含该类目：不要求配额
    have = counts.get(category, 0)
    if have < quota:
        gaps.append(f"{category} {have}/{quota}")
```

### CR-05: JWT_SECRET 采用公开默认值且无启动校验——部署漏配即伪造 token；配合 eval 工具的固定 user_id 可稳定冒充真实账号

**File:** `server/core/security.py:24-39`（配合 `server/config.py:16`、`eval/virtual_candidates.py:150-159`、`server/main.py:16-28`）
**Issue:** `config.JWT_SECRET` 默认 `"change-me-in-.env"`，该字面量公开提交在 `.env.example` 中；`main.py._load_env` 在 .env 缺失时静默返回，`create_token`/`jwt.decode` 全链路**无任何启动或调用前校验**。若部署时漏配 JWT_SECRET（.env 未复制/未设环境变量），HS256 对称密钥即公开常量，任何人可离线伪造合法签名 token。角色虽经 `_current_user` 从 DB 重取（伪造 role 不生效），但 `sub` 直接决定身份：凡 `user_id` 可知即可冒充该用户访问其全部资源（会话、答题、报告、反馈）——这正是本阶段 IDOR 修复要保护的数据面。

可达放大器：`_ensure_eval_user` 在**生产同库**写入 `user_id="eval_user"`（字面量、非随机），只要管理员跑过一次虚拟考生评测，该 user_id 即为可枚举的已知值——攻击者可用默认密钥伪造 `{"sub": "eval_user"}` 直接通过认证。另外 `payload["sub"]` 无 KeyError 防护，带正确签名但缺 sub 的 token 会 500（小问题，修 CR-05 时顺带）。

**Fix:** 启动期 fail-closed（security.py 模块级或 main startup）：
```python
# server/core/security.py
_INSECURE_DEFAULTS = {"", "change-me-in-.env"}
if config.JWT_SECRET in _INSECURE_DEFAULTS:
    raise RuntimeError("JWT_SECRET 未配置：拒绝以公开默认密钥签发 token（请设置环境变量）")
```
同时 `_current_user` 用 `payload.get("sub")`，缺失返回 401。

---

## Warnings

### WR-01: 同一 assessment 路由族 409 detail 两种形态——readiness 返回 dict、report/score 返回 string，错误体契约不统一

**File:** `server/api/assessment.py:80-84` 对照 `server/api/assessment.py:313-319` 与 `web/src/views/assessment/PositionAssess.vue:137-143`
**Issue:** readiness 拒绝时 `detail={"error_code":..., "message":...}`；report 的两个 409 是纯字符串 detail。前端 `detail?.message || detail || '...'` 恰好兼容两种（string 无 .message 短路到自身），但任何只按一种形态写处理的新消费方（Chat.vue / Report.vue）会对另一种显示 `[object Object]` 或空文案。error_code 可编程契约只覆盖 readiness 三态。这是任务点名要求的跨计划 seam 检查对象。

**Fix:** 统一 409 body 为 `detail={"error_code": ..., "message": ...}`（如 `SESSION_NOT_COMPLETED` / `REPORT_ALREADY_EXISTS`），前端保留 fallback；或抽共享错误工厂。

### WR-02: `submit_answer` 的 answer 校验不 strip——纯空格串过检，与同文件 `submit_feedback` 的 `.strip()` 语义不一致

**File:** `server/api/assessment.py:143-145`（对照 355-357）
**Issue:** `if not question_id or not answer:` 只拒 falsy，`"   "` 直通 refine 与 decide_next_action（mock 下 len<20 触发 followup 勉强兜底；真实 LLM 无字符数护栏，纯空格作为正式回答落库并参与评分）。同为候选人自由文本入口两处校验语义不一致。

**Fix:**
```python
raw_answer = body.get("answer")
answer = raw_answer.strip() if isinstance(raw_answer, str) else ""
if not question_id or not answer:
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 question_id 或 answer")
```

### WR-03: `generate_question_bank` 幂等粒度太粗——item 部分成功后任何重触发整体跳过，残缺链条永不补齐

**File:** `server/services/question_bank.py:110-124`
**Issue:** 幂等条件为「该 (scope, position/std_name, category) 存在任一 active 题即跳过整个 item」。plan 为 easy/medium/hard 三题时，首轮 LLM 对 easy 成功、medium 异常 → task FAILED、题库仅 1 题。重触发（CR-02 修复后即有该路径）时该 item 因「已存在 active 题」被整体跳过，medium/hard 永久缺失；readiness 第 5 项按 hard 配额 6 计数，残缺岗位持续 INCOMPLETE。幂等保护无法区分「完整生成过」与「部分生成过」。

**Fix:** 幂等按 (std_name, category, difficulty) 计数对比 plan 目标，缺口补生成；或 FAILED retry 语义中先清掉该 item 未完成链的残留行。

### WR-04: `confirm_model` 的 task 行插入在主事务之外且失败无补偿——可出现「confirmed 但无 task 行」的不可恢复态

**File:** `server/api/admin/models.py:98-115`
**Issue:** 顺序为 UPDATE confirmed → commit → INSERT task QUEUED → commit → add_task。插行失败（磁盘满、DB busy 下 sqlite3.OperationalError）时：已 commit 的 confirmed 不回滚、add_task 不执行、无 catch。岗位进入「confirmed 但无 task 行」状态：readiness 第 3 项查不到 task 行 → 按实际题量判定 → 题库为空 → INCOMPLETE → 永久锁死（叠加 CR-02 无重试）。注释声明这是有意的小事务设计，但没有为「插行失败」这一窗口提供任何补偿。

**Fix:** 把 task 行 INSERT 合并进 confirm 同一事务（UPDATE confirmed 后、commit 前插入），保证 confirmed ⇔ QUEUED 行原子共存；后台任务异常路径仍各自更新行，与「三态真实可查」诉求不冲突。

### WR-05: `get_report_by_session` 第一步查询不带所有权且两个 404 文案不同——任意登录用户可探测任意 session_id 是否已生成报告

**File:** `server/api/assessment.py:329-340`
**Issue:** 第一步 `SELECT report_id FROM report WHERE session_id=?` 无 ownership 过滤：报告不存在 → 404「报告尚未生成」；存在但属他人 → `load_owned_report` → 404「报告不存在」。持 token 用户可借文案差异区分「从未生成」与「已生成（可能是别人的）」。泄露量小，但与 D-01「统一不存在、不做存在性 oracle」的设计目标相悖。

**Fix:** 第一步 join assessment_session 限定 `user_id=?`；或两处 404 统一文案「报告不存在或无权访问」。

### WR-06: `submit_feedback` 的 item_id 仅全局存在性校验——可挂入与本报告无关模型的能力项

**File:** `server/api/assessment.py:360-362`
**Issue:** `SELECT 1 FROM competency_item WHERE item_id=?` 是全表校验，不校验该 item 属于此 report 会话锚定的 model。owner 可对「岗位 A 的报告」提交「岗位 B 模型的 item_id」，feedback 行照常插入（FK 只引用 competency_item 整表）。后续反馈回溯流按 report→item 追溯评分依据会拿到无关 item，破坏 07 §11 ② 的数据完整性。

**Fix:**
```python
it = conn.execute(
    "SELECT 1 FROM competency_item ci"
    " JOIN assessment_session s ON s.model_id=ci.model_id"
    " JOIN report r ON r.session_id=s.session_id"
    " WHERE r.report_id=? AND ci.item_id=?",
    (report_id, item_id),
).fetchone()
```

### WR-07: `update_model` 对 body 完全无结构校验——缺字段/非法类型直接 KeyError/ValueError → 500

**File:** `server/api/admin/models.py:55-80`
**Issue:** 仅校验 items 非空与权重合计；`it["std_name"]`/`it["category"]` 缺失时 KeyError（76 行）、`float(it.get("weight"))` 遇非数字 ValueError（60 行）、gate 非数字 `int()` 抛 ValueError（77 行）——全部未捕获 → 500（未 commit 因连接关闭回滚，数据不坏但接口崩坏）。且 model_json 原样存入 body 全部额外字段。对照 auth/eval 路由族均用 Pydantic 模型，唯此 admin 写入口收裸 dict。

**Fix:** 定义 `ModelItemsPayload(BaseModel)`（items: list[ModelItem]，std_name/category/weight/required_level/importance/gate/years 字段强类型），复用 schemas.py 风格。

### WR-08: `trigger_aggregate` 查询了 position.status 却不检查——pending_review 岗位可被聚合出模型，直接喂出 CR-03 的 FK 崩溃路径

**File:** `server/api/admin/models.py:14-22`
**Issue:** 函数查询 `SELECT status FROM position` 却只判 None；`run_aggregate` 自身（aggregate.py:101-110）同样不查 status。管理员对 pending_review 岗位手动聚合即写入 competency_model 行，此后 reject 该岗位必触发 CR-03 的 FOREIGN KEY constraint failed。这也是状态机治理缺口：pending 岗位不应产生正式模型分叉（自动聚合链在 pipeline.py 里明确只在 active 时触发，手动入口却绕过该判断）。

**Fix:** `if pos["status"] != "active": raise HTTPException(409, "仅上架岗位可触发聚合")`。

### WR-09: `PositionAssess.vue` 的 `loadModel` 无 catch——404/网络错误导致空白页 + 未处理的 Promise rejection

**File:** `web/src/views/assessment/PositionAssess.vue:116-125`
**Issue:** `loading.value = true; try { ... } finally { loading.value = false }` 无 catch。该岗位无 confirmed 模型时后端返回 404（合法业务态，assessment.py:52-53），axios reject → onMounted 链上未处理 rejection，页面主体（表格与「开始测评」按钮，均 `v-if="model"`）永不渲染，用户只看到头部与 loading 关闭后的空白，无任何提示。对照同文件 `onStart` 有完整 catch 分支。

**Fix:**
```javascript
async function loadModel() {
  loading.value = true
  try {
    const { data } = await api.get(`/assessment/positions/${positionId}/model`)
    meta.value = { model_id: data.model_id, version: data.version }
    model.value = data.model
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '加载岗位模型失败')
  } finally {
    loading.value = false
  }
}
```

### WR-10: `get_confirmed_model` 不校验岗位 active——任意登录用户可读未上架岗位的模型明细

**File:** `server/api/assessment.py:43-56`（对照 20-31 行 list 的 `WHERE p.status='active'`）
**Issue:** 按 position_id 直查 confirmed 模型，不 join position 查 status。pending_review/被下架岗位的模型（一个岗位可同时 pending 且有 confirmed 模型——confirm_model 亦不查岗位状态，models.py:86-115）对**任意登录用户**开放阅读。与列表接口的 active 过滤形成授权不一致，泄露未发布岗位的胜任力配置细节（招聘策略情报）。

**Fix:** 查询 join position 并校验 `p.status='active'`，否则 404。

### WR-11: `check_session_readiness` 四个失败分支在 close 前 return——连接释放依赖 CPython 引用计数，模式脆弱且与同模块 try/finally 纪律不一致

**File:** `server/services/readiness.py:51-117`
**Issue:** `conn = get_conn()` 后仅成功路径（116 行）显式 close；58-60、76-77、86-88、112 行四个失败分支提前 return。坦率修正常见误报：CPython 下 `sqlite3.Connection.__del__` 会关闭连接，且函数返回即引用归零，**不构成持续累计的 fd 泄漏**——此前一轮评审若称「每次 409 泄漏一个 fd 直至 too many open files」属高估。真正的问题是：(a) 依赖 GC 释放资源是非确定性契约（备选运行时、异常帧延长生命周期、未来加循环引用即失效）；(b) 同一 PR 内 API/测试均遵守 try/finally close（`_append_task_event`、测试 `_q`），唯独本服务例外；(c) 异常帧持连接窗口内连接可能持有读锁，与其他写事务冲突。

**Fix:**
```python
conn = get_conn()
try:
    # ...原有判断逻辑，各 return 分支不变...
    return None
finally:
    conn.close()
```

### WR-12: `_update_task_status` 的 finished_at CASE 无 ELSE 且取最新行无 tie-break——非终态更新会清空完成时间戳，created_at 并列时定位不确定

**File:** `server/services/question_bank.py:70-80`
**Issue:** `finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED') THEN ? END` 缺 ELSE → 条件不满足时置 NULL（标准 SQL 语义）。当前调用序列（QUEUED→RUNNING→终态）下因无重触发入口而不可达，但 CR-02 修复引入 retry/并发路径后即成为活缺陷：第二次生成的 RUNNING 更新会命中并抹掉已终态行的 finished_at。同为审计字段，started_at 有 `COALESCE` 保护而 finished_at 没有，属不对称疏漏。另 `ORDER BY created_at DESC LIMIT 1` 无 rowid 次级排序键，now_iso() 微秒并列时目标行不确定。

**Fix:** `finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED') THEN ? ELSE finished_at END`，且排序补 `, rowid DESC`（完整语句见 CR-02 修复块的 WHERE 部分）。

### WR-13: eval 虚拟考生工具把占位单选题直接写入生产题库——混入真实候选人的选题池

**File:** `eval/virtual_candidates.py:70-95`（配合 `server/services/question_selection.py:23-28`）
**Issue:** `_get_or_seed_bank` 以 `status='active'`、`scope='position'`、`category='hard_skill'`、`qtype='objective'` 写入 3 道题干为「（虚拟考生造题）请简述 X 的核心概念。」、answer_key 为 fixture 关键词（索引/事务/缓存）的题。该工具经 `/api/admin/eval/virtual-candidates`（admin/eval.py:65-74）跑在主库上，而 `select_questions_for_session` 按同一 WHERE 口径取 active 题且**不区分 source**——这些占位题（评分恒按"索引"等关键词命中，5 分制形同虚设）会进入后续真实候选人的 hard_skill 配额（6 题），既污染测评数据也拉低题库质量。

**Fix:** 造题用 `status='eval_seed'` 之类的隔离态（需同步放宽 question_selection/readiness 口径）或 `scope` 独立值；或最低限度给 stem 前缀打标并在选题 WHERE 排除 `source='human' AND stem LIKE '（虚拟考生造题）%'`——推荐前者，语义干净。

### WR-14: answer_key 直接作正则、评分无输入上限——慢性 ReDoS 与误匹配风险

**File:** `server/services/scoring.py:21-24`（输入来自 `server/services/question_bank.py:139` 存的 LLM/人工 key）
**Issue:** `re.search(answer_key, answer)` 将 answer_key 当正则编译，无超时、无长度限制；answer 为候选人自由文本。`re.error` 时退化子串（正确），但合法且病态的模式（如嵌套量词 `(a+)+$`）配合攻击者构造的长回答可造成灾难性回溯，挂起线程池内的执行线程。另外 LLM 生成的 key 含未转义正则元字符时会静默改变匹配语义（如 "C+" 匹配任何含 C 的回答）而非报错。

**Fix:** 优先 `re.escape` 关键词式 key，仅对显式声明为正则的 key 走 `re.search`；并对 answer 截断（如 64KB）+ `re.search` 前限制 key 长度，必要时 `signal.setitimer` 超时防护（单线程场景）或改用 `regex` 库的 timeout 参数。

### WR-15: 「最新 confirmed 版」口径在 `list_assessable_positions` 与 `create_session` 双实现——JOIN 全版本 + Python 去重的排序随 version 漂移

**File:** `server/api/assessment.py:20-40` 对照 71-77
**Issue:** 列表接口 JOIN 所有 confirmed 行按 `m.version DESC` 排序再 Python seen 去重保首见：功能正确，但 (a) 岗位展示顺序 = 各岗位最新版本号的全局降序，随 re-aggregate 漂移，与业务排序无关；(b) 同一口径在 create_session 内另一份实现，两处各持一份查询，未来改一处漏一处（本阶段 readiness 注释已显式意识到口径漂移问题，却仍留下这一处）。

**Fix:** SQL 相关子查询取每岗位 MAX(version)：`WHERE m.status='confirmed' AND m.version=(SELECT MAX(version) FROM competency_model m2 WHERE m2.position_id=m.position_id AND m2.status='confirmed')`，外层 `ORDER BY p.created_at DESC`；create_session 复用同一查询函数。

---

## Info

### IN-01: `_ensure_eval_user` 直插非 bcrypt 占位密码哈希

**File:** `eval/virtual_candidates.py:150-159`
**Issue:** `password_hash="eval_placeholder"` 写入主库 user 表。真实用户以该用户名登录时 `verify_password` 对非 bcrypt 格式的行为依 passlib 版本而定（多数 False，某些版本抛异常 → 500）。
**Fix:** `hash_password(os.urandom(24).hex())`。

### IN-02: `PositionAssess.vue` 死分支：501 提示与 `data.id` 兜底

**File:** `web/src/views/assessment/PositionAssess.vue:132-136`
**Issue:** 后端 assessment 路由族已全部实现，`e.response?.status === 501`（「测评功能尚未上线」）不可达；`data.session_id || data.id` 的 `data.id` 兜底无对应后端契约。
**Fix:** 删除两条死路径。

### IN-03: `pct()` 对 >1 的权重静默按原值显示

**File:** `web/src/views/assessment/PositionAssess.vue:163-168`
**Issue:** `n <= 1 ? (n*100).toFixed(0) : n.toFixed(0)` 把脏数据 1.5 显示成 "150" 无任何标记（Σ=100% 只在保存时校验）。
**Fix:** `if (!(n >= 0 && n <= 1)) return '—'`。

### IN-04: `score_session` 返回的 scored_count 语义与实际落库行数不符

**File:** `server/services/scoring.py:144-151,162`
**Issue:** item 匹配失败的题被 `continue` 跳过不入分表，但返回值 `scored_count = len(answered)` 仍按已答题数计——POST /score 响应字段名与值不一致，监控/消费方据此统计会偏高。
**Fix:** 返回 `len(pending_rows)`，另加 `skipped_count`，或改名 `answered_count`。

### IN-05: `run_virtual_candidate` 全仓库无调用方

**File:** `eval/virtual_candidates.py:143-147`
**Issue:** 对外入口注释齐全但 admin/eval.py 只调 `test_virtual_candidates`，CLI main 也走三档函数。死代码（若为未来 API 预留，应注明）。
**Fix:** 删除或接通 `/api/admin/eval/virtual-candidates` 的单档模式。

### IN-06: `get_current_model` 的优先级 CASE 用 ELSE 隐式承载 confirmed

**File:** `server/api/admin/models.py:29-33`
**Issue:** `CASE status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END`——当前 CHECK 三值下正确，未来加第四状态会静默落入 2 与 confirmed 混排。
**Fix:** 显式 `WHEN 'confirmed' THEN 2`。

### IN-07: `diff_models` 路由参数 `new_id` 与 update_model 内局部 import 的 `new_id` 同名异义

**File:** `server/api/admin/models.py:153-154`（对照 70 行）
**Issue:** 作用域不同，无运行时 bug；但同名异义降低可读性，若有人将局部 import 提升到模块级即遮蔽路由参数。
**Fix:** 路由参数改名 `new_model_id`。

### IN-08: 四个测试文件在同进程跑整个 pytest 时共享首个 import 的 DB_PATH——「单文件单进程」只是口头纪律

**File:** `server/test_m5_backend.py:11-14`、`server/test_p0_chain.py:30-34`、`server/test_p0_security.py:15-19`
**Issue:** 各文件在 import 时设 `os.environ["DB_PATH"]`，但 `config.DB_PATH` 在 `server.config` 首次 import 时固化。`cd server && pytest`（不带文件名）时按收集顺序 m5 先绑定其临时库，p0_chain/p0_security 的 env 覆写失效、实际与 m5 共库。当前各测试用 `new_id` 新种子隔离所以碰巧全绿，但「DB 用临时文件，不碰 data/app.db」的前提在整体跑测时静默破产；若未来某个断言做全局计数（如 todos 精确值）即翻红。
**Fix:** conftest.py 统一管理 per-session 临时库；或各文件改用 `tmp_path` fixture + 模块级 `init_db`。

### IN-09: `append_event` 的 MAX+1 取号在并发同事务下靠 UNIQUE 兜底，代价是未捕获 IntegrityError → 500

**File:** `server/services/state_events.py:36-48`
**Issue:** 注释已自述（「SQLite 单写者下安全，UNIQUE 为并发兜底」）：两个并发事务同 session 同时取号得相同 sequence_no 时，后者 INSERT 抛 sqlite3.IntegrityError，事务整体回滚（快照更新一并丢失）、API 返回 500 且无 catch。单候选人单会话的产品假设下低概率，一致性防住了，属知悉项而非必修。
**Fix:** 若要根治：捕获 IntegrityError 重试取号一次；或全局写锁串行化 append_event。

---

### 跨计划 seam 总结（供 orchestrator 与 fixer 排期参考）

1. **readiness ↔ report 409 契约**（WR-01）：前端 fallback 当前抹平差异，契约债务留在后端。
2. **题库生成链 ↔ readiness ↔ todos**（CR-02 + WR-03/WR-04/WR-12）：confirm→generate→task 三态→readiness→todos 是一条贯穿四个计划的链，任何一环（插行失败/LLM 失败/幂等跳过）造成的 FAILED 都没有恢复入口，构成同一根因的四种表现，建议一次性补 retry 路由 + 事务化插入 + 粒度修正 + CASE ELSE。
3. **P1 岗位库 ↔ 01-04 新表 FK**（CR-03 + WR-08）：trigger_aggregate 不查 status 使 pending 岗位产生模型，reject 的 DELETE 因此炸 FK——两个独立缺陷互为放大器。
4. **评分正确性**（CR-01 + WR-14）：answer_key 从 LLM 输出直通正则引擎，入库无校验、判分无防护；现有 mock 与种子全部自带合法 key，测试对该路径零覆盖。
5. **安全面**：IDOR 修复本身无绕过（request_report 走 load_owned_session 写路径、读路由带 allow_admin_read 全部经 load_owned_report）；剩余风险是 CR-05（默认密钥）、WR-05（存在性 oracle）、WR-10（非 active 岗位模型可读）、WR-13（eval 污染题库）。
6. **状态事件事务纪律**：SESSION_CREATED 与 INSERT 同事务、QUESTION_ANSWERED/SESSION_COMPLETED 与快照 UPDATE 同事务、TASK_* 独立小事务，均验证合规；唯一缝隙是 IN-09 的并发 500。

---

_Reviewed: 2026-09-03T08:05:12Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
