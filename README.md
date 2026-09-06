# AI 驱动的岗位胜任力测评与人才画像系统

把非结构化 **JD 文本**转化为可测量的**岗位胜任力模型**（尺子），基于它做**有界动态测评**，产出**立体人才画像（评分与报告）**，并用**测试闭环**保证整条链可审计、可回溯、有评测标准。

```
JD 文本 ──► 胜任力模型（模块一）──► 有界动态测评（模块二）──► 人才画像 / 评分（模块三）
                                                                         │
                                             测试闭环（模块四）◄─────────┘
                                         可审计 / 反馈可回溯 / 有测评标准
```

> 全仓库技术、设计文档以中文为准；本文为中文 README，英文版见 [`README_EN.md`](./README_EN.md)。

## 功能概览

系统按四个设计模块组织（划分见 `design/final-design/总设计文档.md`）：

**模块一 · JD 解析与胜任力模型构建**
- 六工位流水线：①接入（粘贴 / JSONL 上传）→ ②清洗（纯规则）→ ③抽取（LLM）→ ④归一消歧（能力词典 + LLM）→ ⑤聚合（代码统计 + LLM 裁决 + 代码算权重）→ ⑥人审（确认升版本）。
- LLM 只做**分类与裁决**，统计、权重、配额等算术全部由代码完成（强约束 ①「LLM 不碰数字」）；聚合频次稀释单次 LLM 随机误差。
- 能力词典（标准名 / 别名 / 排除项）、岗位别名表、JD 工序中间产物留档。
- `confirmed` 模型是下游出题与打分的**唯一权威**，不被静默覆盖；修改走 diff 审阅流升 `v{n+1}`。

**模块二 · 有界动态测评**
- 有界测评循环：`Observation → Policy/Plan → Act → Evaluation → Persist`；**代码是唯一状态机**（题量、追问上限、难度迁移、finish 等由代码裁决，LLM 只提供结构化观察与建议）。
- 题库 + 岗位级配额公式（7:3 类目比例 + 最大余数 + tier 配额）、动态逐题实例化、四层选题结构、难度路径状态机。
- 会话状态机、真实 SSE 对话、追问 / 表单事实核验（gate 项）、计时与暂停恢复、幂等；答案原文不可变归档、状态事件 **append-only**。

**模块三 · 评分、聚合与人才画像**
- 评分链：`score_live` 仅用于导航，不进最终分；拒答（REFUSED）、缺失（IMPUTED 补算）、item 多题合并与综合题裁决。
- **五段式报告**：①总分 + 门槛标签 ②雷达图 ③逐项明细（gap 着色 / 理由 / 异议）④优势·短板·建议（代码排序，短板=gap>0）⑤逐题回顾（证据引用 + 来源定位）。
- 报告**发布前代码校验 + 人工明确点击发布**；重复触发护栏（409）；候选人对逐分可提异议（feedback），**永不自动改分**。

**模块四 · 测试闭环**
- 全链可审计：`report → session → model/version → question → message → score → trace` 经 `trace_link` 闭合。
- 一致性评测（固定 transcript 复跑断言）与**虚拟考生**（强 / 中 / 弱三档端到端）；`eval/` 用独立临时库，不污染业务数据。
- 安全：JWT 鉴权 + 资源级所有权校验（candidate 只能访问本人资源）、输入限额、Prompt injection 事件留痕、trace 访问审计。

**系统明确不做**：最终录用判断 / 排序 / 自动通过淘汰。报告只表达测量结果，不出现「录用结论 / 排名」等表述。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · Uvicorn（单进程） |
| LLM 客户端 | `openai` SDK（base_url 可切 DeepSeek 等 OpenAI 兼容端点）；`mock` 模式用规则模拟 LLM，**离线可跑通全流程** |
| 存储 | SQLite 单文件（默认 `data/app.db`）；DDL + 迁移内嵌 `server/db.py`（`schema_version` 演进） |
| 鉴权 | JWT (HS256) + bcrypt；角色 `admin` / `candidate` |
| 前端 | Vue 3 · Vite · Element Plus · Vue Router · Pinia · axios · ECharts |
| 部署形态 | Vite build 产物由 FastAPI 静态托管，单进程 uvicorn 演示上线 |

## 目录结构

```
.
├── server/                 # FastAPI 后端
│   ├── main.py             # 应用入口：加载 .env / 建表 / 注册路由 / 静态托管 web/dist
│   ├── config.py           # 环境变量与可配置常量（权重口径、测评配额、开放参数占位）
│   ├── db.py               # SQLite DDL + 迁移（schema_version）+ 初始化（20+ 张表）
│   ├── schemas.py          # Pydantic 请求 / 响应模型
│   ├── core/               # 安全等底层（密码哈希、JWT）
│   ├── api/                # 路由：auth、assessment、admin/{jds,models,positions,dict,users,trace,feedback,forms,eval,reports}
│   ├── services/           # 服务层：流水线 / 题库 / 选题 / 难度状态机 / 表单 / 幂等 / 计时 / 评分 / 聚合 / 报告 / 事件
│   └── test_*.py           # pytest：P0 安全 / 模块二~四 / 迁移 / E2E / eval 隔离
├── web/                    # 前端 Vue 3 + Vite + Element Plus
│   └── src/views/          # admin/（管理端）+ assessment/（测评端）+ Login / Register
├── design/                 # 设计与需求文档（见「权威文档」）
├── data/                   # 运行时数据（git 忽略）：app.db、jd_corpus 语料、backups 备份
├── eval/                   # 模块四独立评测：一致性(b) + 虚拟考生(c) + fixtures
├── scripts/                # seed_admin.py（种子管理员）、jd_corpus_normalize.py（语料归一）
├── prototype/              # 高保真静态原型（仅视觉参考，不作功能验收依据）
├── research/               # 研究稿 / 缺口登记等参考文档
├── .planning/              # GSD 推进记录：ROADMAP / STATE / PROJECT / 决策 / 需求条目
├── .github/workflows/      # CI：backend pytest + frontend build
├── .baseline/              # 重构前基线快照（历史追溯）
└── CLAUDE.md               # agent 行为约定（含文档治理摘要）
```

## 权威文档与文档治理

- **唯一 SSOT**：`design/final-design/总设计文档.md`（v2.0）。全系统设计、范围、接口、验收的唯一权威；任何变更**先改 SSOT（正文 + §14 变更日志）再动代码**。
- **从属模块稿**：`design/final-design/模块一~四设计*.md` 为 SSOT 的分块摘录，冲突以 SSOT 为准。
- **上游需求**：`design/需求文档-胜任力测评与人才画像系统.md`、`design/技术方案概述.md`。
- **历史档案**：`design/final-design/历史档案/`、`design/` 下旧版 04/05/06 等仅作追溯；临时讨论稿（`design/临时讨论稿-*`）为收敛过程记录，均**不构成实施依据**。
- SSOT 的修改需经用户明确授权；`design/` 下的 checkpoint 快照与讨论稿只是上下文，不构成改动授权。

## 运行（快速开始）

### 环境要求

- Python 3.11+
- Node.js 20（前端构建 / 开发）
- 可选：DeepSeek（或其他 OpenAI 兼容端点）API key；不配则用 `mock` 模式

### 1) 后端

在**仓库根目录**执行：

```bash
python -m venv .venv && source .venv/bin/activate   # 可选：虚拟环境
pip install -r server/requirements.txt
cp .env.example .env          # 按需修改，见「配置」
```

初始化并启动：

```bash
ADMIN_USERNAME=admin ADMIN_PASSWORD=admin123 python -m scripts.seed_admin   # 幂等，可重复执行
uvicorn server.main:app --reload --port 8000
```

- 健康检查：`curl http://localhost:8000/api/health` → `{"status":"ok"}`
- 启动期会**拒绝**使用未配置或公开默认值的 `JWT_SECRET`（fail-closed）。
- 首次运行自动建库建表，SQLite 落盘到 `data/app.db`（可用 `DB_PATH` 覆盖）。

### 2) 前端（开发模式，热更新）

```bash
cd web
npm install
npm run dev          # http://localhost:5173 ，/api 自动代理到 :8000
```

### 3) 单进程演示（前端构建后由后端托管）

```bash
cd web && npm run build
# 回仓库根目录，再次启动 uvicorn，访问 http://localhost:8000
uvicorn server.main:app --port 8000
```

### 账号

- **管理员**：由 `scripts.seed_admin.py` 种子创建（默认 `admin / admin123`，仅限本地演示，请修改）。
- **候选人**：开放注册（`/register`），系统强制角色为 `candidate`，不可能注册出 admin。

### 配置（`.env`）

| 变量 | 说明 |
|---|---|
| `LLM_PROVIDER` | `mock`（默认，离线规则模拟）或 `deepseek` |
| `LLM_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY` | 真实 LLM 接入（OpenAI 兼容端点） |
| `JWT_SECRET` | **必须**设置为强随机密钥，否则拒绝启动 |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 种子管理员账号（仅 `seed_admin` 读取） |
| `DB_PATH` | 数据库文件路径（默认 `data/app.db`） |

## 测试与 CI

```bash
# 后端回归（conftest 自动注入 mock LLM / test JWT / 独立临时 DB，不碰 data/app.db）
cd server && python -m pytest . -q

# 前端构建校验
cd web && npm ci && npm run build

# 独立评测（eval/ 使用隔离临时库，见 eval/ 内说明）
```

CI 位于 `.github/workflows/ci.yml`，push / PR 时执行上述后端测试与前端构建。

## 当前状态

- 里程碑 v2.0 六阶段（P0 安全与主链 → 动态选题与有界循环 → 表单/SSE/幂等/计时 → 题库版本绑定与模块一收口 → 证据链与报告契约 → 迁移与测试闭环收口）已全部收口。
- 后端回归全量 pytest 通过（**223 passed**，当前分支实测 2026-09-06）；推进记录见 `.planning/STATE.md`。开放参数见 SSOT §31——**待用户校准，禁止臆造默认值**。
- 目标形态为**演示上线**：单机、单实例、单进程；评测基于 `mock` 回归 + 独立 `eval/`，不替代真实 LLM 质量验证。

## 相关约定

- 提交信息使用中文；一次 commit 一个逻辑单元；涉及 SSOT 的变更需先经用户授权并原子提交。
- 运行产物（`.env`、`data/`、`web/node_modules/`、`web/dist/`）均已被 `.gitignore` 忽略，不入库。
