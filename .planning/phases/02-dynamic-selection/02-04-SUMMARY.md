---
phase: 02-dynamic-selection
plan: 04
subsystem: assessment-runtime
tags: [interviewer, two-layer, pydantic, observation, adjudication, refusal-sealing, pytest, sqlite]

# Dependency graph
requires:
  - phase: 02-01-table-evolution
    provides: assessment_question 动态实例列（followup_count/closed_at/seal_reason/item_id/status）+ uq_aq_session_seq
  - phase: 02-02-dynamic-selection
    provides: select_next_question 四层动态选题 + 池耗尽即 finish + ORDINARY_PLAN_N=10 + submit_answer next 分支已调 select_next_question
provides:
  - InterviewObservation/ObservationDims Pydantic 模型（ANSWER_STATES 11 态 Literal + 观察维度 + 可选 score_live 1-5）
  - decide_next_action 内部两层化（签名逐字不变）：观察层 call_llm_json→InterviewObservation(**result)（ValidationError 降级 MODEL_UNCERTAIN 不卡死）+ 裁决层 classify_observation/decide_action 纯函数
  - _mock_interview 重写为规则分类器（拒答词/长度/实义词三向 + 长但空粗判），输出观察契约不出 action（D-23）
  - 拒答确认流：首次 DECLINED → action=confirm（一次性固定话术）；二次 DECLINED → refused 标记键 + 封存 seal_reason='refused' + QUESTION_SEALED + 下一题派发（D-24）
  - followup 计数迁列（assessment_question.followup_count，assistant 消息同事务段自增；FOLLOWUP_MAX≤2 硬约束保持）
  - 三路封存（answered/refused；timeout 枚举位预留）closed_at + seal_reason 落库（D-25）
  - OBSERVATION_CLASSIFIED（每次决策后）+ EVIDENCE_EVALUATED（封存时机，轻量 stable=sufficient_in_row≥2 A2 决议）事件留痕
  - INTERVIEWER_SYSTEM prompt v2：输出契约对齐 InterviewObservation（action 键移出 LLM 输出，"你不决定 action/难度/结束"）
affects: [02-03-difficulty（难度状态机消费 observation 布尔 + EVIDENCE_EVALUATED payload）, 02-05-scoring（拒答 REFUSED 评分写入消费 sealed refused 实例）, Phase 3 错误处理（MODEL_UNCERTAIN 人工通道/INJECTION 事件）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - 观察层/裁决层分离（LLM 只出结构化观察，代码纯函数布尔裁决 + action 决定——REF-1.6/1.7）
    - 内部值 seal_refused + 标记键 refused 透出（API 面对外仍 next——5 键契约只加不减的最小侵入）
    - mock 双轨分类器（模拟观察输出而非绕过裁决——与真实模式共用 Pydantic+裁决层）

key-files:
  created:
    - server/test_phase2_interview.py
  modified:
    - server/schemas.py
    - server/services/interview.py
    - server/services/prompts/interviewer.py
    - server/api/assessment.py
    - server/test_m5_backend.py
    - server/test_question_bank.py

key-decisions:
  - "seal_refused 内部值在 API 层透出为 next + refused 标记键（sse.js 对未知 action 值会破——只加不减原则的最小侵入）"
  - "confirm 痕迹口径取消息表 action=='confirm' 计数（现有口径零新增结构）"
  - "stable_evidence 轻量版＝同 item sufficient_in_row≥2（OBSERVATION_CLASSIFIED payload 布尔聚合；item_id NULL（legacy）恒 False）"
  - "m5 long_answer 补'结果'实义词（D-09：新分类器下长答须含实义词才走充分证据路径——score_live 3/2 不变式保持）"

patterns-established:
  - "Pydantic 消费 + ValidationError 降级 MODEL_UNCERTAIN（aggregate.py:77 先例推广到 interviewer）"
  - "裁决纯函数签名分离：classify_observation(obs)->(bool,dict) 与 decide_action(state,sufficient,followups,confirmed,exhausted)->(action,extra)（不持 conn）"

requirements-completed: [REF-1.3, REF-1.6, REF-1.7, REF-4.3, REF-4.4, REF-4.5]

# Metrics
duration: 13min
completed: 2026-09-04
---

# Phase 2 Plan 04: interviewer 两层化重构 Summary

**观察层（InterviewObservation Pydantic 11 态）+ 裁决层（代码纯函数布尔/规则 1-7）分离落地——拒答 confirm-then-seal、followup 迁列、三路封存与 OBSERVATION/EVIDENCE 事件最小集全绿**

## Performance

- **Duration:** 13 min（09:06 UTC – 09:19 UTC）
- **Started:** 2026-09-04T09:06:22Z
- **Completed:** 2026-09-04T09:19:33Z
- **Tasks:** 3/3（全 auto，TDD：Task 1 红 → Task 2/3 绿）
- **Files modified:** 7（1 新建 + 6 修改——6 在 files_modified + 1 断言适配越界，见偏差区）

## Accomplishments

- schemas.py 新增 ANSWER_STATES 11 态 Literal + ObservationDims（relevance/specificity/attribution 必填 + 4 个 Phase 5 留白维度）+ InterviewObservation（含可选 score_live 1-5——REF-1.3 LLM 直产归观察层）
- interview.py 两层化（决定权移交代码）：call_llm_json → InterviewObservation(**result)（ValidationError 降级 MODEL_UNCERTAIN dims 全默认不卡死）→ classify_observation 布尔（§11.3 排除清单代码化：VALID_EVIDENCE 且 relevance/attribution/具体度≥1 且无矛盾/不确定）→ decide_action 规则 1-7（DECLINED confirm→seal_refused；MODEL_UNCERTAIN 不猜测直接 next；七类特殊态不扣分不猜疑 next 推进）
- _mock_interview 规则分类器（_DECLINE_WORDS/_EVIDENCE_WORDS 模块级元组 + reverse 找"候选人："行手法保留）：拒答词→DECLINED(dims 全 False/0)、<20 字→NEED_CLARIFICATION、实义词→VALID_EVIDENCE(spec=2/attr=True)、长但空→VALID_EVIDENCE 粗判(spec=1/attr=False 交裁决判不足)——mock 模拟观察非绕过裁决（D-23）
- submit_answer 消费扩展：followup_count+1 同事务自增（D-25 迁列）；refused 分支封存（closed_at+seal_reason='refused'+QUESTION_SEALED）后照 next 派发、零 question_score 行（评分归 02-05）；answered 分支补 closed_at+seal_reason='answered'（三路统一）；OBSERVATION_CLASSIFIED 每决策后落、EVIDENCE_EVALUATED 封存时机落（轻量 stable 判据）
- INTERVIEWER_SYSTEM v2：输出契约对齐 InterviewObservation（answer_state 11 值列全 + observation 维度 + score_live 可选 + 明确"你不决定 action/难度/结束"）；docstring 版本注释升 v2
- is_last 语义废除：interview.py 不再强制 finish（02-02 池耗尽是唯一触发源）——guard 段迁移后 FOLLOWUP_MAX 硬约束保持

## Task Commits

1. **Task 1: 红测（分类三向 + 拒答流 + Pydantic 拒绝 + 5 键契约）** - `2f00b81` (test, RED——InterviewObservation 尚不存在的 ImportError 红)
2. **Task 2: schemas + interview 两层化 + mock 分类器 + prompt v2** - `e6103ff` (feat)
3. **Task 3: assessment.py 封存/迁列/事件 + m5/question_bank 断言适配** - `0cdfdd8` (feat)

## Files Created/Modified

- `server/schemas.py` - ANSWER_STATES/ObservationDims/InterviewObservation（含可选 score_live Field(None, ge=1, le=5)）
- `server/services/interview.py` - 两层化重写（116→261 行）：签名逐字保持；classify_observation/decide_action 纯函数；_mock_interview 分类器重写；_count_followups 改读列；_is_confirmed_refusal 消息表口径；_CONFIRM_REPLY 常量
- `server/services/prompts/interviewer.py` - INTERVIEWER_SYSTEM v2 输出契约段（:13-20 → 观察 JSON 结构）；docstring v2
- `server/api/assessment.py` - submit_answer 消费扩展（refused 分支 + followup_count 自增 + 三路封存 + OBSERVATION/EVIDENCE 事件）+ _stable_evidence_light/_question_item_id helper
- `server/test_phase2_interview.py` - 新建：12 测试（三向分类/长但空/拒答二次封存 DB 级断言/followup 硬约束迁列/Pydantic literal_error/11 态白名单/5 键契约/扩展键/两组事件）
- `server/test_m5_backend.py` - D-09：long_answer 补实义词（2 行：注释 + 文案）——:290 final_score 断言未动（02-05 改）
- `server/test_question_bank.py` - D-09：interviewer SYSTEM 断言切观察契约（action 协议断言已失效——见偏差 1）

## Decisions Made

- seal_refused 内部值不在 API 面透出：decision dict 的 action 键写 "next" + refused=True 标记键——sse.js 只认 followup/next/finish，未知 action 值会破裂（plan 裁决规则 2 的实现取舍照录）
- confirm 痕迹判定用消息表 action=='confirm' 计数（现成口径，不新增结构——plan Task 2 action 给的两个选项中取消息表查询）
- EVIDENCE_EVALUATED 的 stable 轻量判据＝事件表 OBSERVATION_CLASSIFIED payload 按 item_id 聚合 sufficient 计数 ≥2（含本次）；item_id NULL（legacy 实例）恒 False——A2 决议 Phase 2 边界
- m5 long_answer 文案补"结果"实义词：新分类器下原 45 字"性能优化"文案不含实义词会走"长但空"路径 followup——与 plan <interfaces> "分类器在 evidence/empty 路径分别给 3/2" 的断言保持口径一致

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_question_bank.py 的 interviewer SYSTEM 断言崩坏（files_modified 外的回归适配）**
- **Found during:** Task 3 验证（test_question_bank 25 通过 1 失败）
- **Issue:** :192 断言 INTERVIEWER_SYSTEM 含 ("followup","next","finish","score_live")——Task 2 按 plan 锁定将 action 键从 prompt 移除后该断言必然失败
- **Fix:** 按 D-09 只改断言语义来源：断言含 ("answer_state","observation","specificity","score_live") 且不含 "followup"
- **Files modified:** server/test_question_bank.py（plan files_modified 之外的第 7 文件）
- **Verification:** python test_question_bank.py → 25 通过 0 失败
- **Committed in:** 0cdfdd8（Task 3 提交内）

**2. [Rule 1 - Bug] Task 1 测试数据自撞词表（_LONG_EMPTY_ANSWER 含"具体"实义词）**
- **Found during:** Task 2 首轮验证（test_mock_classifier_long_but_empty 实得 next）
- **Issue:** 测试的"长但空"文案含"具体"（_EVIDENCE_WORDS 成员）→ 走充分证据路径而非粗判路径——plan Task 1 action 已预告"答案文案避开列表外相近词"，数据构造时漏检
- **Fix:** 文案去"具体"（保持 57 字长度、拒答词零命中）
- **Files modified:** server/test_phase2_interview.py
- **Verification:** test_mock_classifier_long_but_empty 全绿（VALID_EVIDENCE + spec=1/attr=False → followup）
- **Committed in:** e6103ff（Task 2 提交内——与实现同批转绿）

**3. [Rule 1 - Bug] Task 1 测试自身的 ObservationDims 构造缺必填键（attribution）**
- **Found during:** Task 2 首轮验证（test_pydantic_accepts_all_11_states ValidationError: attribution missing）
- **Issue:** 测试构造 ObservationDims(relevance=True, specificity=1) 漏必填 attribution——red 阶段照 <interfaces> 手写样式的笔误
- **Fix:** 补 attribution=False
- **Files modified:** server/test_phase2_interview.py
- **Verification:** test_pydantic_accepts_all_11_states 全绿
- **Committed in:** e6103ff（Task 2 提交内）

---

**Total deviations:** 3 auto-fixed（2 测试数据/断言修正 + 1 files_modified 外回归适配）
**Impact on plan:** #1 是 plan 作用的必然涟漪（prompt 契约变更的下游断言），#2/#3 是红测数据笔误——无范围蔓延；#1 使实际 diff 集 = files_modified + test_question_bank.py（7 文件）

## Issues Encountered

- 调试用临时脚本 server/_dbg_followup.py（未提交、工作区未跟踪文件）：Task 2 中间态排查 followup_count 迁列（确认 API 层 UPDATE 归 Task 3 后删除性使用完毕）。**删除需用户本人执行**：`! rm server/_dbg_followup.py`（settings 拒绝 agent 删除）
- Task 2 提交时 5 个测试红属预期中间态（API 消费归 Task 3——plan 任务切分即如此设计：Task 2 verify 的失败模式与 Task 1 的 RED 不同源，为 assessment.py 未消费扩展键所致）；Task 3 后 12/12 全绿
- test_m6_backend.py 须按文件头以脚本方式运行（python test_m6_backend.py，非 pytest——"no tests ran" 是运行方式差异非缺陷）：41 通过 0 失败

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 02-03（难度状态机）：observation 布尔（answer_state/evidence_sufficient）在 decision dict 与 OBSERVATION_CLASSIFIED/EVIDENCE_EVALUATED payload 就位；stable 轻量判据已按 A2 落地（sufficient_in_row≥2）
- 02-05（拒答 REFUSED 评分）：sealed refused 实例（closed_at+seal_reason='refused'）+ QUESTION_SEALED 事件就位；本计划零 question_score 行产生（grep 确认）
- Phase 3：MODEL_UNCERTAIN 降级路径已保证不卡死（test 覆盖间接）；INJECTION_DETECTED 事件与人工通道完整化留其范围
- legacy 会话兼容：_stable_evidence_light 对 item_id NULL 恒 False（不炸）；confirm 消息口径不依赖新列
- 无阻塞

## Self-Check: PASSED

- 文件存在：7 个实际 diff 文件全部确认（git diff --name-only 0813573..HEAD）
- 提交存在：2f00b81 / e6103ff / 0cdfdd8 全在 worktree 分支（git log 核对）
- 测试全绿：test_phase2_interview 12/12、test_m5_backend 7/7；回归 test_phase2_migration 8、test_phase2_selection 9、test_phase2_weights 5、test_p0_chain 11、test_p0_security 10、test_m6_backend（脚本）41、test_question_bank（脚本）25
- decide_next_action 签名逐字保持（grep :192 确认）
- eval 兼容预检（Pitfall 10）：virtual_candidates INSERT assessment_message 仍只写 role/content——本计划未加任何 NOT NULL 无默认列
- files_modified 偏差：+test_question_bank.py（偏差 1 已记）

---
*Phase: 02-dynamic-selection · Plan: 02-04（wave 3/5）*
*Completed: 2026-09-04*
