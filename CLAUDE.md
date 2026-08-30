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
- **单一事实来源**：《05.模块一实施设计-partial-design-doc.md》。任何设计变更、范围调整、接口改动，**先更新该文档（正文 + §12 变更日志），再动代码**。
- 02 / 03 / 04 三份文档被 `.gitignore` 忽略（本地参考资料，不入库）；`deepseek-chat/` 同理。
- 实施按里程碑推进：M1 鉴权+解析链 → M2 聚合+人审 → M3 外围页面。M4（黄金集、浏览器插件）本期保留不做。
