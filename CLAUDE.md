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
- Large changes (new features, wide-ranging bug fixes, refactors touching multiple files): create a feature branch first. Do not develop large changes directly on the main branch.
- Each commit should represent one logical, self-contained unit of work.

---

## Project Context（本项目约定）

- 本目录是「AI 驱动的岗位胜任力测评与人才画像系统」的 git 仓库根。
- **唯一 SSOT：`design/final-design/总设计文档.md`（v2.0，2026-09-02 起生效）**，四份分模块设计文档（`design/final-design/模块一~四设计`）为其分块摘录。任何设计变更、范围调整、接口改动，**先更新《design/final-design/总设计文档.md》（正文 + §14 变更日志），再动代码**。
- 其余文档只有三种身份：从属模块稿（final-design/ 分模块文档）/ 临时讨论稿（design/ 临时讨论稿-*）/ 历史档案（`design/final-design/历史档案/` 及 design/ 原 04/05/06），均不作为实施依据；与 SSOT 冲突处以 SSOT 为准。要求文档（《需求文档-胜任力测评与人才画像系统》《技术方案概述》）为上游需求输入。
- 实施按里程碑推进，状态用四维口径记录（implemented / contract_complete / verified / production_ready）：M1~M3（模块一）已完成；M5~M7 主体代码已落地但 contract_complete=false，后续按 SSOT §28 修复与重构待办推进（P0：资源所有权校验、score→report 串行、开考检查、状态事件表）。M4（黄金集、插件）本期保留不做。Prompt 模块单独讨论（SSOT §26 已登记扩展点，实施时保留可替换接口）。
