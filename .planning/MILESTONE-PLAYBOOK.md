# MILESTONE-PLAYBOOK — 从 Phase 2 到 milestone 收尾的全流程剧本

- **适用**：本 milestone（SSOT v2.0 契约重构，Phase 2–6 剩余部分）。
- **授权边界**：见 `AUTOMATION-CHARTER.md`（本文件只讲怎么干，不讲能干不能干）。
- **进度权威**：`.planning/ROADMAP.md`。每完成一步先更新它再继续。
- **当前基准**：Phase 1 已完成（4/4 plans + verify + code-review/fix + secure，branch `feature/m5-assessment`，HEAD 53c4b9c，2026-09-03）。

## 1. 总览：两种循环

```
Phase 内循环（§2）——每个 phase 跑一遍：
  ①  discuss →  ②  plan 四连 →  ┃硬关口 A：plan 审查┃ →  ③  execute 逐 wave
  →  ④  verify →  ⑤  code-review(+fix) →  ⑥  secure(条件) →  ⑦  簿记关账
                    ↓  通知用户「可 /compact」，随即开启下一 phase 的 ①
Milestone 收尾循环（§5）——Phase 6 关账后一次性：
  [x] 各 phase 已逐个走完 → M1 审计 / complete-milestone → 收尾报告 → 等用户
```

## 2. Phase 内七步循环（Phase 2–6 通用）

每步含「做什么 / 自动化判定 / 产物」。产物全部落 `.planning/phases/<phase-dir>/`。

### ① discuss（灰区收集）

- **做什么**：`/gsd-discuss-phase <n>`。输出 CONTEXT.md + 灰区清单。
- **自动化**：分析全自动。GSD 若对灰区逐项发起交互提问：能合并的合并成一份问题清单；**不能合并的按硬关口 3 停车**。已决事项不重开（对照 01-CONTEXT.md、DECISIONS、SSOT 决策日志）。
- **产物**：`<NN>-CONTEXT.md`；灰区处置（哪些进关口包、哪些采默认）记入 phase 首条 DECISIONS。

### ② plan 四连（researcher → pattern-mapper → planner → plan-checker）

- **做什么**：`/gsd-plan-phase <n>` 一次跑完四连，产出 RESEARCH.md / PATTERNS.md / 各 `<NN>-0X-PLAN.md`（按 ROADMAP 既定切分）+ plan-checker 检查记录统一归档。
- **自动化**：四连全自动跑完，不中断。plan-checker 的 BLOCK 级问题当场修正（修改 planning 输入重新 planner）——属 fix 机制延长线，无需请示；FLAG 级记档带入关口包呈现。
- **特殊**：发现 ROADMAP 该 phase 的 plan 切分与现实明显不符（范围错、依赖倒置），按硬关口 2 处理（调整切分 = 计划层变更，呈现于关口包一并批准）。
- **注意**：`REQUIREMENTS.md` 的 REF-* 条目是关卡语义边界（哪些属本 phase、哪些不属），plan 只覆盖本 phase 的 REF；越界发现 → 关口包呈报，不擅自扩大范围。
- **产物**：RESEARCH.md / PATTERNS.md / `<NN>-0X-PLAN.md` 们。

### ┃硬关口 A：plan 审审┃（每 phase 唯一例行停车点）

呈现内容（PushNotification「plan 审查就绪」+ 停车）：

1. **目标与成功标准**：本 phase goal + SC 映射（REF 契约 ↔ 测试 ↔ 交付物），验证每个 SC 有可测断言路径。
2. **Plan/wave 结构**：每个 plan 一段话（目标 / 主要文件 / 依赖 wave）；planner 要 AI 集成的 plan 标 `AI-integration`。
3. **灰区处置**：discuss 收集的每个灰区 → 拟采方案（默认采 SSOT 已有条款，与 SSOT 歧义则不采默认）。
4. **遗留项处置**：上一 phase REVIEW 的 Info、verify 非阻断项如何被本 phase 吸收（或显式记档不清）。
5. **上一 phase 帿查记录**（Phase 3 起再次出现）：DECISIONS 摘要（每条一句），异常停车事件复盘。

批准通过 → ③；用户修改意见 → 修订后重呈（只重呈修改影响的部分）。

### ③ execute（逐 wave 执行）

- **做什么**：`/gsd-execute-phase <n>`。GSD 按 wave 顺序逐 plan 派 gsd-executor 子代理（全新上下文，读盘上 PLAN）。
- **自动化**：wave 完成且其 verify 全部绿 → 代确认、续下一 wave（DECISIONS 记一条）；红 → 按异常停车（硬关口 3）。
- **库表与状态**：executor 输出 SUMMARY.md；红线 2（测试卫生）、红线 6（分支纪律）每次执行前自查（见 §3.5）。
- **产物**：代码 commit（原子，含义清晰的 message 带 REF-*/SSOT §* 引用）、`<NN>-0X-SUMMARY.md`。

### ④ verify

- **做什么**：`/gsd-verify-work <n>`（goal-backward 核验所有成功标准）。
- **自动化**：全部通过 → 续 ⑤；有非阻断发现（如 UI 走查类人工项）→ 记档带入关口包（下一个 phase 的关口 A 第 5 项）呈报，不停车;有阻断发现 → 异常停车。
- **产物**：`<NN>-VERIFICATION.md`。

### ⑤ code-review + fix（条件触发）

- **做什么**：`/gsd-code-review <n>`。Critical/Warning → 按章程自动 `--fix`（原子提交），Info 搁置记档。
- **触发规则**：涉及「安全/权限/敏感数据」的 phase（对照 plan 的 threat model 段）**必跑**；其余 phase 跑,不带 --fix 则按需。**默认每个 phase 都跑**（沿用 Phase 1 口径；费时约 1-3 小时，属可接受成本）——若某 phase 改动极小（<5 个 commit），可以记档说明后跳过，记入 DECISIONS。
- **产物**：REVIEW.md、REVIEW-FIX.md、fix commits。

### ⑥ secure（条件必跑）

- **做什么**：`/gsd-secure-phase <n>`，产 SECURITY.md。
- **触发规则**：这个 phase 的 plan threat model 含 X 源头或新增认证/权限/跨用户数据流 → 必跑（对照 D-001~D-013 类威胁登记）。
- **自动化**：无 Critical/高危 → 归档续行；有 → 异常停车。
- **产物**：`<NN>-SECURITY.md`。

### ⑦ 簿记关账（phase 关门）

按顺序做完才允许开下一 phase：

1. 全部 RESEARCH/PATTERNS/PLAN/SUMMARY/VERIFY/REVIEW/FIX/SECURITY/DECISIONS 已落盘 + commit。
2. ROADMAP.md：该 phase 勾选 + 完成 1 口径同 Phase 1（completed_date 在 Progress 表落日期）。
3. PushNotification「Phase <n> 关账，可以 /compact 了」。
4. 随即开启下一 phase 的 ①（discuss）——用户若 /compact 则新会话以启动 prompt 起跑（章程 §7），反之同会话继续。

## 3. 硬关口与异常停车规约

- **停车方式**：PushNotification（一句话：在等什么 + 哪个关口/异常）→ 停止执行，输出当前状态摘要（位置/已完成/待决）+ 关口包/异常报告。
- **恢复**：用户回到对话说「继续」或给裁决。裁决内容记 DECISIONS。
- **异常的种类**（对应章程 §2.3）：测试持续红 / plan 与现实冲突 / 需动业务库 / 需动用户未提交文件 / GSD 技能强制提问不能推迟（即便答案已知，若必须交互的 spec 停车）。
- **中断恢复**（进程被杀/重启）：`claude -c` 或 `claude --resume` 恢复会话；先读 ROADMAP + 最新 DECISIONS + git log 比对断点，从断点续跑，只重派未完成的那一小步。GSD 各阶段产物均落盘（.planning/），中断只丢正在飞的那一步。

## 3.5 执行前自查清单（每个 wave 派发前快速过一遍）

- [ ] git status 干净（存在未提交用户文件 → 停车；executor 切不到 phase 分支时可临时 worktree）
- [ ] 全部测试绿（进入本 wave 前的基线）
- [ ] 本 wave 的 plan 已获关口 A 批准

三项全过才派 executor；任何一项不过停车。

## 4. 各 phase 要点速览（计划性信息，非替代 ROADMAP）

| Phase | 内容 | plans | 特别注意 |
|---|---|---|---|
| 2 动态选题与有界循环 | 四层选题/难度状态机/回答状态分类/评分链 50-50 废除/7:3 权重 | 5 | 契约最密集（SSOT §10/§11）；scoring/question_selection/interview 三线同改，测试面最大 |
| 3 表单/SSE/幂等/计时 | form_instance/SSE/幂等协议/计时区间 | 5 | 前后端同改；sse.js 双形态；涉及表单校验边界（安全相关 → secure 必跑） |
| 4 题库版本绑定 | model/version 绑定/失败可见/orphan 路由/模型编辑校验 | 2 | 最小 phase；schema_version 登记簿在 Phase 6 收口，本期升版级联题库重建只做行为层联动 |
| 5 证据链与报告契约 | 证据 span/trace_link/item 裁决/报告状态机/七项校验 | 4 | 审计语义多；报告不可变版本化（feedback 外键保护）是 DB 演进重头 |
| 6 迁移与测试闭环 | schema_version 收口/pytest+CI/M1 回归/E2E/eval 隔离 | 5 | 测试工程 phase；REF 覆盖验收（REQ-e2e-demo-deliverables 等）；06-05 含安全收尾（输入限额/secret 启动校验/HttpOnly 方向决策）——涉及决策点的按硬关口 2 处理 |

各 phase 权威范围以 ROADMAP 与 SSOT §28 为准，本表只是快速索引。

## 5. Milestone 收尾（Phase 6 关账后一次性）

1. **全链完整性审计**：`/gsd-audit-milestone`（或 gsd-audit-fix 处理发现）。产出审计报告。
2. **complete-milestone**：`/gsd-complete-milestone`——校验全部 phase 关账、branch 合并策略（feature/m5-assessment → main 的合并时机与方式**章属用户**：default 只准备合并就绪状态，不执行合并）。
3. **收尾报告**：对照 milestone 目标（SSOT §28 六步实施顺序全部落地）与 ROADMAP 全部 SC，产出 milestone 完成报告（覆盖率、遗留项、风险）呈用户。
4. **每一 phase 的 VERSION 文件**（若 GSD 产出）与全 .planning 归档 commit。
5. **最后关口**：等用户验收（可能含演示走查）。预期会有推 main / 打 tag / 开 PR 的动作——按红线 5 需用户明确指示后执行。
6. **终态**：授权自动终止（章程 §6）。memory 中登记本 milestone 完成。

## 6. 上下文管理纪律（编排会话自身）

- 编排会话长住上下文只保三类：路线图、决策日志摘要、当前断点。文件级细节按需读，不囤积。
- 重活在子代理：gsd-executor/researcher/planner/verifier/security-auditor 都是全新上下文，不继承本会话历史。
- 每 phase 关账时邀请用户 `/compact`（章程 §1）——新 phase 从近净窗口起跑。
- compaction 损失细节但不丢状态：`.planning/` 是唯一权威。

## 7. 新会话启动 prompt（复制即用）

前置：确认章程已生效（AUTOMATION-CHARTER.md「生效」条款 + memory Status 段均显示用户已批准；未批准则向用户请求批准，不得默认）。

```text
读取 .planning/AUTOMATION-CHARTER.md 与 .planning/MILESTONE-PLAYBOOK.md，严格按其中授权边界与流程执行。
进度权威：.planning/ROADMAP.md（Phase 1 已完成）。从下一个未开始 phase 的循环第 1 步（/gsd-discuss-phase <n>）起跑，
停在硬关口 A（plan 审查打包呈现）等我批准。我已授权例行关口由你按章程代确认并记 DECISIONS.md；
硬关口与红线条款无条件停车。权限模式已放宽，无人值守段无需我确认。
```
