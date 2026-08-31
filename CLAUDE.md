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
- 02 ~ 06 均为设计文档（02/03/04 已于 2026-08-31 取消忽略入库）；07 为单一事实来源。任何设计变更、范围调整、接口改动，**先更新《07.总设计文档.md》（正文 + §13 变更日志），再动代码**。
- 实施按里程碑推进：M1~M3（模块一）已完成；下一步 M5 题库+对话 → M6 评分+报告 → M7 测试闭环。M4（黄金集、插件）本期保留不做。
