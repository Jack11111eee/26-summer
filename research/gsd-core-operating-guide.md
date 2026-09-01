# Claude Code + GSD Core：设计定稿后的大面积重构操作说明

> **适用项目：** 已经有一版代码实现，设计文档正在发生或刚刚完成大面积调整，需要把既有代码重新对齐。
>
> **本文版本核验：** 2026-09-01
>
> **重要说明：** 本文的 GSD 命令和安装结论以 GSD 官方仓库/发布包及本机安装内容为准；不以旧版 `/gsd-help` 输出作为唯一事实来源。当前本机安装版本为 **GSD 1.42.3**。

---

## 1. 先给结论

当前本机已经安装 GSD Core，不需要重复安装：

```text
GSD 版本：1.42.3
安装位置：~/.claude/get-shit-done/
Claude Code Skills：67 个 GSD skill
Claude Code Hooks：已安装并已接入 ~/.claude/settings.json
```

推荐工作流：

```text
design/（设计 SSOT）
  → 设计冻结提交
  → 代码基线
  → GSD 代码库映射
  → GSD 文档摄取与冲突决策
  → 新建重构里程碑
  → 每阶段 Discuss / Research / Plan
  → 按 Wave 执行迁移切片
  → 外部测试 + 独立验证 + Code Review
  → 人工 Diff 审查
  → 原子提交 / 可回滚
```

不要使用下面这种方式：

```text
一个 Agent + 一个长会话 + “重构整个仓库”
```

---

## 2. 来源、核验范围与证据等级

### 2.1 官方来源

GSD 的官方发布仓库和 npm 包元数据指向：

- 官方仓库：<https://github.com/gsd-build/get-shit-done>
- 官方主页：<https://github.com/gsd-build/get-shit-done>
- npm 包：<https://www.npmjs.com/package/get-shit-done-cc>
- 官方安装入口：`npx get-shit-done-cc@latest`

截至本文核验时，npm 返回的最新稳定版本为 `1.42.3`。安装器输出的产品描述明确列出 Claude Code、OpenCode、Gemini、Codex 等宿主 runtime；本机包内的 runtime 配置也包含 `claude`、`codex`、`opencode`、`cursor`、`cline`、`hermes` 等。

### 2.2 本机事实

以下内容是直接检查本机后的事实：

```bash
cat "$HOME/.claude/get-shit-done/VERSION"
find "$HOME/.claude/skills" -mindepth 1 -maxdepth 1 -type d -name 'gsd-*'
find "$HOME/.claude/hooks" -maxdepth 1 -type f -name 'gsd-*'
grep -n 'gsd' "$HOME/.claude/settings.json"
```

结果：

- `~/.claude/get-shit-done/VERSION` 为 `1.42.3`；
- GSD skills 已安装；
- GSD hooks 已安装；
- `~/.claude/settings.json` 的 `PreToolUse`、`PostToolUse`、`SessionStart`、`Stop` 和 `statusLine` 配置已引用 GSD hooks；
- 项目内目前只有 `.claude/skills/impeccable/`，没有与 GSD 同名的项目级 skill。

### 2.3 不能从官方资料推出的内容

官方仓库和安装包可以证明“有某个命令或能力”，不能证明它在你的真实仓库上一定可靠。以下仍需由真实项目的受控试点验证：

- 设计差异识别的准确率；
- 删除行为的召回率；
- 长任务恢复后的约束保持；
- 并行 Agent 的实际冲突率；
- 不同模型、代理和第三方 API 的稳定性。

---

## 3. 现在要不要安装或更新？

### 3.1 当前状态

已经安装，因此不要再次执行安装器来“初始化”项目。当前可以直接重启 Claude Code，然后使用 GSD skill。

```bash
exit                    # 退出当前 Claude Code 会话
cd /path/to/26-summer-sem
claude
```

### 3.2 以后主动更新

```bash
npx get-shit-done-cc@latest
```

安装器会更新全局 GSD 文件、skills、agents、hooks 和版本清单。更新后必须重启 Claude Code：

```bash
claude
```

更新前建议保存当前版本和配置：

```bash
cat "$HOME/.claude/get-shit-done/VERSION" > /tmp/gsd-version-before-update.txt
cp "$HOME/.claude/settings.json" /tmp/claude-settings-before-gsd-update.json
```

更新后检查：

```bash
cat "$HOME/.claude/get-shit-done/VERSION"
grep -n 'gsd' "$HOME/.claude/settings.json"
find "$HOME/.claude/hooks" -maxdepth 1 -type f -name 'gsd-*' -print | sort
```

### 3.3 本次不建议使用的选项

安装器提示可以使用 `--force-statusline`。当前 statusline 已经配置为 GSD statusline，因此本次不要使用该选项：

```bash
# 不要在当前状态下执行
npx get-shit-done-cc@latest --force-statusline
```

除非你明确希望覆盖现有 statusline，否则保持现有配置。

---

## 4. GSD Skill 是否与现有 Skill 冲突？

### 4.1 当前检查结论

**没有发现名称级冲突。**

当前项目级 skill：

```text
.claude/skills/impeccable/
```

当前全局 GSD skill 使用 `gsd-*` 命名，例如：

```text
gsd-map-codebase
gsd-ingest-docs
gsd-discuss-phase
gsd-plan-phase
gsd-execute-phase
gsd-verify-work
gsd-code-review
gsd-ui-phase
gsd-ui-review
```

因此：

```text
impeccable ≠ gsd-ui-phase
gsd-code-review ≠ code-review（项目不存在同名项目 skill）
gsd-help ≠ 其他项目 skill
```

Claude Code skill 的名称空间没有发生直接重名，通常不会因为“安装了很多 skill”而自动把两个同名实现合并执行。

### 4.2 没有名称冲突，不等于没有语义重叠

未来如果使用 UI 相关工作，可能出现**职责重叠**而不是名称冲突：

```text
impeccable：偏 UI 设计、审美、交互和视觉改进
/gsd-ui-phase：偏 UI 阶段规格、计划、执行和验证
```

建议分工：

```text
先用 impeccable 确定视觉/交互方案
  → 把已确认方案写入设计 SSOT
  → 再用 /gsd-ui-phase 进行阶段化实施和验收
```

不要让两个 Agent 同时修改同一组 UI 文件。

### 4.3 GSD hooks 与项目规则的关系

当前 GSD hooks 会在 Claude Code 工具生命周期中参与：

- 上下文监控；
- Read 注入扫描；
- 阶段边界检查；
- 写入前提示/工作流检查；
- 提交校验；
- Session 状态记录；
- statusline 显示。

它们不是项目设计规则的替代品。项目已有的 `CLAUDE.md` 要继续保留；建议把以下边界写入项目规则：

```text
- design/ 是设计事实来源；
- .planning/ 只保存 GSD 执行状态和计划；
- 设计冲突不得静默解决；
- 当前计划外文件不得未经批准修改；
- 删除的旧行为必须有负向验证；
- 测试、CI 和 Git diff 是最终证据。
```

### 4.4 每次更新后的冲突检查命令

```bash
find "$HOME/.claude/skills" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort > /tmp/claude-global-skills.txt
find .claude/skills -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort > /tmp/claude-project-skills.txt
comm -12 /tmp/claude-global-skills.txt /tmp/claude-project-skills.txt
```

输出为空表示没有同名的全局/项目级 skill。若出现同名，不要立即删除；先读取两个 `SKILL.md`，确认哪个应作为唯一入口。

---

## 5. 设计文档仍在修改时应该做什么

你当前仍在修改设计文档，因此暂时**不要执行重构阶段**。

可以做只读检查：

```text
当前设计文档仍在修改中。请只做只读分析，不编辑任何文件。

请检查 design/：
1. 找出文档之间互相矛盾的要求；
2. 找出没有验收标准的要求；
3. 找出可能影响 API、数据库、后端、前端和测试的章节；
4. 找出新增、修改、删除和澄清的概念；
5. 输出风险清单。

禁止：修改业务代码、删除文件、生成最终迁移计划、执行数据库写入。
```

设计没有冻结前，不建议运行：

```text
/gsd-execute-phase
```

也不建议让 Agent 根据未定稿文档生成最终 `PLAN.md`。

---

## 6. 设计冻结后的标准起始流程

以下命令中的路径需要替换为项目实际路径。

### 6.1 进入项目并检查工作区

```bash
cd /path/to/26-summer-sem
pwd
git branch --show-current
git status --short
git log --oneline -5
```

如果有其他尚未准备纳入本次重构的工作，不要把它们和设计定稿混在一起。

### 6.2 单独提交设计定稿

```bash
git add design/
git commit -m "docs: finalize redesign specification"
git rev-parse HEAD
```

把该 commit 记为：

```text
NEW_DESIGN_COMMIT
```

### 6.3 记录代码基线

```bash
mkdir -p .baseline
git rev-parse HEAD~1 > .baseline/old-code-commit.txt
git rev-parse HEAD > .baseline/new-design-commit.txt
git status --short > .baseline/git-status.txt
git log --oneline -10 > .baseline/recent-history.txt
```

执行真实的基线命令。Node 项目示例：

```bash
npm install
npm run build 2>&1 | tee .baseline/build-result.txt
npm test 2>&1 | tee .baseline/test-result.txt
npm run lint 2>&1 | tee .baseline/lint-result.txt
npm run typecheck 2>&1 | tee .baseline/typecheck-result.txt
```

如果命令不存在，不要伪造结果；改用项目实际命令，并在 `known-failures.md` 记录。

```bash
touch .baseline/known-failures.md
git add .baseline/
git commit -m "chore: record pre-refactor baseline"
```

### 6.4 检查当前 GSD 命令是否已加载

重启 Claude Code 后使用：

```text
/gsd-help
```

注意：`/gsd-help` 是当前安装版本的方便入口，但本文不把旧的 help 文本当成唯一来源。若命令行为和本文不一致，应优先查看当前安装包中的 skill/workflow，并以实际版本为准。

---

## 7. 建立 GSD 项目上下文

### 7.1 映射已有代码库

在 Claude Code 中：

```text
/gsd-map-codebase
```

快速模式：

```text
/gsd-map-codebase --fast
```

按范围映射：

```text
/gsd-map-codebase --focus backend
/gsd-map-codebase --focus frontend
/gsd-map-codebase --focus database
/gsd-map-codebase --focus testing
```

它的目标是建立代码库地图，而不是修改业务实现。完成后检查：

```bash
find .planning/codebase -maxdepth 1 -type f -print | sort
```

让 Claude Code 检查地图是否漏掉设计涉及的区域：

```text
请审查 .planning/codebase/ 下的代码库地图。

对照 design/ 当前版本，检查：
1. API 是否覆盖；
2. 数据库/schema 是否覆盖；
3. 后端调用链是否覆盖；
4. 前端页面和状态是否覆盖；
5. 测试和构建入口是否覆盖；
6. 设计提到但地图没有覆盖的区域；
7. 代码存在但设计没有解释的重要区域。

只输出缺口，不修改代码。
```

### 7.2 摄取设计文档

如果当前项目还没有 `.planning/`：

```text
/gsd-ingest-docs design/ --mode new --resolve interactive
```

如果已有 `.planning/`，要把设计合并进现有上下文：

```text
/gsd-ingest-docs design/ --mode merge --resolve interactive
```

建议先列出文档清单：

```bash
find design -type f | sort > .baseline/design-files.txt
```

摄取后检查：

```bash
find .planning -maxdepth 3 -type f | sort
```

重点查看：

```text
.planning/PROJECT.md
.planning/REQUIREMENTS.md
.planning/STATE.md
.planning/INGEST-CONFLICTS.md
```

### 7.3 处理冲突

如果存在冲突：

```text
请读取 .planning/INGEST-CONFLICTS.md。

逐项列出：
1. 冲突来源和具体章节；
2. 两个要求的语义差异；
3. 选择各自方案会影响哪些代码；
4. 哪些冲突需要我作决策；
5. 哪些冲突可以有明确证据自动解决。

LOCKED 与 LOCKED 的冲突不得自动选择。
不要修改业务代码。
```

---

## 8. 建立“设计对齐重构”里程碑

设计冻结、代码映射和冲突处理完成后：

```text
/gsd-new-milestone "设计对齐重构"
```

在交互中明确告诉 GSD：

```text
这是已有项目的一轮设计对齐重构，不是新项目开发。

权威设计文档：design/
代码基线：.baseline/

要求：
1. 先做设计差异和影响分析；
2. 不把整个仓库压成一个任务；
3. 删除项必须有负向测试；
4. API 和数据库变更单独成可验证任务；
5. 每阶段必须有测试和回滚边界；
6. 设计冲突不能静默猜测；
7. 当前计划外文件不得修改。
```

如果 `.planning/` 已经有合适的 milestone，不需要重复创建，可以使用：

```text
/gsd-phase "设计对齐重构"
```

---

## 9. 推荐的阶段拆分

不要按“所有前端、所有后端、所有数据库”机械拆分；按可验证的迁移结果拆分。

适合本项目的一种候选顺序：

```text
Phase 1：设计差异、术语和 Requirement ID 固化
Phase 2：岗位 JD → 胜任力模型的数据结构和接口
Phase 3：题库、动态对话和测评会话流程
Phase 4：评分、证据链和报告数据结构
Phase 5：立体人才画像生成和展示
Phase 6：管理端 UI 与新流程对齐
Phase 7：删除旧行为、兼容性清理和数据迁移
Phase 8：端到端测试闭环和最终验收
```

需要创建阶段时：

```text
/gsd-phase "固定设计差异与迁移契约"
/gsd-phase "迁移胜任力模型数据结构"
/gsd-phase "迁移动态测评流程"
/gsd-phase "迁移评分与人才报告"
/gsd-phase "完成管理端 UI 对齐"
/gsd-phase "完成回归测试和旧行为清理"
```

插入紧急阶段：

```text
/gsd-phase --insert 3 "修复测评数据兼容性问题"
```

如果阶段仍需同时处理多个可独立验收的系统，应继续拆分。

---

## 10. 每个阶段的执行顺序

以 Phase 4 为例。

### 10.1 Discuss：先明确范围

```text
/gsd-discuss-phase 4 --batch=3
```

复杂阶段：

```text
/gsd-discuss-phase 4 --analyze
```

仅分析实施假设：

```text
/gsd-discuss-phase 4 --assumptions
```

交互时明确：

```text
Phase 4 只负责评分、证据链和报告数据结构。

必须包含：新设计的评分规则、输入输出、证据来源、缺失数据和异常处理。

不包含：新题库设计、管理端视觉重构、无设计依据的模型替换、无关数据库清理。
```

阶段讨论结果应形成该阶段的 `CONTEXT.md`。

### 10.2 Research：先研究再计划

```text
/gsd-plan-phase --research-phase 4
```

强制刷新研究：

```text
/gsd-plan-phase --research-phase 4 --research
```

只查看已有研究：

```text
/gsd-plan-phase --research-phase 4 --view
```

### 10.3 Plan：生成可执行计划

```text
/gsd-plan-phase 4
```

测试驱动顺序：

```text
/gsd-plan-phase 4 --tdd
```

前一次计划检查发现缺口时：

```text
/gsd-plan-phase 4 --gaps
```

本次大重构不建议使用：

```text
/gsd-plan-phase 4 --skip-verify
```

### 10.4 人工审查 PLAN.md

```bash
find .planning/phases -path '*04-*' -name '*PLAN.md' -print | sort
```

在 Claude Code 中：

```text
请审查当前 Phase 4 的所有 PLAN.md，不修改任何文件。

检查：
1. 每个任务是否绑定 Requirement ID；
2. 是否有明确文件边界；
3. 是否有明确测试命令；
4. API、数据库和兼容性影响是否被列出；
5. 删除项是否有负向验证；
6. 是否存在计划外文件风险；
7. 依赖波次是否正确；
8. 是否存在需要人工决策却被静默假设的事项。

任何一项无法回答都标记为 BLOCKED。
```

### 10.5 Execute：按波次执行

执行整个阶段：

```text
/gsd-execute-phase 4
```

只执行指定波次：

```text
/gsd-execute-phase 4 --wave 1
/gsd-execute-phase 4 --wave 2
```

只重新执行验证发现的缺口：

```text
/gsd-execute-phase 4 --gaps-only
```

测试驱动执行：

```text
/gsd-execute-phase 4 --tdd
```

大重构建议先执行 Wave 1，检查后再执行 Wave 2，而不是一开始让所有 Wave 连续运行。

---

## 11. 每个 Wave 之间的人工检查

在终端执行：

```bash
git status --short
git diff --stat
git diff --check
git diff --name-only
git log --oneline -5
```

运行项目验证：

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

将变更文件与当前 `PLAN.md` 的文件边界比较：

```text
请将当前 git diff 的文件与当前 PLAN.md 声明的文件边界逐一比较。

输出：
- 计划内文件；
- 计划外文件；
- 计划中声明但未修改的文件；
- 需要人工确认的间接影响文件。

不要修改文件。
```

如果出现计划外文件，只能：

```text
恢复它；
或修改计划并重新批准；
或把它拆成独立任务。
```

不要接受“顺手改了，应该没问题”。

---

## 12. 独立验证和代码审查

### 12.1 阶段验收

```text
/gsd-verify-work 4
```

### 12.2 代码审查

标准审查：

```text
/gsd-code-review 4 --depth=standard
```

深度审查：

```text
/gsd-code-review 4 --depth=deep
```

指定文件：

```text
/gsd-code-review 4 --files src/assessment/scoring.ts,tests/assessment/scoring.test.ts
```

第一次建议先不自动修复，先阅读审查结果。确认问题属于本阶段后，再使用：

```text
/gsd-code-review 4 --fix
```

### 12.3 安全相关阶段

涉及权限、敏感数据、外部 API 或脚本时：

```text
/gsd-secure-phase 4
```

### 12.4 UI 阶段

管理端 UI 阶段可以使用：

```text
/gsd-ui-phase
```

UI 完成后：

```text
/gsd-ui-review
```

UI 设计决策应先写回 `design/` 的权威文档，再进入 GSD 执行计划。

---

## 13. 删除项的负向验证

设计文档中明确删除的行为，必须单独验证“不再存在”。

先搜索可能的残留：

```bash
rg "旧字段|旧接口|旧等级|旧入口|LegacyName" src tests design
```

让 Claude Code 生成删除清单：

```text
请根据 design/ 当前版本列出所有明确删除或废弃的行为。

对每一项输出：
- 删除项；
- 设计来源章节；
- 可能残留的代码位置；
- 已有负向测试；
- 缺失的负向测试。

不要修改文件。
```

负向测试示例：

```ts
it("does not expose the removed legacy behavior", () => {
  const result = calculateScore(input);
  expect(result.level).not.toBe("legacy-level");
});
```

不要因为 `rg` 没搜到字符串就直接判定删除完成；仍需验证用户入口、API 行为、数据字段和迁移结果。

---

## 14. 恢复、暂停和阶段交接

查看状态：

```text
/gsd-progress
```

完整性审计：

```text
/gsd-progress --forensic
```

暂停：

```text
/gsd-pause-work --report
```

恢复：

```text
/gsd-resume-work
```

恢复时不要只依赖聊天记忆，要求按顺序读取：

```text
请恢复本项目重构上下文，只读，不修改文件。

按以下顺序读取：
1. design/ 当前权威文档；
2. .baseline/；
3. .planning/STATE.md；
4. .planning/ROADMAP.md；
5. 当前阶段 CONTEXT.md；
6. 当前阶段所有 PLAN.md；
7. 最近 SUMMARY.md；
8. git status 和最近提交。

先输出当前状态、未完成任务和阻塞项。
```

---

## 15. 推荐的项目 CLAUDE.md 补充规则

只添加短规则，不把整个设计文档复制到 `CLAUDE.md`：

```md
## Design-aligned refactor rules

- `design/` is the authoritative design source.
- `.planning/` contains execution plans and phase state only.
- Read the relevant design sections before editing code.
- Do not silently resolve conflicting design requirements.
- Every implementation task must identify Requirement IDs and file boundaries.
- Do not modify files outside the current plan without approval.
- Every behavior change requires tests.
- Deleted requirements require negative verification.
- Do not weaken a test oracle merely to make a test pass.
- Git diff, external tests, CI, and independent review are the final evidence.
```

这段规则和 GSD skill 是互补关系，不是替代关系。

---

## 16. 最终可复制命令清单

设计定稿后：

```bash
cd /path/to/26-summer-sem
git status --short
git add design/
git commit -m "docs: finalize redesign specification"
mkdir -p .baseline
git rev-parse HEAD~1 > .baseline/old-code-commit.txt
git rev-parse HEAD > .baseline/new-design-commit.txt
git status --short > .baseline/git-status.txt
git log --oneline -10 > .baseline/recent-history.txt
npm run build 2>&1 | tee .baseline/build-result.txt
npm test 2>&1 | tee .baseline/test-result.txt
npm run lint 2>&1 | tee .baseline/lint-result.txt
npm run typecheck 2>&1 | tee .baseline/typecheck-result.txt
git add .baseline/
git commit -m "chore: record pre-refactor baseline"
```

Claude Code 中：

```text
/gsd-map-codebase
/gsd-ingest-docs design/ --mode new --resolve interactive
/gsd-new-milestone "设计对齐重构"
```

每个阶段：

```text
/gsd-discuss-phase N --batch=3
/gsd-plan-phase --research-phase N
/gsd-plan-phase N
/gsd-execute-phase N --wave 1
/gsd-verify-work N
/gsd-code-review N --depth=deep
/gsd-progress --forensic
```

暂停/恢复：

```text
/gsd-pause-work --report
/gsd-resume-work
```

---

## 17. 本项目的最终操作原则

```text
design/ = 设计事实来源
.planning/ = 执行计划和阶段状态
Claude Code = 本地调查、实施、测试和 Git 集成
GSD Core = 阶段化工作流、计划、交接和验证编排
Git/CI/独立审查 = 最终证据
```

牢记：

1. 设计文档没有冻结，不开始代码重构；
2. 先映射代码库，再摄取设计；
3. 先解决冲突，再创建计划；
4. 每个迁移切片绑定 Requirement ID、文件边界、测试命令和回滚点；
5. 先按 Wave 执行，再进入下一 Wave；
6. 删除项必须有负向测试；
7. 不让多个 Agent 同时修改同一核心文件；
8. 不把 `.planning/` 当成设计 SSOT；
9. 不把 Agent 的完成总结当作验证证据；
10. 每次阶段完成后都保留可回滚的 Git 边界。
