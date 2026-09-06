---
phase: 04-question-bank-version
reviewed: 2026-09-05T10:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - server/api/admin/jds.py
  - server/api/admin/models.py
  - server/api/admin/positions.py
  - server/services/question_bank.py
  - server/services/question_selection.py
  - server/services/readiness.py
  - server/test_phase2_selection.py
  - server/test_phase4_binding.py
  - server/test_phase4_fail_visible.py
  - server/test_phase4_model_edit.py
  - server/test_phase4_orphan.py
findings:
  critical: 0
  warning: 6
  info: 6
  total: 12
status: issues_found
---

# Phase 4：代码评审报告

**Reviewed:** 2026-09-05T10:00:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## 摘要

本轮评审 Phase 4 的核心改动：题库落库绑定 confirmed 模型版本（`model_id`/`model_version`/`item_id`/`rubric_version='v1'`），消费侧 `readiness`/`selection` 强制 `model_id + model_version` 匹配，以及模块一管理端收口（`/jds/orphan` 路由顺序修复 + `ModelItem` 字段级校验）。

**正向确认：**
- SQL 注入面：本 phase 全部为参数化查询（`?` 占位符），未发现字符串拼接/格式化进 SQL 的新注入面。
- 路由声明序：`/jds/orphan`（`jds.py:79`）确实先于 `/jds/{jd_id}`（`jds.py:90`），修复正确，`test_phase4_orphan.py` 有对应断言。
- Pydantic v2 校验：`weight`/`years` 的 `allow_inf_nan=False` + `ge=0/le=1`、`importance` 的 `Literal`、`required_level` 的 `ge=1,le=5` 均已实际生效（`NaN` 由 `ge=0` 兜底拒绝，`inf` 由 `allow_inf_nan=False` 拒绝）。
- 判重键升级：落库判重含 `model_id + model_version + std_name + category + difficulty`，v2 生成不因 v1 active 行跳过（`test_phase4_binding.py` 覆盖）。

但发现 **6 个 warning**（其中 2 个为真实逻辑缺陷：readiness 配额缺口判定恒为 False、todos 未按「最新 task 行」口径导致重试成功后仍误报未就绪）与 6 个 info 级质量项。无 critical 级（未发现越权绕过、注入或不可恢复数据丢失）。

---

## Warnings

### WR-01：readiness 配额缺口判定恒为 False，「配额可行」检查失效

**File:** `server/services/readiness.py:161-167`
**Issue:** 第 5 步「配额可行」的缺口判定条件恒不成立，导致题库题量不足时 readiness 仍放行开考，会话会在不足 N 题时提前 finish。

`have`（来自 `_question_count_by_category` 的该类目总题数）与 `sum(available[category].values())`（tier 分组计数之和）来自**同一 WHERE 口径**，二者恒相等；而 `target_total` 来自 `plan_quotas`，其内部 `tier_targets` 已按可用量 clamp，故 `target_total ≤ sum(available)` 恒成立。因此：

```python
if have < min(target_total, sum(available[category].values())):
```

即 `have < min(target_total, have)`，因 `min(target_total, have) ≤ have`，恒为 False。示例：N=10，hard 可用 4 题、soft 可用 3 题，`required` 项均各有一题覆盖（`missing_required` 为空），此时配额本应不足（hard 需 7），但该判定不触发 → readiness 返回 `None` 放行。

**Fix:** 用未 clamp 的原始大类配额（`largest_remainder_73` 的 `hard_n/soft_n`）对比实际题量，而不是用 clamp 后的 `target_total` 自比。例如：

```python
raw_hard, raw_soft = largest_remainder_73(n)
required_quota = {"hard_skill": raw_hard, "soft_skill": raw_soft}
for category, target in required_quota.items():
    if category not in needed_categories:
        continue
    have = counts.get(category, 0)
    if have < target:
        gaps.append(f"{category} {have}/{target}")
```

（需同步 import `largest_remainder_73`。）

---

### WR-02：todos 未按「最新 task 行」口径，重试成功后仍误报未就绪/失败

**File:** `server/api/admin/positions.py:25-34`
**Issue:** `question_bank_not_ready` 统计 `status != 'SUCCEEDED'` 的**所有** task 行，`question_bank_failed` 列出**所有** `status='FAILED'` 行。但 `retry_question_bank_task`（`models.py:162-192`）明确「保留旧 FAILED 行作审计」并新增 QUEUED 行，重试成功后旧 FAILED 行仍在。结果是：重试已成功的岗位仍被计入 `question_bank_not_ready`，并继续出现在 `question_bank_failed` 明细里——与 `readiness.py`（`ORDER BY created_at DESC LIMIT 1` 取最新行）以及 retry 文档「最新行判定口径即 D-12」自相矛盾。

**Fix:** 两个查询都改为按 `(position_id, model_id, model_version)` 取最新行后再判定，例如：

```sql
-- not_ready：最新行非 SUCCEEDED 的岗位数
SELECT COUNT(*) c FROM (
  SELECT position_id, status,
         ROW_NUMBER() OVER (PARTITION BY position_id, model_id, model_version
                            ORDER BY created_at DESC, rowid DESC) rn
  FROM question_bank_task
) WHERE rn=1 AND status != 'SUCCEEDED'
```

SQLite 版本若 < 3.25 不支持窗口函数，可用「EXISTS 自身无更新行」等价写法；`question_bank_failed` 同理只取 `rn=1 AND status='FAILED'`（审计旧行可由单独接口按需暴露，勿混入「当前状态」口径）。

---

### WR-03：readiness 失败详情把内部 `error_msg` 泄露给考生端

**File:** `server/services/readiness.py:108-112`（来源 `server/services/question_bank.py:189`）
**Issue:** FAILED 分支将 `task["error_msg"]`（即 `generate_question_bank` 里 `str(e)[:200]`）拼进 `detail` 返回。`check_session_readiness` 在 `create_session` 预检阶段由**普通考生**触发（非仅管理员），异常原文可能包含 LLM provider 报错、内部文件路径、prompt 片段等内部信息，构成对未授权用户的信息泄露（ASVS V7.4.1）。

**Fix:** 面向考生仅返回固定文案，去掉 `error_msg` 拼接；内部细节保留在管理员侧的 `todos.question_bank_failed` 明细：

```python
if task is not None and task["status"] == "FAILED":
    return {"error_code": "QUESTION_BANK_INCOMPLETE",
            "detail": "该岗位题库生成失败，不可开考"}
```

---

### WR-04：PUT /models/{id} 会丢弃 model_json 中的 position_id/version 元数据

**File:** `server/api/admin/models.py:32-34, 106-109`
**Issue:** `ModelUpdateBody` 仅声明 `items`，Pydantic v2 默认 `extra='ignore'`，因此前端提交的 `position_id`/`version`/`stall_reason` 等元数据在解析期被静默丢弃；`stored = body.model_dump()` 只产出 `{"items": [...]}`。这与 docstring「position_id/version 由 GET 下发、编辑时原样透传、存库合并保留」的承诺不符，且 `stored.pop("stall_reason", None)` 成为空操作。编辑后 `GET /model` 返回的 `model` 对象将缺失 `position_id`/`version`，前端若依赖这些字段做回显/透传会失效。

**Fix:** 显式保留非 items 元数据（最稳妥是从库内读旧 `model_json` 合并）：

```python
existing = json.loads(conn.execute(
    "SELECT model_json FROM competency_model WHERE model_id=?", (model_id,)
).fetchone()["model_json"])
existing["items"] = body.model_dump()["items"]
existing.pop("stall_reason", None)
stored = existing
```

（或给 `ModelUpdateBody` 设 `model_config = ConfigDict(extra="allow")`，但需确认不会把前端任意垃圾字段一并落库。）

---

### WR-05：generate_question_bank 从不关闭数据库连接

**File:** `server/services/question_bank.py:97`
**Issue:** `generate_question_bank` 直接 `conn = get_conn()`，全程无 `try/finally: conn.close()`（对比 `question_selection.select_next_question` 与 `readiness.check_session_readiness` 均显式 close，且 `readiness.py` 的 WR-11 注释明确「不依赖 CPython 引用计数释放连接」）。该函数作为后台任务反复触发（含 retry 路径），连接泄漏会逐步累积，最终耗尽连接池。

**Fix:** 用 `try/finally` 包裹：

```python
conn = get_conn()
try:
    ...  # 现有逻辑
finally:
    conn.close()
```

---

### WR-06：objective 降级 subjective 时未提供 rubric 兜底

**File:** `server/services/question_bank.py:167-174`
**Issue:** CR-01 修复将「缺 `answer_key` 的 objective 题」降级为 subjective，注释声称「rubric 兜底」，但代码仅 `rubric=q.get("rubric")` 直接透传——当 LLM 返回 objective 且 `answer_key` 与 `rubric` 均为空时，降级后的主观题 `rubric=None` 落库。后续主观题评分依赖 rubric 时会缺判据。mock 路径（`_mock_question_gen` 恒给 objective 填 `answer_key`）永远走不到此分支，故测试未覆盖该真实缺口。

**Fix:** 降级时补默认 rubric：

```python
if q_qtype == "objective" and not (q_answer_key or "").strip():
    q_qtype = "subjective"
    q_answer_key = None
    if not (q.get("rubric") or "").strip():
        q["rubric"] = f"能结合实例说明{item['std_name']}的应用；思路清晰；有结果数据"
```

---

## Info

### IN-01：positions.py 存在未使用的 import

**File:** `server/api/admin/positions.py:6`
**Issue:** `new_id`、`now_iso` 自 `...services.pipeline` 导入，但本文件所有函数均未使用。
**Fix:** 删除该行 import（仅保留实际用到的）。

### IN-02：NaN/Inf 的 HTTP 提交返回 500 而非 422

**File:** `server/api/admin/models.py:22`（行为见 `test_phase4_model_edit.py:217-232` 注释）
**Issue:** 校验本身生效（数据被拒绝且不落库），但当 JSON body 含 `NaN`/`Infinity` 字面量时，Pydantic 抛 422 后 Starlette `JSONResponse(allow_nan=False)` 无法序列化错误详情里的 input 值，最终对客户端表现为 500。状态码误导运维，且属可控的健壮性缺口。
**Fix:** 注册自定义 RequestValidationError 异常处理器，用 `math.isfinite` 过滤/脱敏错误详情中的非有限浮点后再返回 422。

### IN-03：ModelItem 使用可变默认值 `{}` / `[]`

**File:** `server/api/admin/models.py:28-29`
**Issue:** `occurrence: dict = {}`、`evidence: list = []`。Pydantic v2 会逐实例深拷贝默认值，故当前无实际 bug，但属易误导读者的反模式。
**Fix:** 改用 `Field(default_factory=dict)` / `Field(default_factory=list)`。

### IN-04：判重与 chain 判定中的死分支/无效代码

**File:** `server/services/question_bank.py:129-159`、`server/services/question_selection.py:545-555`
**Issue:** `_question_plan` 决定 position 题难度恒非 None、general 题难度恒为 None，故 `generate_question_bank` 中 position 的 `difficulty is None` 分支与 general 的 `difficulty is not None` 分支均为死代码；`_instantiate` 的 chain 判定 `ORDER BY ... DESC LIMIT 1` 后 `for row in reversed(rows)` 对单元素列表取 `reversed` 无意义。
**Fix:** 删除不可达分支，chain 判定直接取 `rows[0]` 判断即可（或在注释中说明仅检最新一题）。

### IN-05：readiness 取 task 行缺 rowid tie-break，与 WR-12 口径不一致

**File:** `server/services/readiness.py:99-104`
**Issue:** `_update_task_status` 特意用 `ORDER BY created_at DESC, rowid DESC` 处理 `created_at` 并列（WR-12），但 readiness 取最新 task 行只 `ORDER BY created_at DESC LIMIT 1`，无 rowid 兜底。retry 与失败行若 `created_at` 同值（`now_iso()` 精度内），可能非确定性地读到旧 FAILED 行。
**Fix:** 补 `, rowid DESC` 与 `_update_task_status` 保持一致。

### IN-06：ModelItem.gate 无取值范围校验

**File:** `server/api/admin/models.py:26`
**Issue:** `gate: int = 0` 无 `ge/le` 约束，可接收任意整数；消费侧 `_load_model_items`/`_uncovered_required_items` 均以 `gate=0` 为「非门槛项」判据，非 0 值即被当作门槛项，语义上 gate 应是 0/1 开关。
**Fix:** `gate: int = Field(default=0, ge=0, le=1)`。

---

_Reviewed: 2026-09-05T10:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
