---
phase: 04-question-bank-version
verified: 2026-09-05T07:27:02Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 04: 题库版本绑定与模块一收口 Verification Report

**Phase Goal:** 题库与 confirmed 模型版本强绑定（升版须重建题库否则阻止开考），题库生成失败对管理员可见；模块一管理端已知缺陷修复（orphan 路由、模型编辑校验）
**Verified:** 2026-09-05T07:27:02Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | question_bank 行携带 model_id/model_version（绑定岗位 + confirmed 模型版本）；模型升版后旧题库不再对新会话生效，未生成新题库时开考被阻止 | ✓ VERIFIED | `question_bank.py:61-70` INSERT 写 model_id/model_version/item_id/rubric_version='v1'；`db.py:142-151` DDL 列已落；`readiness.py:24,37,101,146` 与 `question_selection.py:234` 消费侧强制 `model_id+model_version` 过滤；`test_phase4_binding.py` 4 passed（含 v2 阻断/selection 只取匹配版本/判重键升级） |
| 2   | 题库生成失败不再静默 pass：失败在题库状态与管理员待办中可见（失败状态 + 明确错误信息） | ✓ VERIFIED | `readiness.py:99-112` FAILED 分支返回 QUESTION_BANK_INCOMPLETE + error_msg[:200]；`positions.py:29-34` get_todos 新增 question_bank_failed 明细；`test_phase4_fail_visible.py` 2 passed |
| 3   | 管理员访问 /jds/orphan 返回孤儿 JD 列表（修复被 /jds/{jd_id} 参数路由捕获恒 404） | ✓ VERIFIED | `jds.py:79` `@router.get("/jds/orphan")` 声明在 `jds.py:90` `@router.get("/jds/{jd_id}")` 之前；查询 `WHERE position_id IS NULL AND status != 'failed'`；`positions.py` 无重复 orphan 路由（grep 计数 0）；`test_phase4_orphan.py` 1 passed |
| 4   | 管理员编辑模型提交 NaN 权重/越界类别/重复 std_name 被服务端拒绝并返回明确错误（保留 Σ=100% 校验） | ✓ VERIFIED | `models.py:22-25` weight `Field(ge=0, le=1, allow_inf_nan=False)`、required_level `Field(ge=1, le=5)`、importance `Literal`、years `Field(ge=0, allow_inf_nan=False)`；`models.py:86-89` Σ=100% 校验 + `models.py:93-101` 同 category 重复 std_name 拒绝；`test_phase4_model_edit.py` 10 passed |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/question_bank.py` | _insert_question 写 model_id/model_version/item_id/rubric_version + 4 处判重键升级 | ✓ VERIFIED | 4 处 exists 判重均含 `model_id=? AND model_version=?`（lines 133/140/149/157）；generate_question_bank 取 model_version（line 104-107） |
| `server/services/readiness.py` | 三处 count/tier WHERE 加双列过滤 + task 查询取 error_msg + FAILED 分支 | ✓ VERIFIED | 两 count helper（line 24/37）+ tier LEFT JOIN（line 146）+ task 查询（line 101）均双列过滤；FAILED 分支（line 108-112） |
| `server/services/question_selection.py` | _load_candidate_rows 强制 model_id+model_version（去 NULL 放行） | ✓ VERIFIED | line 234 `AND b.model_id=? AND b.model_version=?`，无 IS NULL 放行 |
| `server/api/admin/positions.py` | get_todos 新增 question_bank_failed 明细 | ✓ VERIFIED | lines 29-34，question_bank_not_ready 保持 int |
| `server/api/admin/jds.py` | GET /jds/orphan 声明置于 /jds/{jd_id} 之前 | ✓ VERIFIED | line 79 vs line 90 |
| `server/api/admin/models.py` | ModelItem 字段级校验 + update_model 重复 std_name 拒绝 | ✓ VERIFIED | lines 22-25 + 93-101 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| generate_question_bank | question_bank.model_id/model_version/item_id/rubric_version | _insert_question INSERT 列清单 | ✓ WIRED | 值依次 model_id/model_version/item["item_id"]/"v1" |
| check_session_readiness / _load_candidate_rows | question_bank.model_id/model_version | AND model_id=? AND model_version=? | ✓ WIRED | readiness 3 处 + selection 1 处同源 |
| check_session_readiness | question_bank_task.status='FAILED' | QUESTION_BANK_INCOMPLETE + error_msg[:200] | ✓ WIRED | FAILED 分支显式返回 |
| GET /jds/orphan | jd_record WHERE position_id IS NULL AND status != 'failed' | FastAPI 声明序 | ✓ WIRED | 先于 /jds/{jd_id} |
| PUT /models/{model_id} | ModelItem.weight | Field(ge=0, le=1, allow_inf_nan=False) | ✓ WIRED | 解析期 422 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| generate_question_bank → question_bank | model_version | `SELECT version FROM competency_model WHERE model_id=?` | Yes（真实 DB 行） | ✓ FLOWING |
| check_session_readiness → counts | counts/covered | `SELECT ... FROM question_bank WHERE status='active' AND model_id=? AND model_version=?` | Yes（真实题库行） | ✓ FLOWING |
| get_todos → question_bank_failed | failed list | `SELECT ... FROM question_bank_task WHERE status='FAILED'` | Yes（真实任务行） | ✓ FLOWING |

无 HOLLOW / STATIC / DISCONNECTED——所有消费侧数据均来自真实 DB 查询，无硬编码空值。

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 落库绑定/判重键/消费侧阻断/selection 只取匹配版本 | `python -m pytest test_phase4_binding.py -q` | 4 passed | ✓ PASS |
| readiness FAILED 带 error_msg + todos 明细 | `python -m pytest test_phase4_fail_visible.py -q` | 2 passed | ✓ PASS |
| /jds/orphan 返回 200 列表非 404 | `python -m pytest test_phase4_orphan.py -q` | 1 passed | ✓ PASS |
| 模型编辑字段校验/重复/Σ=100% | `python -m pytest test_phase4_model_edit.py -q` | 10 passed | ✓ PASS |
| 回归：test_phase2_selection.py | `python -m pytest test_phase2_selection.py -q` | 9 passed | ✓ PASS |
| 回归：test_question_bank.py | `python test_question_bank.py` | 25 通过, 0 失败 | ✓ PASS |

### Probe Execution

无 probe 脚本声明（本 phase 为纯 Python 改造，无 `scripts/*/tests/probe-*.sh`）。以单文件单进程 pytest 佐证替代（见上表）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| REF-2.5 | 04-01 | question_bank 演进（model/version 绑定、rubric_version、锚点等） | ✓ SATISFIED | model_id/model_version/item_id/rubric_version='v1' 落库；锚点随 Phase 2 先行；综合绑定（integrated_bindings_json）延后 REF-3.9（见 deferred 备注） |
| REF-3.4 | 04-01 | 题库绑定 model/version；升版须重建题库否则阻止开考 | ✓ SATISFIED | 消费侧强制双列过滤 + QUESTION_BANK_INCOMPLETE 阻断 v2 无题库 |
| REF-7.1 | 04-02 | /jds/orphan 路由顺序修复 | ✓ SATISFIED | jds.py orphan 声明前置，positions.py 移除重复路由 |
| REF-7.2 | 04-02 | 模型编辑字段校验（NaN/范围/类别/重复 std_name） | ✓ SATISFIED | ModelItem 字段强化 + update_model 重复拒绝，Σ=100% 保留 |
| REF-8.4 | 04-01 | 题库生成失败静默（状态 + 管理员待办可见） | ✓ SATISFIED | readiness FAILED + get_todos question_bank_failed 明细 |

5/5 requirement IDs 全部追踪。无 orphaned requirements（Phase 4 的 5 个 REF 均出现在对应 PLAN frontmatter 中）。

### Anti-Patterns Found

无。6 个修改源文件扫描 `TBD/FIXME/XXX`、`TODO/HACK/PLACEHOLDER/placeholder`、`return null/{} /[] / => {}` 均零命中。

### Human Verification Required

无。4 项 success criteria 均为纯后端可程序化验证项（SQL 落库/路由顺序/Pydantic 校验/失败可见），源码实锤 + 单文件单进程 pytest 全绿，无需人工视觉/交互/外部服务验收。

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | question_bank 综合绑定（question_type='integrated' + integrated_bindings_json） | 延后（REF-3.9，未排期） | CONTEXT.md deferred：「综合题槽位 question_type='integrated' + integrated_bindings_json（REF-3.9——Prompt 待讨论 D-030）」 |

REF-2.5 描述中的「综合绑定」子项属 REF-3.9 范围，已显式延后，不构成 Phase 4 缺口（Phase 4 主体 = model/version 绑定 + rubric_version + item_id，均已落地）。

### Gaps Summary

无缺口。4/4 success criteria 源码实锤 + 新增/回归测试全绿 + 5 项 REF 全追踪。Phase 4 目标达成，可进入下一阶段。

---

_Verified: 2026-09-05T07:27:02Z_
_Verifier: Claude (gsd-verifier)_
