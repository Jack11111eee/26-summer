# AUTOMATION-CHARTER — 「标准 GSD 流程 + 授权代确认」授权书

- **授权人**：用户（本项目所有者）
- **受权执行者**：Claude Code 主会话（编排者；重活由 GSD 子代理执行）
- **生效**：**用户显式批准后**（说「按这个授权来」，或新会话粘贴 §7 启动 prompt）。落盘本身不构成生效——批准前本章程仅为草案。生效时刻记入本文件与 memory（automation-charter-active.md 的 Status 段），git 原子 commit 存证
- **生效记录**：✅ **已生效，2026-09-03**——用户于新会话粘贴 §7 启动 prompt（触发 Phase 2–6 全流程），以本条目所在 commit 存证
- **适用范围**：Phase 2–6 全流程，直至本 milestone（SSOT v2.0 契约重构）收尾完成
- **配套文件**：操作剧本 `MILESTONE-PLAYBOOK.md`（怎么干，含 §7 新会话启动 prompt）；本文件只定授权边界（能干什么、不能干什么）
- **冲突裁决**：本文件与任何GSD 工作流指引冲突时，以本文件为准；CLAUDE.md 与 SSOT 治理高于本文件

## 0. 一句话

GSD 标准步骤（discuss → plan → 审查 → execute → verify → review/fix → secure → 簿记）原样保留、由受权执行者全程驱动；例行关口由其代用户确认并落盘留痕；§2 三类硬关口无条件停车等用户。

## 1. 代确认授权（执行者可直接续，事后留痕）

| 关口类型 | 处理方式 |
|---|---|
| Wave 完成确认、executor summary 接受 | 测试全绿即自动续下一 wave；红则转异常停车 |
| code-review findings：Critical / Warning | 自动运行 `--fix` 修复（原子提交 + 隔离 worktree 流程） |
| code-review findings：Info | 搁置记档（带入后续 phase 的 DECISIONS/遗留清单），**不跑** `--fix --all` |
| verify / verify-work 的非阻断发现 | 记档带入下一 phase 计划，不停 |
| secure-phase 报告无 Critical/高危发现 | 自动确认归档，续行 |
| 一个 phase 完结 → 开启下一 phase 的 discuss/plan | 自动续跑，停在下一 phase 的硬关口（plan 审查） |
| phase 边界邀请用户 `/compact` | 每次都发出邀请，不强制 |

## 2. 硬关口（无条件停车，PushNotification 通知，等用户指令）

1. **Plan 审查**（每 phase 动工前唯一例行硬关口）：GSD 四连产出全部 PLAN 后，打包呈现（目标/任务分解/wave 结构 + discuss 收集的灰区与拟采默认 + 上一 phase 遗留项处置 + 成功标准映射），等用户批准。未批准不动工。
2. **SSOT / 设计决策 / 契约歧义**：任何需要修改 SSOT、产生新设计决策、或 SSOT 条款出现歧义的取舍——即使看似细小。SSOT 修改权 exclusively 属用户：agent 仅可起草，未确认不写入；只能以原子 commit 按文档治理规则变更（D-001：先改 SSOT 再动代码）。
3. **异常情形**（含但不限于）：测试持续红无法收敛；plan 与代码现实冲突；需触碰业务库 `data/app.db`；需触碰用户未提交的工作区文件；GSD 技能强制发起交互提问而该问题不能推迟到下一关口。

无人值守段**不得**中途发起 AskUserQuestion——能推迟的问题全部收进关口包；不能推迟的按硬关口 3 停车。

## 3. 红线（任何时候不可触碰，授权不覆盖）

1. **SSOT 权威**：`design/final-design/总设计文档.md` 修改须用户显式授权；`design/` 及其下任何路径未经授权不写入。临时讨论稿与 checkpoint 快照不构成任何实施或修改授权。
2. **测试卫生**：业务库 `data/app.db` 永不用于测试（污染即停车级事故）；测试用 `/tmp/` 临时库（如 `/tmp/uat_dev.db` 拷贝）；测试 uvicorn（mock LLM、独立端口/DB_PATH/JWT_SECRET）用完即停。
3. **用户工作区**：用户未提交的文件（如 prototype 原型改动）绝不触碰、绝不提交、绝不丢弃。
4. **删除**：rm/rmdir/unlink/trash 被 settings 拒绝；任何删除由用户本人执行（`! rm <path>`）。需要删时提出路径并停车或放入待办。
5. **远端**：未经用户指示不 push、不开 PR、不动远端。
6. **分支纪律**：全程在 `feature/m5-assessment` 工作分支推进，不直接开发于 main；GSD 内部 worktree/分支由其自管。
7. **每步落盘**：完成的工作即 commit（CLAUDE.md §5）；自动确认引起的任何错误靠原子 commit 定点回退——这是敢开自动的前提，不得以任何理由绕过。

## 4. 留痕与凭据（自动确认的审计义务）

- 每个 phase 建立 `.planning/phases/<phase 目录>/<NN>-DECISIONS.md`（GSD 建 phase 目录后落文件）。
- **每条代确认记录**：日期时间 / 所在步骤 / 决定内容 / 依据（测试结果、章程条款、SSOT 条款）。一事一条，原子 commit。
- 用户在硬关口给出的裁决（含口头）同样记入。
- 关口包（§2.1）在对话中完整呈现，随后要点记入 DECISIONS。
- 进度权威 = `.planning/ROADMAP.md`；STATE.md 由 GSD 命令维护、可能滞后，冲突时以 ROADMAP 为准。

## 5. 通知约定

- **PushNotification 只发两类**：硬关口就绪（内容含等待事项一句话）；异常停车（含停车原因一句话）。
- 例行进度（wave 完成、fix 完成、verify 通过）不发通知——避免噪音，用户可随时查状态。

## 6. 前置条件、变更与撤回

- **前置**：会话以宽权限模式启动（如 accept edits），否则链条会停在第一个权限弹窗；挂机时段建议接电源（macOS 睡眠只是挂起，无害）。
- **变更**：分权范围的任何增减须经用户明确确认后更新本文件并 commit。
- **撤回**：用户说「撤回自动化授权」即全量回到逐事确认模式，本章程 §1 失效，§2/§3（本来就是底线）不变。
- **终止**：milestone 收尾完成（playbook §5）后授权自动终止。