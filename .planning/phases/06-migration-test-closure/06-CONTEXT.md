# Phase 6: 迁移体系与测试闭环收口 - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning

<domain>
## Phase Boundary

把项目从「功能已重构完毕、验证未闭环」收口到 SSOT §27 的 `verified`（对 M5–M7）与 `contract_complete`（对 M1 验收）：(1) schema_version 迁移登记簿替换 DDL 字符串嗅探，迁移可在临时库重放、备份/回滚路径落地；(2) 全部后端测试统一 pytest 可收集 + CI 为正式验收入口（消除 question_bank pytest 3 errors 基线红灯）；(3) M1 回归清单（模块一 §8 八项）通过，含 mock interviewer 主观题固定 3 分的处置；(4) 候选人端完整 E2E（注册→登录→选岗→session→首题→作答/追问→表单→完成→评分→报告→异议，另测刷新恢复/断线重试/超时/越权/报告失败重试）；(5) eval 隔离（独立/临时库，不写业务库）+ b 一致性 / c 虚拟考生 / 自动 bad case 候选 + 安全收尾三项（JWT 方向 / secret 启动校验 / 输入限额按类型配置）。

对应 REQUIREMENTS.md：REF-2.1, REF-2.11, REF-5.11, REF-6.1, REF-6.2, REF-6.3, REF-7.4, REF-7.5, REF-7.6, REF-8.6, REF-8.8（11 项，支撑 REQ-data-compliance / REQ-e2e-demo-deliverables / REQ-iterative-loop / REQ-jd-parse-model 回归验收）。

**不在本阶段**：等值备用题组（REF-3.8 延后）、综合题槽位（REF-3.9 延后）、Tools 白名单（REF-4.11 延后）、黄金集 a 评测（§2.5 推迟）、公平性离线评估（D-031 保留不做）、真实 LLM 质量验证替代 mock 回归（D-027，本期仍 mock 离线）、容器化/多实例部署（D-005）。
</domain>

<decisions>
## Implementation Decisions

> D-68~D-79 为 Phase 6 编号（接续 05 的 D-67）。auto 模式（章程 §1）推荐项选取，逐条依据 = SSOT 条款/既定决策/代码现状三者之一。**标「关口包」项 = 计划审查硬关口由用户确认**（非 auto 可代决的开放参数/设计取舍）。

### 迁移登记簿（REF-2.1/REF-2.11，计划 06-01）

- **D-68: schema_version 登记簿 = `schema_version` 表 + 有序迁移注册，替换 DDL 字符串嗅探（§8.1/矩阵 2.11「替换 DDL 字符串嗅探式迁移」）。** 现状 `_migrate_*`（db.py:226-275）靠 `"'report'" in row[0]` 字符串匹配 DDL 判断是否已迁移——脆弱（CHECK 子串误判、DDL 三份重复）。改 = `schema_version(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)` + 迁移函数注册为有序列表 `[(version, name, fn), ...]`，`init_db` 收尾按 version 顺序执行「未在登记簿」的迁移并写登记；旧 `_migrate_*` 改造为注册迁移（保留幂等语义，但判断依据从「嗅探 DDL」改为「查 schema_version」）。**备份/回滚路径** = 迁移前 SQLite 备份（`.backup`/`VACUUM INTO` 到 `backups/`）+ 文档化降级脚本（§28-6「迁移/回滚/备份恢复功能需要开发，但不作为本期上线硬门槛」）。**迁移测试** = 空临时库重放全部迁移序列，断言最终 schema 与「从零建表」一致（§24 必测项「迁移」）。

### 测试统一 pytest + CI（REF-7.4，计划 06-02）

- **D-69: 脚本式测试重构为 pytest 可收集，并解掉「单进程不可导入两测试模块」的 DB_PATH 冲突（§24「统一 pytest 收集」）。** `test_question_bank.py` 的 `test_generation(pid, mid)` 带参被 pytest 误判为 fixture（3 errors）→ 改名 `check_*`（保留 `__main__` runner）或转真 pytest fixture；`test_m6_backend.py` 的 `_test_*` 仅在 `__main__` 执行 → 转 `test_*` 函数（保留 `_seed_full_chain` 种子）。**DB_PATH 冲突** = 现状各文件 import 时设 `os.environ["DB_PATH"]`（首个 import 生效、后续文件共用首文件 DB）——统一收集须改为 per-session 隔离：`conftest.py` 提供 session 级 temp DB fixture（`monkeypatch.setenv` 或把 config 的 DB_PATH 改为惰性读取），使 pytest 一次性收集全部文件而不串库。此为「统一收集」的关键使能项。

- **D-70: CI = GitHub Actions（`.github/workflows/ci.yml`），on push/PR，跑统一 pytest 收集 + `npm run build`，全绿为验收 bar。** 无 CI 现状（CONCERNS「No CI pipeline」）；gh CLI 已可用，GitHub Actions 为默认选择。验收口径 = §24「CI 为正式验收入口」：后端全 pytest 绿（含新迁移测试、M1 回归、必测补充项）+ 前端 build 通过。**CI 具体 steps / 缓存 / 触发分支 = Claude's Discretion。**

### M1 回归清单（REF-7.5/REF-8.6，计划 06-03）

- **D-71: M1 回归 = 模块一 §8 八项（清洗边界 / 抽取异常 / 消歧 / 权重尾差 Σ=1 / 冲突 stalled / confirmed 不可静默覆盖 / 版本 diff / 管理员权限）收口为专测文件，并把 [04-011] 的 13 个会话类测试文件（test_m5/m6/m7、test_p0_chain/security、phase2/phase3 等直插 question_bank 不写 model_id/model_version）补齐 model/version 使 Phase 4 消费侧收紧后全绿。** 现状 CONCERNS 已记 `_compute_weights` 尾差吸收脆弱（aggregate.py:81-98）、clean_jd/normalize_title 无直测、_gate_check 无直测——M1 回归清单逐项落 `test_m1_regression.py`（锁权重 Σ=1、清洗边界、消歧、diff、权限）。conflict stalled / confirmed 不可静默覆盖由 Phase 4 已验证，回归清单只补断言锁定。

- **D-72: mock interviewer 主观题固定 3 分处置 = 保持 mock 确定性（记档，不增强），c 虚拟考生靠客观题 answer_key 命中区分强弱，b 一致性 mock 方差=0 记档「mock 只做工程回归」。** 现状 `_mock_score` 恒返 3（scoring.py:27），`test_m6_backend.py` 的数值断言（total_score=31.4、Python=15.2）依赖该恒值——增强 mock 会大面积破坏既有断言。REF-8.6「测试重构时处理」= 测试重构（06-02）时**记档**该局限：b 一致性在 mock 下方差恒 0（无意义但通过），c 虚拟考生靠客观题（hit=5/miss=1）实现 strong>medium>weak；真实一致性/强弱区分需 real LLM（D-027「mock 回归不能替代真实 LLM 质量验证」，本期不做）。**不增强主观 mock、不虚构可变分数。**

### 候选人端完整 E2E（REF-7.6，计划 06-04）

- **D-73: E2E 形态 = API/service 层脚本化全链（无 Playwright 新依赖）+ 前端契约修复使主链在 UI 真实可走通（§3「候选人端完整 E2E 为 M5–M7 verified 必要条件」）。** E2E 覆盖清单照 SSOT §3 与模块四 §3：注册→登录→选岗→session→首题→作答/追问→表单→完成→评分→报告→异议，另测刷新恢复（get_session 返回 messages——修复 CONCERNS 记的 Chat.vue 契约漂移）、断线重试（幂等，Phase 3 已测）、超时（计时，Phase 3 已测）、越权（越权矩阵，Phase 1 已测）、报告失败重试。**理由**：D-005 本地演示、前端零测试为已承认范围；Playwright 引入浏览器自动化重依赖与基建，超出课程项目收益；上述「刷新恢复/断线/超时/越权」均为 API 层行为可脚本化。**前端契约修复（本计划必做）** = `get_session` 补 `position_name` + `messages`（CONCERNS Chat.vue 漂移）、FormCard 表单流程接线（gate 评测前置，CONCERNS 记端点不存在）、报告失败重试 UI。**E2E 自动化载体 = 脚本式（沿用 eval harness 模式）或 pytest+TestClient 全链测试文件，planner 定。**

### eval 隔离 + b/c 评测 + bad case（REF-5.11/REF-8.8，计划 06-05）

- **D-74: eval 隔离 = eval 入口支持 DB_PATH 覆盖（临时/独立库），不写业务库 `data/app.db`（§23「eval 必须使用独立/临时数据库」+ §2.4 数据隔离——当前虚拟考生直接写业务库为必改项）。** 现状 `eval/consistency_test.py`、`eval/virtual_candidates.py` 直接 `get_conn()` 读 `data/app.db`。改 = eval 运行前把目标会话/岗位数据拷贝（或重建种子）到 temp DB，`DB_PATH` 指向 temp 后跑评测，结果写 `eval_results`；`runs` 参数加边界校验（§2.4）。admin eval 触发端点（`server/api/admin/eval.py` BackgroundTasks）在任务内建 temp DB 再 import/跑 eval 函数。

- **D-75: 自动 bad case 候选 = 双分背离检测落 `bad_case_candidate` + 管理员审核不自动改分（§2.3「当前完全未实现，设计有、代码无」）。** 触发条件照 §2.3：`score_live` 与 `score_final` 可比 且 `|live − final| ≥ 阈值` → 建候选（**排除**：题目无效 / 模型不确定 / 系统错误 / 状态不可比）；管理员审核确认，**永不自动改分**（D-031）。落点：评分/报告生成时计算背离、插入候选行 + admin 列表呈现（TestCenter）；**阈值 = §2.3「配置阈值」开放参数 → 关口包呈报**。`bad_case_candidate` 表结构（新表 vs 复用 feedback/eval_results 标记列）= Claude's Discretion。

### 安全收尾三项（REF-6.1/REF-6.2/REF-6.3，计划 06-05）

- **D-76（关口包）: JWT 认证方向 = HttpOnly cookie vs 保持 Bearer。** SSOT §6「JWT HttpOnly cookie 方向（现 Bearer；SSOT 标'方向'，实施期决定，非 P0）」。**auto 推荐：迁移到 HttpOnly cookie**（登录返回 `Set-Cookie HttpOnly + SameSite=Lax`，前端 `credentials:'include'` 去 Authorization 头，后端从 cookie 读 token）——对齐 SSOT 明确方向、消除 XSS 窃 token 面、Phase 6 是唯一收口时机；代价 = 测试 auth 辅助（Bearer→cookie）+ 前端 api 层全量改造 + CSRF 考量（单源本地演示 SameSite=Lax 已缓解）。**因安全面 + 前端/测试大面积 churn，此为设计取舍 → 计划审查硬关口由用户确认**（备选：保持 Bearer 记档「方向已登记、本期不迁移」，理由 = 非 P0 + Vue 转义收敛 XSS + cookie 迁移 churn 远超收益）。

- **D-77: 生产 secret 启动校验（REF-6.2）= `JWT_SECRET == "change-me-in-.env"` 且 `LLM_PROVIDER != "mock"` 时启动拒绝（或 loud warning），mock 模式放行默认值但告警。** 现状 config.py:16 默认已知常量，任何人可伪造 admin token（CONCERNS Security「JWT secret defaults to a known constant」）。改 = main.py 启动时校验：真实 provider 下默认 secret → 拒绝启动（fail fast）；mock 下 → 打印 warning。生成随机 secret 并持久化属可选增强，本期只做校验（最简）。

- **D-78: 输入限额按类型配置（REF-6.3）= config.py 集中定义限额常量 + 接口层校验（JD 长度 / 文件行数 / 回答长度 / prompt max_tokens / 分页 limit）。** 方向 = 「按类型配置」明确；**各类型具体数值 = 开放参数 → 关口包呈报**（不臆造默认值）。校验落点（Pydantic 字段 vs 路由层手动）= Claude's Discretion。

### 前端遗留收口范围（范围决策，计划 06-04 侧带）

- **D-79: Phase 6 E2E 范围内的前端修复 = 主链完整性必做项，polish 延后。** **必做**（阻塞 E2E 主链）：Chat.vue 会话渲染契约（position_name/messages，刷新恢复）、FormCard 表单流程接线（gate 评测前置）、missing_reasons score_state 码→中文映射（Phase 5 遗留）、报告失败重试 UI（报告失败可见性前端）。**延后**（polish，不阻塞验收）：报告版本历史/对比 UI（VersionHistory.vue 已存在）、admin 发布/复核完整 UI（Phase 5 已最小化落库 + 发布按钮，完整化属打磨）。**05-HUMAN-UAT.md 2 项**（IMPUTED 徽标/覆盖率视觉 + 管理员发布流程）→ 并入 E2E 人工目验清单收口，不单独排计划。

### 开放参数（SSOT §31 类，关口包呈报项——不 auto 代决数值）

> §31 六项中已裁决：§31-1 N=10（[02-007]）、§31-2 MAX_CONTEXT_TOKENS=8000 + REFINE_MIN_TOKENS=500（[03-007]）、§31-3 补算阈值=0.2（Phase 5 关口 A）。**Phase 6 待呈报：**

1. **§31-4 词典候选 top10 匹配阈值 + 清洗标题词表**（模块一 M1 回归域）；
2. **§31-5 trace 保留期/脱敏细节 + LLM 供应商数据约束**（数据治理，Phase 5 deferred）；
3. **§31-6 幂等清理阈值与策略**（idempotency_record 清理）；
4. **REF-5.11 bad case 双分背离阈值**（§2.3「配置阈值」）；
5. **REF-6.3 输入限额按类型的具体数值**。

plan 落 config 占位 + 常量注释「实施期校准」，数值不代决；若用户不裁决则维持 plan 占位默认。

### Claude's Discretion

- schema_version 迁移注册的具体机制（有序函数列表 vs SQL 文件）
- 测试统一收集的 DB_PATH 冲突解法（conftest fixture vs config 惰性读取）
- CI workflow 的 steps / 缓存 / 触发分支
- M1 回归测试文件组织（`test_m1_regression.py` vs 分文件）
- eval 隔离的 DB 拷贝/种子重建机制
- `bad_case_candidate` 表结构（新表 vs 复用标记列）
- JWT cookie 迁移的 CSRF 具体机制（若关口采纳）
- 输入限额校验落点（Pydantic vs 路由层）
- 测试组织（沿用单文件单进程 + tempfile + mock 三件套纪律，但统一收集后走 conftest）

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 设计权威（SSOT）
- `design/final-design/总设计文档.md` §23 — 评测（eval 必须独立/临时库、mock 回归≠真实 LLM 验证、b+c 评测）
- `design/final-design/总设计文档.md` §24 — 测试与验收要求（统一 pytest 收集 / CI 正式验收入口 / 越权矩阵 / 必测项：幂等·并发·计时·迁移·SSE / prototype 不作验收依据）
- `design/final-design/总设计文档.md` §27 — 四维口径（implemented/contract_complete/verified/production_ready）
- `design/final-design/总设计文档.md` §28 — 六步实施顺序第 6 步（迁移体系 schema_version+备份+回滚+迁移测试；测试重构与 CI；M1 回归；E2E；eval 隔离）
- `design/final-design/总设计文档.md` §31 — 开放问题（§31-4 词典阈值/清洗词表、§31-5 trace 保留期/脱敏、§31-6 幂等清理阈值）
- `design/final-design/总设计文档.md` §8.1 — 工序实现约束（迁移/回滚/备份恢复需开发但不作上线硬门槛）
- `design/final-design/总设计文档.md` §13.4 — 幂等三键作用域（§31-6 清理策略的载体）
- `design/final-design/总设计文档.md` §26 + 附录 A — Prompt 清单（P-* 登记；bad case 聚类摘要/复核辅助摘要可选——本期不做）
- `design/final-design/模块四设计-测试闭环.md` — 模块四分块摘录：§2.3 自动 bad case 候选伪码、§2.4 数据隔离、§3 测试与验收（E2E 全链 + 刷新恢复/断线重试/超时/越权/报告失败重试）、§6 重构注意（bad case 完全未实现 / eval 隔离）

### 证据基线
- `research/ssot-code-gap-matrix.md` — 68 行契约核对（Phase 6 相关：矩阵 §2 的 2.1/2.11、§5 的 5.11、§6 的 6.1/6.2/6.3、§7 的 7.4/7.5/7.6、§8 的 8.6/8.8）
- `.planning/intel/decisions.md` D-027（评测契约 b 分差≤1 / c 强>中>弱 / bad case 不自动改分 / eval 隔离）、D-031（数据治理 / 输入限额 / 异议只进人工）、D-005（本地演示、单实例）、D-029（黄金集/插件/真实 JD 保留不做）、D-018（模型升版须重建题库）
- `.planning/phases/05-evidence-report-contract/05-CONTEXT.md` — Phase 5 已决（D-67 REVIEW_* 事件；deferred：trace 保留期 §31-5、bad case §REF-5.11、admin 发布完整 UI、报告版本对比 UI）
- `.planning/phases/04-question-bank-version/04-CONTEXT.md` — Phase 4 已决（D-54 rubric_version "v1"；deferred：schema_version 收口、M1 回归清单）
- `.planning/phases/03-sse/03-CONTEXT.md` — Phase 3 已决（D-46 存量端点 Pydantic 化延后 Phase 6；幂等/计时/SSE 已落地——E2E 覆盖而非重做）

### 代码现状（改造对象）
- `server/db.py` — `_migrate_*`（226-275 DDL 字符串嗅探——D-68 替换对象）、`get_conn()`（无 busy_timeout/close——CONCERNS 记）
- `server/test_question_bank.py` / `server/test_m6_backend.py` — 脚本式不可 pytest 收集（D-69 重构对象）
- `server/test_m5_backend.py` / `server/test_m7_backend.py` — pytest 参考范式（temp DB + mock + TestClient）
- `server/config.py` — JWT_SECRET 默认 `change-me-in-.env`（D-77）、LLM_PROVIDER 默认 mock、限额常量落点（D-78）
- `eval/consistency_test.py` / `eval/virtual_candidates.py` — 直接 get_conn() 读业务库（D-74 eval 隔离对象）
- `server/api/admin/eval.py` — eval 触发端点（BackgroundTasks + eval_results，隔离改造点）
- `server/services/scoring.py` — `_mock_score` 恒 3（D-72 记档）、双分 score_live/score_final（D-75 bad case 检测源）
- `server/services/aggregate.py` — `_compute_weights` 尾差吸收（M1 回归锁定）、`_gate_check`（M1 回归锁定）
- `server/api/assessment.py` — `get_session` 不返回 position_name/messages（D-79 Chat.vue 契约修复）
- `web/src/views/assessment/Chat.vue` / `web/src/components/FormCard.vue` — 前端契约漂移（D-79 修复对象）
- `.planning/codebase/TESTING.md` / `CONCERNS.md` — 测试纪律 / 已知债务（13 会话测试 model/version、eval 只 mock 有意义、无 CI）

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `eval/assertions.py` — `assert_score_consistency(max_variance=1)` / `assert_tier_ordering` / `assert_weakness_identified` 断言谓词，b/c 评测既有载体（隔离后复用）
- `eval_results` 表 + `server/api/admin/eval.py` BackgroundTasks — eval 触发/结果轮询既有链路（隔离改造点）
- `test_m5_backend.py` — pytest + TestClient + temp DB + mock 三件套范式（D-69 统一收集的参考模板）
- `_seed_full_chain()`（test_m6）— 全链种子，E2E 脚本化可复用
- `_q()` 只读查询 helper（test_m5）— 避免持锁，E2E/回归测试沿用
- `idempotency_record` 表 + `services/idempotency.py` — 断线重试/幂等已落地（E2E 覆盖，非重做）
- `state_events` / `append_event` — 状态事件留痕（E2E 越权/权限矩阵断言可复用）

### Established Patterns
- raw SQL + get_conn() per-call + 显式 commit；DDL 迁移幂等嗅探（D-68 要替换掉的对象）
- 「同一进程不得导入两测试模块（DB_PATH import 时冲突）」——D-69 统一收集须以 conftest/lazy-config 解掉
- mock 三件套纪律（temp DB + LLM_PROVIDER=mock + JWT_SECRET=test-secret）——统一收集后走 conftest 收敛
- eval harness 位于 `eval/` 仓库根（可迁移、与岗位/模型解耦）——D-74 隔离保持该定位

### Integration Points
- `server/db.py init_db` 收尾 — schema_version 登记簿 + 迁移注册落点（D-68）
- `server/config.py` — JWT 校验（D-77）+ 限额常量（D-78）+ DB_PATH 惰性读取（D-69 使能）
- `server/api/assessment.py get_session` — 补 position_name/messages（D-79）
- `eval/*.py` + `server/api/admin/eval.py` — DB_PATH 覆盖 + temp DB 种子（D-74）
- `server/services/scoring.py` / `server/services/report.py` — 双分背离检测落点（D-75）
- `.github/workflows/ci.yml` — 新建（D-70）
- `server/test_m1_regression.py` 等 — 新建（D-71）

</code_context>

<specifics>
## Specific Ideas

- **越权权限矩阵为上线阻断测试**（§24/§3）——Phase 1 已测 candidate↔candidate + admin 边界，Phase 6 E2E 只做覆盖性复测，不重写。
- **bad case 背离「可比」判定**：score_live 属过程值（§2.1「不在断言范围」），bad case 背离只在「live 与 final 可比」时触发（同一 item、非 REFUSED/INVALIDATED/系统错误），排除项照 §2.3 四类。
- **M1 回归的权重尾差**：生成器 Σ=1 精确 vs 编辑器 ±0.005 容差（CONCERNS），回归断言须锁定两者口径不混用。
- **E2E「报告失败重试」** = 后台生成失败（FAILED 态，Phase 5 D-65 已落）→ 重新触发生成，断言不重复计分、版本递增——E2E 覆盖而非新机制。
- **刷新恢复** = `get_session` 返回 messages 后，Chat.vue 重载能恢复历史对话（CONCERNS 契约漂移修复的直接验收点）。
- **mock 确定性**：b 一致性在 mock 下方差恒 0（无 LLM 非确定性），该测试仅在 real LLM 下有意义——记档为已知局限，不伪装通过。
- **prototype 不作验收依据**（§24）——E2E 只对 web/ + server/ 真实链路，不对 `prototype/` 静态原型断言。

</specifics>

<deferred>
## Deferred Ideas

- 等值备用题组 equivalence_group_id（REF-3.8——登记不排期）
- 综合题槽位（REF-3.9——Prompt 待讨论 D-030）
- Tools 白名单（REF-4.11——本期无工具调用）
- 黄金集 a 评测（§2.5——真实数据收集后另行排期）
- 真实 LLM 质量验证（D-027——mock 回归不能替代，本期仍 mock 离线）
- 公平性离线评估（D-031——仅留记录）
- 报告版本历史/对比 UI（VersionHistory.vue 已存在，polish 延后）
- admin 发布/复核完整 UI（Phase 5 最小化已落库，完整化 polish 延后）
- 进程重启后 BackgroundTasks 恢复 / 持久化 job 表（§28「不作为本期上线硬门槛」）
- trace 保留期/脱敏的完整合规方案（§31-5 数值在关口包呈报，落地策略随裁决）
- 随机 secret 生成并持久化（D-77 只做校验，生成属可选增强）

</deferred>

---

*Phase: 6-迁移体系与测试闭环收口*
*Context gathered: 2026-09-05*
