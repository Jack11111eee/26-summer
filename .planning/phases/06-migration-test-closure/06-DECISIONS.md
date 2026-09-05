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
| 结果 | **已获用户批准（2026-09-05，[06-009]）** |

## 硬关口 A 用户裁决（§2.1 plan 审查——用户已批准）

| ID | 日期 | 决定 | 落点 |
|----|------|------|------|
| [06-009] | 2026-09-05 | 动工审批 = **批准 — 按计划执行**（5 计划 3 wave） | 开启 execute-phase |
| [06-009] | 2026-09-05 | D-76 JWT 方向 = **jwt-cookie-migrate**（迁移 HttpOnly cookie；本期仅锁方向，实际迁移为 Phase 6 外后续计划） | 06-05 Task 0 `<resolution>` |
| [06-009] | 2026-09-05 | REF-6.2 secret = **secret-failclosed-keep**（维持 main.py fail-closed-always 现状） | 06-05 Task 0/3 按推荐默认，无修订 |
| [06-009] | 2026-09-05 | 5 开放参数 = **维持占位默认**（None/[]，实施期校准） | config 占位不变 |

## verify 结果前置记录（本轮为 plan 阶段，execute/verify 待批准后进行）

后端测试现状：`test_p0_chain.py::test_completed_session_guardrail` 为既有 [04-011] 题库版本化涟漪（缺种子题），随 06-03 收口；其余 Phase 5 全绿。execute 前先 06-01 落 conftest + set_db_path，再逐 wave。

## execute-phase 执行留痕（2026-09-06）

| ID | 日期 | 步骤 | 决定 | 依据 |
|----|------|------|------|------|
| [06-010] | 2026-09-06 | post-merge test gate（auto） | 全量回归 `5 failed / 218 passed`。3 个 test_phase2_migration 回归已修复；剩余 5 个均以基线（commit 13f6743，无 conftest）核实为**既有失败**，记 deferred-items.md | 基线全量 98 failed（无 conftest DB_PATH 首导入冻结污染 + 13 文件缺双列），06-01 conftest + 06-03 补列把 98→5 |
| [06-011] | 2026-09-06 | 回归修复（auto） | test_phase2_migration 3 回归根因 = 06-01 conftest 先 import server.db 冻结 DB_PATH，使该文件模块级 `os.environ["DB_PATH"]` 失效。修复：module 级 `set_db_path(_tmp_db)` → function 级 autouse `_point_old_db` fixture（set→yield→reset None）+ 3 处 `db_module.DB_PATH` 改 `set_db_path()` | module 级 set_db_path 会泄漏全局 `_DB_PATH_OVERRIDE` 到 test_phase3_forms（实测 net +1 failure），function 级 fixture 正确隔离 |

| [06-012] | 2026-09-06 | code-review gate（auto，advisory） | 标准深度 36 文件评审：**0 critical / 5 warning / 8 info**。0 critical → 不阻塞；5 warning 依章程 §1 行 20「Critical/Warning 自动 `--fix` 修复」全部自动修复（WR-01~WR-05，见下表），8 info 搁置记档 | 章程 §1 行 20 + workflow「code review advisory 永不阻塞」 |

## 代码评审 5 warning 处置（0 critical，全部自动修复，详见 06-REVIEW.md）

依章程 §1 行 20「code-review Critical/Warning 自动 `--fix` 修复」全部修复（commit fba6f68 / 1002d2f）：

| Warning | 性质 | 修复 |
|---------|------|------|
| WR-01 db.py 备份文件名 `isoformat()` 含 `:`/`+`（Windows NTFS 崩溃）+ 新库 13 冗余备份 | Phase 6 自身新代码 | 改 `_backup_before_migration(conn)`：每次 init_db 至多备份一次（module 级 `_backup_done_for_this_init` 标志，init_db 开头复位）+ `_safe_ts()` 文件系统安全时间戳（`%Y%m%dT%H%M%S%fZ`） |
| WR-02 input_limits.py 死代码（仅自身测试 import） | 按设计（REF-6.3 占位） | `validate_jd_length` 接线到 `jds.py::_insert_jd`（None 时放行，裁决后生效）；`clamp_pagination_limit` 接线到 WR-03 |
| WR-03 eval.py list_history 未钳 limit（`limit=-1`=无限制） | Phase 6 loose end | `list_history` 首行 `limit = clamp_pagination_limit(limit)` |
| WR-04 eval 两脚本 get_conn() 不 close（长驻泄漏） | Phase 6 触及脚本 | consistency_test 2 处 + virtual_candidates 3 处 `get_conn()` 均包 try/finally close |
| WR-05 conftest import 序冻结 DB_PATH 使 ~15 文件 `os.environ` 隔离失效 | 已知既有 | test_phase4_binding + test_phase5_evidence 迁到 function 级 autouse `set_db_path` fixture（全量 5→3 failed） |

8 info 依章程 §1 行 21 搁置记档（IN-01~IN-08，不改）。

## verify 缺口闭环 + SSOT gap 符号发现（[06-013]）

verify（06-VERIFICATION.md）标 SC5-c「c 虚拟考生」仅 1/6 兑现（`assert_weakness_identified` 已定义却无调用点）。修复：把 `generate_report` 接入 c 评测链路，`test_virtual_candidates` 补 4/5 子项断言（报告状态 / 证据引用 / required 覆盖 / 缺失状态，均绿），并接线 `assert_weakness_identified` 断言短板定位。

**发现（SSOT §21 gap 符号约定与 §23「短板定位」语义张力，待用户裁决）：**

- SSOT §21（行 561）约定 `短板=gap<0`（gap=required_level−actual_level，§20.3 行 553），代码与 test_m6 均忠实实现。
- c 评测 weak 档全部 miss → `actual=1 < required=3` → `gap=+2 >0` → 现约定落入 **strengths**（优势）而非 **weaknesses**（短板）。故 `assert_weakness_identified(report, expected_weakness)` 对 weak 档恒返回「实际短板=[]」。
- 「短板」自然语义 = 木桶短板 = 低于要求（actual<required，即 gap>0），与 §21 公式相反——疑似 §21 符号反转（短板应为 `gap>0`、优势应为 `gap≤0`）。**SSOT 修改权 exclusively 属用户（章程 §3.1），本项未动 SSOT/aggregation.py/test_m6，留待用户裁决。**

| ID | 日期 | 步骤 | 决定 | 依据 |
|----|------|------|------|------|
| [06-013] | 2026-09-06 | verify gap 闭环（auto） | c 评测接入报告生成 + 补 4/5 子项断言；`assert_weakness_identified` 接线但如实报告 failure（暴露 §21 符号张力），不动 SSOT | 章程 §1 行 22（verify 发现记档）+ §3.1（SSOT 修改须授权） |

## 执行期回归修复纪要

- **第一版修复失败（module 级 set_db_path 泄漏）**：初版在 test_phase2_migration.py 模块级加 `set_db_path(_tmp_db)`，隔离跑 8 passed，但全局 `_DB_PATH_OVERRIDE` 泄漏到 `test_phase3_forms.py`（其 252-299 行用 `db_module.DB_PATH` 直改），致 `test_new_db_direct_path` 新失败，全量 9 failed。改为 function 级 autouse fixture 后全量回到 5 failed。教训：`set_db_path` 是 module 级全局，测试隔离必须用 function 级 fixture 且 teardown 复位。
