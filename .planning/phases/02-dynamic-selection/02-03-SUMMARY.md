---
phase: 02-dynamic-selection
plan: 03
subsystem: assessment-runtime
tags: [difficulty-state-machine, path-snapshot, pure-function, events, pytest, sqlite]

# Dependency graph
requires:
  - phase: 02-01-table-evolution
    provides: assessment_question.path_state_snapshot 列（TEXT，ALTER+_DDL 双轨已建）
  - phase: 02-02-dynamic-selection
    provides: select_next_question 四层选题 + 实例 difficulty 列写入 + 事件同事务惯例 + append_event 取号模式
  - phase: 02-04-interviewer-two-layer
    provides: decision 扩展键（answer_state/evidence_sufficient）+ 三路封存（closed_at+seal_reason）+ followup_count 迁列
provides:
  - next_difficulty 纯函数（§11.2 全判据：升 easy→medium 一次充分 / medium→hard 充分且稳定 + required_level>4 / 降级 fail≥2 或 followup 模糊（easy 不降）/ 恢复滞回（两次充分或一次稳定）/ 跳级禁止（easy 永不直迁 hard））
  - advance_snapshot 计数器推进（充分→in_row+1 清 fail；有效失败→fail+1 清 in_row；七类排除 is_valid_failure=False 计数器不动）
  - update_path_state 持久化（读前一封存行 snapshot → 推进 → 判定 → UPDATE 当次封存行 + DIFFICULTY_RAISED/LOWERED/RESTORED 事件 payload 四键——同事务不 commit）
  - assessment.py 封存点接入（answered/refused 两分支，followup 分支不触发——一次实例内不升降）
  - question_selection.py 难度承接（_snapshot_target_difficulty + _apply_snapshot_difficulty：item 有 snapshot 时按 current_difficulty 过滤候选池；无该档落回可得最高档不高于目标）
  - server/test_phase2_difficulty.py（10 测试全绿：表驱动 8 + 集成 2）
affects: [02-05-scoring（sealed 实例上的 snapshot 可作为评分上下文）, Phase 5 证据链（stable_ever/sufficient_in_row 计数器可复审）, Phase 6 E2E（难度路径行为可断言）]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - 纯函数裁决（next_difficulty 不持 conn）与持久化（update_path_state 接 conn 不 commit）分层
    - snapshot 读取排除当前封存行（question_id<>?）——当前行是本次状态的目标载体不是读取源
    - snapshot 行序按 seq 而非 closed_at（同一秒时间戳并列会破坏「最新」语义）
    - 事件 payload 判据摘要（criterion 常量 + evidence_counts 计数镜像——Pitfall 5）

key-files:
  created:
    - server/services/difficulty.py
    - server/test_phase2_difficulty.py
  modified:
    - server/api/assessment.py
    - server/services/question_selection.py

key-decisions:
  - "is_valid_failure 计算留在 assessment.py（七类 answer_state 元组模块级常量——difficulty.py 只认布尔，函数边界清洁）"
  - "封存点接入用 _advance_difficulty_state 单一 wrapper——next/finish 与 refused 两分支复用（grep 意图等价：两条封存路径都过状态机）"
  - "snapshot 初始 current_difficulty=easy（plan Simplicity 口径——不取实例行 difficulty，那是选题层第④层排序结果不是路径状态）"
  - "selection 难度承接落回规则：无目标档行时取「不高于目标档」的该 item 可得最高档（跳级禁止持续生效）"
  - "test_p0_chain 零改动——mock 决策走 VALID_EVIDENCE 充分路径无 DIFFICULTY_* 事件冲突，既有 sequence_no 断言天然兼容（D-09 无需适配）"

patterns-established:
  - "状态机服务三件套：判据纯函数（无 conn）→ 计数器推进纯函数 → 持久化函数（conn 归调用者）"
  - "跨行状态读取的行序锚定：ORDER BY seq（单调实例序）代替时间戳（同秒并列不可靠）"

requirements-completed: [REF-4.2]

# Metrics
duration: 100min
completed: 2026-09-04
---

# Phase 2 Plan 03: 难度路径状态机 Summary

**§11.2 全判据代码化为纯函数状态机（next_difficulty/advance_snapshot/update_path_state 三件套）+ 封存点接入（answered/refused 同事务 DIFFICULTY_* 事件含判据摘要四键）+ 选题层 snapshot 难度承接——10 项测试 + 6 套回归套件全绿**

## Performance

- **Duration:** 100 min（09:25 UTC – 11:05 UTC）
- **Started:** 2026-09-04T09:25:38Z
- **Completed:** 2026-09-04T11:05:00Z
- **Tasks:** 3/3（全 auto，TDD：Task 1 红 → Task 2/3 绿）
- **Files modified:** 4（2 新建 + 2 修改）——与 files_modified 5 项中的 4 项一致（test_p0_chain.py 零改动，见 Decisions）

## Accomplishments

- difficulty.py 新建：next_difficulty 纯函数（§11.2 判据逐条代码化——升/降/滞回/跳级禁止/easy 不降/required_level>4 门槛）+ advance_snapshot 计数器推进（七类排除语义在计数层实现：is_valid_failure=False 时两个计数器都不动）+ update_path_state 持久化（前一封存行读取 → 推进 → 当前行 UPDATE + 事件同事务；模块零 conn.commit）
- assessment.py 封存点接入：_advance_difficulty_state wrapper（is_valid_failure 按 §11.2 七类 answer_state 排除计算）在 answered（next/finish）与 refused 两个封存分支的最终 commit 之前调用；followup_ambiguous = 实例发生过 followup 且证据仍不充分（降级判据 2）；followup 分支（实例未封存）不触发状态机
- question_selection.py 难度承接：_snapshot_target_difficulty（各 item 最新封存 snapshot 的 current_difficulty 口径）+ _apply_snapshot_difficulty（候选池按 item 目标难度过滤；无该档行落回可得最高档、不高于目标档）；实例 INSERT 的 difficulty 列照旧写实际选中档
- test_phase2_difficulty.py 10 测试：表驱动 8（每个 §11.2 判据至少一行 + skip 全组合枚举 + advance_snapshot 计数不变式）+ 集成 2（LOWERED payload 四键断言 + snapshot==to_state 同事务断言；RAISED 后 selection 层承接 medium 断言）

## Task Commits

1. **Task 1: 红测（表驱动判据 + 集成断言）** - `1bb44d6` (test, RED)
2. **Task 2: difficulty.py 状态机服务** - `5263425` (feat)
3. **Task 3: 封存点接入 + selection 承接** - `023c36c` (feat, 含 Task 2 遗留的两处修正——见偏差 1/2)

## Files Created/Modified

- `server/services/difficulty.py` - 新建（206 行）：判据纯函数 + 计数器推进 + 持久化；CRITERION_* 常量事件判据摘要
- `server/test_phase2_difficulty.py` - 新建（397 行）：§11.2 表驱动 + 集成（事件 payload + 快照同事务 + 选题承接）
- `server/api/assessment.py` - _EXCLUDED_FAILURE_STATES 七类元组 + _advance_difficulty_state/_instance_followup_count helpers + 两封存分支接线（+68 行）
- `server/services/question_selection.py` - _snapshot_target_difficulty + _apply_snapshot_difficulty + _pick_ordinary 承接参数（+83 行）

## Decisions Made

- 七类排除清单写在 assessment.py 而非 difficulty.py（plan Task 2 action 的函数边界要求——UI 文件只认布尔，answer_state 语义归调用方）
- 封存点接入用单一 wrapper（grep "update_path_state(" 在 assessment.py 1 处但 _advance_difficulty_state 调用 2 处——两分支复用同一状态机接线，与 plan 「grep ≥ 2」意图等价，非字面量满足）
- snapshot 读取排除当前封存行（question_id<>sealed_question_id）：当前行是本次 UPDATE 的目标载体，其 snapshot 在首封存时为 NULL——不排除会把「最新」读成空导致状态丢失（见偏差 2）
- 行序锚定用 seq 不用 closed_at：测试环境下同秒封存多行时时间戳并列会破坏 ORDER BY closed_at DESC 的「最新」语义
- test_p0_chain.py 零改动：mock 长答案走 VALID_EVIDENCE 充分路径不触发 DIFFICULTY_* 事件；sequence_no 断言（严格递增 + 无重复）对新增事件行天然兼容——plan Task 3 预备的「若受影响只按 D-09 加宽松」分支未被激活

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] difficulty.py 漏掉 append_event import（Task 2 提交后集成测试暴露）**
- **Found during:** Task 3 集成验证（NameError: append_event is not defined）
- **Issue:** Task 2 全文件重写时丢失 from .state_events import append_event 一行（Task 2 提交时纯函数测试全绿掩盖了该缺陷——update_path_state 首次被集成路径触达才暴露）
- **Fix:** 补回 import（一行）
- **Files modified:** server/services/difficulty.py
- **Verification:** test_phase2_difficulty 10/10 全绿
- **Committed in:** 023c36c（Task 3 提交内）

**2. [Rule 1 - Bug] snapshot 读取含当前封存行 → 每次「最新」读到 NULL 重置状态**
- **Found during:** Task 3 集成验证（降级测试 fail 计数恒 1 不推进）
- **Issue:** update_path_state 的 snapshot 读取查询「该 item 最新 closed_at 行」——但当前正在封存的行（UPDATE 刚在同一事务置 closed_at）seq 最大且 snapshot 为 NULL（首封存）→ 每次都重新初始化 easy，RAISED 后的 medium 状态丢失
- **Fix:** 读取加 AND question_id<>?（排除当前封存行）+ 行序改 ORDER BY seq DESC（同秒时间戳并列问题一并消除）
- **Files modified:** server/services/difficulty.py（+ question_selection.py 的 _snapshot_target_difficulty 同步改 seq 序——selection 读发生在封存 commit 之后不含当前行，只受益于确定性排序）
- **Verification:** test_events_payload_and_same_transaction 转 GREEN（medium 两连失败 → LOWERED payload 断言全通过）
- **Committed in:** 023c36c（Task 3 提交内）

**3. [Rule 1 - Bug] Task 1 集成测试的两处设计错误（RED 阶段测试自身 bug，非实现缺陷）**
- **Found during:** Task 3 集成验证
- **Issue:** (a) test_events_payload 设计为「easy 直接两连失败 → LOWERED」——但 §11.2 easy 不降，从 easy 起步永不触发 LOWERED（测试构造性不可达）；(b) test_selection_reads_snapshot 答一题后直接断言「该 item 下一实例」——忽略三 item 配额下下一实例可能属其他 item
- **Fix:** (a) 改「先充分证据升 medium → 再两连有效失败 → LOWERED」（§11.2 真实序列：降级只可能发生在非最低档）；(b) 改循环答完其他 item 直到目标 item 再派发，断言其后续实例 difficulty=='medium'
- **Files modified:** server/test_phase2_difficulty.py
- **Verification:** 两集成测试转 GREEN；表驱动 8 项不受影响
- **Committed in:** 023c36c（Task 3 提交内——与接线修正同批转绿）

---

**Total deviations:** 3 auto-fixed（3 × Rule 1：1 个实现遗漏 import + 1 个读取语义 bug + 1 个红测构造错误）
**Impact on plan:** 全部为正确性必需（状态丢失会导致难度路径静默重置——正是 T-02-12 不可解释威胁面）；无范围蔓延；files_modified 的 test_p0_chain.py 零改动（plan 预备的适配分支未激活）

## Issues Encountered

- 调试用临时脚本 4 个（server/_dbg_difficulty.py、_dbg_e2e.py、_dbg_loop.py、_dbg_spy.py——未提交、工作区未跟踪）：状态机读取路径与 mock 分类器行为断点排查用。**删除需用户本人执行**：`! rm server/_dbg_difficulty.py server/_dbg_e2e.py server/_dbg_loop.py server/_dbg_spy.py`（settings 拒绝 agent 删除）
- 多测试文件同进程并发跑（pytest 一次传多文件）会因 DB_PATH import 时捕获只在首文件生效而互相污染（migration 测试的旧库种子会落到 interview 的临时库）——项目「单文件单进程」纪律本就要求逐文件跑，本计划全部验证按单文件循环执行（与 02-02/02-04 相同口径，非本计划引入）
- competency_item 表实际列名为 required_level（与 plan <interfaces> 的「medium→hard 门槛 required_level > 4」写法一致，無需适配——INT 类型比较直接可用）

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 02-05（评分链）：sealed 实例的 snapshot 列在升级/降级行上有值，评分消费不受影响；DIFFICULTY_* 事件已在事件表可审计
- Phase 5（证据链强化）：stable_ever/sufficient_in_row 计数器持久在 snapshot，跨实例复审可解析（Pitfall 5 的 evidence_counts 镜像与计数器实际值同步）
- Phase 6（E2E）：难度路径行为（升→降→恢复滞回）已被 test_selection_reads_snapshot 与表驱动测试锁定
- 测试全套绿：test_phase2_difficulty 10、test_p0_chain 11、test_p0_security 10、test_phase2_selection 9、test_phase2_interview 12、test_phase2_migration 8、test_phase2_weights 5、test_m5_backend 7、test_m6_backend（脚本）41、test_m7_backend（pytest）5、test_question_bank（脚本）25
- 无阻塞

## Self-Check: PASSED

- 文件存在：4 个实际 diff 文件（git diff 1bb44d6^..HEAD --name-only）全部在 files_modified 清单内；第 5 项 test_p0_chain.py 零改动（plan 预备分支未激活）
- 提交存在：1bb44d6 / 5263425 / 023c36c 全在 worktree 分支（git log 核对）
- 测试全绿：上述 11 套逐文件全绿
- next_difficulty 纯函数无 conn 参数（签名 def next_difficulty(snap: dict, *, ...) 核对）
- difficulty.py 零 conn.commit()（grep 核对——事务归调用者）
- 调试脚本 4 个为未跟踪文件（等待用户删除，不入版本库）

---
*Phase: 02-dynamic-selection · Plan: 02-03（wave 4/5）*
*Completed: 2026-09-04*
