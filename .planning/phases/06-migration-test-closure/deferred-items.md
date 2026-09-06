# Phase 6 — Deferred / Out-of-Scope Items

> Log of discoveries during plan execution that are out of scope for the current plan and deferred to a later plan (or user decision). Kept separate from STATE.md's global Deferred Items for phase-level visibility.
>
> **2026-09-06 收口复核：本文件列出的全部 5 个既有失败 + 13 文件回归缺口均已闭合**（f827ceb / fbc4aac / 1002d2f / d5f377f），全量回归 **236 passed**（见 STATE.md）。各条目下方已标 CLOSED。

## From 06-01 (migration registry + conftest + migration tests)

### [04-011] — test_m5_backend.py 4 failures are pre-existing (NOT caused by 06-01) — **✅ CLOSED**

- **Found during:** 06-01 plan-level regression check (`cd server && python -m pytest test_m5_backend.py test_m7_backend.py -q`)
- **Symptom:** 4 failed / 8 passed. All 4 failures in `test_m5_backend.py`:
  - `test_session_creation_and_question_selection` → `QUESTION_BANK_INCOMPLETE: 必备能力项缺题：Python、MySQL、后端开发经验`
  - `test_session_state` / `test_answer_flow_and_scoring` / `test_form_submission` → `KeyError: 'session_id'` (cascading from the session-creation 409)
- **Root cause:** `test_m5_backend.py::_seed_question_bank` (lines 86–90) INSERTs `question_bank` without `model_id`/`model_version`. Phase 4 consumer-side tightening (D-50, `services/readiness.py` `WHERE model_id=? AND model_version=?`) rejects those rows at session-creation readiness check.
- **Why out of scope for 06-01:** The 13 session-test files' `model_id`/`model_version` gap is the known deferred item `[04-011]`, assigned to **06-03 (M1 regression)** per D-71. 06-01's `files_modified` is only `db.py`/`conftest.py`/`test_migration.py`.
- **Evidence it is pre-existing:** documented in `.planning/STATE.md` Deferred Items ("13 个会话类测试文件…直插 question_bank 不写 model_id/model_version，Phase 4 消费侧收紧后失败 → 并入 Phase 6 M1 回归收口（[04-011]）"). 06-01 did not touch `test_m5_backend.py`, `services/readiness.py`, or `question_bank` DDL.
- **Confirmation 06-01 is clean:** `test_m7_backend.py` is fully green (5 passed); `test_migration.py` is green (3 passed). 06-01's own artifacts verified.
- **Action:** 06-03 fixes the seed (add `model_id`/`model_version` to the 13 files' `question_bank` INSERTs). No action for 06-01.

## From 06-03 (M1 regression + config §31-4 + 13-file column fill)

### 2 pre-existing failures unmasked by the 13-file column fill (NOT caused by 06-03) — **✅ CLOSED（两项均）**

06-03's Task 3 is a purely mechanical edit: add `model_id`/`model_version` to each `INSERT INTO question_bank` across 13 session-test files + thread `mid`. It does **not** touch `api/assessment.py`, `db.py`, or any migration/report logic. Two failures surfaced after the fill, both in code paths unrelated to `question_bank` columns — they were previously masked because the missing `model_id`/`model_version` caused those tests to fail earlier (at session creation / readiness), before ever reaching these assertions.

| # | Test | Failure | Root cause (pre-existing) |
|---|------|---------|---------------------------|
| 1 | `test_p0_chain.py::test_completed_session_guardrail` (line 426) | second `POST /report` returns **202** instead of 409 | `request_report` guard only rejects `report_status=='GENERATING'` (branch b). A terminal-status row (`READY`/`PUBLISHED`/`FAILED`) falls into branch (c) → new `GENERATING` row + 202. The P0 test expects 409 for *any* existing report row ("已生成报告再请求"). This is a D-08 (score→report serial chain) endpoint-semantics vs P0 "成功标准 5" mismatch — a design-level question, not a column-fill bug. |
| 2 | `test_phase3_timer.py::test_phase_column_defaults` (line 541) | `row["phase"] == "PENDING_START"` fails with `None` after re-running `init_db()` | The phase backfill migration is registered in the `schema_version` registry (D-68). Re-running `init_db()` is idempotent — it does **not** re-apply the `phase=NULL → PENDING_START` backfill to a manually `NULL`ed row, because the migration is already recorded as applied. Unrelated to `question_bank`. |

- **Why out of scope for 06-03:** Task 3 scope is "补 model_id/model_version 两列，不改其他列、不改断言数值、不改测试语义". Fixing #1 requires changing the report endpoint's re-trigger semantics (a D-08 design decision, Rule 4 architectural); fixing #2 requires changing migration-registry idempotency semantics (D-68, also design-level). Neither is a mechanical column fill.
- **Evidence of correctness of 06-03's own changes:** the 3 acceptance files `test_m5_backend.py` / `test_m6_backend.py` / `test_m7_backend.py` are green (16 passed). The grep acceptance check (each `INSERT INTO question_bank` column list contains both `model_id` and `model_version`) is clean for all 13 files.
- **Action:** defer to a design decision. #1 needs SSOT confirmation of whether `POST /report` on a terminal-status report should 409 (test's expectation) or re-generate (current D-08 endpoint). #2 needs a decision on whether the phase backfill should be idempotently re-applied (e.g. a `WHERE phase IS NULL` idempotent backfill outside the registry) or the test's re-run expectation is stale.
- **Closure（2026-09-06）:** #1 由 `f827ceb` 收口（§21.1 终态报告 409 护栏，SSOT fbc4aac 已记 §14 变更日志）；#2 同由 `f827ceb` 修 `test_phase3` 过期断言。两项现均绿（236 passed 全量回归）。

## From post-merge test gate（执行期全量回归 — 5 failed / 218 passed）

执行期全量回归（`cd server && python -m pytest -q`）最终 **5 failed / 218 passed**。全部 5 个均以基线（commit 13f6743，无 conftest）核实为**既有失败**：基线全量 **98 failed**（无 conftest 的 DB_PATH 首导入冻结污染 + 13 文件缺 model_id/model_version），06-01 conftest + 06-03 补列把 98 降到 5。5 个中 2 个（test_p0_chain / test_phase3_timer）已在上文 06-03 节记档；本节补记其余 3 个。

### test_phase2_weights.py::test_aggregation_no_double_scaling — 过期源码字符串断言 — **✅ CLOSED**

- **Symptom:** `assert 'actual / 5.0' in src`（`inspect.getsource(aggregation_module)` 取整模块源码后做字面量断言）失败 —— 聚合模块源码已不含字面量 `actual / 5.0`（公式锚点写法漂移）。
- **Root cause:** 测试用 `inspect.getsource` 抓整模块源码再断言字符串字面量，脆弱且与实现细节强耦合；重构后字面量漂移即挂。与 DB/conftest 无关（纯源码字符串断言）。
- **Why out of scope:** Phase 6 未触及 `services/aggregation.py` 或 `test_phase2_weights.py`；该断言是 Phase 2 遗留的脆弱断言，非本 phase 回归（单独跑同样失败）。改为行为断言（调函数断言结果）而非源码字面量断言属测试重构，超出 5 计划 files_modified 范围。
- **Closure（2026-09-06）:** `f827ceb`（修 test_phase2/3 两处过期断言）收口，现绿。

### test_phase4_binding.py::test_generate_writes_binding_columns — 旧式 DB_PATH 隔离假设被 conftest 打破 — **✅ CLOSED**

- **Symptom:** `assert len(rows) == 6` 实得 **1046**（`SELECT * FROM question_bank`）。
- **Root cause:** 该文件沿用旧式 `os.environ["DB_PATH"] = _tmp_db`（第 18 行，`from server.db import` 之前）的隔离手法。06-01 conftest 先 import server.config 冻结 DB_PATH 到 session 级 `gsd-test-` 共享库，测试文件的 `os.environ["DB_PATH"]` 赋值失效 → `init_db()`/`get_conn()` 落在共享库，`SELECT *` 读到其他测试文件播种的 1046 行。
- **Pre-existing 证据:** 基线（无 conftest，首导入冻结污染）同测**同样失败**（基线 98 failed 之列）。非 06-01 新引入 —— 06-01 之前它就因「首导入 wins」污染挂；06-01 只是把污染机制从「首导入 wins」换成「共享 session 库」，未修复该文件的隔离。
- **Why out of scope:** 修复即把该文件迁移到 `set_db_path()` 模式（与 test_phase2_migration 同款），属测试文件隔离模式迁移，超出 5 计划 files_modified。**可低成本跟进**：改 `os.environ["DB_PATH"]` → autouse fixture `set_db_path(_tmp_db)`，或直接改用 `db_module.DB_PATH = _tmp_db` 直接改 config 属性（test_phase3_forms 同款）。
- **Closure（2026-09-06）:** `1002d2f`（迁移 test_phase4_binding + test_phase5_evidence 到 set_db_path autouse fixture，WR-05）收口，现绿。

### test_phase5_evidence.py::test_ref_id_import_migration — 裸连接指向从未建表的 _tmp_db — **✅ CLOSED**

- **Symptom:** `sqlite3.OperationalError: no such table: assessment_session`（`sqlite3.connect(_tmp_db)` 后直插 assessment_session）。
- **Root cause:** 该测试用**裸 sqlite3** 直连自建 `_tmp_db`，期望 `_tmp_db` 已有 `assessment_session` 表。但 `_tmp_db` 的建表依赖旧式 `os.environ["DB_PATH"] = _tmp_db`（被 conftest 冻结失效），`init_db()` 实际建表落在共享 `gsd-test-` 库，`_tmp_db` 始终为空。
- **Pre-existing 证据:** 基线同测**同样失败**（98 failed 之列）。非 06-01 新引入。
- **Why out of scope:** 修复即让 `_tmp_db` 真正被 init（迁移到 `set_db_path()` 模式或裸连后手动 `executescript` 建 assessment_session），超出 5 计划 files_modified。**可低成本跟进**：同 test_phase4_binding，改 `set_db_path()` 隔离模式。
- **Closure（2026-09-06）:** `1002d2f`（同上，set_db_path autouse fixture 迁移）收口，现绿。

## From verify-gap closure — SSOT §21 gap 符号约定 vs §23「短板定位」语义张力（§2.2 硬关口）✅ 已解决（选项 A）

**发现于 [06-013]**（verify SC5-c「c 虚拟考生」缺口闭环时接线 `assert_weakness_identified`）：

- **现象**：weak 档虚拟考生全部 miss → `actual_level=1 < required_level=3`。但 `generate_report` 产出的报告 `weaknesses=[]`、`strengths` 却含这些低于要求的项——与「短板定位」直觉相反，`assert_weakness_identified(report, expected_weakness)` 对 weak 档恒失败。
- **根因（SSOT 符号约定）**：SSOT §21（行 561）原约定 `gap = required_level − actual_level`（§20.3 行 553），短板=`gap<0`、优势=`gap≥0`。`actual<required`（低于要求，即自然语义的「短板」）算出 `gap>0` → 落入 **strengths**，符号与「木桶短板=低于要求」的自然语义相反。
- **性质**：SSOT 条款歧义/需修改 SSOT，属章程 §2.2 硬关口。

**解决（用户裁决 [06-013] 选项 A，2026-09-06）**：反转符号约定——`gap = required − actual` 不变，优势=`gap≤0`、短板=`gap>0`，短板排序键 `|gap|×weight` → `gap×weight`。

- **SSOT**：§21 行 561 正文 + §14 变更日志（commit `ce09bb1`）。
- **代码**（commit 随本项）：`aggregation.py:357-366` 筛选反转（优势 gap≥0→≤0、短板 gap<0→>0、`-abs(gap*weight)`→`-(gap*weight)`）；`test_m6_backend.py` 断言反转（strengths=沟通能力 / weaknesses=Python / strengths_text / weaknesses_text）；`eval/virtual_candidates.py` 注释更新。
- **验证**：全量回归 3 failed/220 passed（同 3 个既有设计级失败）；isolated virtual_candidates 6/6 子项全绿（weak 档实际短板=['Python','MySQL']）。

## Other notes

- **06-01 did not run `init_db()` against the business `data/app.db`** (red line: business DB never used for tests). The first real server startup by the user will backfill `schema_version` 1..13 on `data/app.db` (idempotent migrations make this safe), with a pre-migration `backups/app-*.db` backup. This is a deployment-time smoke test, not an executor-run test.
