# Context Notes — Synthesized Intel

- 来源批次：ingest-docs（MODE=new，2026-09-02）
- 结构：按主题组织的运行笔记；内容保留原文语义，逐条标注来源。
- 权威提示：所有设计类内容以 `design/final-design/总设计文档.md`（SSOT v2.0）为准；本文件主题笔记仅作下游理解背景，不构成实施依据。

---

## Topic: 项目背景与目标

- 系统定位：把非结构化 JD 转化为可测量的岗位胜任力模型（尺子），基于尺子对候选人进行有界动态测评，产成立体人才画像（读数），并通过测试闭环保证全链可审计、可回溯、有评测标准。端到端链路：JD 文本 → 胜任力模型（模块一）→ 有界动态测评（模块二）→ 人才画像/评分（模块三）→ 测试闭环（模块四）。
  - source: design/final-design/总设计文档.md §1
- 项目背景：招聘市场 JD 为非结构化文本，学生难以评估自身能力与岗位匹配度；以个人形式完成核心功能开发与闭环；本实验面向课程考核（学生角色，非真实企业生产）。
  - source: design/需求文档-胜任力测评与人才画像系统.md §一、§二
- 能力培养目标：AI 应用开发（调用大模型 API 解决业务问题）、提示词工程（结构化信息提取/生成/逻辑判断）、全栈开发流程（后端/API/前端）、数据合规意识。
  - source: design/技术方案概述.md §一

## Topic: 参考架构（上游描述，已被 SSOT 收敛取代）

- 技术方案概述提出三层架构：前端交互层（AI 对话测评窗口 + 报告可视化）、后端逻辑层（JD 提取→测评框架→动态测评→画像，含业务流程/输入输出/存储/交互逻辑设计）、AI 能力层（LLM API，不直接参与业务逻辑，按指令执行文本分析/生成/推理）。AI 能力层"不直接参与业务逻辑"的意图与 SSOT 四条强约束方向一致，但 SSOT 的"代码是唯一状态机/LLM 不碰数字"约束更严格。
  - source: design/技术方案概述.md §二
- 技术方案描述的朴素多轮对话实现（后端维护对话历史列表整表发送、大模型自行判断追问/切题/结束、0-10 分打分）为**教学示意**；SSOT 已用有界测评循环、代码裁决状态机、1–5 锚点评分取代。该差异已登记 INGEST-CONFLICTS.md INFO。
  - source: design/技术方案概述.md §三.2–三.3；design/final-design/总设计文档.md §4、§17

## Topic: 文档治理与身份（实施前必读）

- 全仓库唯一 SSOT = design/final-design/总设计文档.md（v2.0，2026-09-02 生效），取代 2026-08-30 版（已移入历史档案，仅追溯）。其余文档三种身份：从属模块稿（final-design/ 分模块文档）/ 临时讨论稿（design/ 临时讨论稿-*）/ 历史档案（历史档案/ 及 design/ 原 04/05/06）。任何设计变更、范围调整、接口改动，先更新 SSOT（正文 + §14 变更日志）再动代码。旧顶层 design/总设计文档.md 已移入历史档案，靠 git 管历史，不删除。
  - source: design/final-design/总设计文档.md 文档头部、§29、附录 C
- SSOT 修改须授权：agent 仅可起草，未经用户确认不得写入 design/ 路径；SSOT 权威路径以原子 commit 变更。
  - source: 26-summer-sem/CLAUDE.md Project Context
- 临时讨论稿第一~十轮、checkpoint 快照只是收敛过程记录，不构成实施授权，不作为实施依据。
  - source: design/final-design/总设计文档.md 附录 C；26-summer-sem/CLAUDE.md Project Context
- 实施方式：基于现有代码**重构演进，不重写**。旧版中与 SSOT 不冲突的已实现细节（模块一流水线、报告五段式、部署形态等）继续有效；实施时不需要查阅任何旧文档。
  - source: design/final-design/总设计文档.md 文档头部

## Topic: 与旧版（2026-08-30）的差异登记

- N1 类目 55/20/20/5 → 评分类目 7:3 + gate 事实核验不占权重（第八轮）
- N2 score_live 50/50 合成 → score_live 仅导航不进最终分（第五轮）
- N3 14 张表 → 18→21 张（新增事件表/trace_link/form_instance）（第八轮）
- N4 题量 hard6/soft2/exp2 固定 → 岗位级 N + 7:3 最大余数 + tier 0.8/0.6/0.3 公式；exp/qual 走表单（第八轮）
- N5 一次性预选题 → 动态实例化 + 四层选题结构（第四五轮）
- N6 难度递进按类目 → easy→medium→hard 路径状态机 + 3/4/5 上限映射（第八十轮）
- N7 24h abandoned → 6h 无活动 abandoned 且本期不可恢复（第九轮）
- N8 拒答未明确 → REFUSED=0，只进行为/完整度聚合不进能力等级（第八九轮）
- N9 SSE"待切" → 真实 SSE 本期实现（第八轮）
- N10 范围含录用表述 → 明确不做录用判断/排序（第一轮）
- N11 CHECK 约束遗留争议 → 新表避免不可 ALTER 的 CHECK，用代码校验枚举（实施约束）
- N12 里程碑"完成" → 四维状态（implemented/contract_complete/verified/production_ready）（第八轮）
  - source: design/final-design/总设计文档.md §30

## Topic: 当前实现状态基线（重构起点）

- M1 鉴权 + 单 JD 解析链、M2 聚合 + 人审、M3 外围页面：2026-08-30 完成（大体 implemented，verified 不足）。
- M5 题库/session/对话核心、M6 评分报告、M7 测试闭环：主体代码已落地（2026-08-30），按四维口径当前 contract_complete=false、verified=false。
- M4（保留不做）：黄金集、浏览器插件、真实 JD 数据集。
- 模块二状态自评：主体已实现，契约需按 SSOT 重构（动态选题、状态机、事件表、表单链、SSE、计时均未兑现）。
- 模块三状态自评：后端主体已实现，契约需重构（score_live 旧合成逻辑、报告发布链、补算、人工复核字段未兑现）。
- 模块四状态自评：功能骨架已实现，质量闭环未验证（eval 隔离、短板断言、自动 bad case、真实 LLM 验证、E2E 未兑现）。
  - source: design/final-design/总设计文档.md §27、附录 B；模块一~四设计文档状态头部

## Topic: 修复与重构待办（实施顺序，SSOT §28）

1. P0：资源所有权校验（§7）；正常 UI score→report 串行（§21.1）；开考可测量性检查（§10.4）；状态事件表落地（§13）
2. 动态选题四层结构替换一次性预选（§10.6）；难度路径状态机（§11.2）；非末题 finish 护栏；回答状态分类完整化
3. 表单 instance/schema/幂等链（§16）；SSE 真实化（§11.5）；幂等与并发（§13.4）；计时区间（§15）
4. 题库 model/version 绑定与生成失败可见（§9.2）；/jds/orphan 路由顺序修复；模型编辑字段校验（NaN/范围/重复）
5. 证据 span/trace_link 落地（§12.5/§13.3）；报告发布校验（§21.1）；feedback 补 user_id/note/审计字段；报告版本化
6. 迁移体系（schema_version + 备份 + 回滚 + 迁移测试）；测试重构与 CI；M1 回归；E2E；eval 隔离
  - source: design/final-design/总设计文档.md §28

## Topic: Prompt 登记与讨论延后

- Prompt 讨论按既定安排延后，用户先拟业务初稿。SSOT 仅固化扩展点要求：所有 LLM 位置保留可替换接口或稳定设计记录（Prompt ID/调用阶段/输入输出 schema/允许与禁止影响范围/版本与 trace/启用条件）；接口可注入 Prompt 版本、模型标识、schema、trace 关联、重试策略、人工接管、mock 切换。
- 已登记场景：JD 抽取、消歧、等级裁决、题库生成（普通/综合）、回答分类、证据评估、追问/探针/脚手架/情绪支持话术、过渡收尾、事实抽取、逐题评分、综合题拆分评分、一致性校验辅助、报告文字、虚拟考生生成、评测解释、bad case 聚类摘要（可选）、复核辅助摘要（可选）。
- Prompt 清单状态：P-extract/P-disambiguate/P-aggregate-level（已实现 v1）；P-question-gen（已实现 v1，综合题待讨论）；P-interviewer（已实现 v1，按 §26 重构）；P-refine/P-score（已实现 v1）；P-report/P-form-facts/P-integrated-score/P-virtual-candidate（待 Prompt 模块讨论）。
  - source: design/final-design/总设计文档.md §26、附录 A

## Topic: 开放问题（实施期定，不得臆造）

- N 默认值与 40 分钟体验校准；滑窗 Token 参数与 REFINE_MIN_TOKENS 校准；补算人工复核阈值；词典候选 top10 匹配阈值与清洗标题词表；trace 保留期/脱敏细节与 LLM 供应商数据约束（实施期与合规确认）；幂等清理阈值与策略。
  - source: design/final-design/总设计文档.md §31

## Topic: 交付与考核（上游约束，SSOT 已吸收为验收口径）

- 交付物：完整源码仓库、API 接口文档、部署说明；全流程演示（JD 解析 → 测评框架构建 → 交互测评 → 画像生成）；答辩重点阐述提示词工程设计思路与工程化落地难点（如 AI 输出不稳定性处理、对话上下文管理）。
  - source: design/需求文档-胜任力测评与人才画像系统.md §四；design/技术方案概述.md §五
- 数据合规：严禁恶意爬虫抓取招聘网站；合规路径 = 手动输入/文件上传（支持不少于上百条）或浏览器插件辅助。SSOT 本期范围将浏览器插件列为保留不做（D-029），JD 接入收敛为粘贴/JSONL 导入。该差异登记 INGEST-CONFLICTS.md INFO。
  - source: design/需求文档-胜任力测评与人才画像系统.md §三；design/技术方案概述.md §四；design/final-design/总设计文档.md 附录 B
