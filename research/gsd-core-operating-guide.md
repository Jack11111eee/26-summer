# Claude Code + GSD Core：SSOT v2.0 落地重构操作指南

> **适用场景：** 设计已冻结（SSOT v2.0，commit `a18d0fc`），代码主体已落地但 `contract_complete=false`，按 SSOT §28 待办基于现有代码**重构演进，不重写**。
>
> **本文版本核验：** 2026-09-02。所有 GSD 命令与旗标均对照本机 GSD 1.42.3 的 workflow 源码逐一核实，非凭记忆或旧 help 文本。
>
> **基线实测（2026-09-02）：** 后端 `13 passed, 3+1 errors`（test_question_bank.py 预先损坏：fixture `pid/mid` 未定义 + `sqlite3.OperationalError`）；`web build` 通过（有 chunk 体积警告）；分支 `feature/m5-assessment`。

---

## 0. v1 指南（旧版）的错误修正表

本文取代 2026-09-01 版。重写前逐条核对了 GSD 1.42.3 实际 workflow 源码，v1 指南有以下错误：

| v1 写法 | 实际行为（1.42.3） | 修正 |
|---|---|---|
| `/gsd-ingest-docs design/ --mode new --resolve interactive` | `--resolve interactive` 是保留字，v1 只支持 `auto`，传入直接被拒绝 | 用 `--resolve auto`，冲突后人工审查 `INGEST-CONFLICTS.md` |
| `/gsd-discuss-phase 4 --batch=3` | `--batch` 是布尔旗标，无 `=N` 形式 | 写 `/gsd-discuss-phase 4 --batch` |
| `/gsd-plan-phase 4 --tdd` / `/gsd-execute-phase 4 --tdd` | `--tdd` 未在任何 workflow 中定义 | 删除；用常规 plan→execute 流程 |
| `/gsd-map-codebase --fast` / `--focus backend` | 不存在；真实旗标是 `--paths <p1,p2>`（增量重映射） | 用 `/gsd-map-codebase`（全量）或 `--paths server,web/src` |
| `/gsd-phase "设计对齐重构"` 无参描述直接建 phase | add-phase 需要描述文本 | `/gsd-phase <描述>`；milestone 用 `/gsd-new-milestone` |
| "Claude Code Skills：67 个 GSD skill" | 67 个已安装，但本会话只浮出 8 个核心入口（surface 机制） | 需要时 `/gsd-surface list` 检查并调整 |
| ingest 扫描 `design/` 即可发现所有文档 | 目录约定只识别 adr/prd/spec/docs 子目录与 ADR-*/PRD-* 命名，**中文文件名全部发现不了** | 必须用 `--manifest` 显式列出（见 §4） |

---

## 1. 你和设计的"距离"是什么（先读这个）

SSOT（`design/final-design/总设计文档.md`）已经替你完成了距离分析：

- **§27 里程碑四维口径**：M1–M3 implemented；M5–M7 主体 implemented、`contract_complete=false`、`verified=false`。
- **§28 修复与重构待办**：6 组、按实施顺序排列的差距清单（P0 优先）。

也就是说，"设计文档和代码的距离"**不需要你或 GSD 从零推导**——SSOT §28 就是权威差距登记。GSD 的任务不是"重新发明路线图"，而是把 §28 落成可执行、可验证的 phase/plan 结构，并补上 §28 没细说的"每条差距对应哪些文件"。

距离的三种形态（执行时逐一辨认）：

```text
A. 代码缺失   —— SSOT 要求的表/字段/状态机/校验不存在（如 assessment_state_event、7:3 配额、所有权校验）
B. 代码存在但违约 —— 实现与 SSOT 契约不一致（如 score_live 50/50 合成、24h abandoned、一次性预选题）
C. 代码存在且合规 —— 保持不动（如模块一流水线、报告五段式、JWT）
```

GSD 的 ingest 差距检查 + map-codebase 对照，就是把每条 §28 待办归入 A/B/C 并定位到文件。

---

## 2. 总流程图

```text
第 0 步  前置检查（分支、工作区、GSD 就绪）
   ↓
第 1 步  代码基线固化（.baseline/，记录真实测试结果）
   ↓
第 2 步  GSD 代码库映射（map-codebase）
   ↓
第 3 步  设计摄取（ingest-docs + manifest，冲突人工裁决）
   ↓
第 4 步  新建里程碑"SSOT v2.0 对齐"（new-milestone）
   ↓
第 5 步  逐阶段：discuss → research → plan → 人工审 PLAN → execute（按 wave）→ wave 间人工检查
   ↓
第 6 步  阶段收尾：verify-work → code-review → （涉及时）secure-phase
   ↓
第 7 步  全程穿插：progress / pause / resume；结束做负向验证清单
   ↓
第 8 步  最终验收（§24 测试要求 + 四维口径核对）
```

---

## 3. 第 0 步：前置检查

```bash
cd /Users/huaxinzhang/Desktop/trifles/26-summer-sem
git branch --show-current          # 当前在 feature/m5-assessment
git status --short                 # 确认没有未提交的无关变更
ls .planning 2>/dev/null           # 应为不存在（首次）
```

当前工作区有两处**用户进行中的变更**（`prototype/redesign/` 修改 + `final-admin/` 未跟踪），与本次重构无关，**不要提交、不要还原**，重构期间不要动 `prototype/`。

GSD 就绪性检查（在 Claude Code 会话内）：

```text
/gsd-help
/gsd-surface list
```

若核心循环命令（new-milestone / discuss-phase / plan-phase / execute-phase / verify-work / code-review）未浮出，执行：

```text
/gsd-surface profile full
```

然后重启会话使其生效。

**本机配置注意（已实测）：** `~/.gsd/defaults.json` 将全部 GSD 子代理（executor/planner/verifier/reviewer 等 33 个）的模型覆盖为 `ccswitch-anthropic-k3/kimi-k3`，且 `mode: yolo`。含义：

- yolo 模式下 GSD 自动批准大多数决策，只在关键检查点停——**对本重构偏激进**；
- 子代理全部走 kimi-k3，与主会话模型无关。

建议本次重构改为 interactive：

```text
/gsd-settings
```

把 mode 改为 interactive（或在 `.planning/config.json` 建好后手动改 `"mode": "interactive"`）。若希望子代理与主会话同模型，删除 defaults.json 中的 `model_overrides` 块。这不是硬前置，但 yolo+错档子代理会放大重构风险。

---

## 4. 第 1 步：代码基线固化

目的：给整个重构一个可回滚、可对比的锚点。

```bash
mkdir -p .baseline
git rev-parse HEAD > .baseline/base-commit.txt
git log --oneline -10 > .baseline/recent-history.txt
find server web/src -type f | sort > .baseline/file-inventory.txt
```

执行真实基线测试并留档：

```bash
# 后端（mock 模式，临时 DB，不污染 data/app.db）
cd server
python3 -m pytest test_m5_backend.py test_m6_backend.py test_m7_backend.py test_question_bank.py -q 2>&1 | tee ../.baseline/backend-tests.txt
cd ..

# 前端
cd web && npm run build 2>&1 | tee ../.baseline/web-build.txt; cd ..
```

**当前实测基线**（写进 `known-failures.md`）：

```text
test_question_bank.py:
  - 3 个 ERROR：fixture 'pid'/'mid' 未定义（测试文件预先损坏，非本次引入）
  - 1 个 FAILED：test_prompts — sqlite3.OperationalError
其余 m5/m6/m7 测试：13 passed
web build：通过（chunk >500kB 警告，不阻断）
```

SSOT §24 要求"M1 回归为动态测评实施硬前置"——当前 server/ 下**没有 M1 回归测试**，这本身就是要登记的第一条差距。

把已知失败登记下来，避免后续被误判为重构引入：

```bash
cat > .baseline/known-failures.md <<'EOF'
# 基线已知失败（2026-09-02）
- test_question_bank.py: fixture pid/mid 未定义（3 errors）
- test_question_bank.py::test_prompts: sqlite3.OperationalError
- 无 M1 回归测试（SSOT §24 硬前置缺失，待补）
EOF
```

`.baseline/` 建议提交（它不属于 SSOT 也不属于 .planning，是重构审计材料）：

```bash
git add .baseline/
git commit -m "chore: record pre-refactor baseline (SSOT v2.0 alignment)"
```

---

## 5. 第 2 步：GSD 代码库映射

```text
/gsd-map-codebase
```

说明：

- 无 `--fast`/`--focus` 旗标；全量映射。生成 7 份文档到 `.planning/codebase/`，含 `last_mapped_commit` 戳。
- 若想限制范围（例如只重映射后端），用真实旗标：

  ```text
  /gsd-map-codebase --paths server,web/src
  ```

映射完成后，做**交叉核验**，不是重新找缺口——缺口已由 `research/ssot-code-gap-matrix.md`（2026-09-02 穷举核对，68 条契约带文件:行号证据）完成。给 CC 的 prompt：

```text
背景：research/ssot-code-gap-matrix.md 是已完成的 SSOT v2.0 ↔ 代码逐条核对矩阵
（68 条契约，标注 [缺失]/[违约]/[合规]，带文件:行号证据）。

任务：交叉审查 .planning/codebase/ 地图与该矩阵，不重新做全量对照。

1. 矩阵引用的每个文件，地图是否都覆盖了？列出地图缺失的文件；
2. 地图中存在、但矩阵第 0 节"覆盖范围声明"之外的代码区域（矩阵盲区），列出区域名+路径；
3. 抽查矩阵 5 条 [违约] 行（优先 P0 与结构性），打开对应文件验证行号引用是否准确；
4. 以上三项之外不展开。

只输出：地图缺失清单、矩阵盲区清单、抽查验证结果（准确/偏差+正确行号）。
不修改任何文件。
```

发现矩阵盲区时，人工决定：补进矩阵，还是留到对应 phase 的 research 步骤处理。

---

## 6. 第 3 步：设计摄取（关键步骤，有坑）

### 6.1 为什么必须用 manifest

ingest-docs 的目录约定扫描只识别 `adr/prd/spec/docs` 子目录和 `ADR-*/PRD-*/SPEC-*` 前缀文件。`design/final-design/` 是中文命名，**自动发现不了**；`design/` 顶层还有十余份临时讨论稿和历史档案，自动扫描会混入非权威文档（上限 50 份也容易超）。

因此**必须手写 manifest**，只列权威文档：

```bash
mkdir -p .planning
cat > .planning/ingest-manifest.yaml <<'EOF'
docs:
  - path: design/final-design/总设计文档.md
    type: DOC
    precedence: 0
  - path: design/final-design/模块一设计-岗位JD解析与胜任力模型构建.md
    type: DOC
    precedence: 1
  - path: design/final-design/模块二设计-AI动态测评.md
    type: DOC
    precedence: 1
  - path: design/final-design/模块三设计-立体人才画像.md
    type: DOC
    precedence: 1
  - path: design/final-design/模块四设计-测试闭环.md
    type: DOC
    precedence: 1
  - path: design/需求文档-胜任力测评与人才画像系统.md
    type: PRD
    precedence: 2
  - path: design/技术方案概述.md
    type: DOC
    precedence: 2
EOF
```

precedence 数值越小优先级越高：总设计文档 0（唯一权威），分模块 1，上游需求 2。

### 6.2 执行摄取

```text
/gsd-ingest-docs design/ --manifest .planning/ingest-manifest.yaml --mode new --resolve auto
```

- `--mode new`：当前无 `.planning/`（首次摄取）；后续如有设计增量，用 `--mode merge`。
- `--resolve auto`：v1 只支持 auto；LOCKED-vs-LOCKED 硬冲突会自动阻断并列出，不会静默选择。

产物检查：

```bash
find .planning -maxdepth 2 -type f | sort
# 重点：PROJECT.md / REQUIREMENTS.md / ROADMAP.md / STATE.md / INGEST-CONFLICTS.md
```

注意：`--mode new` 会走 `new-project-from-ingest` 路线，自动生成 ROADMAP（gsd-roadmapper 代理）。**生成的 ROADMAP 是机器初稿**，第 4 步你必须人工重排（它不知道 §28 的优先级）。分模块文档与总文档的重复内容由 synthesizer 按 precedence 去重，LOCKED 冲突进 `INGEST-CONFLICTS.md`。

### 6.3 冲突裁决

如产生 `INGEST-CONFLICTS.md`：

```text
请读取 .planning/INGEST-CONFLICTS.md。逐项列出：
1. 冲突来源章节；2. 语义差异；3. 各方案影响的代码区域；
4. 哪些需要我决策；5. 哪些有明确证据可自动解决。
LOCKED-vs-LOCKED 不自动选择。不修改业务代码。
```

理论上不应有真实冲突——分模块文档是总文档的分块摘录（SSOT 附录 C）。若出现，多半是摄取了非权威文档，检查 manifest。

### 6.4 把 §28 + 差距矩阵摄进 REQUIREMENTS

摄取的 ROADMAP 不会自动包含 §28 待办。补一步（在 CC 中说）：

```text
请读取 design/final-design/总设计文档.md §27–§28、research/ssot-code-gap-matrix.md
与 .planning/REQUIREMENTS.md。
以差距矩阵为主源、§28 为顺序框架，生成带唯一 ID 的需求条目（REF-1 ~ REF-N）：
- 矩阵每行 [缺失]/[违约] 项对应一个 REF（[合规] 行不生成 REF，只留档）；
- 每个 REF 注明：SSOT 章节、差距类型、矩阵证据（文件:行号）、验收命令；
- §28 第 6 组（迁移/测试/CI）在矩阵第 7 节有文件级对账，同样转 REF；
- 矩阵第 8 节"新发现"5 项转 REF 时标注"SSOT §28 未登记，需先回写 SSOT"。
不修改业务代码，只更新 .planning/REQUIREMENTS.md。
```

注意矩阵第 8 节的 5 项新发现属于设计外发现——按项目治理规则，转 REF 前应先**回写 SSOT**（§14 变更日志 + 正文对应章节），保持"设计先行"不被执行顺序倒置。

---

## 6.5 阶段拆分映射（§28 → phases）

照 SSOT §28 的实施顺序拆 phase（不要按前端/后端/数据库机械拆）：

```text
Phase 1  P0：权限与运行契约（所有权校验 §7、score→report 串行 §21.1、开考检查 §10.4、状态事件表 §13）
Phase 2  题库与选题（题库绑定 model/version §9.2、动态选题四层结构 §10.6、required 例外 §10.5）
Phase 3  会话与难度路径（难度路径状态机 §11.2、实例模型 §11.1、answer/score 状态分离 §11.4）
Phase 4  传输与上下文（真实 SSE §11.5、幂等 §13.4、计时区间 §15、P-refine 滑窗 §14）
Phase 5  评分与证据（score_live 仅导航 §17、REFUSED 特殊值 §18、item_measurement 裁决 §19、
         IMPUTED 补算 §20、证据 span §12.5、trace_link §13.3）
Phase 6  表单链（form_instance 生命周期 §16.1、extract_form_facts §16.2、Tools 边界 §16.3）
Phase 7  题库生成与管理端修复（生成失败可见、orphan 路由、模型编辑校验、feedback/报告版本化）
Phase 8  迁移与测试体系（schema_version 迁移、M1 回归、测试重构与 CI、E2E、eval 隔离）
```

这个顺序遵循 §28 的依赖：P0 权限契约先于一切（否则后续测试全踩在无防护接口上）；事件表（Phase 1）先于依赖它记账的行为（Phase 2–4）；评分链重排（Phase 5）先于报告契约依赖它的部分；迁移体系（Phase 8）殿后收口。

---

## 7. 第 4 步：新建里程碑

map + ingest 完成后：

```text
/gsd-new-milestone "SSOT v2.0 对齐"
```

交互时明确告知（这段可直接粘贴）：

```text
这是既有项目按 SSOT v2.0（design/final-design/总设计文档.md，commit a18d0fc）的
契约对齐重构，基于现有代码演进，不重写。

要求：
1. 阶段结构以 .planning/REQUIREMENTS.md 中 REF-* 条目和 §28 实施顺序为准；
2. 每个任务绑定 REF ID、SSOT 章节、明确文件边界和测试命令；
3. 差距类型是"违约"的，先写负向测试锁定旧行为，再改；
4. API/数据库变更独立成可验证任务，迁移先行；
5. 设计冲突不得静默解决，列出来问我；
6. 计划外文件不得修改。
```

若 ROADMAP 需要调整 phase 顺序（对照 §6.5 的映射）：

```text
/gsd-phase --remove <编号>
/gsd-phase --edit <编号>
/gsd-phase --insert <编号> <描述>
```

---

## 8. 第 5 步：逐阶段执行

以 Phase 1（P0 权限与运行契约）为例。每个 phase 重复此循环。

### 8.1 Discuss

```text
/gsd-discuss-phase 1 --analyze
```

可用旗标（本机 1.42.3 实测）：`--all --auto --chain --batch --analyze --text --power --assumptions`。交互时把范围说死：

```text
Phase 1 只负责 §7/§21.1/§10.4/§13 四件事。
包含：资源所有权校验（candidate 只能访问本人 session/report/form/feedback）、
score→report 串行、开考前可测量性检查、assessment_state_event/trace_link 落表。
不包含：题库配额公式、难度路径、SSE、评分链重排。
```

### 8.2 Research

```text
/gsd-plan-phase --research-phase 1
```

研究专用模式，只产 RESEARCH.md 不生成计划。刷新用 `--research-phase 1 --research`。

### 8.3 Plan

```text
/gsd-plan-phase 1
```

重要旗标核实结果：

- `--tdd` **不存在**——但 SSOT 本身就是测试先行的哲学，直接在 discuss/plan 提示中把"先负向测试锁旧行为"写进任务描述即可；
- `--gaps`：plan-checker 发现缺口后重新规划用；
- `--skip-verify`：**本重构禁用**（跳过 plan 检查，风险不可接受）；
- `--mvp`：裁剪范围用，本次不用。

### 8.4 人工审查 PLAN.md

```bash
ls .planning/phases/*1-*/
git diff --stat
```

```text
请审查 Phase 1 的所有 PLAN.md，不修改文件。检查：
1. 每任务是否绑定 REF ID 与 SSOT 章节；
2. 文件边界是否明确（对照 server/api/assessment.py 等实际路径）；
3. 测试命令是否真实存在（pytest 目标文件）；
4. "违约"类任务是否先写负向测试；
5. 依赖波次是否正确（如事件表先于记事件的行为）；
6. 是否存在被静默假设的设计决策。
任何一项无法回答 → BLOCKED，向我列出。
```

### 8.5 Execute（按 wave）

```text
/gsd-execute-phase 1 --wave 1
```

- 旗标实测：`--wave N`（执行指定波次）、`--gaps-only`（只补验证缺口）、`--auto`、`--interactive`、`--mvp`。
- **Wave 安全机制**：指定 `--wave 2` 时若 wave 1 有未完成计划，GSD 会拒绝并要求先完成低波次。这是好的，配合它。
- Wave 之间做人工检查（下节）。

### 8.6 每波次之间的人工检查

```bash
git status --short
git diff --stat
git diff --name-only
git diff --check          # 尾随空格/冲突标记
cd server && python3 -m pytest test_m5_backend.py test_m6_backend.py test_m7_backend.py -q; cd ..
```

对照 PLAN 边界：

```text
请把当前 git diff 的文件与 Phase 1 PLAN.md 声明的文件边界逐一比较。
输出：计划内/计划外/声明未改/间接影响文件。不修改文件。
```

计划外文件三选一：恢复、改计划重新批准、拆独立任务。不接受"顺手改的"。

---

## 9. 第 6 步：阶段收尾

### 9.1 verify-work

```text
/gsd-verify-work 1
```

目标导向验证：不是"任务勾完了"，而是"Phase 1 承诺的契约真的成立"。

### 9.2 code-review

```text
/gsd-code-review 1 --depth=deep
```

`--depth=standard|deep`、`--files=<paths>`、`--fix`（自动修复）均实测存在。第一次先读 REVIEW.md，确认问题属于本阶段后再 `--fix`。

### 9.3 涉及安全/权限/敏感数据的 phase

Phase 1（所有权校验）、Phase 4（幂等）、Phase 5（证据/trace，含 PII）必须跑：

```text
/gsd-secure-phase 1
```

---

## 9.4 删除旧行为的负向验证

"不重写"意味着大量任务是**替换违约实现**，替换后必须验证旧路径死透。SSOT §30 的 N1–N12 就是权威删除清单：

| REF 类 | 必须消失的旧行为 |
|---|---|
| N2 score_live 合成 | `score_final = 0.5*live + 0.5*final` 式合成代码与测试 |
| N4 固定题量 hard6/soft2/exp2 | 一次性预选的常量与逻辑 |
| N5 一次性预选 | session 创建时全量预选逻辑 |
| N7 24h abandoned | `24*3600` 类常量 |
| N8 拒答按 0 分进聚合 | REFUSED 进能力等级分母的代码路径 |
| N1 55/20/20/5 权重 | 旧比例常量与分摊代码 |

操作（先全库搜残留）：

```bash
rg -n '0\.5.*live|50/50|live.*0\.5' server/ --type py
rg -n '24.*3600|86400' server/
rg -n 'final_score' server/          # §12.4 废弃列，迁移合并到 score_final
rg -n '55|0\.55' server/services/aggregate.py server/services/aggregation.py
```

然后让 CC 生成完整删除清单并补负向测试：

```text
请对照 SSOT §30 N1–N12 与 §28，列出所有"必须消失的旧实现"。
每项输出：删除项、SSOT 章节、可能残留位置（rg 搜索）、
已有负向测试、缺失的负向测试。先输出清单，我批准后你再补测试。
```

负向测试示例（REFUSED 不进能力等级分母）：

```python
def test_refused_not_in_competency_denominator():
    # REFUSED 观察不应进入能力等级聚合（SSOT §18）
    ...
```

注意：`rg` 搜不到字符串 ≠ 删除完成；还要验证用户入口、API 行为与数据迁移结果。另外 §12.4 的 `final_score`→`score_final` 是**数据迁移**不是纯删除，属 Phase 8 迁移体系的活，先把代码契约改对，迁移脚本在 Phase 8 做。

---

## 9.5 迁移注意（SQLite 单文件）

SSOT §5：DDL+迁移内嵌 `server/db.py`，含 schema_version 演进。21 表清单（§6）是**目标结构**，演进到它属于 Phase 8 迁移体系；但 Phase 1–7 各阶段落新表/新列时，必须同步在 db.py 的迁移框架里登记版本号，避免 Phase 8 收口时积重难返。

---

## 10. 第 7 步：状态管理与中断恢复

### 10.1 进度

```text
/gsd-progress
/gsd-progress --forensic    # 完整性审计
```

### 10.2 暂停/恢复

```text
/gsd-pause-work --report
/gsd-resume-work
```

### 10.3 跨会话恢复上下文

GSD 的状态全在 `.planning/STATE.md`，不依赖聊天记忆。新会话直接：

```text
/gsd-resume-work
```

或手动恢复提示词：

```text
请恢复本重构上下文，只读。按序读取：
1. design/final-design/总设计文档.md（SSOT）；
2. .baseline/（基线与已知失败）；
3. .planning/STATE.md → ROADMAP.md → 当前 phase 的 CONTEXT.md → PLAN.md → 最近 SUMMARY.md；
4. git status 与最近提交。
先输出：当前 phase、未完成任务、阻塞项。
```

---

## 10.4 关于子代理模型（重要）

本机 `~/.gsd/defaults.json` 将全部 GSD 子代理覆盖为 `ccswitch-anthropic-k3/kimi-k3`。这意味着：

- `/gsd-map-codebase`、`/gsd-execute-phase`、`/gsd-verify-work` 等命令的所有子代理实际跑在 kimi-k3 上，与主会话模型选择无关；
- 如果你在主会话换了更强的模型（比如 Opus 5），子代理依然是 kimi-k3——**规划与执行的模型策略要在 GSD 层面配，不能只换主会话模型**；
- 配置入口：`/gsd-settings`（交互式）或直接编辑 `~/.gsd/defaults.json`（全局）／`.planning/config.json`（项目级）。

如需子代理与主会话同档（如全用主会话当前模型），把 defaults.json 的 `model_overrides` 置空。项目级优先于全局：`.planning/config.json` 的 `model_profile` 设 `inherit` 并清空覆盖，GSD 子代理就用主会话模型。

---

## 11. 第 8 步：最终验收

### 11.1 §24 测试要求核对

```text
1. 统一 pytest 收集（脚本测试重构为可收集或明确独立命令）；CI 为正式验收入口；
2. M1 回归为动态测评实施硬前置——当前缺失，Phase 8 必须补齐；
3. 候选人端完整 E2E（注册→选岗→session→作答/追问→表单→完成→评分→报告→异议，
   含刷新恢复/断线重试/越权/超时）为 M5–M7 verified 必要条件；
4. 越权/权限矩阵、幂等/并发、计时、迁移、SSE 为必测项；
5. prototype 为视觉参考，静态原型不作功能验收依据。
```

### 11.2 四维口径核对（§27）

让 CC 做终局审计：

```text
请对照 SSOT §27 四维口径做最终审计，只读：
对每个里程碑（M1–M7）输出 implemented / contract_complete / verified / production_ready
四维状态与证据（测试名、文件、提交）。任何一维"是"都必须指向可复核证据，
没有证据一律写"否"。
```

### 11.3 报告一致性校验（§21.1 七项）

发布前代码校验：数字可重算、weight 和一致、引用归属 session、model/version 快照一致、无效题/系统错误不进分母、IMPUTED/REFUSED 警告与结构化状态一致、文案无录用判断表述。这条在 Phase 5 落地后作为常驻校验保留。

### 11.4 顺路修复基线问题

`test_question_bank.py` 的 fixture 损坏属于 Phase 8"测试重构"范围，会在统一 pytest 收集时一并处理；不要提前单独修它（避免计划外文件修改），但要在 Phase 8 的 plan 里显式列出。

---

## 12. 可复制命令速查（全部已核实）

设计冻结后的完整启动序列：

```bash
cd /Users/huaxinzhang/Desktop/trifles/26-summer-sem
git status --short
mkdir -p .baseline
git rev-parse HEAD > .baseline/base-commit.txt
cd server && python3 -m pytest test_m5_backend.py test_m6_backend.py test_m7_backend.py test_question_bank.py -q 2>&1 | tee ../.baseline/backend-tests.txt; cd ..
cd web && npm run build 2>&1 | tee ../.baseline/web-build.txt; cd ..
git add .baseline/ && git commit -m "chore: record pre-refactor baseline (SSOT v2.0 alignment)"
```

Claude Code 内按序：

```text
/gsd-surface list                    ← 确认核心命令浮出（缺则 /gsd-surface profile full）
/gsd-map-codebase                    ← 生成 .planning/codebase/
（写 ingest-manifest.yaml，见 §6.1）
/gsd-ingest-docs design/ --manifest .planning/ingest-manifest.yaml --mode new --resolve auto
/gsd-new-milestone "SSOT v2.0 对齐"
（用 /gsd-phase --edit/--insert/--remove 把 ROADMAP 调成 §6.5 的顺序）
```

每个 phase 循环：

```text
/gsd-discuss-phase N --analyze
/gsd-plan-phase --research-phase N
/gsd-plan-phase N
（人工审 PLAN.md → BLOCKED 项问清楚）
/gsd-execute-phase N --wave 1
（wave 间人工检查：git diff + pytest）
/gsd-execute-phase N --wave 2
/gsd-verify-work N
/gsd-code-review N --depth=deep
/gsd-secure-phase N                  ← 仅权限/幂等/PII 相关 phase
/gsd-progress
```

暂停/恢复：

```text
/gsd-pause-work --report
/gsd-resume-work
/gsd-progress --forensic
```

---

## 13. 本项目最终操作原则

```text
design/final-design/总设计文档.md = 唯一设计权威（SSOT，commit a18d0fc）
.planning/                          = GSD 执行状态与计划（非 SSOT）
.baseline/                          = 重构审计锚点
server/ + web/src                   = 实现
pytest + git diff + verify-work     = 最终证据
```

十条铁律：

1. 设计变更先改 SSOT（§29 规则）再动代码——本文流程内不允许出现"代码先行、文档后补"；
2. 每个任务绑定 REF ID + SSOT 章节 + 文件边界 + 测试命令；
3. 违约类差距先写负向测试锁定旧行为，再替换；
4. 不修改计划外文件；计划外文件只有恢复/改计划/拆任务三条路；
5. P0（权限、串行、开考检查、事件表）先于一切；
6. 删除的旧行为必须负向验证死透（§30 N1–N12 是清单）；
7. 不把 Agent 完成总结当证据，verify-work + pytest + git diff 才是；
8. wave 间必做人工 diff 检查，"顺手改的"一律退回；
9. yolo 模式不适合本重构，用 interactive；
10. 迁移版本号随阶段登记，不留到 Phase 8 积重难返。
