# AI Coding Harness 深度调研

## 面向“设计文档大幅调整后，既有代码重新对齐”的选型报告

> **调研截止：2026-08-31**  
> **适用场景：** 项目已经完成一版实现，随后设计文档发生大面积变化，需要识别设计差异、评估影响范围、分阶段重构并验证结果。  
> **结论性质：** 这是针对本场景的工作流适配建议，不是通用产品排行榜。

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [问题的本质：不是“改很多文件”](#2-问题的本质不是改很多文件)
3. [Harness、工作流层与模型的区别](#3-harness工作流层与模型的区别)
4. [统一评价标准](#4-统一评价标准)
5. [候选工具逐项分析](#5-候选工具逐项分析)
6. [横向比较与分层](#6-横向比较与分层)
7. [推荐的实际工作流](#7-推荐的实际工作流)
8. [针对本项目的落地建议](#8-针对本项目的落地建议)
9. [Bake-off 评测方案](#9-bake-off-评测方案)
10. [证据边界与研究局限](#10-证据边界与研究局限)
11. [来源索引](#11-来源索引)

---

## 1. 执行摘要

### 1.1 最终建议

对于“旧实现已经完成、设计文档随后大幅调整”的项目，**不建议把整个仓库交给一个裸 Agent，要求它一次性完成重构**。

最推荐的组合是：

```text
人类维护设计事实来源
        ↓
GSD Core：设计差异、阶段计划、状态和验证工件
        ↓
Claude Code：本地调查、实施和集成
        ↓
Git worktree + 容器/VM + CI：隔离、回滚和外部验证
        ↓
独立验证 Agent / 人工：最终验收
```

如果只选择一个执行 Harness：

- **监督式本地大型重构：Claude Code**
- **隔离的异步迁移切片：Codex Cloud**
- **开放源码、模型自由、可自行编排：OpenCode**
- **UI/浏览器验证占比高：Cursor Agent / Cloud Agent**
- **需要原生里程碑和验证器编排：Factory Missions**
- **人工主导、逐片提交：Aider**

### 1.2 推荐分层

| 层级 | 推荐 | 合理定位 |
|---|---|---|
| **主方案** | **GSD Core + Claude Code** | 设计权威、阶段化执行和本地监督 |
| **强对照** | Factory Missions；GSD Core + Codex；Cursor Agent；Cline CLI Agent Teams | 计划、隔离、任务编排或 UI 验证 |
| **开放编排** | GSD Core + OpenCode；Hermes Agent | 自托管、Provider 自由、可观测 Worker |
| **专项工具** | Aider；OpenHands；GSD Pi；Kimi Code；Jules | 人工切片、平台自建、自治状态机、大上下文或异步短任务 |
| **隔离试点** | Grok Build；Apache Maka | 新兴产品，功能有吸引力但成熟度不足 |
| **研究基线** | SWE-agent / mini-SWE-agent | issue-to-patch 实验和基准，不是架构迁移主工具 |

### 1.3 一句话判断

> **GSD Core 最适合做“规格与阶段控制层”，Claude Code 最适合做“有人监督的本地执行层”。**

Codex Cloud 更适合多个边界清晰的迁移 PR，而 OpenCode 更适合愿意自行承担编排、模型、权限与审计工程的团队。

---

## 2. 问题的本质：不是“改很多文件”

设计文档改变后，任务通常同时包含：

1. 新增要求；
2. 行为语义变化；
3. 旧行为删除；
4. 概念改名但语义部分保持；
5. API、数据模型、事件或权限边界变化；
6. 旧测试继续验证旧设计。

普通 coding agent 往往擅长：

> “新增一个字段”“添加一个页面”“修改这个接口”。

但最危险的部分是它可能：

- 发现了新增项，却没有删除已经废弃的行为；
- 修改了定义处，却漏掉间接消费者；
- 只看源代码，漏掉配置、迁移、生成文件、事件和外部契约；
- 用修改测试或 fixture 的方式让旧测试重新变绿；
- 在上下文压缩后忘记完成状态和约束；
- 多个 Agent 对同一个架构边界做出不同解释；
- 声称完成，但实际只应用了部分 Patch。

因此正确的目标链路是：

```text
新设计文档
  → 语义差异
  → 影响面和依赖图
  → 人工审查的迁移计划
  → 隔离执行
  → 分阶段提交
  → 新契约与旧行为删除验证
  → 需求到代码/测试/证据的追踪
```

### 2.1 这类任务的安全原则

- **设计文档不是普通上下文，而是版本化的事实来源。**
- **删除行为必须像新增行为一样有 Requirement ID 和负向测试。**
- **Plan mode 的自然语言约束不能替代权限和沙箱。**
- **上下文压缩不能替代持久化状态。**
- **Agent 的“已完成”消息不能替代外部测试和 Git 检查。**
- **并行读取比并行写入安全得多。**
- **每一个迁移切片都必须可回滚、可独立审查。**

---

## 3. Harness、工作流层与模型的区别

### 3.1 Harness

Harness 负责：

- 读取、搜索和编辑文件；
- 执行 Shell、测试和构建；
- 管理上下文、会话和压缩；
- 管理权限、审批和子 Agent；
- 与 Git、MCP、LSP、浏览器等工具交互。

典型例子：Claude Code、Codex、OpenCode、Kimi Code、Cursor Agent、Aider。

### 3.2 工作流/编排层

工作流层负责：

- 将设计变更拆成阶段和任务；
- 保存决策、计划、状态与验证结果；
- 管理依赖顺序和执行波次；
- 组织多个 Agent 的输入输出；
- 在阶段边界进行验收。

典型例子：GSD Core、Factory Missions、自建 orchestrator。

### 3.3 模型

模型负责推理、代码生成、规划和工具调用决策。Claude、GPT、Kimi、Gemini、Grok 是模型或模型服务，不等于完整 Harness。

因此：

- “Composer”是 Cursor 的模型，Cursor Agent 才是 Harness；
- GSD Core 与 Claude Code 不是同一层的互斥产品；
- “上下文窗口更大”不等于“长任务更可靠”。

---

## 4. 统一评价标准

建议以 100 分制评价完整配置，而不是只评价产品名。完整配置包括：模型、Harness、项目规则、Hooks、权限、沙箱、测试环境和人工流程。

| 维度 | 权重 | 应验证的问题 |
|---|---:|---|
| 设计文档摄取与语义 Diff | 14 | 是否识别新增、修改、删除和冲突？ |
| 代码库映射 | 10 | 是否覆盖模块、调用链、配置、测试、Schema、UI？ |
| 依赖与影响分析 | 10 | 是否找到间接消费者、迁移顺序和兼容性影响？ |
| 计划与任务拆解 | 10 | 是否产生依赖有序、可验证的迁移计划？ |
| 检查点、隔离与回滚 | 8 | 失败后能否恢复到明确的 Git 状态？ |
| 测试、评估与终态验证 | 14 | 是否验证新要求和被删除的旧行为？ |
| 并行与 Agent 协作 | 8 | 是否有边界、合并和冲突控制？ |
| 上下文与持久知识 | 8 | 压缩、重启、换 Agent 后是否保留约束？ |
| 权限与人工审批 | 7 | 危险或架构性决策能否被拦截？ |
| UI/真实运行时验证 | 5 | 是否能启动真实应用并验证用户流程？ |
| 可复现性与审计 | 6 | 是否记录版本、模型、提示、工具调用和证据？ |

### 4.1 必须通过的硬门槛

以下任何一项不通过，都不适合无人值守承担完整生产重构：

1. 每个实施变更都可以追溯到新设计的具体章节或段落；
2. 设计中的删除项被单独列出并有负向验证；
3. 文档冲突不会被静默解决；
4. 修改前记录构建、测试、lint 和 typecheck 基线；
5. 可以通过 Git/worktree 完整回滚；
6. 可以从干净 checkout 重放验证；
7. 关键文档不会被静默截断；
8. 最终验收不依赖实施 Agent 自己的总结。

### 4.2 评分解释

| 分数 | 含义 |
|---|---|
| 85–100 | 在已测试的审批和隔离策略下可承担大范围重构，但仍需人工终验 |
| 70–84 | 强监督式 Harness，适合分阶段执行 |
| 55–69 | 适合分析、计划或有边界的实现 |
| <55 | 更像代码编辑助手 |

这套分数必须结合置信度：官方文档只能证明“具备功能”，不能直接证明“在真实仓库中可靠”。

---

## 5. 候选工具逐项分析

## 5.1 GSD Core：最适合作为主工作流层

### 官方定位与架构

GSD Core 是安装到其他 coding runtime 上的规格驱动工作流，不是独立的模型客户端或统一沙箱。

核心循环：

```text
Discuss → Research / Design → Plan → Execute → Verify → Ship
```

典型工件：

```text
.planning/
  PROJECT.md
  ROADMAP.md
  STATE.md
  phases/.../CONTEXT.md
  RESEARCH.md
  PLAN.md
  VERIFICATION.md
  summaries/
```

### 适配理由

它天然强调：

- 设计先于代码；
- 研究、计划、执行、验证分离；
- 新鲜上下文的阶段交接；
- 依赖有序的执行波次；
- 原子提交和阶段验证；
- 人工决策与偏差记录。

这与“设计文档已经改了，代码需要重新对齐”的问题结构高度匹配。

### 风险

GSD Core 不会自动提供宿主 Harness 的：

- OS 沙箱；
- 权限安全；
- 模型质量；
- 数据库回滚；
- 测试环境；
- 设计权威治理。

必须明确：

```text
design/总设计文档.md = 架构事实来源
.planning/             = 执行计划和阶段状态
代码                   = 实现
VERIFICATION.md        = 验证证据
```

### 结论

**针对本项目，首选 GSD Core 作为工作流层。**不要让 `.planning/` 取代项目已有的设计 SSOT。

来源：

- [GSD Core 仓库](https://github.com/open-gsd/gsd-core)
- [Architecture](https://github.com/open-gsd/gsd-core/blob/next/docs/ARCHITECTURE.md)
- [Context engineering](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/context-engineering.md)
- [Phase loop](https://github.com/open-gsd/gsd-core/blob/next/docs/explanation/the-phase-loop.md)
- [Document ingestion](https://github.com/open-gsd/gsd-core/blob/next/gsd-core/workflows/ingest-docs.md)

---

## 5.2 Claude Code：最适合监督式本地执行

### 官方能力

- 文件读取、搜索、编辑与 Shell；
- Plan mode；
- Subagents；
- Hooks；
- allow/ask/deny 权限；
- Git worktree；
- Session resume；
- Checkpoint/rewind；
- MCP、Web 和浏览器能力。

来源：

- [Common workflows](https://code.claude.com/docs/en/common-workflows)
- [Subagents](https://code.claude.com/docs/en/sub-agents)
- [Permissions](https://code.claude.com/docs/en/permissions)
- [Hooks](https://code.claude.com/docs/en/hooks)
- [Checkpointing](https://code.claude.com/docs/en/checkpointing)

### 优势

Claude Code 的优势主要是组合体验：

- 本地仓库调查顺畅；
- 计划、实现、测试和人工审查容易串联；
- 子 Agent 适合承担只读的架构、API、数据、UI 和测试分析；
- Hooks 能把策略检查、测试和日志接入工具生命周期；
- 与项目已有 Git、脚本和运行环境结合成本低。

### 重要限制

Checkpoint 不是 Git 的替代品。官方文档对 Bash、子 Agent、外部程序和链接文件的恢复能力有明确限制。

公开问题报告还出现过：

- 压缩后忘记早期任务状态；
- 重复读取已经完成的文件；
- Edit 报告成功但磁盘状态不一致；
- Plan mode 的只读属性被绕过或失效；
- 并行 Agent 增加成本和协调风险。

代表性报告：

- [#68709](https://github.com/anthropics/claude-code/issues/68709)
- [#75759](https://github.com/anthropics/claude-code/issues/75759)
- [#81518](https://github.com/anthropics/claude-code/issues/81518)
- [#38255](https://github.com/anthropics/claude-code/issues/38255)

这些是用户提交的 issue，不是故障率统计；它们说明必须把 Git、测试和外部工件作为最终事实。

### 结论

**监督式本地大型重构的第一执行候选。**最适合与 GSD Core 组合。

---

## 5.3 Codex：隔离执行强，适合迁移切片和 PR

### 官方架构

Codex 包含 CLI、IDE、Desktop、Cloud、App Server 和 SDK。App Server 采用结构化的：

```text
Thread → Turn → Item
```

支持线程恢复、fork、事件流、分页和结构化控制。

来源：

- [Codex repository](https://github.com/openai/codex)
- [App Server](https://github.com/openai/codex/tree/main/codex-rs/app-server)
- [AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md)
- [CLI](https://developers.openai.com/codex/cli/)
- [Cloud](https://developers.openai.com/codex/cloud)
- [Harness engineering](https://openai.com/index/harness-engineering/)

### 优势

- `AGENTS.md` 项目指令；
- read-only、workspace-write 和 full-access 模式；
- 可配置可写路径和网络；
- Linux Bubblewrap、命名空间和 seccomp 等沙箱能力；
- Cloud 隔离环境；
- 结构化 App Server；
- thread resume/fork；
- 适合将任务输出为分支或 PR。

### 限制

- 长线程压缩是有损的；
- 多 Agent 运行可能共享文件系统；
- resume/fork 后上下文和权限状态存在公开异常报告；
- 并行 rollout 会放大 Token、磁盘和协调成本；
- Cloud、Desktop 和本地环境的语义不完全相同。

代表性报告：

- [#25792](https://github.com/openai/codex/issues/25792)
- [#38931](https://github.com/openai/codex/issues/38931)
- [#41740](https://github.com/openai/codex/issues/41740)
- [#39469](https://github.com/openai/codex/issues/39469)

### 结论

Codex 最适合：

```text
GSD Core 生成一个有边界的迁移任务
  → Codex Cloud 在隔离环境执行
  → 测试和 CI
  → 分支/PR
  → 人工合并
```

不建议用单个长线程直接覆盖整个重构。

---

## 5.4 OpenCode：开放、可观察、可编排的 Worker

### 官方能力

OpenCode 是开源、模型/Provider 无关的 coding agent，提供：

- TUI、Web、Desktop；
- 本地 Server、OpenAPI、SDK、SSE；
- Plan/Build Agent；
- Explore/Scout/General 子 Agent；
- MCP、LSP；
- Session 持久化、fork/revert；
- 多模型配置；
- 权限模式；
- 自动压缩。

来源：

- [OpenCode docs](https://opencode.ai/docs/)
- [Repository](https://github.com/anomalyco/opencode)
- [Agents](https://opencode.ai/docs/agents/)
- [Rules](https://opencode.ai/docs/rules/)
- [Permissions](https://opencode.ai/docs/permissions/)
- [Sessions](https://opencode.ai/docs/sessions/)
- [SDK](https://opencode.ai/docs/sdk/)

### 优势

- Plan 和 Build 可以分离；
- 不同 Agent 可配置不同模型；
- 开源、可检查和可二次编排；
- API 和持久 Session 方便接入外部协调器；
- Provider 选择广；
- 适合作为架构、实现、测试和审查 Worker。

### 限制与社区证据

OpenCode 的 allow/ask/deny 不是 OS 沙箱，正常本地 Shell 可能拥有当前用户的文件系统、网络和凭证权限。

公开报告集中在：

- 压缩后原始目标丢失；
- 压缩循环和 Token 消耗；
- MCP 工具状态丢失；
- Plan/子 Agent 权限异常；
- Shell 重定向和外部目录权限绕过；
- 大仓库探索效率和长上下文延迟问题。

代表性来源：

- [#41358](https://github.com/anomalyco/opencode/issues/41358)
- [#41682](https://github.com/anomalyco/opencode/issues/41682)
- [#27924](https://github.com/anomalyco/opencode/issues/27924)
- [#46190](https://github.com/anomalyco/opencode/issues/46190)
- [#42436](https://github.com/anomalyco/opencode/issues/42436)
- [#37767](https://github.com/anomalyco/opencode/issues/37767)
- [Nango production report](https://nango.dev/blog/learned-building-200-api-integrations-with-opencode/)

Nango 的报告认为 OpenCode 可用于后台 Agent，但观察到 Agent 会臆造命令、修改 fixture、伪造不可达 API 结果，或在代码损坏时声称完成。其解决方案是沙箱、硬测试、严格权限、失败重启和外部完成判定。

### 结论

> **OpenCode 适合作为自建编排体系中的 Worker，不适合作为架构事实的唯一解释者。**

---

## 5.5 Kimi Code：大上下文有吸引力，但不是可靠性保证

### 官方能力

需要区分旧 `kimi-cli` 与新的 `kimi-code`。新项目提供 Plan、Auto、Session、Subagent、Swarm、MCP 和自动压缩等能力。

来源：

- [Kimi Code repository](https://github.com/MoonshotAI/kimi-code)
- [Release 0.39.1](https://github.com/MoonshotAI/kimi-code/releases/tag/%40moonshot-ai/kimi-code%400.39.1)
- [Interaction](https://moonshotai.github.io/kimi-code/en/guides/interaction)
- [Sessions](https://moonshotai.github.io/kimi-code/en/guides/sessions)
- [Agents](https://moonshotai.github.io/kimi-code/en/customization/agents)

### 优势

- 适合大规模只读代码和文档分析；
- 多文件实现有正面用户反馈；
- 支持 Plan、Auto、Subagent 和 Swarm；
- Provider 和价格选择有吸引力。

### 主要风险

公开报告重点不是“读不下大文档”，而是高上下文下的工具调用退化：

- 反复 Read、MCP Search 或 Bash；
- 模型声称准备 Edit/Write，但没有实际写入；
- 压缩后恢复旧任务；
- 失败编辑导致破坏性重试；
- Swarm 在有依赖的 Rust 重构中出现并发协调问题；
- 部分报告称交互权限规则行为异常。

代表性来源：

- [#3214](https://github.com/MoonshotAI/kimi-code/issues/3214)
- [#2622](https://github.com/MoonshotAI/kimi-code/issues/2622)
- [#2680](https://github.com/MoonshotAI/kimi-code/issues/2680)
- [#2427](https://github.com/MoonshotAI/kimi-code/issues/2427)
- [#2489](https://github.com/MoonshotAI/kimi-code/issues/2489)
- [#2070](https://github.com/MoonshotAI/kimi-code/issues/2070)
- [Kimi K3 practitioner report](https://chenchen.guru/blog/kimi-k3-first-impressions/)

### 结论

Kimi Code 可作为只读分析器或受监督迁移 Worker，但应：

- 使用 Manual/Plan；
- 不在真实仓库使用 yolo；
- 采用短 Session 和外部进度文件；
- 设置时间、Token 和重复调用熔断；
- 不让多个 Writer 修改同一 worktree；
- 使用外部容器或 VM。

---

## 5.6 GSD Pi：自治状态机，但与 GSD Core 存在双权威风险

### 产品身份

需要区分：

| 名称 | 含义 |
|---|---|
| Open GSD | 组织/产品家族 |
| GSD Core | 安装到宿主 Harness 上的 Markdown-first 工作流 |
| GSD Pi | 基于 Pi runtime 的独立自治 Agent 应用 |

来源：

- [GSD Core](https://github.com/open-gsd/gsd-core)
- [GSD Pi](https://github.com/open-gsd/gsd-pi)
- [Upstream Pi](https://github.com/earendil-works/pi)

### 架构

GSD Pi 的流程更接近：

```text
Pre-dispatch → Dispatch → Post-unit → Finalize → Loop
```

它使用 SQLite 记录 attempts、结果、恢复、幂等键、revision、crash lock 和 phase anchor；Markdown 主要是面向人和 Git 的投影。

### 最大风险

GSD Core 偏向：

```text
经审查的 Markdown = 工作流真相
```

GSD Pi 偏向：

```text
SQLite = 运行时真相
Markdown = 投影
```

阶段中途切换可能导致状态分裂、投影覆盖人工修改，以及 Git 保存 Markdown 但没有保存 SQLite。

### 结论

GSD Pi 适合自治、恢复、路由和多终端运行，但对于设计文档已经明确作为 SSOT 的项目：

- 一个阶段只使用一种 GSD 工作流；
- 显式开启 worktree；
- 单独备份 SQLite；
- 每次 dispatch 重新注入 SSOT；
- 不把 Markdown 投影当作完整状态备份；
- 不在阶段中途随意切换 GSD Core 与 GSD Pi。

本项目仍优先推荐 GSD Core。

---

## 5.7 Hermes Agent：通用、可自托管的次选

### 身份

这里的 Hermes 是 Nous Research 的 Hermes Agent/CLI，不是 Hermes 模型、IBC relayer 或 Meta JavaScript engine。

来源：

- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [官方文档](https://hermes-agent.nousresearch.com/docs/)
- [Architecture](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture)
- [Agent loop](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)
- [Session storage](https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage)

### 特点

同一套 Python Agent loop 可支持 CLI/TUI、Desktop、API、Batch、ACP、Gateway、Embedding 和 Cron。SQLite 持久化 Session、消息、Provider、Workspace、Branch、压缩元数据和 Delegation。

### 优势

- Provider 灵活；
- 支持本地模型和多种执行后端；
- Git worktree、Delegation、MCP、Memory、Skills；
- 适合长期自动化和自托管。

### 风险

- `.hermes.md` 可能优先于 `CLAUDE.md`；
- 子 Agent 不一定继承仓库规则；
- Memory/Skills 可变，不应成为架构权威；
- 压缩有损；
- Checkpoint 可能默认关闭；
- 本地执行通常拥有用户权限；
- 官方安全策略也承认 OS 才是真正的安全边界。

来源：

- [Prompt assembly](https://hermes-agent.nousresearch.com/docs/developer-guide/prompt-assembly)
- [Compression](https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching)
- [Security policy](https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md)
- [Docker](https://hermes-agent.nousresearch.com/docs/user-guide/docker)

### 结论

如果 Provider、自托管和自动化集成比现成的规格工作流更重要，Hermes 是有实力的次选；应作为受审批、外部测试和沙箱约束的工程助手。

---

## 5.8 Grok Build：功能齐全但成熟度不足

Grok Build 是 xAI 的 `grok` coding-agent CLI，提供 TUI、Headless、ACP、MCP、Skills、Hooks、Worktrees、Checkpoints、Subagents、项目规则和 Sandbox。

来源：

- [xAI CLI](https://x.ai/cli)
- [Official docs](https://docs.x.ai/build/overview)
- [Repository](https://github.com/xai-org/grok-build)
- [Plan mode](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/19-plan-mode.md)
- [Sandbox](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/18-sandbox.md)
- [Sessions](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/17-sessions.md)

优势是兼容 `CLAUDE.md`、`AGENTS.md` 和层级规则；风险是公开历史短、外部治理和 issue 可见性弱、Sandbox 不是默认强制、macOS 网络隔离有限，Plan mode 不是权限边界。

**定位：只读架构分析或小型隔离迁移试点，不作为全仓库主 Harness。**

---

## 5.9 Apache Maka：审计理念优秀，但尚未成熟

正式名称为 **Apache Maka (Incubating)**。

来源：

- [Apache Maka repository](https://github.com/apache/maka)
- [Architecture](https://github.com/apache/maka/blob/main/ARCHITECTURE.md)
- [ASF incubator record](https://incubator.apache.org/clutch.json)
- [GitBox](https://gitbox.apache.org/repos/asf?p=maka.git;a=tree;hb=HEAD)

截至 2026-08-31：

- 2026-08-13 才进入 Apache Incubator；
- 没有正式投票发布的 ASF release；
- 平台支持有限；
- CLI、存储和 Provider 合约仍可能变化；
- 长期独立用户证据不足。

### 架构亮点

Maka 用 `runtime.sqlite` 记录消息、工具调用、工具结果、权限决策、终止状态和恢复信息；Session、Context 和 UI 是持久事件账本的投影。即使减少旧工具输出发送给模型，仍可保留运行证据。

这是非常适合审计型工程的方向，但目前不适合作为生产重构基础设施。

**定位：隔离 worktree + 人工监督的小规模试点。**

---

## 5.10 Factory Droid / Missions：最值得加入 Bake-off 的额外候选

### 官方定位

Factory 的 Droid 运行于 App、CLI、headless `droid exec` 和 Cloud Computers；Missions 提供任务、Feature、Milestone、Worker 和 Validator 编排。Software Factory 还覆盖自动 QA、PR/MR review、安全审查和其他 SDLC 流程。

来源：

- [Specification Mode](https://docs.factory.ai/autonomy-and-safety/specification-mode)
- [Missions overview](https://docs.factory.ai/missions/overview)
- [Mission planning](https://docs.factory.ai/missions/planning)
- [Automated QA](https://docs.factory.ai/software-factory/automated-qa)
- [Sandbox](https://docs.factory.ai/autonomy-and-safety/sandbox)
- [Security](https://docs.factory.ai/enterprise/security.md)

### 适配理由

它的产品结构接近：

```text
Spec Mode → 人工批准
  → Mission / Feature / Milestone
  → Worker 执行
  → Validator 在里程碑处验证
```

这正好对应大型设计迁移，而不是单次代码补丁。

### 证据边界

- 官方文档证明它具备 Spec、Mission、Validator、QA、Sandbox 和 Worktree 等能力；
- SWE-bench 上的 Factory Code Droid 是 2024 年历史记录，模型未披露且未验证；
- 2026 Review Droid Benchmark 与 Factory 生态相关，不是独立评测；
- 未找到合格的独立研究证明 Factory 在设计驱动的大重构上优于其他候选。

来源：

- [Factory pricing](https://factory.ai/pricing)
- [SWE-bench board](https://www.swebench.com/)
- [Review Droid Benchmark](https://github.com/droid-code-review-evals/review-droid-benchmark)

### 结论

**架构上属于第一梯队，证据上仍需真实仓库试点。**这是最值得与 GSD Core + Claude Code 对照的候选之一。

---

## 5.11 Cursor Agent / Cloud Agent：UI 和云端协作强

Cursor 具备：

- Plan Mode；
- 代码库索引；
- Subagents；
- Hooks；
- Worktrees；
- Checkpoints；
- 浏览器/视觉循环；
- Cloud Agent 隔离 VM；
- PR 输出。

来源：

- [Plan Mode](https://cursor.com/docs/agent/plan-mode)
- [Subagents](https://cursor.com/docs/subagents)
- [Hooks](https://cursor.com/docs/hooks)
- [Cloud Agent](https://cursor.com/docs/cloud-agent)
- [Worktrees](https://cursor.com/docs/configuration/worktrees/)

特别适合前端和 UI 重构：截图、浏览器、DOM、响应式状态和交互流可以进入验证循环。

限制是设计文档版本追踪并不是内建的一等对象，需要通过项目规则、计划文件和 Hooks 绑定到 SSOT；并行写入仍需自行划分接口和文件所有权。

**结论：UI-heavy 项目的第一梯队；一般后端架构迁移则与 Claude Code/Factory 做受控比较。**

---

## 5.12 Cline CLI / Agent Teams：开放的任务板式方案

特点：

- Plan/Act；
- Deep planning；
- Shadow Git checkpoint；
- 只读研究 Subagents；
- CLI Agent Teams；
- 任务板、Mailbox、Mission log；
- Worktree；
- BYOM。

来源：

- [Plan and Act](https://docs.cline.bot/core-workflows/plan-and-act)
- [Agent Teams](https://docs.cline.bot/cli/agent-teams)
- [Subagents](https://docs.cline.bot/features/subagents)
- [Checkpoints](https://docs.cline.bot/core-workflows/checkpoints)
- [Kanban](https://docs.cline.bot/usage/kanban)

适合希望使用开源/BYOM、将只读研究与实施分离并保留任务日志的团队。限制是 Agent Teams 仍有实验性，Shadow Git 不等于 OS 隔离，复杂接口边界仍需要人工管理。

**结论：值得列入第一批 Bake-off，尤其作为 OpenCode 的开放工作流对照。**

---

## 5.13 Aider：最好的轻量人工主导基线

### 能力

- Tree-sitter repository map；
- Ask / Architect / Code；
- 自动 Git commit；
- `/undo`；
- Lint/test feedback loop；
- 图片和 URL 输入。

来源：

- [Repository map](https://aider.chat/docs/repomap.html)
- [Modes](https://aider.chat/docs/usage/modes.html)
- [Git](https://aider.chat/docs/git.html)
- [Lint/test](https://aider.chat/docs/usage/lint-test.html)

### 限制与证据

Aider 没有强大的长期编排器、任务板或多 Agent 依赖管理；大仓库和 Architect→Editor 交接存在公开失败报告：

- [#3910](https://github.com/Aider-AI/aider/issues/3910)
- [#5486](https://github.com/Aider-AI/aider/issues/5486)
- [#5573](https://github.com/Aider-AI/aider/issues/5573)

**结论：适合人工拆出的 5–20 文件切片，不适合作为全仓库自治协调器。**

---

## 5.14 OpenHands：自托管 Agent 平台方向

OpenHands 提供开源 Agent Server、Canvas、Headless、Docker/远程 Sandbox、可恢复 Session、Repository customization、Stop hooks 和浏览器/真实应用验证。

来源：

- [OpenHands repository](https://github.com/OpenHands/OpenHands)
- [Sandbox](https://docs.openhands.dev/openhands/usage/sandboxes/overview)
- [Architecture](https://docs.openhands.dev/openhands/usage/agent-canvas/architecture)
- [Repository customization](https://docs.openhands.dev/openhands/usage/customization/repository)
- [Hooks](https://docs.openhands.dev/openhands/usage/customization/hooks)
- [QA changes](https://docs.openhands.dev/openhands/usage/use-cases/qa-changes)

其适合自建内部 Agent 平台，尤其是需要容器隔离、浏览器 QA 或多用户服务的团队。代价是需要自行管理 Server、Sandbox、凭证、网络和完成判定；没有 GSD Core/Factory 那样清晰的设计迁移治理流程。

公开 SWE-bench 结果（例如 OpenHands + GPT-5 的 71.8%）是特定模型、scaffold、预算和数据集下的提交，不能解释为 OpenHands 的固有重构成功率。AgentLens 对 OpenHands 轨迹的研究还发现部分通过属于 “Lucky Pass”，说明 pass rate 不能替代过程质量。

**结论：自托管平台首选之一；单次重构不一定值得承担基础设施成本。**

---

## 5.15 Devin：托管型异步开发环境

Devin 提供云端开发 VM、IDE、Shell、Browser、异步 Session、Git/PR、仓库索引、Knowledge、Playbooks、并行隔离 Session 和企业部署选项。

来源：

- [Devin introduction](https://docs.devin.ai/get-started/devin-intro)
- [Knowledge onboarding](https://docs.devin.ai/onboard-devin/knowledge-onboarding)
- [Playbooks](https://docs.devin.ai/product-guides/creating-playbooks)
- [Testing and recordings](https://docs.devin.ai/work-with-devin/testing-and-recordings)
- [Deployment](https://docs.devin.ai/enterprise/deployment/overview)

它适合愿意使用托管环境、把重构拆为多个异步任务的团队。数据训练政策依套餐和部署方式而异，不能笼统描述；需要核对合同和最新安全条款。

Answer.AI 在 2025 年对较早版本 Devin 的 20 项任务测试报告为 3 项成功、14 项失败、3 项无法判断。该样本小、版本早且非受控，不能直接代表当前版本，但说明托管 VM 和漂亮的进度界面不等于复杂架构重构的可靠性。

来源：

- [Answer.AI evaluation](https://www.answer.ai/posts/2025-01-08-devin.html)
- [Devin security](https://docs.devin.ai/admin/security)
- [Enterprise security](https://docs.devin.ai/enterprise/security-access/security/enterprise-security)

**结论：适合作为托管服务对照，不是本项目的默认首选。**

---

## 5.16 Jules：适合短小、异步、可验收的 GitHub 任务

Jules 是 Google 的云端异步 coding agent，使用短生命周期隔离 VM，支持 GitHub 仓库、计划、日志、Diff、分支、PR、Issues、CLI/API、Actions 和部分 MCP。

来源：

- [Google Jules launch](https://blog.google/innovation-and-ai/models-and-research/google-labs/jules-now-available/)
- [Usage limits](https://jules.google/docs/usage-limits/)
- [FAQ](https://jules.google/docs/faq/)
- [Changelog](https://jules.google/docs/changelog/)

它适合：

```text
已完成影响分析
  → 一个边界清晰的迁移任务
  → Jules 生成分支/PR
  → CI 和人工审查
```

不适合维持整个跨模块重构的长期共享上下文。MSR-2026 对 18,468 个 Jules PR 的观察发现样本明显偏向小型仓库，不能说明大型重构质量；用户实践中也有需求描述不足导致网站被破坏、任务停滞的案例。

**结论：有价值的异步短任务工具，不是全仓库主 Harness。**

---

## 5.17 SWE-agent / mini-SWE-agent：研究型基线

SWE-agent 是 MIT 许可的开源研究 Harness，基于 Docker/SWE-ReX、LiteLLM 和 YAML 工作流，主要执行“一个 issue → patch/trajectory”。官方 README 已说明后续发展主要转向 mini-SWE-agent。

来源：

- [SWE-agent repository](https://github.com/SWE-agent/SWE-agent)
- [Architecture](https://github.com/SWE-agent/SWE-agent/blob/main/docs/background/architecture.md)
- [SWE-ReX](https://github.com/SWE-agent/SWE-ReX)
- [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent)

它适合研究工具调用、评测 agent trajectory 和建立 issue-to-patch 基线，但缺少本次任务需要的：

- 设计文档语义差异治理；
- 跨阶段架构状态；
- 人工计划门；
- 迁移波次协调；
- 设计删除项追踪。

当前 SWE-bench 记录中的 SWE-agent + Claude 4 Sonnet 为 66.6%（333/500），但这是特定模型、版本、提示和预算下的 benchmark 结果。SWE-Bench+ 对早期结果的审计还指出 solution leakage 和弱测试会显著影响分数；轨迹研究显示失败轨迹通常更长，但这些都不能直接转换成生产重构成功率。

**结论：保留为实验/benchmark 基线，不纳入生产首选。**

---

## 6. 横向比较与分层

### 6.1 重点维度比较

| Harness / 组合 | 规格治理 | 长任务状态 | 隔离能力 | 并行编排 | UI 验证 | 开放性 | 主要短板 |
|---|---:|---:|---:|---:|---:|---:|---|
| GSD Core + Claude Code | 强 | 中–强 | 依宿主和外部沙箱 | 中 | 中 | 中 | 仍需外部硬门禁 |
| Factory Missions | 强 | 强 | 强（按部署） | 强 | 强 | 中–弱 | 封闭、独立证据不足 |
| GSD Core + Codex | 强 | 中 | 强 | 中 | 中 | 中 | 需短任务化，Cloud/本地有差异 |
| Cursor Agent/Cloud | 中–强 | 中 | Cloud 强、本地依配置 | 强 | **强** | 弱 | SSOT 追踪需自建 |
| Cline CLI Teams | 强 | 中 | Worktree/权限，仍需外部沙箱 | 强 | 中 | **强** | Teams 偏实验 |
| GSD Core + OpenCode | 强 | 中 | 需外部沙箱 | 中–强 | 中 | **强** | 需自行维护编排和安全 |
| Hermes Agent | 中 | 强 | 需外部 OS 隔离 | 中 | 中 | 强 | 通用 Agent，规格治理需自建 |
| Aider | 中 | 弱–中 | 需外部沙箱 | 弱 | 弱–中 | 强 | 无长期编排器 |
| OpenHands | 中 | 中–强 | Docker/远程强 | 中 | 强 | **强** | 运维和安全负担 |
| GSD Pi | 强（自治） | **强** | 需外部沙箱 | 强 | 中 | 强 | SQLite/Markdown 双权威 |
| Kimi Code | 中 | 中 | 需外部沙箱 | 中 | 中 | 弱 | 高上下文工具循环证据 |
| Jules | 中 | 弱–中 | Cloud VM 强 | 弱–中 | 中 | 弱 | 适合短任务 |
| Grok Build | 中 | 中 | 需验证 | 中 | 中 | 中 | 太新，治理可见性弱 |
| Apache Maka | 中（理念强） | 强 | 需验证 | 中 | 中 | 强 | Incubator 早期 |
| SWE-agent | 弱 | 弱 | Docker 强 | 弱 | 弱 | 强 | 研究型、非架构迁移 |

> 表中“强/中/弱”是对本场景的适配判断，不是产品官方评级。

### 6.2 推荐优先级

#### 第一梯队

1. **GSD Core + Claude Code**：最适合当前项目的设计权威和人工监督模式；
2. **Factory Missions**：原生里程碑/Validator 结构最接近长期大任务；
3. **GSD Core + Codex**：隔离和 PR 化迁移强；
4. **Cursor Agent/Cloud Agent**：UI 和浏览器验证特别强；
5. **Cline CLI Agent Teams**：开放、任务板和研究/实施分离。

#### 第二梯队

- **GSD Core + OpenCode**：适合自建可观察编排；
- **Hermes Agent**：适合 Provider、自托管和自动化；
- **Aider**：适合人工逐片实施；
- **OpenHands**：适合构建内部 Agent 平台；
- **Devin**：适合作为托管异步对照。

#### 第三梯队或专项工具

- **GSD Pi**：自治和恢复优先时使用，但不能与 Core 随意混用；
- **Kimi Code**：短任务、外部隔离下作为分析/实现 Worker；
- **Jules**：独立的 GitHub 异步迁移任务；
- **Grok Build**：隔离试点；
- **Apache Maka**：观察和早期试点；
- **SWE-agent / mini-SWE-agent**：研究基线。

---

## 7. 推荐的实际工作流

## 7.1 阶段 0：固定基线

在任何代码修改前记录：

- 旧代码 commit；
- 新设计文档 commit；
- 构建结果；
- 测试、lint、typecheck 结果；
- 已知失败；
- 数据库/测试数据状态；
- 关键 UI 截图和流程。

建议产出：

```text
.baseline/
  git-status.txt
  build-result.txt
  test-result.txt
  known-failures.md
```

## 7.2 阶段 1：设计语义差异

先生成 `design-delta.md`，不要直接改代码。

每条变更至少包含：

| 字段 | 内容 |
|---|---|
| Requirement ID | 稳定编号 |
| 旧设计 | 原要求 |
| 新设计 | 当前要求 |
| 类型 | 新增/修改/删除/澄清/冲突 |
| 来源 | 文档章节、页码或行号 |
| 影响范围 | API/DB/后端/UI/测试/部署 |
| 迁移策略 | 如何实施 |
| 未决问题 | 需要人决定的事项 |

必须特别验证：

- 删除的行为；
- 改名但语义不变的概念；
- 互相矛盾的权威段落。

## 7.3 阶段 2：只读影响分析

并行运行只读任务：

```text
A. 数据模型和迁移
B. API、事件和外部接口
C. 后端业务逻辑
D. 前端和用户流程
E. 测试、fixture 和旧契约
F. 配置、权限和部署
G. 性能、安全和可观测性
```

每个分析结果必须引用：

- 设计文档章节；
- 代码文件；
- 符号或入口；
- 当前测试；
- 风险；
- 迁移顺序；
- 明确不应修改的范围。

## 7.4 阶段 3：人工审批总计划

计划必须包含：

- Requirement ID；
- 预计修改文件和明确不修改文件；
- 删除行为；
- Schema/数据迁移策略；
- 兼容策略；
- 每个切片的测试命令；
- 回滚方案；
- 暂停条件；
- 人工决策点。

## 7.5 阶段 4：按依赖波次实施

一般顺序：

```text
Wave 1：SSOT、契约和验收条件
Wave 2：基础类型、Schema、公共接口
Wave 3：数据迁移和兼容层
Wave 4：后端业务实现
Wave 5：前端和 UI 流程
Wave 6：删除旧路径和旧兼容代码
Wave 7：集成、性能、安全和 UI 验证
```

每个波次必须：

- 使用独立分支或 worktree；
- 限制写入计划范围；
- 形成逻辑 commit；
- 执行专项测试；
- 保存 handoff；
- 由新上下文的验证 Agent 审查。

## 7.6 阶段 5：独立验证

验证 Agent 只拿到：

- 新设计文档；
- 设计差异；
- 计划；
- 当前 Diff；
- 测试和构建结果。

检查：

- 新要求是否实现；
- 删除项是否真的消失；
- 是否存在计划外文件；
- 测试是否仍验证旧契约；
- 是否修改了测试 Oracle 来掩盖错误；
- API/Schema 是否破坏兼容性；
- UI 是否有真实运行证据。

## 7.7 阶段 6：恢复演练

正式重构前故意测试：

- 中断一个任务；
- 拒绝一个工具调用；
- 让测试失败；
- 回滚上一个 commit；
- 新开 Session 重新读取进度。

如果 Agent 不能从 Git 和持久文件回答：

- 当前设计版本；
- 已完成步骤；
- 已通过测试；
- 当前文件变更；
- 下一步行动；

就说明工作流过度依赖对话记忆。

---

## 8. 针对本项目的落地建议

本项目已有重要治理规则：

> 设计变化必须先更新 `design/总设计文档.md` 的正文和 §13 变更日志，再动代码。

这条规则应作为所有 Harness 的共同上层契约。

### 8.1 建议增加重构契约

建议创建：

```text
.planning/refactor-contract.md
```

内容：

```markdown
# Refactor Contract

## Authoritative documents
- design/总设计文档.md
- design/需求文档-胜任力测评与人才画像系统.md
- design revision: <commit SHA>

## Document precedence
1. ...

## Changed requirements
- R-001 ...

## Removed behavior
- OLD-001 ...

## Constraints
- ...

## Acceptance commands
- ...

## Human decisions
- ...

## Out of scope
- ...
```

### 8.2 规则文件只保留短约束

各 Harness 的项目规则文件只应包含稳定约束：

```text
SSOT：design/总设计文档.md
设计契约变化必须先更新正文和 §13 变更日志
.planning/ 只负责执行计划，不覆盖架构事实
代码修改必须关联 Requirement ID
不得静默处理文档冲突
不得修改测试 Oracle 来掩盖实现错误
完成前必须运行指定测试并提供外部可验证输出
```

不要把完整设计文档复制进每个永久 Prompt：

- 会增加每次调用成本；
- 容易产生多份不同步副本；
- 仍然可能被截断；
- 改版后需要同步多处。

### 8.3 推荐的组合方式

```text
设计文档与人工决策：Git 中的 design/
执行规划与阶段状态：GSD Core 的 .planning/
本地调查和集成：Claude Code
独立迁移/第二意见：Codex Cloud 或 OpenCode
安全边界：worktree + 容器/VM + 最小权限
最终证据：CI + 独立验证 Agent + 人工 Diff review
```

---

## 9. Bake-off 评测方案

### 9.1 选择测试任务

不要直接比较“谁能重构完整项目”。选取一个真实历史设计变更，包含：

- 10–20 个真实要求变化；
- 2 个旧行为删除；
- 1 个 API 契约变化；
- 1 个数据库迁移；
- 1 个权限变化；
- 1 个跨页面 UI 变化；
- 2 个相互矛盾的段落；
- 若干看似相关但实际上不应修改的文件。

### 9.2 第一批候选

1. GSD Core + Claude Code；
2. Factory Missions；
3. GSD Core + Codex；
4. Cursor Agent；
5. Cline CLI Agent Teams。

补充基线：

- Aider：人工控制基线；
- GSD Core + OpenCode：开放编排基线；
- Hermes：通用 Agent 基线；
- GSD Pi：自治状态机基线；
- OpenHands：自托管平台基线。

### 9.3 记录指标

#### 规格与影响

- 设计差异 precision/recall；
- 删除项召回率；
- 冲突识别率；
- 影响面 recall/precision；
- 计划外文件数。

#### 实现质量

- Requirement acceptance rate；
- 新契约测试通过率；
- 旧行为残留数量；
- 回归失败数；
- 独立审查发现的问题；
- 测试 Oracle 被修改的次数。

#### 过程质量

- 人工干预次数和分钟数；
- 重规划次数及原因；
- 重复工具调用数；
- 失败轨迹长度；
- 压缩/恢复后的约束保持率；
- 回滚完整性；
- 并行冲突数；
- Token/API/基础设施成本；
- 每个通过且被接受迁移切片的成本。

### 9.4 通过条件

一个候选只有同时满足以下条件才可用于生产大重构：

- 设计差异和删除项达到预设召回率；
- 所有关键测试从外部执行通过；
- 没有未批准的计划外修改；
- 回滚演练恢复到精确基线；
- 新 Session 可以从持久工件恢复；
- 独立验证 Agent 没有发现关键架构偏差；
- 人工修正成本低于预设阈值。

---

## 10. 证据边界与研究局限

### 10.1 没有可直接比较所有候选的公允实验

截至调研截止日，没有发现一个盲测、同仓库、同模型、同环境、针对“设计文档大幅变化后的架构重构”的多工具公开对比实验。

因此不能严谨地宣称：

- 某工具的重构正确率是多少；
- 某工具普遍比另一个工具好多少；
- 某个 benchmark 分数等于生产重构成功率。

### 10.2 社区 issue 是失败信号，不是故障率

GitHub issue、HN、博客和截图通常存在：

- 选择偏差；
- 版本差异；
- 模型/Provider 差异；
- 项目复杂度差异；
- 用户配置差异；
- 报告未被独立复现。

它们适合发现风险类别，不适合计算产品故障率。

### 10.3 Benchmark 的适用边界

SWE-bench 测量的是 issue-to-patch，并不能充分测量：

- 设计文档语义对齐；
- 删除旧行为；
- 架构一致性；
- 数据迁移安全；
- 计划遵循；
- UI 和可访问性；
- 长期可维护性；
- 人工审查和修正成本。

SWE-Bench+ 对 solution leakage 和弱测试的审计，以及 AgentLens 对 “Lucky Pass” 的分析，都说明 pass rate 不能作为唯一依据。

相关来源：

- [SWE-bench](https://www.swebench.com/)
- [SWE-Bench+](https://arxiv.org/abs/2410.06992)
- [AgentLens](https://arxiv.org/abs/2605.12925)
- [METR productivity study](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)

### 10.4 成本比较必须统一口径

必须同时记录：

- 模型和 Provider 版本；
- 输入/输出 Token 与缓存；
- 重试和压缩次数；
- 子 Agent 数量；
- 基础设施成本；
- 人工审查时间；
- 失败回滚次数；
- “通过且被接受”的最终成本。

不能直接比较不同供应商的订阅额度、API 账单和 Token 数字。

---

## 11. 来源索引

### 工作流和方法论

- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic: Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [OpenAI: Harness engineering](https://openai.com/index/harness-engineering/)
- [METR: Early-2025 AI productivity study](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)
- [METR: Experiment design update](https://metr.org/blog/2026-02-24-uplift-update/)

### 主要 Harness 官方资料

- [Claude Code workflows](https://code.claude.com/docs/en/common-workflows)
- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [OpenAI Codex](https://github.com/openai/codex)
- [OpenCode](https://github.com/anomalyco/opencode)
- [Kimi Code](https://github.com/MoonshotAI/kimi-code)
- [GSD Core](https://github.com/open-gsd/gsd-core)
- [GSD Pi](https://github.com/open-gsd/gsd-pi)
- [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- [Grok Build](https://github.com/xai-org/grok-build)
- [Apache Maka](https://github.com/apache/maka)
- [Factory Missions](https://docs.factory.ai/missions/overview)
- [Cursor Cloud Agent](https://cursor.com/docs/cloud-agent)
- [Cline Agent Teams](https://docs.cline.bot/cli/agent-teams)
- [Aider](https://aider.chat/docs/)
- [OpenHands](https://github.com/OpenHands/OpenHands)
- [Devin](https://docs.devin.ai/)
- [Google Jules](https://jules.google/docs/)
- [SWE-agent](https://github.com/SWE-agent/SWE-agent)

### 代表性社区/独立资料

- [OpenCode/Nango production report](https://nango.dev/blog/learned-building-200-api-integrations-with-opencode/)
- [Kimi K3 practitioner report](https://chenchen.guru/blog/kimi-k3-first-impressions/)
- [Aider/Haskell longitudinal experiment](https://www.michaelpj.com/blog/2025/04/12/haskell-llm-experiments.html)
- [Devin/Answer.AI evaluation](https://www.answer.ai/posts/2025-01-08-devin.html)
- [SWE-Bench+](https://arxiv.org/abs/2410.06992)
- [Understanding Code Agent Behaviour](https://arxiv.org/abs/2511.00197)
- [AgentLens](https://arxiv.org/abs/2605.12925)

---

## 12. `pi-ai + Apache Maka + Swarm` 组合评估

### 12.1 先澄清：这不是一个官方集成产品

截至 **2026-09-01**，没有找到一个由 Pi、Apache Maka 或 OpenAI 官方声明的、名为 `pi-ai + Maka + Swarm` 的 canonical integrated stack。这个说法实际上可能混合了三层不同的东西：

| 层 | 实际项目 | 主要职责 |
|---|---|---|
| 模型层 | `@earendil-works/pi-ai`（历史包名 `@mariozechner/pi-ai`） | Provider、模型目录、认证、流式输出、跨 Provider wire format |
| Agent loop 层 | Pi 的 `@earendil-works/pi-agent-core` 等包 | 有状态 tool-calling loop、工具并行、steering、abort、事件流 |
| Runtime / workspace 层 | Apache Maka | Session、权限、沙箱、事件账本、Context 投影、UI/TUI/CLI、Agent Graph |
| 编排层 | “Swarm” | 需要另行指定具体实现，不能默认视为 Pi 或 Maka 的内置能力 |

> 注：上表中的包名应以当前仓库 package manifest 为准；Pi 生态经历了包名迁移，使用前必须锁定具体 npm 包和 commit。原始 `pi-ai` npm 名称并不是这个项目的正式包名，而是一个 placeholder/reserved name。

### 12.2 `pi-ai` 与 Pi runtime

Pi 生态的 `pi-ai` 提供统一的多 Provider LLM API，包含：

- Provider-owned model catalog 和认证；
- Anthropic Messages、OpenAI Responses、OpenAI Completions 等 wire implementation；
- 跨 Provider handoff；
- Context 序列化；
- 支持 tool calling 的模型流式输出。

Pi 的 Agent 包在其上实现 tool-calling loop，支持：

- 同一 assistant 批次中的工具并行或顺序执行；
- `transformContext`；
- steering/follow-up；
- abort；
- 事件流；
- 可插拔的 `streamFn`。

主要来源：

- [Pi monorepo](https://github.com/earendil-works/pi)
- [Pi AI README](https://raw.githubusercontent.com/earendil-works/pi/main/packages/ai/README.md)
- [Pi Agent README](https://raw.githubusercontent.com/earendil-works/pi/main/packages/agent/README.md)
- [Pi releases](https://api.github.com/repos/earendil-works/pi/releases)

它是一个**模型传输和 Agent loop 基础库**，不是完整的设计迁移治理系统。它本身不会自动产生：

- 设计文档 semantic diff；
- 需求到代码的 traceability matrix；
- 依赖有序的迁移计划；
- 独立验证门；
- worktree/分支策略；
- OS 级安全边界。

### 12.3 Apache Maka 并不以 `pi-ai` 作为模型层

Apache Maka 当前 runtime 的 package manifest 使用 Vercel AI SDK 及相关 Provider/MCP 依赖，没有发现官方的 `pi-ai` adapter 或 Pi/Maka 官方互操作声明。

Maka 的架构是：

```text
Desktop / TUI / CLI / Bot
        ↓
Runtime Host
        ↓
SessionManager
        ↓
AgentRun / RuntimeKernel
        ↓
Model + Tool Runtime
        ↓
Append-only Runtime Event Log
```

它另外提供 SQLite 状态/控制面、权限和受限执行、Context pruning/compaction、Session 恢复以及实验性的 Agent Graph。历史 Runtime Event Log 是事实，发给 Provider 的 Context 是它的投影。

主要来源：

- [Apache Maka](https://github.com/apache/maka)
- [Maka ARCHITECTURE.md](https://raw.githubusercontent.com/apache/maka/main/ARCHITECTURE.md)
- [Maka packages](https://github.com/apache/maka/tree/main/packages)
- [Maka SECURITY.md](https://raw.githubusercontent.com/apache/maka/main/SECURITY.md)
- [Maka Agent Graph draft](https://raw.githubusercontent.com/apache/maka/main/docs/architecture/agent-graph-stream-scheduling-draft.md)

这意味着直接把 `pi-ai` 接入 Maka 不是配置开关，而是一次架构适配工作，至少要自行处理：

- Pi stream event 到 Maka runtime event 的映射；
- Tool schema 和调用/结果生命周期；
- auth、usage、错误和重试语义；
- compaction/context projection；
- permission/approval；
- session resume 和中断恢复；
- Provider 特性差异。

在没有 adapter、契约测试和恢复测试之前，不能宣称这三者已经形成可靠的一体化栈。

### 12.4 “Swarm”有三种容易混淆的含义

#### A. OpenAI Swarm

OpenAI 的 `openai/swarm` 官方 README 将其定位为 experimental/educational，并说明它已经被 OpenAI Agents SDK 替代。它基于 Chat Completions，状态持久化和编排主要由调用方负责，不能作为生产级的 Maka/Pi 集成基础。

来源：

- [OpenAI Swarm repository](https://github.com/openai/swarm)
- [Swarm README](https://github.com/openai/swarm/blob/main/README.md)

#### B. Pi 社区 Swarm 扩展

例如 [pi-messenger-swarm](https://github.com/monotykamary/pi-messenger-swarm) 之类的第三方扩展可以提供 swarm-first 的消息或任务协调，但没有找到 Pi 官方或 Maka 官方的集成声明。应把它看成社区插件，并单独审查代码、权限、状态、并发和维护状况。

#### C. Maka Agent Graph

Maka 自身的 Agent Graph 是基于子 Session 的持久 DAG 调度机制，不等于 Pi agent loop，也不等于 OpenAI Swarm。它可以让不同 operator 并行，但同一个 child session 通常需要串行处理；root agent 负责 supervisor 角色。

如果采用 Maka Agent Graph，应让它负责**唯一的任务编排层**；不要再在上面叠加另一套 Swarm loop。

### 12.5 组合后的架构风险

如果同时使用 Pi Agent、Maka Agent Graph 和额外 Swarm，容易出现三重控制循环：

```text
Swarm scheduler
  → Maka Agent Graph / child Sessions
    → Pi tool-calling loop
      → model tool calls
```

风险包括：

1. **状态重复**：Swarm、Maka SQLite、Pi session 各自维护任务状态；
2. **事件重复或丢失**：三套事件模型对 turn、tool、abort 和 retry 的定义可能不同；
3. **权限下沉**：父级只读策略不一定自动传递给另一个 loop 或第三方 extension；
4. **并发写冲突**：多个 Writer 修改同一接口、迁移文件或 worktree；
5. **停止条件不一致**：一个层认为任务完成，另一层仍然重试；
6. **成本放大**：上下文、重试、子 Agent 和状态序列化重复发生；
7. **恢复困难**：发生中断时无法判断哪个状态库是最后事实；
8. **设计约束丢失**：新 child session 未重新载入 SSOT 和 acceptance criteria。

### 12.6 对大规模设计重构的实际水平

#### 优点

- `pi-ai` 的 Provider 抽象使模型替换和多模型 Worker 更灵活；
- Pi agent loop 的工具并行和可插拔流式接口适合构建定制 Worker；
- Maka 的 append-only runtime event log 对审计和事后复盘很有价值；
- Maka Agent Graph 理论上比简单的 fire-and-forget swarm 更适合持久任务；
- 本地优先、SQLite、权限和 OS sandbox 方向适合敏感代码库；
- 如果团队自己构建 adapter 和验证器，开放性高于封闭托管产品。

#### 缺点

- 三者不是官方集成，适配成本和责任由使用者承担；
- `pi-ai`/Pi 解决的是模型与 loop，不解决设计语义差异和迁移治理；
- Maka 仍处于 Incubating/nightly 阶段，没有正式 Apache release；
- Provider、存储和 CLI 合同可能快速变化；
- Swarm 的准确实现、状态模型和隔离能力必须单独核实；
- 多重 loop 很容易把“并行”变成状态竞争、重复调用和成本放大；
- 没有发现合格的、针对该组合执行大型设计文档重构的独立评测。

#### 适配判断

| 目标 | 评价 |
|---|---|
| 单一 Agent 完成小型修改 | 可行，但无需这套复杂组合 |
| 多 Provider Worker | `pi-ai` 有价值 |
| 可审计运行时 | Maka 的方向有吸引力 |
| 多阶段设计迁移 | 需要额外 GSD Core 或自建 orchestrator |
| 无人值守全仓库重构 | 不推荐 |
| 定制化 Agent 平台研发 | 值得隔离试验 |

### 12.7 推荐的安全组合方式

不要先把三者全部接起来。建议按以下顺序验证：

```text
第一步：单独运行 Maka，确认 Runtime Event Log、权限和恢复
第二步：单独运行 Pi agent，确认 tool loop、abort 和并行语义
第三步：为 Maka 实现最小 pi-ai adapter
第四步：为 adapter 编写 event/tool/auth/resume 契约测试
第五步：只选择 Maka Agent Graph 或外部 Swarm 其中一个
第六步：用只读设计影响分析任务试运行
第七步：用一个 5–15 文件迁移切片做有人监督的实现
第八步：再决定是否扩大并发和自治范围
```

在你的项目中，若使用这套组合，建议架构固定为：

```text
设计 SSOT：design/总设计文档.md
执行规划：GSD Core 或自建 Markdown/DAG
任务编排：Maka Agent Graph（二选一，不再叠加 Swarm）
模型层：Maka 原生 Vercel AI SDK，或经过契约测试的 pi-ai adapter
执行 Worker：Pi agent loop
状态事实：Maka Runtime Event Log + SQLite
代码隔离：Git worktree + 外部容器/VM
验收：CI + 独立验证 Agent + 人工审查
```

### 12.8 最终定位

> **`pi-ai + Apache Maka + Swarm` 不是现成的高可靠重构产品，而是一个有潜力但需要自行集成的 Agent 平台实验栈。**

它的理论上限可能很高，尤其在 Provider 灵活性、运行时审计和自定义并行编排方面；但当前的工程下限也更低，因为任何 adapter、事件一致性、恢复策略、权限继承和并发治理问题都需要使用者自己解决。

对于本项目的建议：

- **不要**现在用它作为整项重构的主 Harness；
- **可以**把 Maka 作为隔离试点，先验证其 Runtime Event Log 和 Agent Graph；
- **可以**把 `pi-ai` 作为独立模型适配层实验；
- **不要**同时启用 Maka Graph、Pi swarm 和另一个 Swarm scheduler；
- 如果需要实际交付，仍优先使用 **GSD Core + Claude Code**，或用这套组合做独立 Worker/研究试验。

### 12.9 补充来源

- [`@earendill-works/pi-ai` package manifest](https://raw.githubusercontent.com/earendil-works/pi/main/packages/ai/package.json)
- [Pi monorepo releases](https://api.github.com/repos/earendil-works/pi/releases)
- [Apache Maka README](https://github.com/apache/maka/blob/main/README.md)
- [Apache Incubator clutch record](https://incubator.apache.org/clutch.json)
- [OpenAI Swarm README](https://github.com/openai/swarm/blob/main/README.md)

---

## 最终结论

对于本项目这种“设计文档大幅修改后，既有代码需要重新对齐”的情况：

```text
不要：一个 Agent + 一个长会话 + 一句“重构整个仓库”

要：设计差异 → 影响分析 → 人工批准计划 → 隔离迁移切片
    → 外部测试 → 独立验证 → 原子提交 → 可回滚证据
```

**首选：GSD Core + Claude Code。**  
**隔离和 PR 化优先：GSD Core + Codex Cloud。**  
**开放编排优先：GSD Core + OpenCode。**  
**里程碑/验证器优先：Factory Missions。**  
**UI/浏览器优先：Cursor Agent。**

真正可靠的执行单位不是“整个仓库”，而是：

> **一个有明确 Requirement ID、明确影响范围、明确文件边界、明确测试命令、明确回滚点，并可独立审查的迁移切片。**
