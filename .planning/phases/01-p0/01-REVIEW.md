---
phase: 01-p0
reviewed: 2026-09-03T12:00:00Z
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
  critical: 4
  warning: 7
  info: 6
  total: 17
status: issues_found
---

# Phase 01 (p0): Code Review Report

**Reviewed:** 2026-09-03T12:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

审查了 Phase 01（p0）四个计划的串行实现：候选人资源所有权检查（IDOR 修复）、assessment_state_event append-only 审计链、score→report 服务端串行链与 completed 护栏、开考前可测量性检查 gate + question_bank_task 表。

主要结论：IDOR 修复本身（load_owned_session / load_owned_report）实现扎实——读写路由全覆盖、404 语义统一、admin 读豁免/写拒绝一致、owner 判定优先（Pitfall 10）；串行链三分支裁决（B-1）与事件 append-only 触发器按计划落地；测试矩阵对护栏和越权路径覆盖充分。但发现 4 个 Critical：题库生成失败后无任何重触发入口（confirm 已 409、全仓库无 retry 路由），FAILED/题库不足的岗位被 readiness gate 永久锁死，与 D-12「可手动重触发」契约直接断裂；`check_session_readiness` 全部失败分支泄漏数据库连接；`_update_task_status` 的 `finished_at` CASE 无 ELSE 会静默清空已有完成时间；`review_position` reject 在 FK 开启下遇子表数据即未捕获 IntegrityError → 500。另有 7 个 Warning（409 错误体契约不一致、answer falsy 校验、task 行插入非原子、幂等粒度太粗、by-session 404 文案存在性 oracle、feedback item 校验缺口、岗位列表排序漂移）。

---

## Structural Findings (fallow)

无（本阶段无 structural_findings 载荷）。

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: 题库生成失败后无任何重触发入口，岗位被 readiness gate 永久锁死（与 D-12「可手动重触发」契约断裂）

**File:** `server/services/question_bank.py:83-151`（配合 `server/api/admin/models.py:93-115`、`server/services/readiness.py:79-91`）
**Issue:** 题库生成唯一入口是 confirm_model 插入 QUEUED task 行后 `background.add_task(generate_question_bank, ...)`。任务失败置 FAILED 不抛（设计如此），readiness 判定链：task 行 QUEUED/RUNNING → GENERATING；配额/required 覆盖不足 → INCOMPLETE。问题在于**失败后的恢复路径不存在**：
- 再次 confirm 同一模型 → 409「模型已确认」（models.py:93-94）；
- 全仓库（grep 验证）除 `confirm_model` 与测试外**没有任何路由再次调用 `generate_question_bank` 或插入新 task 行**；
- `_update_task_status` 只更新既有行，不新建行。

于是「FAILED + 题库不足」形成死局：readiness 永远返回 QUESTION_BANK_INCOMPLETE → 岗位开考 409；`GET /api/admin/todos` 的 `question_bank_not_ready` 永远非零（positions.py:25-27 按 `status != 'SUCCEEDED'` 计数，FAILED 无法消除）；管理员唯一出路是绕过 API 手动改库。代码注释多处声称「失败不抛（可手动重触发）」（question_bank.py:84）、「FAILED → INCOMPLETE（失败细节 Phase 4 REF-8.4 再做）」（readiness.py:89-90），但重触发入口在交付范围内不存在——这是实现与契约断裂，也是 01-04（readiness）与上游生成链之间最尖锐的 seam。

附带缺陷：`_update_task_status` 的 `ORDER BY created_at DESC LIMIT 1` 无 rowid tie-break，`now_iso()` 微秒精度下两行 created_at 并列时会命中错误行。

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
    return {"task_id": task_id, "requeued": True}
```
同时 question_bank.py:76-77 的 `ORDER BY created_at DESC` 加 `, rowid DESC`。

### CR-02: `check_session_readiness` 所有失败分支都不关闭连接——每次被 409 拒绝的开考请求泄漏一个 SQLite 连接

**File:** `server/services/readiness.py:51-117`
**Issue:** 第 51 行 `conn = get_conn()`，只有第 116 行成功路径 `return None` 前有 `conn.close()`；四个失败分支（58-60 岗位非 active、76-77 items 空、86-88 GENERATING、112 INCOMPLETE）全部在 close 前 return，连接永不释放。`get_conn()`（db.py:269-274）无连接池、无释放钩子；codebase 惯例是显式 close（同 PR 内 test 文件 `_q` 均 try/finally close）。每次 POST /api/assessment/sessions 被 readiness 拒绝即泄漏一个文件描述符，uvicorn 长运行下累积到 `too many open files`，**整个服务**（登录、JD 导入、答题等）拒绝服务——不止影响开考路径。

**Fix:**
```python
def check_session_readiness(position_id: str) -> dict | None:
    conn = get_conn()
    try:
        # ...原有全部判断逻辑，各 return 原样保留...
        return None
    finally:
        conn.close()
```

### CR-03: `_update_task_status` 的 `finished_at` CASE 无 ELSE——非终态更新会把已有完成/失败时间戳静默清空

**File:** `server/services/question_bank.py:70-80`
**Issue:** SQL 片段：
```sql
finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED') THEN ? END
```
`CASE WHEN ... THEN ... END` 无 ELSE 时条件不满足返回 **NULL**。当前调用序列（QUEUED→RUNNING→SUCCEEDED/FAILED）多数情况无感（初始为 NULL），但对**已终态行**的任何后续更新都会把 finished_at 从真实时间清成 NULL。且 `_update_task_status` 按 (position_id, model_id) 定位「最新行」而不感知其当前状态，一旦同一 (position, model) 出现第二次生成（CR-01 修复后即存在此路径），RUNNING 更新会命中/误命中已终态行并抹掉完成时间。question_bank_task 是 D-12 声明的三态可查审计载体，完成时间是核心审计字段。对照同一语句中 `started_at` 用 `COALESCE(started_at, ...)` 保护旧值，`finished_at` 缺少同等的 `ELSE finished_at` 保护是明显的不对称疏漏。

**Fix:**
```python
conn.execute(
    "UPDATE question_bank_task SET status=?,"
    " started_at=COALESCE(started_at, CASE WHEN ?='RUNNING' THEN ? END),"
    " finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED') THEN ? ELSE finished_at END,"
    " error_msg=?"
    " WHERE task_id=(SELECT task_id FROM question_bank_task"
    "  WHERE position_id=? AND model_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1)",
    (task_status, task_status, now_iso(), task_status, now_iso(), error_msg,
     position_id, model_id),
)
```

### CR-04: `review_position` reject 分支直接 DELETE position——FK 开启下子表有行即抛未捕获 IntegrityError → 500

**File:** `server/api/admin/positions.py:63-69`（配合 `server/db.py:273` `PRAGMA foreign_keys = ON`）
**Issue:** reject 分支清理 jd_record（归 NULL）和 position_alias（删除）后 `DELETE FROM position`。但 competency_model.position_id、question_bank.position_id、**question_bank_task.position_id（01-04 新表）**、assessment_session.position_id 均 REFERENCES position，且每连接开启外键。真实触发路径：
- 管理员对 pending_review 岗位手动 `POST /positions/{position_id}/aggregate`（models.py:15-22 **无 position status 检查**）→ 产生 competency_model 行 → 此后 reject 必触发 FOREIGN KEY constraint failed；
- 01-04 的 question_bank_task 存在任何历史行（含 QUEUED/FAILED/SUCCEEDED）→ 同样失败；
- 会话已创建 → assessment_session 同样失败。

sqlite3.IntegrityError 未捕获 → 500，无全局异常处理器转友好错误。这是 P1 岗位库与 01-04 新表之间的 FK seam，也是四个计划交叉的风险点。

**Fix:** reject 前检查子表占用并给出可解释的 409：
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

---

## Warnings

### WR-01: 跨计划 seam：readiness 409 返回 dict detail、report/score 409 返回 string detail——错误体契约不统一

**File:** `server/api/assessment.py:80-84` 对照 `server/api/assessment.py:313-319` 与 `web/src/views/assessment/PositionAssess.vue:137-143`
**Issue:** readiness 拒绝时 `detail={"error_code": ..., "message": ...}`（结构化），report 的两个 409 分支 `detail="会话未完成，不能请求报告"` / `"报告已生成，不允许重复报告"`（纯字符串）。前端 `detail?.message || detail || '...'` 对两种形态都能取到文案（string 的 `.message` 是 undefined，短路到 detail 本身）——功能正确，但这正是任务提示点名的跨计划 seam：同一 assessment 路由族两种 detail 形态，任何新消费方（Chat.vue / Report.vue）若只按一种形态写处理逻辑就会对另一种显示 `[object Object]` 或空文案。error_code 可编程契约只覆盖 readiness 三态，report/score 的 409 无 error_code。

**Fix:** 统一 409 body 为 `detail={"error_code": ..., "message": ...}`（如 `SESSION_NOT_COMPLETED` / `REPORT_ALREADY_EXISTS`），前端保留 fallback 兼容层；或抽共享 `http_error(error_code, message)` 工厂。

### WR-02: `submit_answer` 的 `answer` 校验 `not answer` 不 strip——纯空格串过检，与同文件 `submit_feedback` 的 `.strip()` 模式不一致

**File:** `server/api/assessment.py:143-145`（对照 355-357 行）
**Issue:** `if not question_id or not answer:` 只拒绝 falsy，`"   "` 通过校验进入精炼与 decide_next_action（mock 下 len<20 触发 followup 勉强兜底；真实 LLM 模式无字符数护栏，纯空格作为正式回答落库并参与评分）。同文件 submit_feedback 用 `.get("feedback_text", "").strip()` 再判空——同为候选人自由文本入口两处校验语义不一致。

**Fix:**
```python
raw_answer = body.get("answer")
answer = raw_answer.strip() if isinstance(raw_answer, str) else ""
if not question_id or not answer:
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "缺少 question_id 或 answer")
```

### WR-03: `confirm_model` 的 task 行插入在 confirm 主事务之外且失败无补偿——插行失败时模型已 confirmed 但题库永不生成（叠加 CR-01 无重试即锁死）

**File:** `server/api/admin/models.py:98-115`
**Issue:** 顺序为 UPDATE confirmed → commit → INSERT task QUEUED → commit → add_task。104-105 行注释声明这是有意设计（自身小事务先落库），但插行失败（磁盘满、DB busy）时已 commit 的 confirmed 不回滚、add_task 不执行，岗位进入「confirmed 但无 task 行」状态：readiness 第 3 项查不到 task 行 → 落到第 4/5 项按实际题量判定 → 题库为空 → INCOMPLETE → 永久锁死（无重试入口，见 CR-01）。并发双 confirm 第二次会 409，这一点安全；「插行失败窗口」低概率但后果不可恢复。

**Fix:** 把 task 行 INSERT 合并进 confirm 同一事务（`UPDATE ... SET status='confirmed'` 后、commit 前插入），保证 confirmed ⇔ QUEUED 行原子共存；注释中「三态仍真实可查」诉求不受影响（后台任务异常仍会更新行）。

### WR-04: `generate_question_bank` 幂等粒度太粗——item 部分成功后任何重触发都会跳过该 item，残缺链条永不补齐

**File:** `server/services/question_bank.py:110-124, 126-141`
**Issue:** 幂等条件为「该 (scope, position_id, std_name, category) 存在任一 active 题即跳过整个 item」。场景：plan 为 easy/medium/hard 3 题，首轮 LLM 对 easy 成功、medium 异常 → task FAILED，题库已有 1 题。重触发（CR-01 修复后即有该路径）时该 item 因「存在 active 题」被**整体跳过**，medium/hard 永久缺失；readiness 第 5 项按配额计数（hard 需 6），残缺岗位持续 INCOMPLETE。幂等保护本意防重复生成，粒度粗到无法区分「完整生成过」与「部分生成过」。

**Fix:** 幂等检查对比实际题数与 plan 目标（按 (std_name, category, difficulty) 计数），缺口补生成；或 FAILED 任务的 retry 语义中先删除该 item 未完成链的残留行。

### WR-05: `get_report_by_session` 第一步查询不带 ownership，两个 404 文案不同——任意登录用户可探测任意 session_id 是否已生成报告（存在性 oracle）

**File:** `server/api/assessment.py:329-340`
**Issue:** 第一步 `SELECT report_id FROM report WHERE session_id=?` 无所有权过滤：report 不存在 → 404「报告尚未生成」；report 存在但会话属他人 → load_owned_report → 404「报告不存在」。两处文案不同，持 token 用户可通过文案差异区分「该 session_id 从未生成报告」与「已生成（但可能是别人的）」——对-IDOR 设计（load_owned_* 统一 404，D-01）被第一步的非所有权查询和文案差异弱化。泄露信息量小（仅报告存在性），但与统一不存在语义的目标相悖。

**Fix:** 第一步查询 join assessment_session 限定 user_id；或两处 404 统一文案「报告不存在或无权访问」。

### WR-06: `submit_feedback` 的 item_id 只做全局存在性校验——不校验 item 属于该 report 会话锚定的模型，可挂入无关模型 item

**File:** `server/api/assessment.py:359-362`
**Issue:** `SELECT 1 FROM competency_item WHERE item_id=?` 是全表校验。owner 可对「岗位 A 的报告」提交「岗位 B 模型的 item_id」，feedback 行插入成功（feedback.item_id 只 REFERENCES competency_item 整表，FK 不拦）。后续 07 §11 ② 反馈回溯流按 report→item 追溯评分依据会拿到与本报告无关的 item，数据完整性破坏。

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

### WR-07: `list_assessable_positions` JOIN 全部 confirmed 版本再 Python 去重——岗位顺序随版本号漂移，且「最新 confirmed」口径与 create_session 双实现

**File:** `server/api/assessment.py:20-40`
**Issue:** 查询 JOIN 所有 confirmed 模型行，`ORDER BY m.version DESC` 后 Python 端 seen 去重保首见。功能正确（每岗位留最高 version），但：(a) 岗位展示顺序 = 最新版本号的全局降序，与业务排序无关，随 re-aggregate 漂移；(b) create_session 内部另行实现「最新 confirmed 版本」查询（71-77 行），两个入口各持一份口径，未来一处改另一处易不同步。

**Fix:** SQL 层取每岗位最新版（相关子查询 `WHERE m.version=(SELECT MAX(version) FROM competency_model m2 WHERE m2.position_id=m.position_id AND m2.status='confirmed')`），外层 `ORDER BY p.created_at DESC`。

---

## Info

### IN-01: `eval/virtual_candidates.py` 占位密码 "eval_placeholder" 非合法 bcrypt 哈希——真实 eval 用户走登录路径行为未定义

**File:** `eval/virtual_candidates.py:150-159`
**Issue:** `_ensure_eval_user` 直插 `password_hash="eval_placeholder"`，写进生产同库的 user 表。若有人用该用户名登录，`verify_password` 对非 bcrypt 格式的行为取决于 passlib 版本（多为 False，某些版本抛异常 → 500）。

**Fix:** `password_hash=hash_password(os.urandom(24).hex())`。

### IN-02: `get_current_model` 的 priority CASE 用 ELSE 承载 confirmed——显式列举更稳

**File:** `server/api/admin/models.py:27-33`
**Issue:** `CASE status WHEN 'stalled' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END`，当前 CHECK 只有三值所以 ELSE==confirmed，正确；未来加第四状态会静默落入 priority 2 与 confirmed 混排。

**Fix:** 改为 `WHEN 'confirmed' THEN 2` 保持显式。

### IN-03: `diff_models` 路由参数 `new_id` 与 update_model 函数内 import 的 `new_id` 同名异义

**File:** `server/api/admin/models.py:153-154`（对照 70 行）
**Issue:** 作用域不同（函数内 import 仅 update_model 内生效），无运行时 bug；但同文件同名异义降低可读性，若有人把 import 提升到模块级即炸。

**Fix:** 路由参数改名 `new_model_id`。

### IN-04: `test_p0_chain.py` admin 密码 "admin"，与 `test_p0_security.py` 的 `_ensure_admin` 双份维护且口径不一

**File:** `server/test_p0_chain.py:287-299`
**Issue:** 两文件各自复制 `_ensure_admin`（admin/admin vs p0_admin/admin123456）。「单文件单进程纪律」是文件头显式决策，临时库无风险，仅记录维护成本。

**Fix:** 无需改动；后续可 conftest 化。

### IN-05: `test_m6_backend.py` 直调 `submit_feedback` 绕过 Depends 链——路由层鉴权依赖 p0_security 矩阵补齐

**File:** `server/test_m6_backend.py:261-281`
**Issue:** 手工构造 user dict 直调，验证函数体而非路由鉴权。p0_security 已有 API 层反馈越权矩阵，此处仅提示分工明确。

**Fix:** 无需改动。

### IN-06: `PositionAssess.vue` 的 `pct()` 对 n>1 静默显示数值——越界权重显示为 150 无任何标记

**File:** `web/src/views/assessment/PositionAssess.vue:164-168`
**Issue:** Σ=100% 校验在保存时执行，但单项>1 的脏数据在展示层无防御，`n <= 1 ? ... : n.toFixed(0)` 会静默显示 150。

**Fix:** `if (!(n >= 0 && n <= 1)) return '—'`。

---

### 跨计划 seam 总结（供 orchestrator 参考）

1. **readiness 409 vs report 409**：detail 形态 dict vs string 不一致（WR-01），PositionAssess.vue 的 fallback 链当前抹平了表现层差异，但契约债务已在。
2. **ownership helper vs 新路由**：request_report（串行链新入口）正确走 `load_owned_session`（写路径无 allow_admin_read → admin 404）；get_report/get_report_by_session 走 `load_owned_report`（读豁免）——**无新路由绕过所有权链**；唯 by-session 两步查询的 404 文案差异弱化了统一 404 语义（WR-05）。
3. **state-event 写入 vs 护栏路径**：SESSION_CREATED 与 INSERT 同事务（assessment.py:102-105）✔；QUESTION_ANSWERED / SESSION_COMPLETED 与快照 UPDATE 同事务（196-206）✔；TASK_QUEUED 请求级连接独立 commit 后 add_task（320-325）✔；TASK_STARTED/SUCCEEDED/FAILED 后台任务独立小事务（262-299）✔。**未覆盖缝隙**：`_generate_report_task` 内 `score_session(allow_completed=True)` 与 `generate_report` 之间无互锁——若 B-1 分支 c 的重试与首次后台任务并发（罕见），report 表 DELETE+INSERT 覆盖写竞态下有短暂 0 行窗口，轮询端会得到误导性 404；低概率，记为知悉。
4. **question_bank_task FK vs review_position reject**（CR-04）与 **FAILED task 行 vs todos 计数永久非零**（CR-01）：01-04 新表与 P1 岗位库双向 seam，管理员操作会遇到 500 或不可消除的待办数。
5. **append_event 并发取号**：同事务 SELECT MAX+1 在两个并发事务同时取号时拿到相同 sequence_no，UNIQUE(session_id, sequence_no) 触发 IntegrityError 使整个事务（含快照更新）回滚——数据一致性防住了，代价是并发同 session 答题时第二个请求 500（无 catch）。单候选人单会话场景可接受，知悉即可。

---

_Reviewed: 2026-09-03T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
