# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Git Version Control

**Commit every working-tree change.** Never leave completed work uncommitted.

- Small changes (typos, single-function tweaks, config): commit directly to the current branch.
- Large changes (new features, wide-ranging bug fixes, refactors touching multiple files): cut a new branch from the current branch's HEAD and do the work there — never develop large changes directly on the original branch (this applies to any existing branch, not just main). When done, merge or PR back into the original branch.
- Each commit should represent one logical, self-contained unit of work.

### 5.1 Branch Model（本仓库实际运行的分支模型）

**`main` 只经 PR 更新，是同步远程的干线；`feature/m5-assessment` 是集成分支（跑服务的基线，须常绿）；所有 debugging / 功能主题分支从 m5 切出，短命快合。**

纪律（每条约束一个已知失败模式，不可省略）：

1. **合回 m5 前先查文件重叠**：`git diff --name-only $(git merge-base m5 <branch>) <branch>`——并行会话同改热门文件（如 Chat.vue / candidate.css）的同一区域会文本冲突。
2. **主题分支短命快合**：分支活得越久基线越旧（期间 m5 收编了其他合并），合回时撞旧快照的概率越大。
3. **合回 m5 后立即构建 + 冒烟（必要时回归）**：文本合并干净 ≠ 语义没坏（改签名/改调用类冲突 Git 不报）。m5 常绿是它作为跑服务基线的前提。
4. **m5 定期推 origin**：基线分支只存在本地有风险；每次合入后推一次。
5. **合并过的分支及时清理**：已并入 m5 的主题分支积压会让拓扑难读；删除由用户本人执行（deny 规则）。
6. **主工作树被其他会话占用时（未提交改动 / 已切走分支），切换分支用临时 worktree 旁路**（`git worktree add <tmp> <branch>`，完成后 `worktree remove`），不碰、不 stash、不改别人的工作。
7. **主工作树钉死在 `feature/m5-assessment`，任何会话不得在主 checkout 上签出其他分支**：主树是全仓库共享的 m5 集成位（跑服务基线），在主树上 `git checkout` 自己的主题分支 = 私占共享资源（2026-09-08 事故：并行会话陆续在主树切走分支，另一会话的合并静默落在别人分支上）。主题分支一律 `git worktree add ../26s-<话题> <分支名>` 开独立工作区实施（沿用 `26s-*` 命名惯例）；对 m5 的合并/提交/推送是主树上仅有的合法写操作，且每次动手前先 `git branch --show-current` 复核——发现主树不在 m5 就停手复位（绝不带着别人的未提交改动硬切分支；等该会话归位或报告用户裁决）。

## 6. Project Context（本项目约定）

- 本目录是「AI 驱动的岗位胜任力测评与人才画像系统」的 git 仓库根。
- **唯一 SSOT：`design/final-design/总设计文档.md`（v2.0，2026-09-02 起生效）**，四份分模块设计文档（`design/final-design/模块一~四设计`）为其分块摘录。任何设计变更、范围调整、接口改动，**先更新《design/final-design/总设计文档.md》（正文 + §14 变更日志），再动代码**。
- 其余文档只有三种身份：从属模块稿（final-design/ 分模块文档）/ 临时讨论稿（design/ 临时讨论稿-*）/ 历史档案（`design/final-design/历史档案/` 及 design/ 原 04/05/06），均不作为实施依据；与 SSOT 冲突处以 SSOT 为准。要求文档（《需求文档-胜任力测评与人才画像系统》《技术方案概述》）为上游需求输入。
- **SSOT 修改须授权**：SSOT 的任何修改须先经用户明确授权，agent 仅可起草，未经确认不得写入；SSOT 权威路径只能按既定文档治理规则以原子 commit 变更。
- checkpoint 快照（`design/checkpoint-*.md`）与各轮临时讨论稿只是上下文记录，不构成实施、修改文档或修改代码的授权。
