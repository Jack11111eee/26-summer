---
phase: 01-p0
verified: 2026-09-03T12:35:00Z
status: verified
score: 5/5 must-haves verified
overrides_applied: 0
human_verification: []
---

# Phase 1: P0 安全与主链修复 验证报告

**Phase Goal:** 候选人资源不可越权访问，正常 UI 主链（作答完成→评分→报告）真实可用且全程事件留痕，不可创建空测评会话
**Verified:** 2026-09-03T12:35:00Z
**Status:** verified（5/5 truths 全部 VERIFIED，3 项 UI 层人工验证已通过 — 2026-09-03 UAT）
**Re-verification:** No — 初次验证（无前序 VERIFICATION.md）

## Goal Achievement

### Observable Truths（源自 ROADMAP.md 五条 Success Criteria）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 候选人 A 无法读写候选人 B 的 session/report/form/feedback，admin 可访问且可查完整 trace——越权测试矩阵通过 | ✓ VERIFIED | `server/core/security.py:60-96` load_owned_session/load_owned_report（单查询 `WHERE resource_id AND user_id=?` + admin 读豁免回退 + 404 统一语义，全 ? 参数化）；`server/api/assessment.py` 8 条资源路由全部首调 helper（grep 计 8 处）；`test_p0_security.py` 6 个矩阵用例实跑全 PASS（B 读 A session/report/by-session→404、B 写 A answer/forms/score/report/feedback→404、admin 读 A→200/admin 写 A→404、admin 自有资源→200、owner 主链含 in_progress score→200、admin trace by-session→200） |
| 2 | 候选人在 UI 正常完成测评后直接进入报告页，报告含真实逐题评分与雷达数据（服务端 score→report 串行，不再 no_data） | ✓ VERIFIED | `server/api/assessment.py:275-300` _generate_report_task 先 `score_session(session_id, allow_completed=True)` 再 `generate_report(session_id)`（D-08 方案 B）；`test_p0_chain.py::test_ui_main_chain_score_report_serial` 实跑 PASS：API 完成整场答题→不调 POST /score→直接 POST /report→202→question_score>0→radar_data.indicators 非空→非 gate 项无 no_data（断言不经 Python 直调掩盖）；前端接线：`Chat.vue:247-249` finish→router.push 报告页，`Report.vue:377-402` GET-first→POST /report→3s 轮询→renderRadar，前端全程不调 POST /score；`npx vite build` 通过（9.72s） |
| 3 | 题库未就绪/模型不可测量时创建 session 返回明确状态并产生管理员待办，绝不创建 0 题会话 | ✓ VERIFIED | `server/services/readiness.py:38-117` check_session_readiness（三状态名单点返回：QUESTION_BANK_GENERATING/QUESTION_BANK_INCOMPLETE/MODEL_NOT_MEASURABLE + CATEGORY_QUOTA 配额 + required 覆盖，6/7 no-op 按 D-11 占位）；`server/api/assessment.py:80-84` INSERT 会话前预检 409+dict detail{error_code, message}；`server/db.py:255-265` question_bank_task 9 列 DDL；`test_p0_chain.py` 5 用例实跑 PASS（GENERATING/INCOMPLETE/空模型 MODEL_NOT_MEASURABLE/inactive 岗位 MODEL_NOT_MEASURABLE，四态均有 `_assert_session_not_created` COUNT==0 断言；legacy 无 task 行+足量题库→201 不误伤）；`server/api/admin/positions.py:25-27` get_todos 含 question_bank_not_ready 键（test_admin_todos_includes_question_bank_not_ready PASS）；confirm 插 QUEUED 行（models.py:107-112）+ generate_question_bank 首尾 RUNNING/SUCCEEDED/FAILED 更新（question_bank.py:70-151） |
| 4 | assessment_state_event 表落地且 append-only：关键状态迁移均写事件，直接 UPDATE/DELETE 被测试证明拒绝 | ✓ VERIFIED | `server/db.py:221-248` 19 列 DDL + UNIQUE(session_id, sequence_no) + ase_no_update/ase_no_delete 触发器 RAISE(ABORT)；`server/services/state_events.py:14-48` append_event（actor_type 三值白名单 ValueError + COALESCE(MAX(sequence_no),0)+1 取号，不 commit）；迁移点全部接入：SESSION_CREATED（create_session 同事务，assessment.py:102-104）、QUESTION_ANSWERED（submit_answer，from=active/to=answered，:196-199）、SESSION_COMPLETED（from=in_progress/to=completed，:205-206）、TASK_QUEUED/STARTED/SUCCEEDED/FAILED + SESSION_ENTERED_SCORING（01-03 串行链）；`test_p0_security.py::test_event_table_rejects_update_delete` 实跑 PASS（UPDATE/DELETE→sqlite3.IntegrityError 含 "append-only"）；test_session_created_event / test_question_answered_and_session_completed_events / test_serial_chain_events PASS（from/to/actor_type/sequence_no 从 1 连续递增无重复） |
| 5 | completed 会话再调 POST /score、/report 被状态护栏拒绝 | ✓ VERIFIED | `server/services/scoring.py:107-124` score_session 入口护栏（completed 且未豁免→ValueError("会话已结束，不允许重复评分")，keyword-only allow_completed 默认 False，grep 全库仅 _generate_report_task 一处传 True）；`server/api/assessment.py:253-256` ValueError→409；`request_report:312-319` B-1 三分支（非 completed→409 / completed 且已有 report 行→409 / completed 且无 report 行→202 入队）；`test_p0_chain.py::test_completed_session_guardrail` 实跑 PASS（completed 后 POST /score→409、POST /report→409、report 行数仍为 1）；test_in_progress_report_rejected PASS（in_progress→409）；test_m5_backend.py:257-258 断言已重写为 409（7/7 PASS）；eval/virtual_candidates.py:130-138 顺序已对调（score 先于 UPDATE completed）；DDL 幂等（二连 init_db 验证通过） |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|-----------|--------|---------|
| `server/core/security.py` | load_owned_session/load_owned_report 所有权 helper | ✓ VERIFIED | 两函数存在（:60/:81），404 统一语义 + owner 优先 + admin 读豁免，全 ? 参数化 |
| `server/api/assessment.py` | 8 条路由接入 helper + user 注入 + 串行链 + 三分支 + readiness 接入 | ✓ VERIFIED | helper 调用点 8 处；7 条路由补 user 注入；_generate_report_task 串行链；request_report 三分支；create_session 预检 |
| `server/services/state_events.py` | append_event 唯一写入入口 | ✓ VERIFIED | actor_type 校验 + MAX+1 取号，不 commit（事务归调用者） |
| `server/db.py` | assessment_state_event DDL（19 列+两触发器）+ question_bank_task DDL | ✓ VERIFIED | :221-248 / :255-265 均落地，幂等 |
| `server/services/scoring.py` | score_session 状态护栏 + allow_completed | ✓ VERIFIED | :107 签名含 keyword-only 参数；:123-124 completed 拒绝 |
| `server/services/readiness.py` | check_session_readiness 三态统一返回 | ✓ VERIFIED | 三状态名在文件内单点返回，CATEGORY_QUOTA 从 question_selection import |
| `server/test_p0_security.py` | 越权矩阵 + 事件矩阵（≥150 行） | ✓ VERIFIED | 450 行 10 用例，实跑全 PASS |
| `server/test_p0_chain.py` | 主链串行+护栏+三态测试（≥120 行） | ✓ VERIFIED | 558 行 11 用例，实跑全 PASS |
| `server/api/admin/models.py` | confirm 插 QUEUED task 行 | ✓ VERIFIED | :107-112 INSERT INTO question_bank_task（new_id("qbt")+"QUEUED"，commit 后 add_task 前） |
| `server/api/admin/positions.py` | todos 含 question_bank_not_ready | ✓ VERIFIED | :25-27 COUNT(DISTINCT position_id) WHERE status != 'SUCCEEDED' |
| `web/src/router/index.js` | route guard admin 例外（requiresAuth） | ✓ VERIFIED | :53/:59 两条测评路由 meta 为 requiresAuth: true，文件内无 role: 'candidate'（grep 0 命中）；vite build 通过 |
| `web/src/views/assessment/PositionAssess.vue` | 409 可读提示 | ✓ VERIFIED | :137-141 catch 409 分支，detail?.message \|\| detail \|\| 中文兜底 |
| `eval/virtual_candidates.py` | score 先于置 completed | ✓ VERIFIED | :130-138 commit→score→UPDATE completed 顺序 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| api/assessment.py 8 条路由 | core/security.py helper | 路由首调 load_owned_session/load_owned_report | ✓ WIRED | grep 计 8 处路由调用点，实测越权矩阵全 PASS |
| create_session | services/readiness.py | INSERT 会话前预检不通过 409 | ✓ WIRED | assessment.py:80-84；四态测试断言不建会话 |
| create_session / submit_answer / 串行链 | assessment_state_event | SESSION_CREATED / QUESTION_ANSWERED / SESSION_COMPLETED / TASK_* | ✓ WIRED | 事件断言测试全部实跑 PASS |
| _generate_report_task | services/scoring.py score_session | 后台链先评分再生成（allow_completed=True） | ✓ WIRED | assessment.py:290；test_ui_main_chain_score_report_serial PASS |
| score_session 入口 | 状态护栏 | completed→ValueError→API 409 | ✓ WIRED | scoring.py:123-124 + assessment.py:253-256；双端点 409 实测 |
| confirm_model | question_bank_task | confirm 后插 QUEUED 行 | ✓ WIRED | models.py:107-112 |
| generate_question_bank | question_bank_task | RUNNING/SUCCEEDED/FAILED 首尾更新 | ✓ WIRED | question_bank.py:96/143/148（含 pos is None 分支 FAILED） |
| Chat.vue finish | /assessment/report/:session_id | router.push | ✓ WIRED | Chat.vue:247-249 |
| Report.vue bootstrap | POST /report + GET by-session 轮询 | 触发+轮询 | ✓ WIRED | Report.vue:377-432（GET-first→POST→3s poll→renderRadar） |
| PositionAssess.vue onStart catch | 409 detail.message | e.response?.data?.detail | ✓ WIRED | PositionAssess.vue:137-141（Pitfall 7 无 [object Object]） |
| test_m6_backend.py _test_feedback_api | submit_feedback(user=) | 直调适配 | ✓ WIRED | test_m6_backend.py:268-275 补传种子 user dict，m6 全脚本 41/0 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| Report.vue 报告页 | report.value / radar | GET /reports/by-session → report 表 report_json | 是（report_json 由串行链真实生成，含 radar_data/item_details） | ✓ FLOWING |
| readiness.py 判定 | position/model/task/question_bank 计数 | 真实 SELECT（无硬编码返回） | 是 | ✓ FLOWING |
| test_p0_chain 主链断言 | question_score / report 计数 | _q 直查临时库 | 是 | ✓ FLOWING |
| get_todos 待办 | question_bank_not_ready | COUNT(DISTINCT position_id) 实表查询 | 是 | ✓ FLOWING |

### Behavioral Spot-Checks（实跑记录，2026-09-03）

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 越权+事件矩阵 | `cd server && python3 -m pytest test_p0_security.py -v` | 10 passed（15.3s 内含 chain 同进程） | ✓ PASS |
| 主链串行+护栏+三态 | `cd server && python3 -m pytest test_p0_chain.py -v` | 11 passed | ✓ PASS |
| 两套件合跑 | `python3 -m pytest test_p0_security.py test_p0_chain.py` | 21 passed | ✓ PASS |
| m5 回归（断言重写后） | `python3 -m pytest test_m5_backend.py -v` | 7 passed（含 :257-258 的 409 断言） | ✓ PASS |
| m6 脚本回归 | `python3 test_m6_backend.py` | 41 通过 0 失败，exit 0 | ✓ PASS |
| m7 admin 回归 | `python3 -m pytest test_m7_backend.py -v` | 5 passed | ✓ PASS |
| 前端构建 | `cd web && npx vite build` | ✓ built in 9.72s | ✓ PASS |
| DDL 幂等 | 双连 init_db()（临时 DB） | 'DDL idempotent OK' | ✓ PASS |
| eval 冒烟（未知岗位） | `python3 eval/virtual_candidates.py --position-id nonexistent-smoke` | 停在「岗位 nonexistent-smoke 无 confirmed 模型」（预先种子行为，符合验证上下文预期） | ✓ PASS（预期行为） |

### Probe Execution

本阶段无声明 probe（`scripts/*/tests/probe-*.sh` 不存在；PLAN 声明的验证入口为 pytest 套件，已作为 Behavioral Spot-Checks 全部实跑通过——非采信 SUMMARY 叙述，验证者独立进程复跑）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| REF-1.1 | 01-01 | 候选人资源级所有权校验（WHERE user_id=current） | ✓ SATISFIED | 8 路由 helper 接入 + 读写矩阵 404 全 PASS |
| REF-1.2 | 01-01 | 角色限制后端执行收口（越权矩阵） | ✓ SATISFIED | admin 读豁免/写拒绝矩阵 + route guard 修复 |
| REF-1.5 | 01-02 | 状态事件 append-only 体系 | ✓ SATISFIED | 触发器拒绝 UPDATE/DELETE 实测 + 全迁移点写事件 |
| REF-2.2 | 01-02 | assessment_state_event 新表（UNIQUE(session_id,sequence_no)） | ✓ SATISFIED | DDL 19 列 + UNIQUE 约束 + sequence_no 连续递增断言 |
| REF-3.5 | 01-04 | 开考前可测量性检查（不通过阻止开考+管理员待办） | ✓ SATISFIED | 三态 409 + 不建会话断言 + todos 新键 |
| REF-5.10 | 01-03 | score→report 串行（零步断裂修复） | ✓ SATISFIED | test_ui_main_chain_score_report_serial（API-only 断言、无直调掩盖） |
| REF-8.2 | 01-03 | completed 会话重复评分/报告护栏 | ✓ SATISFIED | 服务层 ValueError + API 409 双端点，report 行数仍 1 |
| REF-8.5 | 01-04 | 模型 items 为空不阻断开考 | ✓ SATISFIED | 空模型/inactive 岗位均 409 MODEL_NOT_MEASURABLE |

**孤儿检查：** REQUIREMENTS.md Phase 1 行登记 8 项 REF（REF-1.1, 1.2, 1.5, 2.2, 3.5, 5.10, 8.2, 8.5），四个 PLAN frontmatter 声明的 requirements 集合并集与之完全一致——无 ORPHANED、无遗漏。支撑的 REQ-interactive-multiturn-assessment / REQ-talent-profile-report 属 Phase 2/5 深化，Phase 1 交付其链路修复前提（REQUIREMENTS.md Traceability 明确）。

### Anti-Patterns Found（含 01-REVIEW.md 发现的代码级核实）

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| server/services/readiness.py | 51, 58-60, 76-77, 86-88, 112-116 | 四个失败分支 return 前未 conn.close()（REVIEW CR-02 核实属实：仅成功路径 :116 有 close） | ⚠️ Warning | 依赖 CPython 引用计数兜底回收；代码卫生缺陷，不破坏任何 SC 行为（三态 409 测试全 PASS）。建议 try/finally 收口 |
| server/services/question_bank.py | 74-75 | finished_at CASE 无 ELSE（REVIEW CR-03 核实属实） | ⚠️ Warning | 已终态行的后续更新会清空完成时间；当前调用序列下多数无感，属审计字段保护不足，不影响 SC-3 断言 |
| server/services/question_bank.py + server/api/admin/models.py | 83-151 / 102-112 | FAILED 后无重触发入口（REVIEW CR-01：全仓库无 retry 路由；再次 confirm→409"模型已确认"） | ⚠️ Warning | D-12 计划决策层"可手动重触发"未闭环；SC-3 字面要求（409+error_code+管理员待办+绝不建 0 题会话）全部满足，retry 归 Phase 4（REF-8.4）邻接范围。待 todo 已能暴露问题岗位 |
| server/api/admin/models.py | 98-115 | task 行插于 confirm 主事务外，插行失败无补偿（REVIEW WR-03 核实属实） | ⚠️ Warning | 低概率窗口；确认态与 QUEUED 行非原子。属质量债，不影响 SC |
| server/api/assessment.py | 329-340 | get_report_by_session 第一步查询无 ownership，两种 404 文案不同（REVIEW WR-05：报告存在性 oracle） | ⚠️ Warning | B 仍得 404（SC-1 字面满足）；信息泄露量小，与统一 404 语义目标相悖，建议 join session 限定 |
| server/api/admin/positions.py | 63-69 | review_position reject 直接 DELETE position，FK 开启下遇子表（含新 question_bank_task）数据→IntegrityError 500（REVIEW CR-04 核实属实） | ⚠️ Warning | P1 既有路由与新表的 FK seam，非本阶段 SC 范畴；建议补 409 可解释拒绝 |
| server/services/question_bank.py | 110-124 | 幂等粒度按 item 整体跳过（REVIEW WR-04） | ℹ️ Info | 重触发路径尚不存在（CR-01），当前无实际触发面 |

**债务标记门：** 所有本阶段修改文件扫描 TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER——零命中。readiness.py 第 6/7 步「no-op 占位（Phase 2-4/Phase 3 填充）」为 PLAN 明文设计（D-11），非未完成债务。

**REVIEW 结论权衡（per 任务指令）：** 4 Critical 发现经代码核实全部属实，但逐条对照五条 Success Criteria——没有一条 SC 字面要求 retry 入口、连接 close 纪律、finished_at 保护或 reject 500 处理。全部归类为 Warning（不阻断本阶段验收，作为后续阶段改进输入）；CR-01 与 Phase 4 REF-8.4（题库生成失败可见/处理）邻接，判断上归后续阶段消化而非本阶段 gap。

### Human Verification Required

[全部完成 — 2026-09-03 人工 UAT 三项全部通过（01-HUMAN-UAT.md）：1) UI 主链浏览器走查（finish→报告页，真实雷达图与逐题明细）；2) 开考被拒 409 中文提示走查；3) admin 完成测评进报告页不被 route guard 弹回]

### Gaps Summary

**无失败 truth。** 五条 Success Criteria 全部经代码检查与独立复跑的测试证明：越权矩阵（10 用例）、主链串行+护栏+三态（11 用例）、m5/m6/m7 回归（7+41+5）全绿，前端构建通过，DDL 幂等，eval 冒烟符合预期预种子行为。

01-REVIEW.md 的 4 Critical 经代码核实属实，但均在 Success Criteria 字面范围之外（retry 入口、连接卫生、审计字段保护、既有路由 FK seam），按 GSD gates 属 advisory——已列为 Warning 供后续阶段与 code-review 跟踪消费，不构成本阶段 gap。唯一无法自动化裁决的是三项 UI 层走查（视觉渲染、提示文案、admin 浏览器流程），已列入 human_verification 待人工确认。

---

_Verified: 2026-09-03T12:35:00Z_
_Verifier: Claude (gsd-verifier)_
