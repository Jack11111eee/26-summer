## Conflict Detection Report

来源批次：ingest-docs（MODE=new，2026-09-02）
范围：7 份文档（SSOT 总设计文档、模块一~四设计、需求文档、技术方案概述）
裁决依据：manifest precedence（SSOT=0 最高权威；模块摘录=1；上游需求输入=2）+ 仓库约定（SSOT 决策按 locked 处理；模块摘录为 SSOT 分块，重叠不算 competing variants）

### BLOCKERS (0)

无。

- 无 LOCKED-vs-LOCKED ADR 矛盾：本次 ingest 集无 ADR 类型文档；SSOT 为唯一权威源，无与其同级冲突源。
- 无 cycle 阻断：SSOT 与模块一~四的相互引用为「主文—分块摘录」包含关系（SSOT→模块为拆录，模块→SSOT 为依据声明），按 orchestrator 指令记录为链接而非环；遍历深度 3（远低于 50 上限）。指向 ingest 集之外的历史档案/临时讨论稿/checkpoint 在边界处终止。
- 无 UNKNOWN-confidence-low 文档：7/7 分类均为 high confidence。

### WARNINGS (0)

无 competing acceptance variants：需求文档为唯一 PRD，不存在两份 PRD 定义同一需求不同验收的情形；模块一~四与 SSOT 的重叠为同一系统不同粒度的摘录（仓库明确声明），不登记为竞争变体，统一以 SSOT 为准提取。

### INFO (6)

[INFO] Auto-resolved: SSOT > 上游技术方案 — LLM 决策权
  Found: design/技术方案概述.md §三.2 描述「大模型基于完整上下文判断回答质量，并决定进行深度追问、切换下一个问题还是结束面试」
  Note: SSOT（design/final-design/总设计文档.md §3–§4、§11.5）锁定「代码是唯一状态机」「finish 仅由代码规则触发」；技术方案为上游教学示意。SSOT 胜，intel 按 SSOT 口径提取（decisions.md D-004/D-021）
  → 无需动作；roadmapper 直接按 D-004 排程

[INFO] Auto-resolved: SSOT > 上游技术方案 — 评分口径
  Found: design/技术方案概述.md §三.3 描述「大模型扮演公正评估官打分（如 0-10 分）」
  Note: SSOT §9.4、§17 锁定 1–5 锚点评级 + score_final 独立终局评分 + 代码聚合；0-10 自由打分被取代（差异登记 §30 N2 对应 score_live 旧口径）。SSOT 胜（decisions.md D-012、constraints.md C-030）
  → 无需动作

[INFO] Auto-resolved: SSOT > PRD — 浏览器插件合规路径
  Found: design/需求文档-胜任力测评与人才画像系统.md §三 与 design/技术方案概述.md §四 将「浏览器插件辅助提取」列为合规数据获取方案之一
  Note: SSOT 附录 B（M4 保留不做）明确本期不做浏览器插件，JD 接入收敛为粘贴/JSONL 文件导入；禁恶意爬虫的合规原则双方一致，无实质冲突。SSOT 胜（decisions.md D-029、requirements.md REQ-data-compliance）
  → 若课程考核确实要求插件，须先经用户授权修订 SSOT（§14 变更日志）后重新 ingest

[INFO] Auto-resolved: SSOT > PRD — 「摒弃固定题库」的语义
  Found: design/需求文档-胜任力测评与人才画像系统.md §二.2 要求「摒弃传统的固定题库，AI 动态生成情景测试题或技术追问」
  Note: SSOT §9.2、§10.6 锁定题库绑定岗位 + confirmed 模型版本（结构化题库实体），「动态」指动态实例化 + 四层选题（LLM 只做题面轻包装），不是运行时自由生成。意图（个性化贴合岗位）被保留，实现口径以 SSOT 为准（decisions.md D-009）
  → 无需动作

[INFO] Auto-resolved: 模块摘录与 SSOT 的粒度差异不构成冲突
  Found: 模块一~四设计（design/final-design/模块一~四设计-*.md）与 SSOT 重叠内容一致；模块摘录另含代码级细节（config 常量、前端路由表、已知缺陷清单）为 SSOT §28 的展开
  Note: 按仓库约定模块摘录为 SSOT 分块摘录，重叠部分以 SSOT 为准提取且不重复登记；新增代码级细节已并入 intel（constraints.md C-050–C-052）
  → 无需动作

[INFO] 分类哈希后缀为确定性回退值（非 SHA-256）
  Found: CLASSIFICATIONS_DIR 内 7 个 *.json 的文件名哈希后缀（如 0000404c、e6a8a1e5、56db8bbe）由分类器在无执行工具环境下生成的确定性回退摘要
  Note: 各分类 JSON 的 source_path 字段为权威指向；source_hash 后缀仅为防止并行分类文件名碰撞，不影响内容与溯源。仅记录供审计
  → 无需动作
