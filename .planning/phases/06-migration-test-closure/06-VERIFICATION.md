---
phase: 06-migration-test-closure
verified: 2026-09-06T02:10:00Z
reverified: 2026-09-06T10:30:00Z
status: verified
score: 8/8 must-haves verified
overrides_applied: 0
gaps: []
reverification_note: "初验 SC5-c gaps 已闭合：commit d5f377f 将报告生成纳入 test_virtual_candidates（六子项 checks：ordering/weakness/report_status/evidence/required_coverage/missing_state），2026-09-06 复验于隔离临时库全 PASS（strong 120 > medium 80 > weak 0、短板命中技能0、报告 READY、证据引用非空）。"
---

# Phase 6: 迁移体系与测试闭环收口 — Verification Report

**Phase Goal:** schema_version 迁移登记簿收口全部演进；测试统一 pytest 收集 + CI 为验收入口；M1 回归、候选人 E2E、评测契约（b/c + bad case + eval 隔离）全部兑现——项目达到「端到端可演示 + 全链可审计」验收态
**Verified:** 2026-09-06T02:10:00Z
**Status:** verified（复验后；初验 7/8，SC5-c partial 已闭合）
**Re-verification:** Yes — 2026-09-06（SC5-c 六子项全 PASS，见 frontmatter reverification_note）

## Goal Achievement

### Observable Truths

| #   | Truth (roadmap SC) | Status     | Evidence |
| --- | ------------------ | ---------- | -------- |
| 1   | SC1: schema_version 迁移登记簿 + 13 迁移有序注册 + 备份/回滚 + 迁移测试通过 | ✓ VERIFIED | `server/db.py` `MIGRATIONS` 13 项、`_SCHEMA_VERSION_DDL`、`_backup_before_migration`、`set_db_path`/`_resolve_db_path`、`init_db` 登记簿循环；`test_migration.py` 3 测试绿（fresh-replay parity 动态 `re.findall` 提取表集 / 幂等 / 旧库迁移） |
| 2   | SC2: 全部后端测试 pytest 统一收集（脚本式重构）+ CI 为验收入口（question_bank 3 errors 消除） | ✓ VERIFIED | `pytest --collect-only` → 223 tests collected，无 fixture 误判；`test_question_bank.py` 带参改 `check_*`、`test_m6_backend.py` `_test_*`→`test_*`；`requirements.txt` 含 `pytest>=8`；`.github/workflows/ci.yml` 存在（backend pytest + frontend build 两 job） |
| 3   | SC3: M1 回归清单八项通过 | ✓ VERIFIED | `test_m1_regression.py` 8 条 `test_*` 全绿；mock=3 局限以模块 docstring 记档（`_mock_score` 未改） |
| 4   | SC4: 候选人端完整 E2E + 四场景（刷新/断线/越权/超时） | ✓ VERIFIED | `test_e2e_full_chain.py` 5 条绿（主链 + 刷新恢复 + 断线重试幂等 + 越权 404/403 + 超时封存）；`get_session` 补 `position_name`+`messages`；`FormCard` submit-v2 + `Report.vue` missing_reasons 中文映射 |
| 5a  | SC5-b: b 一致性（固定 transcript 复跑 score_final 分差 ≤1） | ✓ VERIFIED | `eval/consistency_test.py` + `assert_score_consistency(max_variance=1)`，隔离临时库 `_run_isolated` 运行 |
| 5b  | SC5-c: c 虚拟考生（强>中>弱 + 短板定位 + required 覆盖 + 拒答/缺失 + 证据引用 + 报告状态） | ✓ VERIFIED（复验） | `eval/virtual_candidates.py` `test_virtual_candidates` 六子项 checks 全绿：ordering（120>80>0）/ weakness（assert_weakness_identified 命中被测客观题）/ report_status（READY）/ evidence（question_reviews evidence_quote 非空）/ required_coverage / missing_state——2026-09-06 隔离库复验 PASS |
| 5c  | SC5-bad case: 双分背离自动候选（管理员审核不自动改分） | ✓ VERIFIED | `bad_case_candidate` 表 + `_detect_bad_case_divergence`（只 INSERT、永不 UPDATE score）+ `test_bad_case.py` 2 条绿 |
| 5d  | SC5-eval 隔离: eval 独立/临时库不污染业务库 | ✓ VERIFIED | `set_db_path` + `_run_isolated`（业务库快照→临时库→复位）+ admin `_run` 隔离 + `test_eval_isolation.py` 绿（session 行数不变 + eval_results 增 + status='completed'） |

**Score:** 8/8 truths verified（SC5-c 初验 partial，commit d5f377f 闭合后复验全绿）

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| REF-2.1 | 06-01 | 全局表对齐收口清点 | ✓ SATISFIED | `test_fresh_replay` parity 动态提取（SSOT「21 表」vs 代码实测 24 表差异已在 06-01 SUMMARY 标记待用户裁决，非代码缺陷） |
| REF-2.11 | 06-01 | schema_version 迁移体系 | ✓ SATISFIED | `MIGRATIONS` 13 项 + `init_db` 登记簿循环 + `test_migration.py` |
| REF-5.11 | 06-05 | bad case 双分背离自动候选 | ✓ SATISFIED | `_detect_bad_case_divergence` + `bad_case_candidate` + `test_bad_case.py`（阈值 None 占位，D-031 永不改分） |
| REF-6.1 | 06-05 | JWT HttpOnly cookie 方向 | ✓ SATISFIED | 硬关口 [06-009] 锁定方向 = jwt-cookie-migrate，本期仅锁方向（迁移为 Phase 6 外后续计划，plan 明示零改 security/auth/sse/index.js） |
| REF-6.2 | 06-05 | 生产 secret 启动校验 | ✓ SATISFIED | `main.py` fail-closed-always + `test_secret_gate.py` 3 条绿 |
| REF-6.3 | 06-05 | 输入限额按类型配置 | ✓ SATISFIED (占位) | config 6 占位常量 + `input_limits.py` + `test_input_limits.py`；WR-02 已记「接线待用户裁决后」 |
| REF-7.4 | 06-02 | pytest 统一收集 + CI | ✓ SATISFIED | 收集 223 tests 无 fixture 错 + ci.yml |
| REF-7.5 | 06-03 | M1 回归清单 | ✓ SATISFIED | `test_m1_regression.py` 8 条绿 |
| REF-7.6 | 06-04 | 候选人端完整 E2E | ✓ SATISFIED | `test_e2e_full_chain.py` 5 条绿 |
| REF-8.6 | 06-03 | mock interviewer 固定 3 分处置 | ✓ SATISFIED | docstring 记档，`_mock_score` 未改 |
| REF-8.8 | 06-05 | eval 脚本独立/临时库改造 | ✓ SATISFIED | `set_db_path` + `_run_isolated` + `test_eval_isolation.py` |

REQ 映射：REQ-data-compliance（REF-6.1/6.2/6.3）✓ · REQ-e2e-demo-deliverables（REF-7.4/7.6）✓ · REQ-jd-parse-model（M1 回归）✓ · REQ-iterative-loop（b/bad case/eval 隔离/c 虚拟考生）✓（c 部分初验 partial、复验闭合）。

Orphaned requirements：无（11 个 REF 全部被 5 个 PLAN frontmatter 声明覆盖，与 REQUIREMENTS.md Phase 6 分组一致）。

## Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/db.py` | schema_version + MIGRATIONS + 备份 + set_db_path + bad_case_candidate | ✓ VERIFIED | 全部落地，`init_db` 登记簿循环完整 |
| `server/conftest.py` | mock 三件套 + session 临时库 fixture | ✓ VERIFIED | 3×`setdefault` + `_session_db` + `conn` |
| `server/test_migration.py` | 3 断言 | ✓ VERIFIED | 3 passed |
| `server/test_m1_regression.py` | M1 八项 | ✓ VERIFIED | 8 passed |
| `server/test_e2e_full_chain.py` | 主链 + 四场景 | ✓ VERIFIED | 5 passed |
| `server/test_bad_case.py` / `test_secret_gate.py` / `test_input_limits.py` / `test_eval_isolation.py` | 评测/安全收尾测试 | ✓ VERIFIED | 2+3+4+1 passed |
| `.github/workflows/ci.yml` | CI backend pytest + frontend build | ✓ VERIFIED | 两 job 并行 |
| `server/requirements.txt` | pytest>=8 | ✓ VERIFIED | 存在 |
| `eval/virtual_candidates.py` | c 虚拟考生完整契约 | ⚠️ PARTIAL | 仅 strong>medium>weak，缺 5 子项（见 gaps） |

## Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `db.py init_db` | MIGRATIONS 循环 | 查 applied → 备份 → fn → INSERT schema_version | ✓ WIRED |
| `db.py get_conn/init_db` | `_DB_PATH_OVERRIDE` | `_resolve_db_path()` | ✓ WIRED |
| `conftest.py` | config 三件套 | import 前 `os.environ.setdefault` | ✓ WIRED |
| `eval/*.py` / admin `_run` | `set_db_path` 隔离 | `_run_isolated` 快照→set→reset | ✓ WIRED |
| `report.py generate_report` | `_detect_bad_case_divergence` | 聚合后调用 | ✓ WIRED |
| `assessment.py get_session` | `assessment_message`/`position` | JOIN 补 messages+position_name | ✓ WIRED |
| `FormCard.vue onSubmit` | `submitForm` submit-v2 | form_instance_id + payload | ✓ WIRED |

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `test_migration.py test_fresh_replay` | schema_version rows / table set | `init_db` → `_DDL` | 真实（动态 `re.findall` 提取 24 表） | ✓ FLOWING |
| `test_e2e_full_chain.py` | messages / report | `get_session` JOIN + `request_report` | 真实（断言 messages 非空 + coverage 非空 + total_score） | ✓ FLOWING |
| `test_bad_case.py` | bad_case_candidate rows | `_detect_bad_case_divergence` monkeypatch 阈值 | 真实（score_live=5/score_final=1 → 建候选） | ✓ FLOWING |
| `eval/virtual_candidates.py` | tier scores | `score_session` + `aggregate_session_scores` | 真实（客观题命中拉开三档） | ✓ FLOWING（仅排序，缺报告下游） |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase 6 交付测试全绿 | `python -m pytest test_migration.py test_m1_regression.py test_e2e_full_chain.py test_bad_case.py test_secret_gate.py test_input_limits.py test_eval_isolation.py -q` | 26 passed | ✓ PASS |
| 全量收集干净 | `python -m pytest --collect-only -q` | 223 tests collected，无 fixture error | ✓ PASS |
| 全量回归 | `python -m pytest -q` | 5 failed / 218 passed（5 个均为基线 13f6743 既有失败，见下） | ✓ PASS（除已记 5 项预存） |

全量回归 5 个失败 = `test_p0_chain::test_completed_session_guardrail`、`test_phase2_weights::test_aggregation_no_double_scaling`、`test_phase3_timer::test_phase_column_defaults`、`test_phase4_binding::test_generate_writes_binding_columns`、`test_phase5_evidence::test_ref_id_import_migration`。全部已在 `deferred-items.md` 记档为对基线 commit 13f6743 的**既有失败**（非 Phase 6 回归），按任务指示不列为 gap。

## Anti-Patterns Found

Code review（06-REVIEW.md）0 critical / 5 warning / 8 info，无 TBD/FIXME/XXX debt 标记。5 个 warning 均 defer（非阻断）：

| File | Issue | Severity |
| ---- | ----- | -------- |
| `server/db.py:915-927` | 备份文件名含 `:`/`+`（Windows NTFS 崩溃）+ 新库 13 冗余备份 | ⚠️ Warning |
| `server/services/input_limits.py` | 两个限额函数仅测试 import（死代码，待用户裁决后接线） | ⚠️ Warning |
| `server/api/admin/eval.py:118-127` | `list_history` 未钳 limit（`limit=-1` 无限制） | ⚠️ Warning |
| `eval/*.py` | `get_conn()` 不 close（长驻进程连接泄漏） | ⚠️ Warning |
| `server/conftest.py` import 序 | 冻结 DB_PATH 使 ~15 文件 `os.environ` 隔离失效 | ⚠️ Warning |

## Human Verification Required

（以下为 Phase 5 遗留 + 前端文案目验项，已由 06-VALIDATION 手册项持久化，不阻塞；因已有 BLOCKER 缺口，status 为 gaps_found，优先级由 Step 9 决策树决定）

1. **前端 IMPUTED 徽标 / 覆盖率视觉** — 报告页目验（05-HUMAN-UAT.md 持久化）
2. **管理员发布流** — 管理员登录→点发布
3. **missing_reasons 中文映射文案** — 报告页目验 reason 中文串

## Gaps Summary

Phase 6 的 5 个 roadmap Success Criteria 中，SC1（迁移）、SC2（pytest+CI）、SC3（M1 回归）、SC4（E2E）全部兑现；SC5（评测契约）的 b 一致性、bad case、eval 隔离三个子项兑现，但 **c 虚拟考生只兑现 1/6**：`eval/virtual_candidates.py` 仅断言 `strong>medium>weak` 总分排序，未断言 SSOT §23 / ROADMAP SC 5 明确要求的短板定位、required 覆盖、拒答/缺失状态、证据引用、报告状态五子项（`assert_weakness_identified` 已定义却全仓无调用，是「停在中途」的直接证据）。

**根因**：06-05 PLAN 的 must_have 把 c 收窄为「strong>medium>weak 客观题区分度」，而计划 must_have 不能缩减 roadmap SC 范围——这是 goal-backward 核验须抓出的「任务完成 ≠ 目标达成」类缺口。

**缓解**：五子项底层功能均已实现并有专测（`test_phase5_report.py` required/拒答/报告状态机、`test_phase5_evidence.py` 证据引用、`test_phase2_scoring.py` 拒答缺失、`report.py` 短板排序），故修复是把报告生成接入 c 评测链路并复用既有断言，而非新开发功能。

---

_Verified: 2026-09-06T02:10:00Z_
_Verifier: Claude (gsd-verifier)_
