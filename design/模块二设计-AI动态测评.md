# 模块二设计：AI 动态测评

> 本文档为《总设计文档.md》（单一事实来源）**第三部分的分块摘录**，聚焦模块二阅读。
> 状态：**待实施**（M5 已部分落地：题库生成 / 会话 / 对话 / 打分核心，进展见《总设计文档.md》§13 变更日志）。
> 输入契约：模块一 confirmed 模型快照（见《模块一设计-岗位JD解析与胜任力模型构建》）。
> 维护规则：任何设计变更，先更新《总设计文档.md》（正文 + §13 变更日志），再动代码。

## 6. 测评框架生成（题库 + 选题）

### 6.1 题库双轨设计（U1/U4）

```sql
question_bank(
  question_id TEXT PRIMARY KEY,
  scope TEXT NOT NULL CHECK(scope IN ('position','general')),
  position_id TEXT REFERENCES position,        -- general 时 NULL
  std_name TEXT NOT NULL, category TEXT NOT NULL,
  difficulty TEXT CHECK(difficulty IN ('easy','medium','hard')),  -- 经验/门槛为 NULL
  qtype TEXT NOT NULL CHECK(qtype IN ('objective','subjective')),
  stem TEXT NOT NULL,
  answer_key TEXT,                             -- 客观题代码判分用
  rubric TEXT,                                 -- 主观题评分要点
  chain_key TEXT, chain_seq INTEGER,           -- 问题链条（M1 补）
  source TEXT NOT NULL CHECK(source IN ('llm_seed','imported','human')),
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
)
```

- **岗位题库**：hard_skill/soft_skill，position_id 绑定；**通用题库**：experience/qualification，跨岗位；
- 演示期 = LLM 种子生成（U4，`source=llm_seed`）；演示与测试完成后真实题库走 N8 导入接口；
- **可溯硬约束（N7）**：四要素齐全（能力项绑定/难度/题型/岗位归属）才允许进入对话，出题入库强校验。

### 6.2 题库生成与题量分配

- 模型 confirmed 后**异步触发**题库生成（异步任务+轮询，M3）：prompt 携带岗位名+模型项定义+required_level 锚点+难度档；
- 题量按**类目权重**分配（D2）：总 10~12 题 ≈ 硬技能 6~7 / 软技能 2~3 / 经验 2 / 门槛走表单不占题；required 项必考；
- 每道题必须绑定 std_name（同一能力不同岗位不同题，N2 岗位背景绑定）。

### 6.3 选题规则（代码执行，可审计）

- 每轮 action=next 时，**代码**按规则取下一题：当前 item 完成度 + 难度递进（N1）+ 类目剩余题量；优先沿 chain_key 链条，缺失时退回 `(item, difficulty)` 通用递进；
- LLM 只对题面做岗位化/口语化轻包装，question_id 落库绑定。

## 7. 多轮对话（function call 驱动）

### 7.1 对话控制：结构化 action + function call 分两阶段（H2）

- 决策阶段（**非流式**）：function call `interview_step` 同步返回 `{action: followup|next|finish, reason, assessment}` → 后端**先落库**（action/reason/过程判分先于展示，可审计）；
- 话术阶段（**流式 SSE**）：基于已定 action 生成/转发 reply 逐 token 推送；
- `finish` 由规则触发（题量完成），模型不自主结束全场。

### 7.2 追问与递进

- 追问上限 2 次/题（config）；模型可提前 next；
- 递进（N1）：hard_skill 慢递进（简单→中等→困难，权重越高走完档位越多）、soft_skill 快递进（2 档）、经验/门槛无难度（事实深化）；
- 递进判分来自**过程判分 score_live**（H1）。

## 8. 上下文管理与表单（N5/N6）

```sql
context_raw(raw_id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, full_text TEXT NOT NULL, created_at TEXT NOT NULL)
-- assessment_message 增列：content_refined TEXT, raw_hash TEXT NULL
```

- **精炼（U2 阈值触发）**：长度 > ~500 token（config `REFINE_MIN_TOKENS`）才走 P-refine，短输入原文直存；精炼版进对话历史，原文哈希归档可回溯；同时承担**注入防护**；
- **评分不受损**：终局判分（P-score）按 raw_hash 回捞原文输入；
- **表单工具**：`render_form(form_type, fields[])` 后端工具；开场简历表 / gate 项缺信息时触发；提交直传 `form_submission` 表；与 user_profile 打通（已填自动带入）；原始 payload 落库。

## 9. 会话持久化

三表 + **锚定 model_id+version**（报告永远对应某版尺子）；中断恢复；24h 未完成→abandoned；副产物"我的测评"历史页。
