---
phase: 02-dynamic-selection
plan: 01
subsystem: database
tags: [sqlite, migration, alter-table, weight-ratio, pytest]

# Dependency graph
requires:
  - phase: 01-p0-chains
    provides: question_bank_task 状态事件表等 v2 基线表结构 + test_p0_chain 测试纪律模板
provides:
  - question_bank 10 个 v2 新列（model 绑定/锚点/测量目标）+ §9.4 锚点回填（easy[2,3]/medium[3,4]/hard[4,5]）
  - assessment_question 12 个 v2 新列（question_type='legacy' 旧行语义/followup_count/selection_reason 等）+ uq_aq_session_seq UNIQUE(session_id, seq)
  - question_score.score_state（存量回填 'SCORED'）+ final_score→score_final COALESCE 合并（final_score 列保留至 02-05）
  - config.CATEGORY_RATIO 7:3 口径（0.7/0.3/0.0/0.0）+ _compute_weights total_ratio==0 纯 gate 保护
  - test_phase2_migration.py / test_phase2_weights.py 两套回归
affects: [02-02-dynamic-selection, 02-03-interview, 02-04-difficulty, 02-05-scoring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - PRAGMA table_info 列名集合嗅探 + 逐列 ALTER（幂等早退，N11 无 DB CHECK）
    - NOT NULL 新列带常量 DEFAULT；锚点两步法（裸 ADD + UPDATE CASE difficulty 回填）
    - 双轨纪律：_DDL CREATE 与 _migrate_* 同步加列（新库直建/老库 ALTER 两路径断言）
    - 唯一索引前置重复检测（GROUP BY HAVING raise RuntimeError，不静默去重）

key-files:
  created:
    - server/test_phase2_migration.py
    - server/test_phase2_weights.py
  modified:
    - server/db.py
    - server/config.py
    - server/services/aggregate.py

key-decisions:
  - "迁移函数对重复 (session_id, seq) raise RuntimeError 附行明细（不静默去重，T-02-01）"
  - "_DDL 的 uq_aq_session_seq 修正为 CREATE UNIQUE INDEX（与迁移路径 parity，Rule 1 修复）"
  - "纯 gate 模型 total_ratio==0 全部 weight=0.0 且跳过尾差吸收（防 drift=1.0 压给单个 gate item）"
  - "存量 confirmed 模型 weight 不重算（D-16：零 UPDATE，分数是历史事实）"

patterns-established:
  - "PRAGMA table_info 嗅探式 ALTER 迁移骨架（同一「先查再动 + 幂等早退」，02-05 复用 _v2 函数追加 DROP 段）"
  - "双路径迁移断言（老库模拟 _OLD_DDL + 新库直建）——wave 1 测试纪律模板"

requirements-completed: [REF-2.7, REF-2.9, REF-3.7, REF-5.7]

# Metrics
duration: 16min
completed: 2026-09-04
---

# Phase 2 Plan 01: 表结构演进 + 7:3 权重三落点 Summary

**三表 v2 新列双轨迁移（ALTER 嗅探 + 锚点回填 + score_final 合并 + 唯一索引）与 7:3 权重口径修正（含纯 gate 零比率保护）**

## Performance

- **Duration:** 16 min（04:52 UTC – 05:08 UTC）
- **Started:** 2026-09-04T04:52:25Z
- **Completed:** 2026-09-04T05:07:51Z
- **Tasks:** 3/3
- **Files modified:** 5（2 新建 + 3 修改）

## Accomplishments

- question_bank 加 10 个 v2 新列（model_id/model_version/item_id/question_type/measurement_stage/measurement_target/evidence_requirement/observable_level_max/observable_level_min/rubric_version），§9.4 锚点按 difficulty 两步法 CASE 回填，difficulty NULL 行保持 NULL
- assessment_question 加 12 个 v2 新列（旧行 question_type='legacy'、followup_count=0、status NULL=legacy）+ uq_aq_session_seq UNIQUE(session_id, seq)（Q2 决议：seq 承载 §12.2 sequence_no 语义），建索引前重复检测 raise
- question_score 加 score_state（存量回填 'SCORED'）+ final_score→score_final COALESCE 合并；final_score 列在 _DDL 与迁移后均保留（DROP 属 02-05 消费点切换后，A8 次序）
- CATEGORY_RATIO 5.5/2.0/2.0/0.5 → 0.7/0.3/0.0/0.0（SSOT §8.2）；_compute_weights 加 total_ratio==0 保护；存量模型 weight 零重算（无 UPDATE competency_item）
- 迁移双路径测试 8/8 + 权重回归 5/5 全绿；p0_chain(11)/p0_security(10)/m5(7)/m7(5)/m6 脚本(41) 回归全绿

## Task Commits

Each task was committed atomically:

1. **Task 1: 迁移双路径红测** - `29f55c6` (test)
2. **Task 2: db.py 三表双轨迁移** - `14afc7d` (feat)
3. **Task 3: 7:3 三落点** - `702787a` (test, RED) + `8b002c5` (feat, GREEN)
4. **Rule 1 修复: _DDL 唯一索引** - `38792f8` (fix)

**Plan metadata:** 见 final commit

## Files Created/Modified

- `server/db.py` - _DDL 三表加列（无新 CHECK，legacy CHECK 不动）+ _migrate_question_bank_v2/_migrate_assessment_question_v2/_migrate_question_score_v2 三个嗅探式迁移函数 + init_db 注册
- `server/config.py` - CATEGORY_RATIO 7:3 新口径（四键保留，注释含 D-16 存量不重算说明）
- `server/services/aggregate.py` - _compute_weights total_ratio==0 早退保护（唯一改动，7 行）
- `server/test_phase2_migration.py` - 老库模拟（内置 _OLD_DDL 旧三表 + 旧行直插）+ 新库直建双路径 8 断言
- `server/test_phase2_weights.py` - 7:3 三落点回归 5 断言（Σhard/Σsoft/纯类目归一/gate 零权重/不二次乘）

## Decisions Made

- 重复 (session_id, seq) 迁移 raise RuntimeError 附行明细（T-02-01：不静默去重；演示库允许重跑生成）
- _DDL 内 uq_aq_session_seq 用 CREATE UNIQUE INDEX（与迁移路径 parity，Rule 1 发现修正）
- 纯 gate 模型保护形态：if total_ratio == 0 → 全部 weight=0.0 + return（跳过尾差吸收），注释注明 REF-5.7/§8.2
- 迁移函数对 PRAGMA table_info 空结果（表不存在）早退——新建走 _DDL

## Deviations from Plan

### Auto-fixed Issues

**0. [Rule 3 - Blocking] worktree 基线落后 127 commit，fast-forward 至分支 tip**
- **Found during:** 执行前（load_plan 阶段）
- **Issue:** 工作树 HEAD（69c3a29）落后 feature/m5-assessment tip（e9a9c7f）127 个提交——计划所依赖的 Phase 1 执行代码（readiness/state_events/question_bank_task/test_p0_chain 等）与全部 Phase 2 规划文档（02-PLAN/RESEARCH/PATTERNS）均不在工作树内，计划的行号锚点全部失配
- **Fix:** 确认工作树零独有提交 + 干净后 `git merge --ff-only feature/m5-assessment`（纯 fast-forward，无合并提交，不触碰任何受保护 ref）
- **Files modified:** 无（仅分支指针前移）
- **Verification:** git log 对齐 e9a9c7f；baseline 测试全部通过后才开工
- **Committed in:** 无需提交（ref 移动，工作树文件随之更新）

**1. [Rule 1 - Bug] _DDL 的 uq_aq_session_seq 建成了非唯一索引**
- **Found during:** Task 2 验证后（整体 verification 阶段）
- **Issue:** _DDL 内写的是 `CREATE INDEX`（非 UNIQUE）——新库直建路径 (session_id, seq) 无唯一性约束，与迁移路径（CREATE UNIQUE INDEX）不对齐，违反 Q2 决议与双轨 parity
- **Fix:** 改为 `CREATE UNIQUE INDEX IF NOT EXISTS`；新增 test_unique_index_is_unique 断言双路径 unique 标志 == 1（PRAGMA index_list）
- **Files modified:** server/db.py, server/test_phase2_migration.py
- **Verification:** 迁移测试 8/8 全绿（含新断言）；/tmp 新库 PRAGMA index_list 确认 unique=1
- **Committed in:** 38792f8

**2. [Rule 1 - Bug] dup_rows 行访问用字符串下标抛 TypeError**
- **Found during:** Task 2 首次运行
- **Issue:** init_db 的连接无 row_factory，GROUP BY 查询行是 tuple，`r['session_id']` 抛 TypeError
- **Fix:** 改用整数下标 r[0]/r[1]/r[2]
- **Files modified:** server/db.py
- **Verification:** test_duplicate_seq_blocks_migration 通过（RuntimeError 正确抛出且含行明细）
- **Committed in:** 14afc7d（Task 2 提交内）

---

**Total deviations:** 3 auto-fixed（1 blocking、2 bug）
**Impact on plan:** 全部为正确性必需（基线对齐/唯一性 parity/异常可用），无范围蔓延

## Issues Encountered

- test_phase2_weights + test_phase2_migration 同进程合并跑会互挂（DB_PATH import 时读取冲突）——这是 PROJECT.md 既载的全局测试纪律（单文件单进程），两套各自独立运行全绿即为计划的 verify 命令口径，非缺陷
- test_question_bank.py 在 pytest 下 1 failed/3 errors 为**存量已知问题**（PROJECT.md「脚本式不可收集」；stash 对照验证与本次改动无关），脚本模式 `python test_question_bank.py` 25/25 全绿

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 三表新列就位：02-02（动态选题 selection_reason/policy_version 消费）、02-04（难度路径 path_state_snapshot/锚点消费）、02-05（score_state 消费 + final_score DROP + _DDL 去列——复用本计划 _migrate_*_v2 函数名追加 DROP 段）
- 7:3 就位：新聚合模型自动 7:3；aggregation 不二次乘已由源码断言锁死
- f_followup 语义注意：followup_count 迁至 assessment_question 列（D-25），02-03 改 _count_followups 读列
- 无阻塞

## Self-Check: PASSED

- 文件存在：db.py / config.py / aggregate.py / test_phase2_migration.py / test_phase2_weights.py / 02-01-SUMMARY.md 全 FOUND
- 提交存在：29f55c6 / 14afc7d / 702787a / 8b002c5 / 38792f8 / cbb5f09 全 FOUND（git log 对齐）

---
*Phase: 02-dynamic-selection*
*Completed: 2026-09-04*
