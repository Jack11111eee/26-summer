# Phase 2 DECISIONS — 代确认审计日志

> 按章程 §4：每条代确认记录日期时间/所在步骤/决定内容/依据。一事一条，原子 commit。

## 背景说明（Phase 1 倒签）

Phase 1 完成于章程生效前（2026-09-03），无 DECISIONS 文件。Phase 1 的决策已完整记录于 01-CONTEXT.md（D-01~D-13，discuss 阶段产出）与 01-VERIFICATION.md（REVIEW 结论权衡），本文件不倒签补录。

---

## 2026-09-03 · §① discuss（灰区分析，auto 模式）

**[02-001] 灰区裁决方式 = auto 模式推荐项自动选取**
- 步骤：discuss-phase present_gray_areas / discuss_areas
- 决定：8 个灰区（迁移策略/mock 面score_live 留置/难度状态载体/selection_reason 格式/事件粒度/题目质量代理/7:3 存量模型）按推荐项选取，留痕于 02-DISCUSSION-LOG.md；**N 默认值不代决**（SSOT §31 开放参数——关口包呈报）
- 依据：章程 §1 自动化授权；DISCUSSION-LOG 逐区记录采选理由（SSOT 条款/已决事项/代码现状三者之一）

**[02-002] rm 被拒后 checkpoint 文件留存**
- 步骤：discuss-phase git_commit（checkpoint 清理）
- 决定：02-DISCUSS-CHECKPOINT.json 留存不删（CONTEXT.md 已为权威；Phase 1 同形态先例）
- 依据：settings 全局拒绝 rm（memory: user-deny-deletion-rules）；无信息损失

## 2026-09-03~04 · §② plan 四连

**[02-003] researcher/pattern-mapper/planner 三连全自动派发**
- 步骤：plan-phase §5/§7.8/§8
- 决定：RESEARCH.md（5dca5cb）/PATTERNS.md（84e0097）/5×PLAN.md（558c558）无中断产出
- 依据：剧本 §2「四连全自动跑完，不中断」

**[02-004] checker BLOCK 级两轮修订连续执行（fix 机制延长线）**
- 步骤：plan-phase §10–12 修订循环
- 决定：第一轮（B-1 VALIDATION.md 缺失 / B-2 final_score DDL 契约破裂 + W-1~W-5）与第二轮（B-3 迁移测试断言翻转无人认领 / B-4 p0_security 种子不足 / B-5 p0_chain 种子+答题闭链破裂）均当场修订重验，共 3 commits（feb6c56 / 0647e48）；问题轨迹 7→3→0 收敛
- 依据：剧本 §2「plan-checker 的 BLOCK 级问题当场修正——属 fix 机制延长线，无需请示」

**[02-005] wave 结构偏离建议序：01→02→04→03→05**
- 决定：接受 planner/dev 提出的文件冲突重排（02-02 与 02-04 共改 server/api/assessment.py 与 test_m5_backend.py，不能同 wave 并行；02-03 依赖 02-04 的 answer_state 分类）
- 依据：执行编排事实约束（files_modified 冲突实证）；ROADMAP 已注明说明；5 plan 语义身份不变。**呈报项**：见关口包第 2 项——此为计划层裁量范围（wave 编排非 REF 切分），未触发硬关口 2

**[02-006] gap-analysis 顶层 REQ-* Not covered 判定为工具误报**
- 决定：忽略 gsd-tools gap-analysis 对 REQ-*（milestone 级标签）的 Not covered 行；以 REF-* 逐项核对为准（19/19 覆盖，手工 grep 确认）
- 依据：REQ-* 是 REF-* 的分组标签非实现项；REQUIREMENTS.md 中本 phase 范围以 REF 表达；phase 1 同口径

## 2026-09-04 · 硬关口 A 用户裁决

**[02-007] 关口 A 批准（含三项裁决）**
- 步骤：plan-phase 硬关口 A（plan 审查关口包呈报后；本会话曾发生 macOS TCC 访问中断异常停车一次，用户恢复授权后继续）
- 决定：
  1. **ORDINARY_PLAN_N 生产默认值 = 10**（全局默认；岗位级差异化未来经 SSOT 变更流程再做）——02-02 Task 5 checkpoint 借此裁决直接放行，不再单独停车
  2. **wave 顺序 01→02→04→03→05 批准**（plan 语义与 REF 切分不变）
  3. **遗留项消化路径批准**——「顺带收敛」仅限各计划 files_modified 已列明范围，超出的发现即停车呈报（硬关口 3 口径）
- 依据：用户在关口 A 的明示批复（2026-09-04）；SSOT §31-1 开放参数由用户定值；章程 §4 用户裁决留痕义务。

## 遗留项（带入后续 phase 的 Info/非阻断项）

- [Phase 1 REVIEW Info] IN-04 scored_count 语义、IN-08 测试共库纪律（Phase 6 REF-7.4 消化）、IN-09 append_event 并发 500–低概率知悉项
- [Phase 1 VERIFICATION Warning] readiness.py 四分支 conn.close、question_bank.py finished_at CASE、task 行插入非原子（WR-04）、get_report_by_session oracle（WR-05）、review_position reject FK 500（CR-03/CR-04）——Phase 1 验收时判定 SC 字面之外归后续阶段消费；其中 readiness while 在 02-02 重写范围内自然顺带收敛的机会交执行期判断（不扩权）
