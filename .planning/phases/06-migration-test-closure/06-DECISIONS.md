# 06-DECISIONS.md — Phase 6 决策留痕

## 代确认记录（章程 §1/§4：auto 模式，事后留痕）

每条 = 日期时间 / 所在步骤 / 决定内容 / 依据。

| ID | 日期 | 步骤 | 决定 | 依据 |
|----|------|------|------|------|
| [06-001] | 2026-09-05 | plan-phase（auto） | 研究先行（spawn gsd-phase-researcher，产出 06-RESEARCH.md）；非 --skip-research | 章程 §1「自动续跑」+ 全 5 个前驱 phase 均有 RESEARCH.md 的既定惯例 + research_enabled=true |
| [06-002] | 2026-09-05 | plan-phase（auto） | 运行 gsd-pattern-mapper（06-PATTERNS.md，27 文件 26 analogs）；.github/workflows/ci.yml 唯一无 analog | workflow.pattern_mapper=true + 前驱惯例 |
| [06-003] | 2026-09-05 | plan-phase（auto） | 产出 5 计划 3 wave：06-01（w1，conftest+set_db_path linchpin）→ 06-02/04/05（w2 并行）→ 06-03（w3，依赖 06-01+02+05） | ROADMAP 5 计划标题 + RESEARCH「conftest 先序解锁三计划」 |
| [06-004] | 2026-09-05 | plan-checker round 1（auto） | 0 blocker / 7 warning / 2 info → 触发 revision 迭代 1/3 | 章程 §1「plan-checker 代确认，warning 修正不硬停」 |
| [06-005] | 2026-09-05 | revision 迭代 1（auto） | 修 W1（范围排除注记补 5 文件）、W2（verify 改 INSERT 列清单断言）、W3（06-03 depends_on 加 06-05）、W4（06-05 Task 3 标条件默认）、W5（eval 隔离断言 status=completed）、W6（RESEARCH Open Questions 标注 ROUTED）、W7（规模注记）+ I1（Task 0 补后续后果） | checker 结构化 issues |
| [06-006] | 2026-09-05 | plan-checker round 2（auto） | 0 blocker / 3 doc-only warning / 1 info：W-1（第 6 排除文件 test_phase2_selection.py 补名+修正 rationale）、W-2（VALIDATION wave 列对齐）、I-1（ROADMAP wave3 注记补 06-05）→ 均一线 doc 精度修正，orchestrator 直接 Edit（不重跑 planner） | checker「non-blocking、worth one-line touch-up」 |
| [06-007] | 2026-09-05 | requirements/decision 覆盖关口（auto） | 11/11 REF 全落；decision-coverage 返回 skipped（handler 未识别 D-NN token，格式怪，非缺口）；补 REQ 显式 traceability（4 REQ token 落入 06-02/03/04/05 requirements 字段） | §13/§13a + gap-analysis 误报 REQ 级「未覆盖」为跨 phase 全局扫 |

## 开放参数（SSOT §31 类 + 契约类，关口包呈报——不 auto 代决数值）

plan 落 config 占位（`None`/`[]` + 注释「实施期校准 — 待用户裁决」），禁止臆造默认值：

| 开放参数 | 落点 | 占位 |
|----------|------|------|
| §31-4 词典匹配阈值 + 清洗词表 | 06-03 Task 2 | `DICT_MATCH_THRESHOLD=None` / `TITLE_CLEAN_WORDS=[]` |
| §31-5 trace 保留期/脱敏 | 06-05 Task 3 | 占位 |
| §31-6 幂等清理阈值 | 06-05 Task 3 | 占位 |
| REF-5.11 bad case 双分背离阈值 | 06-05 Task 2 | `BAD_CASE_DIVERGENCE_THRESHOLD=None` |
| REF-6.3 各类型输入限额数值 | 06-05 Task 3 | 占位 |

## 硬关口决策（06-05 Task 0，`checkpoint:decision`，`autonomous:false`）

两处均标「待计划审查硬关口用户确认」，给推荐默认值，不自动裁决：

| 决策 | 推荐默认 | 备选 | 影响面 |
|------|----------|------|--------|
| D-76 JWT HttpOnly cookie 方向 | `jwt-cookie-migrate`（对齐 SSOT 方向、XSS 安全） | `bearer-keep`（churn 小） | 若 migrate：触及 auth.py/security.py/sse.js/index.js 四处，列为 Phase 6 外后续计划（REF-6.1 为「方向/实施期决定，非 P0」） |
| REF-6.2 secret 严格度 | `secret-failclosed-keep`（main.py:59-67 已 fail-closed-always，严于 D-77） | `secret-warn-mock`（D-77 原提议） | 若 warn-mock：06-05 Task 3 需修订 |

## 边界/观察（非代确认，记档）

- **REF-2.1「21 张表」与代码 `_DDL` 实际 24 张 CREATE TABLE 不符**：06-01 迁移测试用动态 `re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _DDL)` 做 parity 断言，不硬编码表数；06-05 追加 bad_case_candidate 表。SSOT 如需改「21→24」须另行授权（§3.1 SSOT 权威）。
- **test_m6 数值口径 stale 已修正**：CONTEXT/TESTING 引 `31.4`/`15.2`，实际 test_m6_backend.py 断言 `9.5`/`24.5`；D-72 保持 mock=3 确定性不动数值。
- **前端契约唯一目标**：`web/src/api/index.js`（无 server/api/index.js）；`GET /api/assessment/forms/{id}` 已存在，真实缺口是 `POST /forms/submit` 旧调用 → `submit-v2`。
- **pytest 缺 requirements.txt**（已装 9.1.1 但未登记）→ 06-02 补 `pytest>=8`，否则 CI 绿条本地不可复现。

## 带入本 phase 的遗留项（上一 phase 非阻断遗留 + 全局 deferred）

| 项 | 来源 | 处置计划 |
|----|------|----------|
| 前端人工目验 2 条（IMPUTED 徽标/覆盖率 + 管理员发布流） | 05-HUMAN-UAT.md | 维持人工目验，不阻塞（06-VALIDATION 手册项） |
| 缺失原因 reason score_state 码未做中文映射 | 05-05-SUMMARY 遗留 | 06-04 前端契约修复（missing_reasons 中文映射） |
| 13 个会话类测试文件 model_id/model_version 直插缺失 | [04-011] | 06-03 Task 3 批量补齐 |
| code-review 6 warning（WR-01~06）候选清单 | [04-016] | 按需处置（06-03/06-05 触及 config/db/report 时） |

## plan 审查硬关口停车（§2.1 唯一例行硬关口——等用户批准，未批准不动工）

| 项 | 内容 |
|----|------|
| ID | [06-008] |
| 步骤 | plan 审查（硬关口） |
| 产出 | 5 计划（06-01~06-05，3 wave）+ 灰区默认 + 5 开放参数 + 2 硬关口决策 + 遗留项处置 |
| 结果 | **停车等用户批准** |

## verify 结果前置记录（本轮为 plan 阶段，execute/verify 待批准后进行）

后端测试现状：`test_p0_chain.py::test_completed_session_guardrail` 为既有 [04-011] 题库版本化涟漪（缺种子题），随 06-03 收口；其余 Phase 5 全绿。execute 前先 06-01 落 conftest + set_db_path，再逐 wave。
