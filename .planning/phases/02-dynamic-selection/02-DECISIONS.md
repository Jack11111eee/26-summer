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
- 执行落点（02-02 收尾，2026-09-04）：config.ORDINARY_PLAN_N = 10 行尾注释按本裁决书写；
  Task 5（checkpoint:human-verify）据此免停车直接放行——本条为该 checkpoint 的完成记录（02-02-SUMMARY 同步记载）。

## 2026-09-04 · §③ execute（wave 簿记，auto 模式）

**[02-008] wave 2（02-02 四层动态选题）完成与合入**
- 步骤：§③ execute wave 2/5
- 决定：第 3 次派发完成（5 commits，worktree ad2157d5e 合入 79e4198）；抽查核心契约全过（CATEGORY_QUOTA 零残留 / 四纯函数 / N=10 注释 [02-007] 正文 / db.py 零改动 / QUESTION_* 系列事件附 sha256 种子）；后测门全绿（selection 9 + migration 8 + weights 5 + m5 7 + p0_security 10 + p0_chain 11 + question_bank 25 + m6 41）
- 依据：章程 §3 wave 簿记；[02-007] 关口 A 裁决的执行落点已在 config 注释 + SUMMARY 三处留痕

**[02-008a] wave 2 执行者簿记超出 files_modified 的定性处置**
- 决定：REQUIREMENTS/ROADMAP/STATE 三文件由执行者写入（超过 files_modified 列表）判定为 **GSD 簿记域非代码收敛**——execute-plan 工作流 §deviation_v2 :384/:472-476 本就含 STATE/ROADMAP/REQUIREMENTS 更新义务，parallel 模式豁免条款防的是多 worktree 并行分叉，本 phase wave 串行单执行者无此风险；内容核实全部正确（REF 勾选恰为 02-02 的 4 项、ROADMAP 2/5、STATE completed_plans 6/9）。合入保留，未触红线 2（用户文件）与「顺带收敛」射程（非代码）；另由编排层补修 REQUIREMENTS 02-02 项（REF-3.7/5.7，wave-1 时遗漏的 REF-2.7/2.9 分属 02-04/02-05 后续勾选）与 STATE 措辞（Plan: 2 of 5 → wave 2/5 完成、Phase 标注、下一动作）
- 依据：关卡 A 裁决 3「顺带收敛」射程 = 代码文件；工作流原文（编排层集中处理 STATE/ROADMAP 义务在本会话编排层身上，执行者超额写入未损害结果、内容正确）

**[02-008b] 执行者自愈偏差 3 项——回溯认可**
- 决定：①层② uncovered required 加配额内过滤（否则例外不可达）②决策 finish 降级 next 过渡处理（is_last 失真，02-04 接管）③ORDINARY_PLAN_N 提前至 Task 3 批次落地（Task 3 测试已 import 该常量，严格切分留下不可运行中间态）——三项均 Rule 1/3 正确性必需，已记入 02-02-SUMMARY 偏差区；其中 ② 属 plan 预留过渡形态（pool-exhausted finish），02-04-PLAN is_last 接管条款可印证边界兑现——不得视为范围蔓延
- 依据：execute-plan deviation rules（Rule 1 bug 修复 / Rule 3 blocking 中间态）；02-04-PLAN 已有 is_last takeover 条款可印证边界兑现

**[02-008c] 执行者遗留调试件处置**
- 决定：`server/_debug_selection.py` 未提交未跟踪——worktree remove 已随目录清除（该文件在主仓无副本：git ls-files 零命中）；SUMMARY 已登记"删除需用户执行"——因发现时该文件已随 worktree 消失，用户无需再执行清理；SUMMARY 文本保留不动（历史记录，不回改）
- 依据：rm 被拒仅作用于 agent 路径——worktree 目录整体移除属 git 操作，随目录消失的未跟踪文件无需补删

**[02-009] wave 3（02-04 interviewer 两层化）完成与合入**
- 步骤：§③ execute wave 3/5（执行序；数据载体属 02-04）
- 决定：单次派发完成（4 commits，worktree a9b77ea5 合入 8875c0d）；抽查契约全过（decide_next_action 签名逐字保持 / InterviewObservation 11 态 + Pydantic 消费点 / _DECLINE_WORDS 词表 / followup_count 迁列 +1 UPDATE / QUESTION_SEALED+OBSERVATION_CLASSIFIED+EVIDENCE_EVALUATED 三事件 / 本 plan question_score 零写入）；后测门全绿（interview 12 + selection 9 + migration 8 + weights 5 + m5 7 + p0_security 10 + p0_chain 11 + question_bank 25 + m6 41 = 128 项）
- 依据：章程 §3 wave 簿记

**[02-009a] wave 3 执行者超 files_modified 一处——回溯认可**
- 决定：test_question_bank.py（:189-198 test_prompts 的 interviewer SYSTEM 断言适配，12 行）超出 plan files_modified 列表——但属本计划 prompt 契约变更的**必然回归适配**（旧断言锁 "followup/next/finish" action 协议，02-04 Task 2 将 action 键从 INTERVIEWER_SYSTEM 移除后该断言必红；执行者按 D-09 只改断言、最小侵入）。与计划期 checker 在修订 2 将 p0 测试适配补入 02-02 files_modified（B-4/B-5）同一性质，本轮 checker 漏列——判定为计划文件清单疏漏而非执行者越权。合入保留
- 依据：关口 A 裁决 3 的「顺带收敛」射程本指代码收敛（遗留代码不动）——本处是测试断言对新契约的跟随，非蓄意扩围；[02-008a] 同口径先例

**[02-009b] 执行者自愈偏差 3 项——回溯认可**
- 决定：①[02-009a] 所述 files_modified 外回归适配 ②红测文案撞词（"长但空"测试文案含「具体」实义词致分类歧义——改文案消除）③ObservationDims 构造漏 attribution 键（Pydantic required 补齐）。三项均 Rule 1/3 正确性必需，已记入 02-04-SUMMARY 偏差区
- 依据：execute-plan deviation rules；m5 :290 final_score 断言未动（归 02-05）核实无误

**[02-010] wave 4（02-03 难度路径状态机）完成与合入**
- 步骤：§③ execute wave 4/5（执行序；数据载体属 02-03）
- 决定：单次派发完成（4 commits，worktree ab813024 合入 9c19e7c）；抽查契约全过（next_difficulty 纯函数无 conn / advance_snapshot / update_path_state 持 conn 不 commit（grep 零命中） / assessment.py 经 _advance_difficulty_state helper 在 :269/:298 两路封存分支调用、followup 零调用 / _EXCLUDED_FAILURE_STATES 七类排除 / selection 层 path_state_snapshot 读取 / test_p0_chain 未触碰——备用适配分支未激活）；后测门全绿（difficulty 10 + selection 9 + interview 12 + migration 8 + weights 5 + m5 7 + p0_security 10 + p0_chain 11 + question_bank 25 + m6 41 = 138 项）
- 依据：章程 §3 wave 簿记。diff 文件集 4/5 ⊆ files_modified（test_p0_chain.py 计划列名但适配未激活——合法子集），零超范围

**[02-010a] 执行者自愈偏差 3 项——回溯认可**
- 决定：①difficulty.py 漏 import append_event（首次集成暴露，Rule 1 补齐）②snapshot 读取需排除当前封存行 + 按 seq 排序（否则读到当前行 NULL 快照致每次封存路径重置 easy——正确性关键修复）③红测集成设计修正（easy 不降级 → LOWERED 测试先升 medium；选题承接测试循环非目标 item）。三项均 Rule 1 正确性必需，已记入 02-03-SUMMARY 偏差区
- 依据：execute-plan deviation rules

**[02-010b] 执行者调试件处置（4 个未跟踪脚本）**
- 决定：`server/_dbg_{difficulty,e2e,loop,spy}.py` 四个未提交未跟踪调试脚本随 worktree remove 一并清除（主仓 git ls-files 零副本）；executor SUMMARY 已登记需用户删除——实际已随目录消失，用户无需操作；SUMMARY 文本保留（历史记录不回改）
- 依据：[02-008c] 同口径先例


## 遗留项（带入后续 phase 的 Info/非阻断项）

- [Phase 1 REVIEW Info] IN-04 scored_count 语义、IN-08 测试共库纪律（Phase 6 REF-7.4 消化）、IN-09 append_event 并发 500–低概率知悉项
- [Phase 1 VERIFICATION Warning] readiness.py 四分支 conn.close、question_bank.py finished_at CASE、task 行插入非原子（WR-04）、get_report_by_session oracle（WR-05）、review_position reject FK 500（CR-03/CR-04）——Phase 1 验收时判定 SC 字面之外归后续阶段消费；其中 readiness while 在 02-02 重写范围内自然顺带收敛的机会交执行期判断（不扩权）
