---
phase: 02-dynamic-selection
plan: 05
subsystem: testing
tags: [scoring, score-state, denominator-rules, sqlite-migration, pytest, tdd]

# Dependency graph
requires:
  - phase: 02-dynamic-selection plan 01 (2758afc)
    provides: question_score.score_state 列 + _migrate_question_score_v2（COALESCE 合并段——本计划在其内追加 DROP 段）
  - phase: 02-dynamic-selection plan 02 (79e4198)
    provides: 动态实例 aq.item_id 绑定（score_session item_id 取值优先实例列）
  - phase: 02-dynamic-selection plan 04 (8875c0d)
    provides: 拒答封存流（二次 DECLINED → seal_reason='refused'）——REFUSED 行的生产来源
provides:
  - score_final 独立落库（50/50 合成废除，score_live 纯参考值——D-26）
  - score_state 三态生产（SCORED/REFUSED/INVALIDATED）+ SCORE_STATES 六值枚举常量
  - §12.4 分母规则落聚合：SCORED 进分母；REFUSED → refusals 列表；排除态 → missing_warnings
  - answer_key 空客观题 → INVALIDATED（不写 1/不写 5——REF-8.1 漏洞变体关闭）
  - final_score 列四消费点切换后原子 DROP（A8 次序合同闭合）
  - test_phase2_scoring.py 评测价新契约全套断言
affects: [03-injection-hardening, 05-imputation, verify-work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "score_state 三路分流在取数循环内（SQL 不过滤——plan <action> 口径覆盖 <interfaces> 的 IN 过滤原型）"
    - "拒答题不经 score_question（代码分支顺序可证：REFUSED 行构造先于 LLM 调用点）"
    - "DROP COLUMN 幂等嗅探（PRAGMA table_info 列存在才 ALTER）"

key-files:
  created:
    - server/test_phase2_scoring.py
  modified:
    - server/services/scoring.py
    - server/services/aggregation.py
    - server/services/report.py
    - server/db.py
    - server/test_m5_backend.py
    - server/test_m6_backend.py
    - server/test_phase2_migration.py

key-decisions:
  - "拒答封存题在评分时产生 REFUSED 行（score_final=0）不经 LLM 评分——拒答不产生能力证据"
  - "INVALIDATED 行 score_final=None（非 0 非 1 非 5）——脱离普通评分通道的语义标记"
  - "aggregate 取数循环内分流（一条 SELECT 含 score_state，代码分流三路）——与 <interfaces> 的 SQL IN 过滤原型相比换取 REFUSED/排除态的单列结构化数据"

patterns-established:
  - "score_state 分母契约：只有 SCORED 进能力等级分母；排除态显式警告不静默（D-28）"

requirements-completed: [REF-5.1, REF-5.2, REF-5.3, REF-8.1]

# Metrics
duration: 33min
completed: 2026-09-04
---

# Phase 2 Plan 05: 评分链契约修正 Summary

**50/50 合成废除 + score_state 三态生产（SCORED/REFUSED/INVALIDATED）+ §12.4 分母规则落聚合 + final_score 列四消费点切换后原子 DROP（A8 次序合同闭合）**

## Performance

- **Duration:** ~33 min（2026-09-04T11:10–11:43 UTC）
- **Tasks:** 4/4（TDD：Task 1 RED → Task 2/3 GREEN）
- **Files modified:** 8（与 files_modified 逐一对应，零外溢）

## Accomplishments

- 评分链契约修正全部落地：主观题 mock 3 分直落数据库（无合成路径，静态 grep "0.5 +" 零残留）、拒答题 REFUSED 行 score_final=0 不进能力分母、answer_key 空客观题 INVALIDATED 不写 1/5 分
- 聚合分母规则（§12.4）：SCORED 进分母；REFUSED → refusals 行为/完整度列表；INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED → missing_warnings 警告列表（不隐式转 0，不静默）
- final_score 列经四消费点（scoring INSERT/remove、aggregation SELECT、report SELECT、测试断言）切换后 DROP——02-01 锁定的「合并不 DROP」次序合同原子收尾，幂等嗅探保护 + 老库 COALESCE 合并先行
- 02-01 交付的 test_phase2_migration.py 两处「列保留」断言按计划翻转（断言翻转所有权归本任务）

## Task Commits

1. **Task 1: 评分链新契约断言（RED）** - `99447bd` (test)
2. **Task 2: scoring 删合成 + score_state 生产 + aggregation/report 切列** - `d3e1987` (feat)
3. **Task 3: final_score DROP + 迁移段 + 02-01 断言翻转** - `0780ae3` (feat)
4. **Task 4: m5/m6 断言重写 + eval 冒烟** - `120c160` (test)

## Files Created/Modified

- `server/services/scoring.py` - 删 50/50 合成；SCORE_STATES 六值常量；score_question 返回 score_state（客观缺 key → INVALIDATED + score_final=None）；score_session 生产 REFUSED（seal_reason 拒答分支，不经 LLM）/INVALIDATED/SCORED 三态；INSERT 列清单去 final_score 加 score_state；item_id 优先 aq.item_id 回退 _find_item_id
- `server/services/aggregation.py` - 取数切 score_final + score_state；三路分流（SCORED/REFUSED/排除态）；返回 dict 新增 refusals + missing_warnings 两键（只加不减）
- `server/services/report.py` - _load_question_reviews SELECT 的 qs.final_score 切 qs.score_final + 补 score_state 列
- `server/db.py` - _DDL question_score 去 final_score 列定义；_migrate_question_score_v2 追加 DROP 段（COALESCE 合并后幂等 DROP）
- `server/test_phase2_scoring.py` - 新建：7 测试（枚举完整性/静态无合成/独立落库/REFUSED 分母排除/INVALIDATED 分母排除/score_final 均值口径/报告端到端）
- `server/test_m5_backend.py` - :306 断言重写 score_final+score_state；补全行 SCORED 断言
- `server/test_m6_backend.py` - _test_dual_scoring SELECT 切列 + 三组断言重写（脚本式 check 保持）
- `server/test_phase2_migration.py` - 两处「final_score 列存在」断言翻转为不存在（D-09 只改断言）

## Decisions Made

- 聚合取数采「一条 SELECT（含 score_state）+ 循环内三路分流」实现——plan `<action>`（Task 2 明确「不过滤——循环内分流」）覆盖 `<interfaces>` 中的 `WHERE score_state IN ('SCORED')` SQL 原型；REFUSED/排除态需要 item_id/std_name/question_id 结构化输出，循环分流是两全实现（同时经 test 断言证分母不含拒答/无效题）
- eval 冒烟用 /tmp 库 + 自建 demo 岗位（pos_eval_demo，confirmed 模型 3 items）——eval 需已有岗位与模型，业务库不可碰（D-15 / REF-8.8 隔离红线）；临时种子脚本跑完即删不入提交
- test_question_bank.py 保持脚本式调用（python test_question_bank.py，25/25 通过）——pytest 误调用时其函数签名（check 风格非 pytest 用例）天然失败，属既有形态非本计划回归（.baseline 快照同状态）

## Deviations from Plan

None — plan executed exactly as written（8 文件 diff 与 files_modified 逐一对齐；「顺带收敛」未发生——test_question_bank.py 的 pytest 形态问题是前 wave 既存状态，非本计划改动引入，不修不扩）。

### 微观决策（plan〈interfaces〉未覆盖处，照 02-PATTERNS 惯例就近取近似）

1. **test_score_final_independent 的断言形态**：plan 允许「DROP 前中期态断言 score_state 即可」——mock 实义词路径下主观题 score_live 由 _latest_score_live 独立读取，断言落在 score_final==3 + score_state=='SCORED'（live 值不属于合成验证主路径，live≠final 场景由 test_aggregation_reads_score_final 单独覆盖）
2. **_answer 辅助函数**：约 260 行处新增时丢了空行导致临时语法错误，当场修复后测试全绿（无遗留）

**Total deviations:** 0 auto-fixed
**Impact on plan:** None — 全部按 plan 契约实现。

## Issues Encountered

- Task 1 debugging 过程中发现 current_question 的 question_id 是 assessment_question 实例 id 而非 bank_question_id——测试内新增 _aq_id_for_bank 映射函数解决（测试侧问题，非生产代码改动）
- eval 冒烟首跑因 /tmp 库无表失败——前置 init_db()（临时种子脚本内）后通过；正式退出码 0

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 2 五 plan 全部完成：01（迁移+权重）、02（动态选题）、03（难度路径）、04（拒答封存）、05（评分链契约）——SC-1~5 主体能力齐备，可进入 verify-work（SC 逐条核）
- REF-5.1/5.2/5.3/8.1 四项已落：score_live 仅导航、聚合无 50/50、answer_key 空判题库无效（INVALIDATED）、拒答不事后评分
- Phase 5 衔接：INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED/INCOMPLETE 枚举位在位（SCORE_STATES 常量），当前无生产者——imputation 生产属 Phase 5
- IMPUTED/HUMAN_REVIEW_REQUIRED 不在 Phase 2 过滤名单（plan 注记：过度过滤会与 Phase 5 冲突）——聚合循环已留注释位

## Self-Check: PASSED

- 8 个 files_modified 全部存在且 diff 无外溢（git diff b592ad7..HEAD 逐一核对）
- 4 个任务 commit 均在 worktree 分支（99447bd/d3e1987/0780ae3/120c160）
- grep "final_score" server/ 业务代码命中仅限 db.py 迁移段（COALESCE/DROP 语句与注释）——零业务读取

---
*Phase: 02-dynamic-selection*
*Completed: 2026-09-04*
