# PROJECT.md — AI 胜任力测评与人才画像系统

- Project code: TP（talent-profile）
- 设计唯一权威（SSOT）：`design/final-design/总设计文档.md`（v2.0，2026-09-02 起生效）
- 工作分支：`feature/m5-assessment`
- 生成：2026-09-02，gsd-roadmapper（new-project-from-ingest）

## What This Is

把非结构化 JD 文本转化为可测量的岗位胜任力模型（尺子），基于尺子对候选人做有界动态测评，产成立体人才画像报告（读数），并以测试闭环保证全链可审计、可回溯、有评测标准。端到端链路：JD 解析（模块一）→ 有界动态测评（模块二）→ 人才画像/评分（模块三）→ 测试闭环（模块四）。本仓库为课程考核项目，以个人形式完成核心功能开发与闭环演示。

## Current Milestone: M1 修复/重构流（SSOT v2.0 对齐）

**Goal:** 按 SSOT §28 六步实施顺序，把既有代码（M1–M7 implemented、contract_complete=false）重构演进到 v2.0 契约（contract_complete），并完成测试闭环验证。

**Scope:** Phase 1–6（见 ROADMAP.md）：P0 安全与主链修复 → 动态选题与有界循环 → 表单/SSE/幂等/计时 → 题库版本绑定 → 证据链与报告契约 → 迁移体系与测试闭环收口。

**Notes:** 本里程碑由 new-project-from-ingest 直接建立（未经 /gsd-new-milestone，无 MILESTONES.md 前置版本）；下一里程碑（Prompt 模块周期等）再走 /gsd-new-milestone 正常流程。

## Core Value

端到端可演示（JD 解析→测评框架→交互测评→画像生成）+ 全链可审计（LLM trace 留痕、状态事件 append-only、报告可回溯）。任何权衡下，"代码是唯一状态机、LLM 只做结构化观察"与"一切留痕"不可让步。

## Requirements

### Validated

<!-- 既有代码已实现的（implemented，verified 不足——四维口径见 D-028） -->

- [x] M1 鉴权 + 单 JD 解析链、M2 聚合 + 人审、M3 外围页面（2026-08-30 完成主体）
- [x] M5 题库/session/对话核心、M6 评分报告五段式、M7 测试闭环骨架（主体代码已落地，contract_complete=false）
- [x] mock 模式离线可跑通全流程（LLM_PROVIDER=mock）

### Active

<!-- 本里程碑（M1 修复/重构流，SSOT §28 六步）的范围，见 REQUIREMENTS.md -->

- [ ] P0 四项：资源所有权校验 / score→report 串行 / 开考可测量性检查 / 状态事件表
- [ ] 动态选题四层 + 难度路径状态机 + finish 护栏 + 回答状态分类
- [ ] 表单链 / SSE 真实化 / 幂等并发 / 计时区间
- [ ] 题库 version 绑定与失败可见 / orphan 路由 / 模型编辑校验
- [ ] 证据 span + trace_link / 报告发布校验 / feedback 字段 / 报告版本化
- [ ] 迁移体系 schema_version / 测试重构 + CI / M1 回归 / E2E / eval 隔离

### Out of Scope

- 最终录用判断、录用排序、自动通过/淘汰、代替企业作招聘决定 — D-002 范围红线，界面/报告文案/Prompt 均不得出现"录用结论""排名"表述
- 黄金集（真实数据收集后另行排期）— D-029 保留不做
- 浏览器插件 — D-029 保留不做
- 真实 JD 数据集 — D-029 保留不做
- 恶意爬虫抓取招聘网站 — 合规红线，JD 接入只走粘贴/JSONL 文件导入
- 容器化 / CI 之外的生产部署承诺 — 本期目标为本地演示上线（D-005）
- 公平性离线评估 — D-031 仅留记录，本期不做

## Context

- **实施方式：基于现有代码重构演进，不重写。** 旧版中与 SSOT 不冲突的已实现细节（模块一流水线、报告五段式、部署形态等）继续有效。
- 当前实现基线（SSOT §27）：M1–M3 大体 implemented、verified 不足；M5–M7 主体 implemented、contract_complete=false、verified=false。
- 代码现状的证据基线：`research/ssot-code-gap-matrix.md`（68 行 SSOT↔代码契约核对，含文件:行号证据）；代码地图见 `.planning/codebase/{ARCHITECTURE,STRUCTURE,CONCERNS,TESTING}.md`。
- 已知最重缺口（矩阵 P0）：候选人资源接口无所有权校验（IDOR）；正常 UI 流程下 score→report 链路为零步断裂（前端从不调 POST /score，报告聚合恒 no_data）；create_session 无开考检查（可建 0 题会话）；无状态事件表。
- 技术栈现状：Python 3.13 + FastAPI + SQLite（无 ORM，raw SQL）+ Vue3/Vite/Element Plus；单进程单实例；BackgroundTasks 内存执行（进程重启丢任务，本期接受）。
- 测试现状：`test_m5/m7_backend.py` pytest 可收集；`test_m6_backend.py`/`test_question_bank.py` 为脚本式不可收集（question_bank 在 pytest 下 3 errors）；无 CI；每测试文件独立临时 DB、LLM_PROVIDER=mock；**同一进程不得导入两个测试模块（DB_PATH 冲突）**。
- SQLite 单写者约束：混用 DB 写与 LLM 调用时必须"先 commit 再调 LLM"或"内存算完单事务落库"（两种既有模式：`api/assessment.py:167`、`services/scoring.py:107`）。
- Prompt 讨论（§26 场景清单）按既定安排延后，用户先拟业务初稿；所有 LLM 位置保留可替换接口（D-030）。
- 开放参数（SSOT §31 六项：N 默认值、滑窗 Token 参数、补算复核阈值、词典阈值、trace 保留期、幂等清理阈值）实施期定值——排"校准"任务而非臆造默认值。

## Constraints

- **文档治理**：`design/final-design/总设计文档.md` 为唯一 SSOT；先改 SSOT（正文 + §14 变更日志）再动代码；SSOT 修改须用户明确授权，agent 仅可起草；不得写 design/ 路径。
- **强约束（D-003，全系统不可谈判）**：LLM 不碰数字；人工是唯一权威；一切留痕；代码是唯一状态机。
- **技术栈（D-005）**：Python 3.11+ / FastAPI / Uvicorn 单进程 / SQLite 单文件（DDL+迁移内嵌 server/db.py）/ JWT HS256 / Vue3+Vite+Element Plus；mock 模式离线可跑通全流程。
- **Schema**：全局 21 张表（18 现有 + 3 新：assessment_state_event/form_instance/trace_link）；新表避免不可 ALTER 的 CHECK，枚举用代码校验（N11）。
- **测试纪律**：新测试必须 pytest 可收集；mock 回归不能替代真实 LLM 质量验证（D-027）；M1 回归为动态测评实施前硬前置（§8.1/§24）；候选人端完整 E2E 为 M5–M7 verified 必要条件。
- **评测隔离**：eval 必须使用独立/临时数据库，不污染业务库（现状 eval 直接操作 data/app.db，违约，矩阵 8.8）。

<decisions>

## Key Decisions（锁定级，SSOT 权威 = locked）

来源：`.planning/intel/decisions.md`（D-001~D-031，全部源于 SSOT）。**其权威等同 locked——任何其他来源不得自动覆盖；修改须用户授权 + SSOT §14 变更日志。** 摘录如下（全文见 intel/decisions.md）：

| ID | 决策（摘要） |
|----|--------------|
| D-001 | SSOT 文档治理：唯一 SSOT；先改 SSOT（正文+§14）再动代码 |
| D-002 | 系统范围边界：只做画像/评分/证据/异常记录/人工复核支持；**不做录用判断/排序/自动淘汰** |
| D-003 | 四条强约束：LLM 不碰数字；人工唯一权威；一切留痕；代码唯一状态机 |
| D-004 | 有界测评循环（Observation→Policy/Plan→Act→Evaluation→Persist）；LLM 永不能决定题量/追问上限/finish/难度迁移/权重/综合题数/最终分数/报告发布 |
| D-005 | 技术栈与演示上线形态：单机单实例单进程；BackgroundTasks 内存执行；mock 离线全流程 |
| D-006 | 类目权重 7:3 + gate 不占权重池（v2.0 取代旧 55/20/20/5）；Σ item.weight=1 尾差归权重最大项 |
| D-007 | tier 语义：required/preferred/plus 只影响题量配额与覆盖优先级，不乘最终分数 |
| D-008 | 题量配额公式：岗位级 N + 7:3 最大余数 + tier 0.8/0.6/1.7 公式；综合题不占 N |
| D-009 | 动态实例化 + 四层选题（合法性→硬约束 required 优先→配额→排序）；followup ≤2 为实例内子轮次；LLM 只做题面轻包装 |
| D-010 | 难度路径状态机：升/降/滞回恢复；一次实例内不升降级；跳级默认禁止；不计入普通失败清单明确 |
| D-011 | 难度与 1–5 等级映射：easy[2,3]/medium[3,4]/hard[4,5]；等级 5 仅 hard 5 级锚点；required_level 不改权重不改评分 |
| D-012 | score_live 仅导航，不进最终分；终局评分 score_final 独立逐题（P-score，temperature≈0，回捞原文） |
| D-013 | 拒答 REFUSED=0 特殊状态值：只进行为/完整度聚合，不进能力等级聚合；拒答事件永久保留 |
| D-014 | item 内合并与综合题裁决：统一 item_measurement；不按来源加权、不按题数重复乘 item.weight；冲突取低留人工标记 |
| D-015 | 缺失补算 IMPUTED：r 比例补算 + 特殊视觉标记 + 覆盖率展示；O=∅ → NO_VALID_OBSERVATION；required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED |
| D-016 | required 刚性例外：每 item 最多一次、仅 medium/hard、不使用综合题；耗尽 → REQUIRED_UNMEASURED 警告 |
| D-017 | 开考前可测量性检查：confirmed model → 题库 readiness → 配额可行 → 表单 schema → session 可创建；不通过返回明确状态 + 管理员待办 |
| D-018 | 全局 21 张表 + 三新表；模型升版必须生成/绑定新题库，否则阻止开考 |
| D-019 | 状态事件 append-only：禁止 UPDATE/DELETE，纠错走补偿事件；快照列与事件同事务；回放仅审计/恢复/测试 |
| D-020 | trace_link 统一审计链：report→session→model/version→question→message→score→trace；UNIQUE(trace_id, entity_type, entity_id, link_role) |
| D-021 | 真实 SSE + 内部 adapter + 幂等：决策非流式先落库再展示；话术流式 SSE；finish 仅代码触发；幂等作用域 session_id+endpoint+idempotency_key |
| D-022 | 计时与 ABANDONED：全场 40 分钟/单题 20 分钟；服务端权威计时区间；暂停不计入且写事件；6h 无活动 → ABANDONED 本期不可恢复 |
| D-023 | 表单生命周期与 gate：schema 代码定义+版本化+不可变快照；重复提交返回第一次结果；gate 代码计算 + 人工覆盖需二次确认；gate 只接受确认后的事实 |
| D-024 | Tools 总边界：阶段白名单 + 所有权校验 + 留痕；工具失败 → 暂停并人工接管；正式测评不做 Web Search |
| D-025 | 报告五段式与发布契约：report_status 状态机 + review_status；发布前七项一致性校验（代码）；管理员**明确点击发布**；正常 UI 主链 score→report 串行（服务端） |
| D-026 | 权限模型（P0 上线阻断项）：全部候选人资源接口资源级所有权校验（WHERE resource.user_id=current）；角色限制后端执行；越权测试矩阵为上线阻断测试 |
| D-027 | 评测契约：b 一致性（分差≤1）+ c 虚拟考生（强>中>弱）+ bad case 双分背离候选（不自动改分）+ eval 隔离 |
| D-028 | 里程碑四维口径：implemented / contract_complete / verified / production_ready |
| D-029 | M4 范围保留不做：黄金集、浏览器插件、真实 JD 数据集 |
| D-030 | Prompt 模块接口化登记：所有 LLM 位置保留可替换接口；Prompt 禁改清单（不得绕过状态机/配额/聚合公式等） |
| D-031 | 安全、公平与数据治理：输入限额按类型配置；数据分级管理 + 管理员访问审计；INJECTION_DETECTED 留痕；异议只进人工处理永不触发改分 |

</decisions>

---
*Last updated: 2026-09-02 after project initialization (ingest → PROJECT/REQUIREMENTS/ROADMAP/STATE)*
