---
phase: 2
slug: dynamic-selection
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-04
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> 内容来源：02-RESEARCH.md「## Validation Architecture」；结构先例：01-VALIDATION.md。

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + FastAPI TestClient（httpx）；脚本式 test_m6/question_bank 为 plain python |
| **Config file** | none — 单文件单进程纪律（约定，Phase 6 REF-7.4 才统一 pytest 收集） |
| **Quick run command** | `cd server && python -m pytest test_phase2_<area>.py -v`（受影响单文件） |
| **Full suite command** | 逐文件：`python -m pytest server/test_phase2_migration.py -v` → `test_phase2_weights.py` → `test_phase2_selection.py` → `test_phase2_interview.py` → `test_phase2_difficulty.py` → `test_phase2_scoring.py` → `test_m5_backend.py` → `test_m7_backend.py` → `test_p0_security.py` → `test_p0_chain.py`；脚本式：`python server/test_m6_backend.py`、`python server/test_question_bank.py`（**一次 pytest 不得收多文件**） |
| **Estimated runtime** | ~60–120 seconds（mock 模式离线，逐文件串行；不含 eval 冒烟） |

---

## Sampling Rate

- **After every task commit:** 该任务撞到的单测试文件（<30s，全 mock 离线）
- **After every plan wave:** 全部测试文件逐个跑（6 新建 + 3 既有重写）+ `python eval/virtual_candidates.py --position-id <seed>` 冒烟（临时库 /tmp/，不碰 data/app.db——红线 2）
- **Before `/gsd:verify-work`:** Full suite must be green；SC-1~5 逐条核（见 ROADMAP Phase 2 Success Criteria）
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | REF-2.7/2.9 | T-02-01 | 老库模拟（旧建表→init_db）→ 三表新列全在；锚点 §9.4 回填（3,2/4,3/5,4）；COALESCE 合并保序；final_score 列保留不 DROP 且 _DDL 保留该列 | unit | `cd server && python -m pytest test_phase2_migration.py -v` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | REF-2.7/2.9 | T-02-01/05 | PRAGMA 嗅探幂等早退；唯一索引重复检测 raise（不静默去重）；迁移后旧 CHECK 不动；无新列 CHECK | unit+integration | `python -c init_db 幂等直跑` + `pytest test_phase2_migration.py -v` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | REF-5.7 | T-02-03/04 | Σhard weight=0.7±尾差、Σsoft=0.3、单类目归一 1.0；纯 gate 模型不除零；aggregation 不二次乘；无 UPDATE competency_item（存量不重算 D-16） | unit | `cd server && python -m pytest test_phase2_weights.py -v` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | REF-3.1/3.2/3.6/4.1 | T-02-07 | §10.2 四行样例 (6,3)/(7,3)/(8,3)/(11,4)；tier soft=2→1/1/0；建会话 aq=0；每 next 递增；selection_reason JSON 七键；followup 不增行；legacy 冒烟 | unit+integration | `cd server && python -m pytest test_phase2_selection.py -v` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 2 | REF-3.2/3.6 | T-02-06/07/10 | select_next_question 零 LLM；事件全经 append_event（无手拼 INSERT INTO assessment_state_event）；种子 sha256(session_id) 可重放；required 例外每 item 一次 + PATH_UNAVAILABLE 不静默 | integration | `python -c 选择烟测` + `pytest test_phase2_selection.py -v` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 2 | REF-3.1/4.1 | T-02-09 | readiness 与 selection 同源 plan_quotas（防口径漂移）；CATEGORY_QUOTA 全库零残留（grep 非零可败）；legacy 会话续答不 500 | integration | `pytest test_phase2_selection.py -v` + CATEGORY_QUOTA grep（残留即 exit 1） | ❌ W0 | ⬜ pending |
| 02-02-04 | 02 | 2 | REF-3.1 | — | ORDINARY_PLAN_N 占位值 + SSOT §31 注释（不 env 覆盖，A5）；m5/question_bank 断言重写（aq=0、新配额、experience 剔除）；p0_security/p0_chain 回归适配（种子补 hard ≥7/soft ≥3 tier 满足、p0_chain _answer_whole_session 改 GET current_question、:390 单题取题同步、:490 注释——D-09 不改结构） | regression | `cd server && python -m pytest test_m5_backend.py test_p0_security.py test_p0_chain.py -v && python test_question_bank.py`（逐文件） | ⚠️ 既有改造 | ⬜ pending |
| 02-02-05 | 02 | 2 | SSOT §31-1 | — | ORDINARY_PLAN_N 生产默认值经用户裁决（checkpoint:human-verify，agent 不代决——章程 §2.2 硬关口） | checkpoint | —（呈报流程见 02-02 Task 5） | — | ⬜ pending |
| 02-04-01 | 04 | 3 | REF-1.3/1.6/1.7/4.3/4.4/4.5 | T-02-15/16/17/20 | mock 三向分类；Pydantic 非法 answer_state 拒绝（literal_error）；5 键契约锁定；followup==2 硬约束；拒答二次封存 | unit+integration | `cd server && python -m pytest test_phase2_interview.py -v` | ❌ W0 | ⬜ pending |
| 02-04-02 | 04 | 3 | REF-1.6/1.7 | T-02-15 | decide_next_action 签名逐字保持；InterviewObservation 无 action 字段（schema 层不可能携带控制指令）；ValidationError → MODEL_UNCERTAIN 降级不卡死 | unit | `pytest test_phase2_interview.py -v` + 签名/键位 grep | ❌ W0 | ⬜ pending |
| 02-04-03 | 04 | 3 | REF-4.5 | T-02-18/19 | refused 分支封存（closed_at + seal_reason='refused' + QUESTION_SEALED 事件）+ 续派发；OBSERVATION_CLASSIFIED/EVIDENCE_EVALUATED 留痕；followup_count 迁列；本计划零 question_score 行 | integration | `pytest test_phase2_interview.py -v && pytest test_m5_backend.py -v` | ⚠️ 既有改造 | ⬜ pending |
| 02-03-01 | 03 | 4 | REF-4.2 | T-02-11/12/14 | §11.2 判据表驱动（升/降双路径/滞回/跳级拒绝/easy 不降/仅 target_level>4/七类排除/实例内不升降）；事件 payload 四键（criterion/evidence_counts/from/to） | unit+integration | `cd server && python -m pytest test_phase2_difficulty.py -v` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 4 | REF-4.2 | T-02-11/13 | next_difficulty 纯函数无 conn（LLM 无法输出难度迁移）；update_path_state 不 commit（快照与事件同事务）；七类排除由调用方传布尔 | unit | `python -c import 烟测` + `pytest test_phase2_difficulty.py -v` | ❌ W0 | ⬜ pending |
| 02-03-03 | 03 | 4 | REF-4.2 | — | 封存点接入（next/finish 两路，commit 前同事务）；followup 路径不触发状态机；选题层读 snapshot；p0_chain 仅 DIFFICULTY_* 事件断言宽松（种子/答题闭链适配已由 02-02 任务 4 完成）；selection 回归绿 | integration | `pytest test_phase2_difficulty.py test_p0_chain.py test_phase2_selection.py`（逐文件三条命令） | ⚠️ 既有改造 | ⬜ pending |
| 02-05-01 | 05 | 5 | REF-5.1/5.2/5.3/8.1 | T-02-21/22 | score_final 独立（"0.5 +" 源码零残留）；INVALIDATED 不写 1/不写 5；REFUSED 分母排除 + score_value=0 + refusals 单列；SCORE_STATES 六值枚举完整；报告闭环（拒答+无效题不炸报告） | integration+regression | `cd server && python -m pytest test_phase2_scoring.py -v` | ❌ W0 | ⬜ pending |
| 02-05-02 | 05 | 5 | REF-5.1/5.2/5.3/8.1 | T-02-21/22/24 | INSERT 列清单含 score_state 不含 final_score；分母 score_state 三路分流（SCORED/REFUSED/excluded）；refusals/missing_warnings 显式非静默；拒答不触发 LLM 评分 | integration | `pytest test_phase2_scoring.py -v` + "0.5 +" grep（残留即 exit 1） | ❌ W0 | ⬜ pending |
| 02-05-03 | 05 | 5 | REF-2.9 | T-02-23 | 四消费点切换完成后原子 DROP final_score（幂等嗅探保护；COALESCE 合并在 DROP 前完成）；_DDL 同步去 final_score；test_phase2_migration.py 两处「列保留」断言同步翻转（score_final==3 保留 + final_score 列不存在、新库列集合不含 final_score——D-09 只改断言） | unit | `python -c PRAGMA 断言` + `pytest test_phase2_scoring.py test_phase2_migration.py`（逐文件） | ❌ W0 | ⬜ pending |
| 02-05-04 | 05 | 5 | REF-5.1/8.1 | — | m6 脚本式断言重写（score_final/score_state 口径）；m5 :290 断言重写；eval 冒烟退出码 0（临时库）；业务代码 final_score 引用仅限 db.py 迁移 | regression | `python test_m6_backend.py && pytest test_m5_backend.py -v` + eval 冒烟 | ⚠️ 既有改造 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*注：Task ID 按各 PLAN.md 实际任务编号映射；执行 wave 按文件冲突重排为 01→02→04→03→05（02-02 与 02-04 共改 assessment.py/test_m5，02-03 依赖 02-04 的 answer_state 分类）。*

---

## Wave 0 Requirements

- [ ] `server/test_phase2_migration.py` — 老库模拟迁移 + 锚点回填 + score_final 合并（REF-2.7/2.9）
- [ ] `server/test_phase2_weights.py` — 7:3 三落点回归断言（REF-5.7）
- [ ] `server/test_phase2_selection.py` — 配额公式四样例 + API 级动态选题 + required 例外（REF-3.1/3.2/3.6/4.1）
- [ ] `server/test_phase2_difficulty.py` — 表驱动判据 + 事件/快照同事务（REF-4.2）
- [ ] `server/test_phase2_interview.py` — mock 分类器 + Pydantic 拒绝 + 拒答确认流（REF-1.6/1.7/4.3/4.4/4.5）
- [ ] `server/test_phase2_scoring.py` — score_final 独立/INVALIDATED/REFUSED 分母（REF-5.1/5.2/5.3/8.1）
- [ ] `server/test_m5_backend.py` — 修改而非新建：question_count/final_score/score_live 断言重写（D-09 前例：只改断言不重构风格）
- [ ] `server/test_m6_backend.py` — 修改而非新建：50/50 三断言重写（脚本式 check 结构保持）
- [ ] `server/test_question_bank.py` — 修改而非新建：test_selection 断言按新配额（脚本式保持）
- [ ] 无框架安装需求（pytest 9.1.1 已在环境——02-RESEARCH Environment Availability 本机实测）

*六个新建测试文件由各 plan 的 Task 1（Wave 0 先红）创建；三个既有文件在各 plan 的断言重写任务中改造。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ORDINARY_PLAN_N 生产默认值裁决 | SSOT §31-1 | 数值属 SSOT §31 开放参数（"实施期结合 40 分钟体验测定"），agent 不代决 N 默认值（章程 §2.2 硬关口） | 02-02 Task 5 checkpoint 呈报：查看 server/config.py 的 ORDINARY_PLAN_N 占位值（10）→ 依据 §31-1 与 §10.2 样例（N=9~15 均合法）→ 回复"维持 10"或新整数 → 改值只需 config 一行，测试种子动态跟随 |

*全部运行时行为（动态选题/难度状态机/回答分类/评分链）均有 API 级自动化验证；上表为唯一人工介入点（决策类 checkpoint，非行为验证）。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
