# 模块一设计：岗位 JD 解析与胜任力模型构建

> 本文档为《design/final-design/总设计文档.md》（唯一 SSOT）**第二部分的分块摘录**，聚焦模块一阅读。
> 状态：**已实现（M1~M3）**；§8 M1 回归已落地为 `server/test_m1_regression.py`（八项脆弱点回归锁）。
> 2026-09-07 与 SSOT v2.0（含 §14 变更日志至 2026-09-06）全量核对同步；同日随 SSOT 2026-09-07「源标题优先归岗」条目同步本文件 §2/§3/§9，随「聚合任务可观测」条目同步本文件 §2/§5/§7/§10。
> 2026-09-10 与 SSOT（§14 变更日志至 2026-09-09）全量核对同步：补岗位生命周期（§2）、聚合并发守卫/收尾触发（§2）、facet 打标与断言等价合并（§3）、证据排除（§3.1 新增）、聚合管理页（§7.1 新增）、confirmed 重聚合入口（§7.1）；§8 等级冲突测试描述相对 SSOT §19（2026-09-09 修订）的实现滞后处加注。
> 维护规则：任何设计变更，先更新《总设计文档.md》（正文 + §14 变更日志），再动代码。

---

## 1. 目标与业务链

把非结构化 JD 转化为**已确认（confirmed）的岗位聚合胜任力模型**（带版本号），作为模块二出题与模块三打分的唯一依据。核心实体是**岗位（Position）**；单条 JD 解析结果只是中间产物，人审只发生在聚合模型一层。

```
①接入(粘贴/JSONL) → ②清洗(纯规则) → ③抽取(LLM#1) → ④归一消歧(词典+LLM#2)
→ ⑤聚合(代码频次+LLM#3裁决+代码算权重) → ⑥人审(审核页确认升版本)
```

## 2. 状态机与归岗

- `imported → parsing → parsed / failed → aggregating → draft / stalled → confirmed`；
- confirmed 后新增 JD / 重解析 → 产出新 draft → **diff 审阅流**（逐项三选一：保留人工值/采用新值/再编辑）升 v{n+1}；
- 标题源优先：JSONL 行内 `job_title`（兼容 `position` 键名）入库即存 `jd_record.job_title`；pipeline 与 reparse 不覆写已存标题，仅库内标题为空时以 LLM#1 抽取兜底；
- 归岗：取标题（上述源标题优先）→ 规范化（去空格/大小写/常见后缀）→ position 精确匹配（`COLLATE NOCASE`，大小写不敏感；存量岗位名不迁移）→ 别名表 → 未命中建 `pending_review` 岗位（人工审核激活；不聚合、不对测评端可见）；**name/alias 匹配限 `active + pending_review`**（2026-09-09 裁决）——inactive 岗不再吞同名新 JD，落穿建新 `pending_review` 壳，管理员可上架旧岗 + 合并新壳收口；
- **岗位生命周期（2026-09-09 产品化，SSOT §8）**：状态机 `pending_review`（入口态）→ approve → `active`；`active ⇄ inactive` 由管理员经 `POST /admin/positions/{id}/status`（body `{"status": "active"|"inactive"}`）手动下架/上架——pending 岗禁用该端点（入口态须经审核流）、目标态=当前态 409、下架时同岗位存在 `RUNNING` 聚合任务 409（等完成再下架）；
  - **下架语义**：不可开考（模块二 §10.4 首项 position active 检查挡）、对测评端不可见（岗位列表过滤 active）、不聚合（auto+manual 均限 active）、不吸收自动归岗的同名新 JD（见上条）、不影响在途会话（豁免同模块二 §9.2 在途精神）；
  - **已归属 JD 改归**：`POST /jds/{jd_id}/reassign` 对任意 JD 开放（不再只限孤儿），管理端岗位详情页 JD 清单行内改归（target 仅 active、排除本岗位）；
  - **岗位合并**：`POST /admin/positions/{source_id}/merge`（body `{"target_id"}`，单事务、先校验后变异）——target 须 active，source 须为数据壳（无 competency_model / question_bank_task / assessment_session 子表数据；有数据岗不可合并——模型属岗位聚合产物不可搬运，走逐条改归+壳岗下架），JD 全量改归 target、source 名及其 `position_alias` 全量迁为 target 别名（UNIQUE 冲突 409 报冲突项）、source 删除，**不自动重聚合**（合并入证据由管理员到聚合页手动重聚合吸收——升版本须 diff 人审，不绕过），响应含 `moved_jds`/`moved_aliases` 计数；pending 岗处置三选一：approve / reject / merge（merge 即以该壳为 source）；
  - `GET /admin/positions/options` 增 `status` 查询参数（默认不传=全量，保持岗位详情页名称查找语义；改归/合并目标下拉传 active）；inactive 岗开放模型审核页**只读浏览**（历史/版本/diff；写操作各端点已有 active 守卫）；
- 异步：导入/聚合不在请求内同步执行；前端列表轮询（5s）；聚合任务进度反馈与任务行追溯见 §3.1 后列表（SSOT §8.4，`aggregate_task` 表）；聚合自动触发钩子独立于解析异常处理（聚合自身异常不连累 JD 状态）；**入口并发守卫**（2026-09-08，SSOT §8.4）——`run_aggregate` 起跑前查同岗位是否已有 `RUNNING` 任务行，命中则本次静默跳过（不产生新任务行/新版本），单点挡住批量导入期间后到 JD 的尾部重复触发与同岗位并发撞 `UNIQUE(position_id, version)`；主动路径（POST aggregate / retry-level）在端点层先判同岗位 RUNNING 行即 409「聚合进行中」（retry-level 守卫须在删除 stalled 模型之前，防「删了模型却没跑起来」）；**收尾触发**（2026-09-08，SSOT §8.4）——pipeline 尾部自动触发前先查同岗位是否仍有 `imported/parsing` 状态的 JD，有则本轮跳过（同批导入每岗位恰好聚合一次，批内最后一条解析完成者触发）；与入口守卫互为兜底，双触发不重跑；跨岗位聚合总览与管理见 §7.1（SSOT §8.6）。

## 3. 工序实现约束

| 工序 | 要点 |
|---|---|
| ② 清洗 | 纯规则按标题词切段，职责块/要求块分离；要求块空或 <30 字 → `low_confidence=1` 但**继续流程**；无 LLM 兜底；header 与内容同行时保留内容段 |
| ③ 抽取 | LLM#1，JSON 模式 + 强 Schema（items[]：name/category/required_level/importance/evidence/years?/job_title）；校验失败带错误重试 ×2 → `failed`；四条硬约束（原子化/抄录证据/三档措辞映射/1–5 级措辞映射）写入 prompt；job_title 仅当库内标题为空时兜底（源标题优先——见 §2，导入行内 job_title 直接入库） |
| ④ 消歧 | 词典候选 = 同 category 相似度过滤（difflib 编辑距离 ratio + 子串包含，归一化 lowercase/strip，阈值 `DICT_MATCH_THRESHOLD=0.5`）取 top10 → LLM#2 裁决同义/包含/重合；失败重试 ×2 → 降级代码精确去重；新标准名写词典 `llm_pending`；词典为空跳过 LLM#2。拼音匹配未启用（干净语料收益低，避免 pypinyin 依赖——§31-4 裁决） |
| ⑤ 聚合 | 纯代码频次（r/req/occ——req 为**条件口径**：「标 required 的 JD 数 ÷ 该能力**出现**的 JD 数」，绝对口径废弃）→ importance 三档映射：`required ⇔ 条件req ≥ REQ_THRESHOLD(0.5) 且 r ≥ REQ_MIN_OCCURRENCE_RATIO(0.25) 且 出现 JD 数 ≥ REQ_MIN_OCCURRENCE(3)`（仅 hard_skill 可判 required，soft_skill 上限 preferred——2026-09-07 裁决；条件 req 修正单 JD 措辞泛滥，r/occ 双门槛保岗位共识与统计证据下限）；`preferred ⇔ 未达 required 且 出现 JD 数 ≥ PREFERRED_MIN_OCCURRENCE(3)`；否则 `plus`（裸条件口径实测否决：图像算法 271/306 泛滥）→ level 冲突交 LLM#3（**无自动取众数后门**）→ 权重纯代码；LLM#3 重试 ×2 仍败 → 模型 `stalled`（管理员 P1 待办）。`_collect_items` 滤除 evidence_exclusion active 行（**全排除的 JD-项不计 r/req 分子**，分母不变——§3.1）。preferred occ 基准（2026-09-08 裁决）：绝对 r 阈值与样本量耦合致 34 模型中 15 个 preferred=0（低样本岗 r 恒不可达 0.5，中段 [0.25,0.5) 全被判 required 无剩余人口）——改 occ≥3 统计语义与 required 双门槛同基；R_THRESHOLD 退役（required 侧 r≥0.25 保留，职责不重叠）。**gate qualification facet 打标与断言等价合并（2026-09-08，SSOT §8.1）**：分组产物中的 gate qualification items 先做 facet 分类（确定性纯函数：关键词词表 + 内嵌数字解析，无 LLM），打标落 `competency_item.facet_key / facet_params_json`（两 nullable 列，/module二 §10 facet 渲染消费）；随后对**有序 facet 且派生参数一致**的组做断言等价合并（一组一行，std_name 取更窄措辞，evidences/jds/req_jds 并集；复合断言如「211硕士及以上学历」横跨学历+院校两轴、专业范围类、长尾未分类项**不参与**），合并先于 LLM#3 分档（被合并项不进其视野）。语义边界：只合「**事实含义完全一致**的同断言不同措辞」（2026-09-09 修订——原举例「本科及以上学历」与「全日制本科学历及以上」可合并**作废**；学习形式/专业范围/院校条件等限定词是断言的组成部分，限定不一致不得合并，SSOT §16.2），不处理「跨 JD 词面近重复」（词典第 3 层管辖，冻结裁决有效）；存量模型 facet_key 为 NULL → 渲染端整组降级勾选组 fallback（模块二 §10），已 confirmed 模型不回填不重打标，岗位重聚合刷版本自然带上 |
| ⑥ 人审 | PUT 编辑草稿 → confirm 升版本；编辑 stalled 模型后自动转 draft 并清 stall_reason（与"重试 LLM"并列的手动定级恢复路径）。证据可标记排除/恢复（语句粒度软排除+留痕，§3.1；前端仅 draft/stalled 可操作） |

### 3.1 证据排除（可标记、可恢复、重聚合生效；SSOT §8.5，2026-09-07 新增）

管理员在模型审核页（工序⑥）审查聚合证据时，可将单条证据摘录标记为**已排除**（软标记，不删数据，操作人/时间/原因留痕，可解除再恢复）。排除是**源头治理**动作：作用于「岗位 × JD × (std_name, category) × 证据原文」粒度（表 `evidence_exclusion`，PK 同四元组，`status: active/lifted` 解除不删行），独立于模型版本持久存在，重聚合不丢失，对新版本生效。

**生效规则**（三条，`run_aggregate` 的 `_collect_items` 单点收口，下游 LLM#3/occurrence/权重全部继承）：

1. **证据级**：被排除摘录不进入新版本的模型快照 evidence、LLM#3 等级裁决 prompt、题库生成岗位背景摘录；
2. **频次级（用户裁决：全排除才影响）**：某 JD 对某 (std_name, category) 的**当期证据全部**被排除（原有证据非空且无剩余）→ 该 JD 不计入该项 r/req 分子（分母口径不变）→ importance 可能降档 → 类内权重重算；部分排除不影响 r/req；原有证据为空的项无可排除对象、行为不变；
3. **消项级**：某能力项在全部 JD 上的证据均被排除 → 该项从聚合产物消失，权重并入其余项（Σ=100% 不变）。

**读取与交互**：`GET /admin/positions/{id}/model` 对 draft/stalled 模型**读取时实时合并**被排除条目（每条附 `excluded: true` + 留痕字段，前端灰显/划线/可恢复，合并非版本历史快照——历史以表内审计列为准）；confirmed 版本返回入库快照不合并；`PUT /admin/models/{id}` 收到含 excluded 标记的 evidence 由后端剥离落库（存储不变量：模型存储只含未排除证据）。

**端点**（岗位作用域，require_admin）：`POST /admin/positions/{id}/evidence-exclusions`（目标须为本岗位 parsed JD 的现存证据摘录，400 校验；幂等 upsert）／`DELETE /admin/positions/{id}/evidence-exclusions`（置 lifted 不删行，幂等）／`GET /admin/positions/{id}/evidence-exclusions`（全量列表含已解除，每行附 `evidence_matched` 实时失配标志——JD 重解析或词典合并改名后失配据此可见，不做自动迁移）。

**行为边界**：后端不因当前模型 confirmed 拒绝标记/解除（排除是版本无关的岗位级治理）；前端仅在 draft/stalled 暴露标记/恢复按钮，confirmed 只读；标记不自动触发重聚合（管理员手动「重新聚合」生效）；全排除致能力项从模型消失后，恢复经由「排除记录」列表完成闭环。

## 4. 权重口径（v2.0 关键修正）

**第一层（类目间）——评分类目比例：**

```
hard_skill : soft_skill = 0.70 : 0.30（Σ 各大类 item.weight 分别 = 0.70 / 0.30）
```

- `experience / qualification` **不占类目权重池**：走表单/简历事实采集，gate 二值判定；
- 某大类无有效能力项 → 现有大类归一到 1.00；大类有 item 但无合法题库 → **阻止开考**（模块二 §10.4），不静默转移权重。

**第二层（类内）：** 各项按 importance 系数分摊（required 1.0 / preferred 0.6 / plus 0.3），合成结果存 `competency_item.weight`（Σ=1，四舍五入尾差由权重最大项吸收）。模块三算总分**直接复用 item.weight，不再二次乘大类比例**。

**tier 语义（v2.0）：** required/preferred/plus 只影响原始重要性、题量配额和覆盖优先级；**不额外乘最终分数**。

**能力项测量模式：** `measurement_mode ∈ {ordinary_question, form, resume}`，来自 confirmed 模型版本，不可由前端/LLM 修改——用于把 qualification/experience 从普通对话选题器中隔离。

## 5. 关键设计原则

- gate 项（qualification 全部 + experience 年限项）二值判定，不进 1–5 评分；
- 人工唯一权威：confirmed 模型不被静默覆盖；分数是历史事实；
- 每道工序中间产物（raw_items / std_items / cleaned_text）落 `jd_record` 可查；
- 能力词典独立管理：被引用条目停用/合并而非删除；`llm_pending` 标签醒目待审；
- 聚合任务全程可观测：每次触发落 `aggregate_task` 行（双计数进度+当前项+成败+error，任务态与模型态并存），溯源链 `aggregate_task → competency_model → llm_trace`（SSOT §8.4）；
- trace：LLM#1/#2/#3 每次调用 prompt+response 落 `llm_trace`。

## 6. 可配置常量（config.py）

`IMPORTANCE_COEF={required:1.0, preferred:0.6, plus:0.3}`、`REQ_THRESHOLD=0.5`（2026-09-07 语义变更：条件 req 口径阈值）、`REQ_MIN_OCCURRENCE_RATIO=0.25`、`REQ_MIN_OCCURRENCE=3`（新增，required 双支撑门槛；soft_skill 不可判 required）、`PREFERRED_MIN_OCCURRENCE=3`（新增，2026-09-08 preferred occ 基准）、`LLM_RETRY=2`、`CLEAN_MIN_REQ_LEN=30`、`DICT_MATCH_THRESHOLD=0.5`（§31-4，2026-09-06 裁决）、`MAX_JD_LENGTH=10000`、`MAX_JD_FILE_LINES=500`。（旧 `CATEGORY_RATIO=5.5:2:2:0.5` 由 7:3 + gate 不占权重的新口径取代。）

清洗噪声词表走 pipeline 内置硬编码表（`NOISE_HEADERS`），配置词表**不启用**（2026-09-06 演示期裁决，`TITLE_CLEAN_WORDS` 占位摘除——§31-4）。

## 7. 前端页面（现状沿用）

| 路由 | 页面 | 说明 |
|---|---|---|
| /admin/positions | P1 岗位库 | 待办条（新岗位审核/stalled/待归属）+ 岗位卡片 + 导入弹窗（粘贴/文件） |
| /admin/positions/:id | P2 岗位详情 | JD 列表轮询、工序留档抽屉、重新聚合、JD 行内改归（2026-09-09）；岗位状态切换/合并入口（2026-09-09，§2） |
| /admin/positions/:id/review | P3 模型审核 | 左右双栏：证据面板（原文高亮+出现率+LLM#3 理由+排除/恢复+已排除切换，§3.1）+ 模型树（Σ=100% 校验）+ 确认模型 + 聚合进度条（双计数+当前项，SSOT §8.4）；inactive 岗只读浏览（2026-09-09） |
| /admin/positions/:id/versions | P4 版本 diff | 版本列表 + 逐项三选一审阅 |
| /admin/models | 模型聚合（2026-09-08 新增） | 跨岗位聚合任务与模型总览：KPI 四块 + 筛选 + RUNNING 进度 + 行内重聚合（§7.1，SSOT §8.6） |
| /admin/dict | P6 能力词典 | 表格 + 编辑抽屉 + 合并对话框 |
| /admin/users | P7 用户管理 | 建号/停用/重置密码 |
| /assessment/positions | P5 岗位列表 | 仅 active + confirmed；卡片式选择 |

状态色约定：pending_review 橙、failed 红、stalled 红、draft 蓝、confirmed 绿。

管理员列表接口（2026-09-06 裁决）：`GET /admin/positions`、`/admin/positions/pending`、`/admin/jds/orphan`、`/admin/dict`、`/admin/users` 均服务端分页（`page`/`page_size`，默认 page_size=20，上限 `MAX_PAGINATION_LIMIT=100`），返回 `{items, total}`；`GET /admin/positions/options`（现立于 jds 路由 `/positions/options`）轻量选项接口全量不分页，供改归下拉/名称查找——**增 `status` 查询参数（默认不传=全量，2026-09-09）与 `banked` 过滤参数（与 status 可组合，仅列 active 且存在 active 题库行的岗位，2026-09-09**，模块四 §23 测试中心下拉消费）。

### 7.1 聚合管理页（SSOT §8.6，2026-09-08 新增）

管理端左侧栏「岗位详情」死链项（`/admin/positions/detail` 被 `positions/:id` 吞作岗位 ID）替换为「模型聚合」页，路由 `/admin/models`。定位：跨岗位的聚合任务与模型产物总览（与「题库状态」页形态对齐）。

- **列表端点**：`GET /api/admin/aggregate-tasks`（require_admin）——行源为**岗位 × 最新聚合任务行 + 左连最新模型**，active 岗位上「有模型或有任务行」即入列（首次聚合进行中、模型行尚未落库的岗位可见）；参数 `page`/`page_size`（服务端分页）/ `model_status`（draft/confirmed/stalled）/ `task_status` / `q`（岗位名子串搜索）；行字段含 position_id / position_name / jd_count（parsed 数）/ 模型状态（version + 状态，无模型为 null）/ 任务行（status、done/total、llm_done/llm_total、current_item、trigger_source、error 摘要、finished_at）/ item_count / task_id；
- **「最新模型」口径（2026-09-09 修正）**：stalled > draft > confirmed 优先序，但 **draft/stalled 行参与竞争须新于最新 confirmed 版**——confirm 不删被取代的旧 draft/stalled 行（版本链留档），被超越的旧待处理行不占「最新」也不入 summary 计数（原优先序不看版本导致死待处理行永久遮蔽 confirmed）；无 confirmed 岗位上原优先序不变（stalled > draft 先分组再取版本新）；
- **响应附 `summary`**：`{draft_positions, confirmed_positions, stalled_positions, running_tasks}`——前三者为最新模型落于该状态的 active 岗位数（与行内取数/筛选口径互为镜像；不随筛选变，KPI 块与侧栏徽标数据源）；
- **前端（`ModelAggregation.vue`）**：KPI 四块 → 筛选（模型状态 + 任务状态 + 岗位名搜索）→ 表格（RUNNING 行内进度条 + 双计数 + current_item；FAILED 行 error 摘要）→ UiPager（含页码跳转）；列表含 RUNNING 行时 3s 轮询（进页认领、离页/keep-alive 失活停表不停任务）；**点行跳现有审核页** `/admin/positions/{id}/review`（审核/证据/版本历史全部复用，零新详情页）；侧栏「模型聚合」菜单项挂 stalled 徽标（数据源 `/admin/todos.stalled_models`）；
- **行内快捷动作三类**：stalled 行「重新聚合（清 stall）」（retry-level 端点）、FAILED 且无模型行「开始聚合」、**confirmed 行「重聚合（升版本）」**（2026-09-09 增补——均走 aggregate 端点，产物为 draft v{n+1}，经审核页确认后自动生成新题库并归档旧库；confirmed 岗产品化换血入口，升版本仍须 diff 人审不绕过），均受 §2 的 409 守卫（仅 active 岗可聚合、RUNNING 撞车 409）；
- **不做**：任务级排队/取消、批量操作、草稿批量清理。

## 8. M1 回归测试（已落地）

SSOT §8.1 八项脆弱点回归锁已实现为 `server/test_m1_regression.py`（统一 pytest 收集）：清洗边界、抽取 schema 异常与 evidence 兜底、消歧（空词典降级 / 非空 merges）、权重尾差 Σ=1（尾差由最大项吸收）、等级冲突极差 ≥ 阈值取低 + 人工复核标记（`ADJUDICATE_CONFLICT_THRESHOLD=2`）、gate 保守失败、confirmed 不可静默覆盖、版本升级与 diff、管理员权限。

**实现滞后标注（2026-09-10 核对）**：「等级冲突极差 ≥ 阈值取低」一项的现行断言（`adjudicate`：极差 ≥ 2 → `min(levels)` + human_review）对应 SSOT §19 **2026-09-09 修订前的旧口径**——SSOT 现行契约为「量表统一前置：不同锚点档证据不直接比较、不跨尺度计算极差；冲突未解决 → 待复核，不以保守为理由自动形成确定低等级（`min(levels)` 取低作废）」。代码 `aggregation.py adjudicate` 仍为极差取低实现，属已登记的待修项，不构成本分册与 SSOT 的规则冲突。

## 9. 重构注意

- ~~`/jds/orphan` 静态路由必须注册在 `/jds/{jd_id}` 参数路由之前~~ **已修复**（现路由顺序正确，注释标明置于参数路由前，并有 `test_phase4_orphan.py` 覆盖）；
- JD 文件导入：解析校验在前、逐行 `_insert_jd` 各自 commit（行级独立，坏行校验时抛 400 回滚该次插入，不留半成品行；跨行非原子为 by-design——多 JD 相互独立）；
- JSONL 行内 `job_title`（兼容 `position` 键）透传入库；pipeline/reparse 不覆写已存标题；存量漂移标题（修复前已被 LLM 覆写的行）的修正走 `scripts/backfill_jd_source_title.py`（raw_text 全文配对源 jsonl，dry-run 默认，须用户审阅后手动 `--apply`），reparse 不是修正漂移的手段；
- 输入限额已接线：JD 长度 10000、文件行数 500（`server/services/input_limits.py` 纯函数 + 接口层调用）；
- 模型编辑 PUT 字段校验已接线：Pydantic 强类型 + `allow_inf_nan=False`（NaN/Inf 拒绝）、weight 0–1 边界、同 category 内 std_name 重复拒绝（判重键 `(std_name, category)` 与 diff 对齐键一致）。

## 10. 本文依据

《总设计文档.md》§8–§8.6、§16.2（合并语义边界）、§17（题库生成结构规则）、§27、§28、§31（开放参数裁决）；变更日志条目 2026-09-06（词典阈值/管理员分页）、2026-09-07（源标题优先归岗、聚合任务可观测、证据排除、聚合管理页雏形）、2026-09-08（聚合管理页与重复触发收敛、preferred occ 基准）、2026-09-09（最新模型死草稿遮蔽修正、岗位生命周期产品化、confirmed 重聚合入口）；差异登记见总文档 §30。
