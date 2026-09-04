---
phase: 02-dynamic-selection
fixed_at: 2026-09-04T17:30:00Z
review_path: .planning/phases/02-dynamic-selection/02-REVIEW.md
iteration: 1
findings_in_scope: 10
fixed: 10
skipped: 0
status: all_fixed
---

# Phase 2: Code Review Fix Report（CR-01/CR-02 + WR-01~WR-08）

**Fixed at:** 2026-09-04T17:30:00Z
**Source review:** .planning/phases/02-dynamic-selection/02-REVIEW.md
**Iteration:** 1
**Base:** c6aa9c0（feature/m5-assessment tip，修复前经 `git merge --ff-only` 快进）

**Summary:**
- Findings in scope: 10（Critical 2 + Warning 8；Info 6 项按章程搁置不修）
- Fixed: 10
- Skipped: 0

## Fixed Issues

### CR-01: LLM 调用失败 RuntimeError 冒泡 → submit_answer 500 主链断裂

**Files modified:** server/services/interview.py, server/test_phase2_interview.py
**Commit:** 93cfa61
**Applied fix:** decide_next_action 观察层把 call_llm_json 包入 try/except RuntimeError，降级构造 `{"answer_state": "MODEL_UNCERTAIN", ...}` 后与既有 ValidationError 降级合流（§11.5 不卡死会话）。新增回归测试 test_llm_failure_degrades_model_uncertain（monkeypatch call_llm_json 抛 RuntimeError）：断言 200 非 500、action=next、OBSERVATION_CLASSIFIED 留痕 answer_state=MODEL_UNCERTAIN、会话可继续派发下一题、fail 计数不动（七类排除）。
**Test proof:** 红→绿验证通过（stash 源文件修复后测试 FAILED，恢复后 PASSED）；test_phase2_interview.py 13 passed（原 12 + 新 1）。

### CR-02: 难度状态机跨难度迁移后档内计数残留 → 陈旧计数错误触发降级

**Files modified:** server/services/difficulty.py, server/test_phase2_difficulty.py
**Commit:** 406d568
**Applied fix:** update_path_state 迁移段（new_level is not None）在写 snapshot 前清档内计数：`fail_same_difficulty=0`、`followup_ambiguous=False`（换档即换「同难度」分母）；降到 easy 时 `sufficient_in_row=0`（滞回按新档重新累计）。新增两组回归测试：(a) test_migration_resets_counters_table_driven——表驱动 4 case（fail=2 降级清零 / famb 判据 2 降级清零 / easy 升档 / 无迁移对照计数照常推进）；(b) test_residual_followup_ambiguous_not_carried_after_migration——报告场景的可达坏序列（hard 因 famb 降 medium → 七类排除封存 → 一次普通失败不得触发二次降级）。
**测试设计说明:** 报告原文场景 3（medium 降 easy → 升回 medium）经逐路径复核在 advance_snapshot 的「充分证据清 famb」下自愈（升回必经充分证据）——真正可达的残留触发路是 hard→medium 迁移路（迁移后无需充分证据即可再次封存），测试按可达路径断言，覆盖同一缺陷面（迁移清理前旧代码必红）。
**Test proof:** 红→绿验证通过（两测试对旧代码均 FAILED）；test_phase2_difficulty.py 13 passed（原 10 + 新 2 + WR-05 新增 1）。

### WR-01: submit_answer 决策事务内三 helper 各自开连接的交错窗口

**Files modified:** server/api/assessment.py
**Commit:** 1b97d51
**Applied fix:** `_question_item_id` / `_instance_followup_count` / `_stable_evidence_light` 签名改为接调用方主 `conn`（同事务自读自写），删除各 helper 内部的 get_conn/close（`_stable_evidence_light` 的 `conn.close()` 按调用方职责移除——conn 归 submit_answer 持有）；两处调用点同步传 conn。commit 时序不变（仅读路径连接归并）。
**Test proof:** test_phase2_interview/difficulty/selection 34 passed。

### WR-02: get_session total_count 例外计数与 `_exception_granted_items` 两套口径

**Files modified:** server/api/assessment.py, server/services/question_selection.py
**Commit:** 9d0bec9
**Applied fix:** question_selection 增公开入口 `exception_granted_items`（复用 `_exception_granted_items` 实现——selection_reason JSON 解析 + REQUIRED_EXCEPTION_GRANTED 事件兜底）；get_session 例外计数由 SQL `json_extract` 改为 `len(exception_granted_items(conn, session_id))`——selection_reason 解析失败时事件兜底计入，进度分母与实发题数不漂移。函数内 `from .. import config as _config` 上移至模块头 import。
**Test proof:** test_phase2_selection/interview 22 passed。

### WR-03: `_apply_snapshot_difficulty` 回落派发无可观测标记

**Files modified:** server/services/question_selection.py
**Commit:** d1778e6
**Applied fix:** 属性纯审计键改造：`_apply_snapshot_difficulty` 返回 `(pool, sources)`——sources 记每候选题的难度源（snapshot_target=精确承接 / snapshot_fallback_lower=无目标档行回落最高可得档）；`_pick_ordinary` 透传返回（四元组扩展）；`_instantiate` 增 `difficulty_source` kwarg 落入 selection_reason。不改任何选题行为（pool 过滤逻辑原样）。
**Test proof:** test_phase2_selection/difficulty 21 passed。

### WR-04: 例外补选绕过 snapshot 难度承接（§10.5 与 §11.2 张力）

**Files modified:** server/services/question_selection.py
**Commit:** 26af147
**Applied fix:** **仅可观测性注记，零行为变更**：`_pick_exception_question` 接收 snapshot_targets，item snapshot 指示 easy 时返回 tension 标记；通过 `_instantiate` 新增 `exception_tension_note` 键（"snapshot_easy_vs_105_medium_hard"）落 selection_reason。§10.5 刚性行为照旧（medium 优先/hard 兜底/easy 不取）。**行为变更路径不越权**——SSOT 裁决建议带入 Phase 3 关口包（见「未修项/移交」）。
**Test proof:** test_phase2_selection 9 passed。

### WR-05: `_criterion_for` 复合触发输出误导性单一 criterion

**Files modified:** server/services/difficulty.py, server/test_phase2_difficulty.py
**Commit:** f1bdc55
**Applied fix:** `_criterion_for` 的 DIFFICULTY_LOWERED 分支改判双判据：fail≥2 且 followup_ambiguous 同立时返回组合态常量 `"two_consecutive_below_anchor+followup_still_ambiguous"`（新增 CRITERION_TWO_BELOW_AND_FOLLOWUP），单一判据照旧各归其名。事件表 append-only 不回写（报告建议的 generating 侧单点修正）。既有集成断言放行组合态；新增 test_criterion_composite_output 直测三态（复合/仅 fail/仅 famb）。
**Test proof:** test_phase2_difficulty 13 passed。

### WR-06: create_session readiness 检查与 `_latest_confirmed_model` 各查各的（TOCTOU/口径不一）

**Files modified:** server/api/assessment.py, server/services/readiness.py
**Commit:** 28a6b20
**Applied fix:** `check_session_readiness` 增可选 `model` 参数（调用方已取的 confirmed 模型行——三列 model_id/version/model_json 恰为 readiness 消费面）；`_check_session_readiness_locked` 缺省时内部自取（独立调用口径不变）。create_session 复用 `_latest_confirmed_model` 已取的行传入——同请求内单源锚定同一 confirmed 版本，消除两套版本口径。
**Test proof:** test_phase2_selection/interview/difficulty 35 passed + test_m5_backend 7 passed。

### WR-07: submit_answer answer 长度无上限 → 超大 payload 直达精炼/LLM

**Files modified:** server/api/assessment.py, server/services/scoring.py
**Commit:** 959a4de
**Applied fix:** submit_answer 在空值 422 后增 `len(answer) > MAX_ANSWER_LEN`（64*1024）→ 422「回答过长」。scoring 侧 `_MAX_ANSWER_LEN` 提升公开常量 `MAX_ANSWER_LEN`（同值单源；模块内旧私有名保留为别名，既有引用不动）。
**Test proof:** test_phase2_interview/scoring + test_m5_backend 27 passed。

### WR-08: `get_confirmed_model` 与 `_latest_confirmed_model` 双实现漂移

**Files modified:** server/api/assessment.py
**Commit:** fb0c72a
**Applied fix:** get_confirmed_model 模型行改调 `_latest_confirmed_model`（相关子查询 MAX(version)——与 create_session/列表接口同口径）；WR-10 的 position active 校验改为前置独立单行查询（不通过 404，原 join 校验语义保持——inactive/无岗位均 404 统一文案）。
**Test proof:** 该端点无既有测试覆盖，以独立 TestClient 脚本人工验证三路径（active+多版本取最新 v2=200 / pending_review 岗位=404 / 无模型=404）通过后删除脚本；test_m5_backend/test_phase2_interview 20 passed。

## 未修项 / 移交

- **WR-04 行为变更路径（§10.5「仅 medium」刚性 vs §11.2「降级后避免高难度」张力）**：本期仅落 `exception_tension_note` 可观测性注记，不改选题行为。**建议将 §10.5/§11.2 张力的 SSOT 裁决带入 Phase 3 关口包**（硬关口——需用户裁决后方可行为变更）。
- **Info 6 项（IN-01~IN-06）**：按章程搁置记档，未修（IN-01 层④ chain 排序键退化已由 02-VERIFICATION Acknowledged Gaps 记录，留 Phase 4/5；IN-02~06 为测试补充/清理/占位项）。

## 回归门（全量）

修复后逐文件全绿（cwd=server/）：

| 文件 | 结果 |
|---|---|
| test_phase2_interview.py | 13 passed（+1 CR-01 新增） |
| test_phase2_difficulty.py | 13 passed（+2 CR-02 新增、+1 WR-05 新增） |
| test_phase2_selection.py | 9 passed |
| test_phase2_scoring.py | 7 passed |
| test_phase2_migration.py | 8 passed |
| test_phase2_weights.py | 5 passed |
| test_m5_backend.py | 7 passed |
| test_p0_security.py | 10 passed |
| test_p0_chain.py | 11 passed |
| test_question_bank.py（python 直跑） | 25 通过 0 失败 |
| test_m6_backend.py（python 直跑） | 43 通过 0 失败 |

**合计 110 项全绿。**

## Commit 清单

| Commit | Finding |
|---|---|
| 93cfa61 | CR-01 |
| 406d568 | CR-02 |
| 1b97d51 | WR-01 |
| 9d0bec9 | WR-02 |
| d1778e6 | WR-03 |
| 26af147 | WR-04 |
| f1bdc55 | WR-05 |
| 28a6b20 | WR-06 |
| 959a4de | WR-07 |
| fb0c72a | WR-08 |

---

_Fixed: 2026-09-04T17:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
