---
phase: 02-dynamic-selection
plan: 02
subsystem: assessment-runtime
tags: [dynamic-selection, quota-formula, pytest, fastapi, sqlite]

# Dependency graph
requires:
  - phase: 02-01-table-evolution
  provides: assessment_question 动态实例列（selection_reason/selection_policy_version/item_id/status/activated_at/uq_aq_session_seq）+ CATEGORY_RATIO 7:3 口径 + 测试纪律模板
provides:
  - select_next_question(session_id) 四层动态选题 + plan_quotas/largest_remainder_73/tier_targets 纯函数
  - create_session 零预选（SC-1）；每次 action=next 动态实例化 + selection_reason 七键 JSON 落库（D-18）
  - required 刚性例外（§10.5：medium 优先/hard 兜底/例外每 item 一次 + REQUIRED_EXCEPTION_GRANTED + PATH_UNAVAILABLE）
  - readiness 第 5 步与选题共享 plan_quotas（同源公式防漂移）
  - config.ORDINARY_PLAN_N = 10（关口 A 用户裁决 [02-007]——生产默认值）
  - legacy 会话（selection_reason 全 NULL）续答走旧 seq 派发不 500（Q5）
affects: [02-04-interview（finish 唯一触发源已移位——is_last 降级逻辑待裁决层统一）, 02-05-scoring（评分消费动态实例）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - 层②required 优先在配额剩余槽位内（quota-bounded required_first——§10.5 例外的语义入口）
    - 配额槽位全满即返回 None（不越配额 fallback 补位——"池耗尽即 finish"计划口径）
    - 决策 finish 在池未空时降级 next（is_last 旧口径失真——02-04 裁决层接管前的过渡）

key-files:
  created:
    - server/test_phase2_selection.py
  modified:
    - server/services/question_selection.py
    - server/services/readiness.py
    - server/api/assessment.py
    - server/config.py
    - server/test_question_bank.py
    - server/test_m5_backend.py
    - server/test_p0_security.py
    - server/test_p0_chain.py

key-decisions:
  - "层② uncovered required 优先必须 quota_remaining 内（否则例外分支不可达）"
  - "决策 finish 在池未空时降级 next——is_last 基于旧静态预选，动态实例化下所有 next 轮都会误判 finish"
  - "例外 granted 双载体：selection_reason JSON 的 layer='exception' + REQUIRED_EXCEPTION_GRANTED 事件 payload item_id"
  - "p0_chain/p0_security 经验 item 挂 gate=1（SSOT §9.1 experience 走表单）——保报告 non-gate 无 no_data 语义"

patterns-established:
  - "tier_targets 可用量 clamp + 优先级回落（required > preferred > plus）"
  - "例外测试构造法：weight 最低 required item 被 tier 目标挡在普通计划外（granted 态）+ model_id 挂他人排除（PATH_UNAVAILABLE 态）双态一会话"

requirements-completed: [REF-3.1, REF-3.2, REF-3.6, REF-4.1]

# Metrics
duration: 41min
completed: 2026-09-04
---

# Phase 2 Plan 02: 四层动态选题 Summary

**select_next_question 四层选题全量重写（N+7:3 最大余数+tier 公式+sha256 稳定种子）+ 三 API 消费点迁移与 readiness 同源预检——会话零预选、每 next 即时实例化、selection_reason 七键可审计**

## Performance

- **Duration:** 41 min（08:09 UTC – 08:50 UTC）
- **Started:** 2026-09-04T08:09:14Z
- **Completed:** 2026-09-04T08:50:18Z
- **Tasks:** 5/5（4 auto + 1 checkpoint 免停车）
- **Files modified:** 9（1 新建 + 8 修改）——与 files_modified 严格一致

## Accomplishments

- question_selection.py 全量重写：largest_remainder_73 / tier_targets（clamp+优先级回落）/ plan_quotas 纯函数 + select_next_question 四层（①合法过滤含 model_id 版本近似放行 ②quota-bounded required 优先 ③配额实时扣减 ④chain 后继→weight 降序→random.Random(seed) tie-break）
- 会话创建零预选（SC-1）；get_session 首题派发 + legacy seq 兜底；submit_answer next 分支替换为 select_next_question（commit 后新事务）；池耗尽→finish（SESSION_COMPLETED 复用既有写点）
- selection_reason 七键 + nth JSON（ensure_ascii=False）+ QUESTION_SELECTED/QUESTION_ACTIVATED 双事件同事务 + selection_policy_version='p2'
- required 刚性例外（§10.5）：N 耗尽后 uncovered required 每 item 一次 medium 补选（无 medium 才 hard）+ REQUIRED_EXCEPTION_GRANTED 事件；无候选 → PATH_UNAVAILABLE 不静默
- readiness 第 5 步换 plan_quotas 同源预检（CR-04 类目口径保持）；CATEGORY_QUOTA 全库零残留
- experience/qualification 剔除普通选题（SC-2；p0 系种子经验 item 挂 gate=1 走表单语义）
- 测试全绿：test_phase2_selection 9/9、test_m5 7/7、test_question_bank 脚本 25/25、test_p0_security 10/10、test_p0_chain 11/11、02-01 回归（migration 8/8 + weights 5/5）

## Task Commits

1. **Task 1: 红测（配额公式 + API 级动态选题断言）** - `3ce1e5b` (test, RED)
2. **Task 2: question_selection 全量重写** - `1316c76` (feat)
3. **Task 2 修正（层②配额内语义 + 种子 tie-break + 例外链路）** - `70854f6` (fix)
4. **Task 3: readiness + assessment 三消费点** - `cefa045` (feat，含 config.ORDINARY_PLAN_N 提前落地)
5. **Task 4: 既有测试断言重写 + 种子补齐** - `1a4b71f` (test)
6. **Task 5: N 默认值 checkpoint** - 免停车（关口 A 裁决 [02-007]，见下）

## Checkpoint Resolution [02-007]

N=10 经关口 A 用户裁定 [02-007]（2026-09-04，02-DECISIONS.md），Task 5 免停车。
config.ORDINARY_PLAN_N = 10 行尾注释按「2026-09-04 关口 A 用户裁决（02-DECISIONS [02-007]）」书写。
[02-007] 条目已补执行落点记注（02-DECISIONS.md 原子于本 plan 收尾 commit）。

## Files Created/Modified

- `server/services/question_selection.py` - 全量重写（434→516 行）：纯函数区 + 四层主函数 + 例外分支 + legacy 兜底 + 零 LLM
- `server/services/readiness.py` - 第 5 步 plan_quotas 同源预检（tier 可用量 LEFT JOIN 统计）；docstring 口径改 §10.1-10.3
- `server/api/assessment.py` - create_session 删预选、get_session 动态派发+legacy 分支+N+E 口径、submit_answer select_next_question+池耗尽 finish+决策 finish 降级 next
- `server/config.py` - ORDINARY_PLAN_N = 10（SSOT §31-1 开放参数经关口 A 用户裁决 [02-007]）
- `server/test_phase2_selection.py` - 新建：9 测试（配额四样例/tier 边界/单类退化/零预选/逐 next 递增/experience 剔除/followup 不增/required 例外双态/legacy 冒烟）
- `server/test_question_bank.py` - test_selection 改 select_next_question 服务级断言（脚本式保持 25/25）
- `server/test_m5_backend.py` - 断言重写（question_count 删键+aq=0、新配额、experience 剔除、逐题 GET 闭链）
- `server/test_p0_security.py` - 种子补齐（Docker hard+1、冲突协调 required soft item+题行）——D-09 只加行
- `server/test_p0_chain.py` - 种子补齐（同款）+ 经验 gate=1 + _answer_whole_session 逐题 GET 循环 + :390 单题取题 + :490 注释口径

## Decisions Made

- 层② uncovered required 优先必须经 _quota_remaining 过滤：否则 required 恒被优先、例外分支（§10.5）永不触发——「required 覆盖让位于配额边界」正是例外的语义入口
- 配额槽位全满返回 None 而非 fallback 越配额补位（大类达标=计划完成；未达 N 即题库量不足口径，不越限）
- 决策 finish 在池未空时降级 next（API 层过渡逻辑）：decide_next_action 的 is_last 按「无未答实例」计算，动态实例化下作答第 k 题时第 k+1 题尚未实例化 → 伪 finish——02-04 裁决层统一接管（02-04-PLAN 已记 is_last 语义废除）
- 例外 granted 判定双载体：selection_reason JSON（layer='exception' + item_id）+ REQUIRED_EXCEPTION_GRANTED 事件 payload——每 item 一次约束在两处收敛
- covered 判定按实例 bank_question_id → (std_name, category) 匹配 competency_item（不依赖 aq.item_id 回填）
- p0 系种子经验 item 挂 gate=1：experience 不再占普通题后无 no_data 语义（SSOT §9.1 表单事实核验）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] workaround 层②语义——uncovered required 无配额约束**
- **Found during:** Task 2 首版运行（例外测试无法构造触发）
- **Issue:** 首版层②对 uncovered required 无配额过滤 → required 恒被优先选中、§10.5 例外分支不可达；且决策 is_last 伪 finish 使会话在第 N-1 题提前终止
- **Fix:** 层②加 _quota_remaining 过滤 + 配额槽满返回 None + submit_answer 决策 finish 在池未空时降级 next（is_last 语义移位属 02-04 计划范围，本计划先以池耗尽为 finish 唯一触发源——plan <消费点改造位置> 预留的最小形态）
- **Files modified:** server/services/question_selection.py, server/api/assessment.py, server/test_phase2_selection.py
- **Verification:** test_phase2_selection 9/9 全绿（含例外双态：granted medium + PATH_UNAVAILABLE）
- **Committed in:** 70854f6 / cefa045

**2. [Rule 3 - Blocking] config.ORDINARY_PLAN_N 提前至 Task 3 批次落地**
- **Found during:** Task 3 测试运行（ImportError: config 无 ORDINARY_PLAN_N）
- **Issue:** 计划将 config 常量归 Task 4，但 Task 3 的 readiness/selection/测试已 import 该常量——严格按任务切分会留下不可运行中间态
- **Fix:** Task 3 批次先落地常量（值实为关口 A 裁决 [02-007] 的 10——非占位，见 Checkpoint Resolution）
- **Files modified:** server/config.py
- **Committed in:** cefa045（Task 3 提交内）

**3. [Rule 1 - Bug] 例外测试种子两轮重设计（plan >interfaces> 微调）**
- **Found during:** Task 3/4 间迭代
- **Issue:** 原构想「单 required item 题排序靠后」在层②逐轮优先 uncovered required 的实现下不可构造（required 第一轮即被选中）
- **Fix:** 采用「5 个 required hard item 抢 4 个 required tier 槽——权重最低者（MySQL）被挡在普通计划外」构造 granted 态 + 「model_id 挂他人排除出候选池」构造 PATH_UNAVAILABLE 态，两会话双态覆盖 §10.5 全行为
- **Files modified:** server/test_phase2_selection.py
- **Verification:** test_required_exception_after_exhaustion 全绿
- **Committed in:** 70854f6

---

**Total deviations:** 3 auto-fixed（1 bug + 1 blocking + 1 测试构造微调）
**Impact on plan:** 全部为正确性必需（例外可达性/is_last 过渡/批次依赖），无范围蔓延

## Issues Encountered

- 调试用临时脚本 server/_debug_selection.py（未提交、工作区未跟踪文件）：选题序列 trace 用，已退役为占位注释。**删除需用户本人执行**：`! rm server/_debug_selection.py`（settings 拒绝 agent 删除）
- decide_next_action 的 is_last 旧口径与动态实例化的交互已按计划 <消费点改造位置> 预留口径过渡处理（API 层降级 next）；02-04 两层化时按其 PLAN 移入裁决层——非本计划遗留缺陷

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 动态选题三消费点就位：02-04（submit_answer followup_count 迁列 + 封存三路 + 裁决层 finish 接管）、02-03（难度状态机在 select_next_question 层④ chain 后继扩展）、02-05（评分消费动态实例 + N+E 分母口径）均可直接续接
- selection_reason JSON 已落库：Phase 5 证据链 / Phase 6 E2E 断言可消费
- legacy 会话兜底行为已锁测试（Q5）
- 无阻塞

## Self-Check: PASSED

- 文件存在：9/9 files_modified 与实际 diff 集严格一致（git diff --stat 核对）
- 提交存在：3ce1e5b / 1316c76 / 70854f6 / cefa045 / 1a4b71f 全在 worktree 分支（git log 核对）
- 测试全绿：test_phase2_selection 9、test_m5 7、test_question_bank 25、test_p0_security 10、test_p0_chain 11、test_phase2_migration 8、test_phase2_weights 5
- CATEGORY_QUOTA 全库 grep 零命中
- N 默认值经关口 A 用户裁决 [02-007]（Task 5 免停车）

---
*Phase: 02-dynamic-selection · Plan: 02-02（wave 2/5）*
*Completed: 2026-09-04*
