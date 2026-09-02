# 模块一设计：岗位 JD 解析与胜任力模型构建

> 本文档为《design/final-design/总设计文档.md》（唯一 SSOT）**第二部分的分块摘录**，聚焦模块一阅读。
> 状态：**已实现（M1~M3）**，重构时按本文保持并补齐回归测试。
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
- 归岗：job_title 规范化（去空格/大小写/常见后缀）→ position 精确匹配 → 别名表 → 未命中建 `pending_review` 岗位（人工审核激活；不聚合、不对测评端可见）；
- 异步：导入/聚合不在请求内同步执行；前端列表轮询（5s）；聚合自动触发钩子独立于解析异常处理（聚合自身异常不连累 JD 状态）。

## 3. 工序实现约束

| 工序 | 要点 |
|---|---|
| ② 清洗 | 纯规则按标题词切段，职责块/要求块分离；要求块空或 <30 字 → `low_confidence=1` 但**继续流程**；无 LLM 兜底；header 与内容同行时保留内容段 |
| ③ 抽取 | LLM#1，JSON 模式 + 强 Schema（items[]：name/category/required_level/importance/evidence/years?/job_title）；校验失败带错误重试 ×2 → `failed`；四条硬约束（原子化/抄录证据/三档措辞映射/1–5 级措辞映射）写入 prompt |
| ④ 消歧 | 词典候选 = 同类目过滤 + 编辑距离/拼音首字母 top10 → LLM#2 裁决同义/包含/重合；失败重试 ×2 → 降级代码精确去重；新标准名写词典 `llm_pending`；词典为空跳过 LLM#2 |
| ⑤ 聚合 | 纯代码频次（r、req）→ importance 阈值映射（配置项）→ level 冲突交 LLM#3（**无自动取众数后门**）→ 权重纯代码；LLM#3 重试 ×2 仍败 → 模型 `stalled`（管理员 P1 待办） |
| ⑥ 人审 | PUT 编辑草稿 → confirm 升版本；编辑 stalled 模型后自动转 draft 并清 stall_reason（与"重试 LLM"并列的手动定级恢复路径） |

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
- trace：LLM#1/#2/#3 每次调用 prompt+response 落 `llm_trace`。

## 6. 可配置常量（config.py）

`IMPORTANCE_COEF={required:1.0, preferred:0.6, plus:0.3}`、`REQ_THRESHOLD=0.5`、`R_THRESHOLD=0.5`、`LLM_RETRY=2`、`CLEAN_MIN_REQ_LEN=30`。（旧 `CATEGORY_RATIO=5.5:2:2:0.5` 由 7:3 + gate 不占权重的新口径取代。）

## 7. 前端页面（现状沿用）

| 路由 | 页面 | 说明 |
|---|---|---|
| /admin/positions | P1 岗位库 | 待办条（新岗位审核/stalled/待归属）+ 岗位卡片 + 导入弹窗（粘贴/文件） |
| /admin/positions/:id | P2 岗位详情 | JD 列表轮询、工序留档抽屉、重新聚合 |
| /admin/positions/:id/review | P3 模型审核 | 左右双栏：证据面板（原文高亮+出现率+LLM#3 理由）+ 模型树（Σ=100% 校验）+ 确认模型 |
| /admin/positions/:id/versions | P4 版本 diff | 版本列表 + 逐项三选一审阅 |
| /admin/dict | P6 能力词典 | 表格 + 编辑抽屉 + 合并对话框 |
| /admin/users | P7 用户管理 | 建号/停用/重置密码 |
| /assessment/positions | P5 岗位列表 | 仅 active + confirmed；卡片式选择 |

状态色约定：pending_review 橙、failed 红、stalled 红、draft 蓝、confirmed 绿。

## 8. M1 回归测试（后续动态测评实施前的硬前置）

清洗边界、抽取 schema 异常、消歧与词典排除项、importance 阈值、多 JD 聚合、权重尾差（Σ=1）、等级冲突失败→stalled、confirmed 不可静默覆盖、版本升级与 diff、管理员权限。

## 9. 重构注意

- `/jds/orphan` 静态路由必须注册在 `/jds/{jd_id}` 参数路由**之前**（当前顺序冲突导致待归属列表恒 404，需修复并加路由集成测试）；
- JD 文件导入：先完整解析校验、单事务批量插入（当前逐行提交遇坏行留半成品，需修复）；
- 文件大小/行数/编码限制按输入类型配置；
- 模型编辑 PUT 除总权重外须校验单项字段/类型/类目/等级/重复项/NaN。

## 10. 本文依据

《总设计文档.md》§8–§8.3、§27、§28；差异登记见总文档 §30。
