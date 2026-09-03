# Requirements — Synthesized Intel

- 来源批次：ingest-docs（MODE=new，2026-09-02）
- 来源：`design/需求文档-胜任力测评与人才画像系统.md`（PRD，precedence 2，上游需求输入）+ `design/技术方案概述.md`（DOC，precedence 2，上游需求输入）+ SSOT 范围承诺
- 权威关系：需求文档与技术方案概述为上游需求输入，SSOT（design/final-design/总设计文档.md）已吸收其意图并收敛实现口径；**验收口径以 SSOT 为准**。每条需求登记 PRD 原始验收描述与 SSOT 落定口径，二者冲突不合并、不择一，记入 INGEST-CONFLICTS.md 的 INFO（SSOT 权威已自动裁决）。
- ID 约定：`REQ-{slug}`。

---

### REQ-jd-parse-model
- Source PRD: design/需求文档-胜任力测评与人才画像系统.md §二.1（+ 技术方案概述 §三.1）
- Description: 系统需支持输入目标岗位的 JD 文本（粘贴/JSONL 批量），利用大模型从非结构化文本提取关键信息（硬技能/软技能/经验要求），构建结构化"岗位胜任力模型"并为各项要求分配权重。
- PRD acceptance（原始）: 从 JD 中提取"硬技能""软技能""经验要求"等关键信息，同时为各项能力分配权重。
- SSOT 落定口径（design/final-design/总设计文档.md §8–§8.3）: 六工位流水线（接入→清洗纯规则→LLM#1 抽取→词典+LLM#2 消歧→代码频次+LLM#3 裁决+代码算权重→人审 confirm 升版本）；权重按 7:3 类目 + importance 系数口径（见 D-006）；人审只发生在聚合模型一层，confirmed 模型不被静默覆盖；M1 回归测试为动态测评实施前硬前置。
- Scope: 模块一

### REQ-dynamic-question-generation
- Source PRD: design/需求文档-胜任力测评与人才画像系统.md §二.2（+ 技术方案概述 §三.2）
- Description: 摒弃传统固定题库。基于解析出的"待验证项"，AI 动态生成贴合真实工作场景的情景测试题或技术追问。
- PRD acceptance（原始）: AI 需动态生成贴合真实工作场景的情景测试题或技术追问。
- SSOT 落定口径（总设计文档 §9–§10、§11.1）: 动态**不是** LLM 自由发挥——题库按岗位 + confirmed 模型版本绑定（model_id/model_version），动态体现在"动态实例化 + 四层选题结构"（D-009），LLM 只做题面岗位化/口语化轻包装；追问每题最多 2 次（代码硬约束）；题量按岗位级 N + 7:3 + tier 公式配额（D-008）。
- Scope: 模块二题库与选题

### REQ-interactive-multiturn-assessment
- Source PRD: design/需求文档-胜任力测评与人才画像系统.md §二.3（+ 技术方案概述 §三.2）
- Description: 提供流畅的 AI 对话交互界面；实现多轮对话与动态追问（根据学生回答进行压力测试或深挖）。
- PRD acceptance（原始）: 多轮对话与动态追问；对话历史列表式上下文管理（技术方案概述：后端维护对话历史列表，整表发给大模型，模型自行决定追问/切题/结束）。
- SSOT 落定口径（总设计文档 §4、§11）: 有界测评循环 Observation → Policy/Plan → Act → Evaluation → Persist（D-004）；LLM **不能**自行决定切题/结束（finish 仅代码触发）；followup ≤2 次/题由代码执行；回答状态 11 类分类 + 处理原则（含糊→中性澄清、跑题→重定向、拒答→一次确认后跳过等）。
- Scope: 模块二对话运行时

### REQ-talent-profile-report
- Source PRD: design/需求文档-胜任力测评与人才画像系统.md §二.3（+ 技术方案概述 §三.3）
- Description: 测评结束后，AI 自动生成包含"能力雷达图""优势与短板分析"及"针对性提升建议"的结构化人才画像报告。
- PRD acceptance（原始）: 报告含能力雷达图、优势与短板分析、针对性提升建议；技术方案概述：大模型扮演"公正评估官"对各项能力打分（如 0-10 分）并给出评价，前端 ECharts 渲染雷达图。
- SSOT 落定口径（总设计文档 §17–§21）: 报告五段式（总分+门槛标签/雷达/逐项明细含逐行异议/优势短板建议/逐题回顾），发布契约见 D-025；打分**不是** LLM 自由打分——score_final 独立终局评分按锚点 rubric（1–5 级）执行，优势/短板由代码排序、LLM 只写文字且只能基于给定短板项；报告状态机 + 七项发布前一致性校验 + 管理员明确点击发布。
- Scope: 模块三

### REQ-data-compliance
- Source PRD: design/需求文档-胜任力测评与人才画像系统.md §三（+ 技术方案概述 §四）
- Description: 严禁使用恶意爬虫直接抓取招聘网站数据；采用合规替代方案。
- PRD acceptance（原始）: 浏览器插件辅助提取，或本地文件/开源工具导入（如 boss-crawler-skill）半自动获取；技术方案概述：手动输入/文件上传（支持不少于上百条）或浏览器插件辅助。
- SSOT 落定口径（总设计文档 附录 B、§25）: 本期范围决策（D-029）：浏览器插件**保留不做**；JD 接入走粘贴/JSONL 文件导入；输入限额按类型配置。合规原则（禁恶意爬虫）被 SSOT 全盘继承，但落地路径收敛为文件导入。
- Scope: 数据获取

### REQ-e2e-demo-deliverables
- Source PRD: design/需求文档-胜任力测评与人才画像系统.md §四（+ 技术方案概述 §五）
- Description: 完整跑通"JD 解析 → 测评框架构建 → 交互测评 → 画像生成"全流程演示；交付完整源码仓库、API 接口文档及部署说明；答辩重点阐述提示词工程设计思路与工程化落地难点。
- PRD acceptance（原始）: 全流程演示 + 源码/API 文档/部署说明 + 答辩（提示词工程 + AI Agent 开发工程师要求测评自测）。
- SSOT 落定口径（总设计文档 §24、§26）: E2E 验收 = 候选人端完整 E2E（注册→选岗→session→作答/追问→表单→完成→评分→报告→异议，含刷新恢复/断线重试/越权/超时）为 M5–M7 verified 必要条件；统一 pytest 收集 + CI 为正式验收入口；Prompt 模块按 §26 接口化登记（答辩素材）。部署说明对应演示上线形态（D-005）。
- Scope: 交付与验收

### REQ-iterative-loop
- Source PRD: design/技术方案概述.md §三.4（+ 需求文档 §二 整体闭环意图）
- Description: 在 JD 解析、测评框架、测评过程、评价过程各环节上提出改进策略，形成持续迭代闭环：过程中收集数据并完成胜任力模型、测评框架、测评过程和评价过程的不断改进。
- PRD acceptance（原始）: 提出更好的提升框架，可在过程中收集并完成各环节不断改进策略。
- SSOT 落定口径（总设计文档 §22–§23）: 测试闭环三大标准（全链可审计 / 反馈可回溯 / 有测评标准）：feedback 异议不改分、bad case 双分背离自动候选、b+c 评测契约、eval 隔离（D-027）。迭代闭环被具体化为可验证的评测/反馈机制而非泛化改进。
- Scope: 模块四

---

## 需求覆盖关系说明（非提取，供路由参考）

- 上述 7 条需求覆盖 PRD 全部核心章节；PRD 未提出 SSOT 之外的独立验收标准。
- SSOT 中的实现级契约（状态机、schema、幂等、事件表等）未按需求登记，已按 constraints 登记（见 constraints.md）。
- PRD 的"0-10 分打分""浏览器插件""上百条 JD 批量"等表述与 SSOT 落定口径存在粒度差异，属上游意图与收敛实现的关系，**不构成 competing variants**（单一 PRD 来源），已在 INGEST-CONFLICTS.md INFO 桶逐条登记。
