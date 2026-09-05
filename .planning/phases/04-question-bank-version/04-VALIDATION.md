---
phase: 4
slug: question-bank-version
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-05
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> 内容来源：04-RESEARCH.md「## Validation Architecture」；结构先例：03-VALIDATION.md。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest（无 pytest.ini/conftest.py/pyproject.toml，默认收集）+ FastAPI TestClient |
| **Config file** | none — 单文件单进程纪律（TESTING.md；Phase 6 REF 才统一收集） |
| **Quick run command** | `cd server && python -m pytest test_phase4_<area>.py -v`（受影响单文件） |
| **Full suite command** | 逐文件串行：`test_phase4_binding.py` → `test_phase4_orphan.py` → `test_phase4_model_edit.py` → `test_phase4_fail_visible.py` + 回归面（`test_phase2_selection.py`、`test_question_bank.py` 脚本式、`test_phase3_forms.py` 判重/候选面）——**一次 pytest 不得收多文件**（DB_PATH 竞态红线） |
| **Estimated runtime** | ~60–120 seconds（全 mock 离线逐文件串行） |

---

## Sampling Rate

- **After every task commit:** 该任务撞到的单测试文件（<30s）
- **After every plan wave:** 4 个 phase4 文件 + 回归面（test_phase2_selection / test_question_bank / test_phase3_forms 判重面）
- **Before `/gsd:verify-work`:** Full suite green + SC 1-4 逐条核（ROADMAP Phase 4 Success Criteria）
- **Max feedback latency:** 30 seconds

---

## REF Coverage（5/5）

| Req | 行为断言 | 测试文件 | 断言点（Nyquist 每行可断言） |
|-----|----------|----------|------------------------------|
| REF-2.5 | generate_question_bank 落库写 model_id/model_version/item_id/rubric_version="v1" | test_phase4_binding.py | test_insert_writes_model_binding / test_item_id_rubric_version_filled |
| REF-3.4 | 升版后 readiness 对旧版题返回 INCOMPLETE（v2 未生成时开考被拦）；selection 只取 v2 题 | test_phase4_binding.py | test_readiness_blocks_old_version / test_selection_filters_by_model_version / test_idempotency_key_includes_version |
| REF-7.1 | `GET /api/admin/jds/orphan` 返回列表（非 404），顺序先于 `/jds/{jd_id}` | test_phase4_orphan.py | test_orphan_route_not_swallowed / test_orphan_returns_position_id_null |
| REF-7.2 | update_model 拒绝 NaN weight / required_level=6 / importance=bad / 重复 std_name（保留 Σ=100%） | test_phase4_model_edit.py | test_nan_weight_rejected / test_weight_gt_1_rejected / test_required_level_range / test_importance_enum / test_duplicate_std_name_rejected / test_sum_100_still_enforced |
| REF-8.4 | 生成失败 → readiness 返回 INCOMPLETE + error_msg；get_todos 含失败明细 | test_phase4_fail_visible.py | test_readiness_failed_returns_incomplete_with_error / test_todos_includes_failed_detail |

---

## Wave 0 Requirements

- [ ] `server/test_phase4_binding.py` — 落库绑定 + 消费侧过滤 + 判重升级（REF-2.5/REF-3.4）
- [ ] `server/test_phase4_orphan.py` — 路由顺序回归（REF-7.1）
- [ ] `server/test_phase4_model_edit.py` — NaN/范围/枚举/重复（REF-7.2）
- [ ] `server/test_phase4_fail_visible.py` — FAILED 明细 + todos（REF-8.4）
- [ ] 既有 `server/test_question_bank.py`（脚本式）与 `test_phase2_selection.py` 的判重/候选断言复核——判重键、`_load_candidate_rows` 签名变更会波及旧断言
- [ ] 无框架安装需求（零新包——RESEARCH 结论「零迁移、零新依赖」）

*四个新建测试文件由各 plan Task 1（Wave 0 先红）创建；回归改造在 04-01 内逐任务落。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| orphan 列表字段口径 + status 过滤 | REF-7.1（D-52） | D-52 字面「字段同 list_jds / WHERE position_id IS NULL」与现有 `positions.py:87` 实现「字段子集 + `AND status != 'failed'`」不一致；与 `get_todos` orphan 计数口径是否统一属裁量 | 关口包呈现：现有实现为准（字段子集 + status != 'failed'，与 get_todos 计数一致）推荐 / D-52 字面（全字段无 status 过滤）两选项——用户裁定 |
| admin todos 失败明细字段结构 + 前端是否新增展示卡 | REF-8.4（D-51） | D-51 允许 `question_bank_failed` 新键 vs `question_bank_not_ready` 内嵌；前端 Positions.vue 当前未展示 question_bank_not_ready——「失败对管理员可见」验收口径需裁定 | 关口包呈现：后端「计数 + question_bank_failed 明细」推荐（前端零破坏）+ 前端新增「题库失败」卡是否纳入本 phase 两选项——用户裁定 |

*上表两项为决策类 checkpoint——**待硬关口 A 用户裁定**，执行段前必须用户裁决，不得代确认。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references（4 新文件）
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s（全 mock 离线）
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** {pending / approved 2026-09-05}
