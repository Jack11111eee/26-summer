# Phase 3 DECISIONS — 代确认审计日志

> 按章程 §4：每条代确认记录日期时间/所在步骤/决定内容/依据。一事一条，原子 commit。Phase 3 编号续接 Phase 2（[02-xxx]），本文件用 [03-xxx]。

---

## 2026-09-05 · §① discuss（灰区分析，auto 模式）

**[03-001] 灰区裁决方式 = auto 模式推荐项自动选取**
- 步骤：discuss-phase present_gray_areas / discuss_areas
- 决定：16 个灰区（D-29~D-46：form_instance 生命周期实体 / render 触发点 / gate 结构化结果 / SSE 同 URL 升级 / 幂等三键 + 可选键 / 惰性计时 / 显式 pause / 超时三路径 / message 分列 / INJECTION 事件 / D-46 新端点 Pydantic 等）按推荐项选取，留痕于 03-DISCUSSION-LOG.md；**SSOT 未授权项不代决**（D-46 边界若 checker 判定语义为全量接口则关口包呈报——已按此触发，见关口包第 3 项）
- 依据：章程 §1 自动化授权；DISCUSSION-LOG 逐区记录采选理由（SSOT 条款/已决事项/代码现状三者之一）

**[03-002] rm 被拒后 checkpoint 文件留存（形态延续）**
- 步骤：discuss-phase git_commit（checkpoint 清理）
- 决定：沿用 Phase 2 先例——checkpoint 快照不构成实施依据，文件留存与否不打断流程
- 依据：02-DECISIONS [02-002] 同形态；settings 全局拒绝 rm（memory: user-deny-deletion-rules）

---

## 2026-09-05 · §② plan 四连

**[03-003] researcher/pattern-mapper/planner 三连全自动派发**
- 步骤：plan-phase §5/§7.8/§8
- 决定：RESEARCH.md（6b24d97）/PATTERNS.md（f062bae）/5×PLAN.md（a8dd096）无中断产出；RESEARCH 含 9 问题/12 陷阱/11 实验/6 Code Examples（全部 /tmp 临时库实测，未碰 data/app.db——红线 2）
- 依据：剧本 §2「四连全自动跑完，不中断」

**[03-004] checker BLOCK 级修订 + 机械修补轮连续执行（fix 机制延长线）**
- 步骤：plan-phase §10–12 修订循环
- 决定：第一轮（2B/7W/4I——B1 03-01 files 与 Task 断言不一致 / B2 03-02 files_modified 漏列回归面 / B3 03-03 idempotency 两阶段缺口等）由 planner 修订；二验发现修订引入 3 个机械性 blocker（key_links YAML 缩进损坏 / 烟测脚本 get_conn FK-on 与 NOT NULL 互斥 / 路径与锚点错位），由 orchestrator 直接执行最小机械修补轮（N1-N7 共 7 项——全部 diff 级可核验，不涉计划语义），合并提交 139a477 后派 checker 第三轮复验
- 依据：剧本 §2「plan-checker 的 BLOCK 级问题当场修正——属 fix 机制延长线，无需请示」；N1-N7 均为机械性（YAML 解析复验 5/5 通过），不构成 plan 语义变更（未触发硬关口 2）；修补轮由 orchestrator 直接执行而非重派 planner——上下文经济考量，Phase 2 无此先例但属同一 fix 机制授权范围（机械修复无新决策）
- 附注：若第三轮复验仍有 BLOCK，按修订循环上限（3 轮）收敛或呈报

**[03-005] wave 结构 = 全串行 1→5**
- 决定：接受 planner 的 files_modified 冲突实证（五计划 server/api/assessment.py 全部重叠 + submit_answer 单函数逐计划深度改造，无任何两计划可并行）；ROADMAP 已注明；REF 切分与计划语义身份不变（gate A 02 批准的编排裁量同源）
- 依据：「Wave 结构说明」（ROADMAP Phase 3 条目）；与 Phase 2 [02-005] 同性质——计划层编排裁量，非 REF 重切

**[03-006] 关口包呈报项新增 6 项（M0 目标 8 项）**
- 决定：①MAX_CONTEXT_TOKENS 数值（SSOT §31-2 开放参数——03-04 Task 5 checkpoint 占位 8000）②A2 gate 行四步放宽法采纳（ASSUMED 标记迁移 docstring）③D-46 存量端点 Pydantic 化范围（11 处 body: dict 端点清单——推荐 Phase 6 收口）④A6 前端 start 接线延后（后端契约测试完备，web 零改动约束）⑤WR-04 §10.5/§11.2 张力（[02-013a] 移交）⑥data/app.db 存量 in_progress 会话处置——全部不代决，随关口包打包呈现
- 依据：章程 §2.2 硬关口（SSOT 开放参数 / SSOT 语义裁决 / 用户演示数据操作）；VALIDATION.md Manual-Only 表全量登记
