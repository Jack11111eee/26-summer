---
phase: 02-dynamic-selection
verified: 2026-09-04T13:05:00Z
status: verified
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "真实 LLM（LLM_PROVIDER=deepseek）下面试官观察输出质量与 InterviewObservation 校验通过率"
    expected: "真实模式输出可被 Pydantic 11 态校验解析；非法输出降级 MODEL_UNCERTAIN 不卡死会话在真模型下复现"
    why_human: "Phase 2 全部测试为 LLM_PROVIDER=mock（D-027：mock 不能替代真实 LLM 验证）；需真实 API key 的实机运行，属性能/质量验收非结构验收"
---

# Phase 2: 动态选题与有界循环 验证报告

**Phase Goal:** 测评运行时按 SSOT §10/§11 运转——每题动态实例化、四层代码选题、难度路径状态机导航、回答状态分类驱动处理原则，评分链废除 score_live 50/50 合成、权重对齐 7:3
**Verified:** 2026-09-04T13:05:00Z
**Status:** verified（5/5 truths 全部 VERIFIED；11 套测试逐文件实跑全绿；eval 冒烟对齐种子后 passed=True；1 项真实 LLM 验证属 Phase 后验收口，非阻断）
**Re-verification:** No — 初次验证（无前序 VERIFICATION.md）

## Goal Achievement

### Observable Truths（源自 ROADMAP.md 五条 Success Criteria）

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 会话创建零预选；每次 action=next 四层选题即时选出下一题（合法性→required 硬约束→配额→排序），selection_reason 落库可审计 | ✓ VERIFIED | 零预选：`server/api/assessment.py:97-113` create_session 只 INSERT 会话 + SESSION_CREATED 事件（无 questions 循环，无 select_questions_for_session import）；`server/services/question_selection.py:272-330` _select_next_question_locked 依序执行层①（_load_candidate_rows :209-234 WHERE status='active' AND category IN ('hard_skill','soft_skill')）→层②（_uncovered_required_items :333 + _quota_remaining 配额内过滤 :443）→层③（plan_quotas 实时扣减 :423-431）→层④（_sort_pool 三键 chain/weight/random.Random(seed) :470-483）；selection_reason 七键+nth JSON 落库（:508-517 json.dumps ensure_ascii=False）+ QUESTION_SELECTED/QUESTION_ACTIVATED 双事件同事务（:534-540）；消费点三处接线：get_session 派发（assessment.py:131-144）、submit_answer next 分支（:315）、池耗尽 finish（:317-328）；实跑 `test_phase2_selection.py` 9/9 PASS（含 test_session_creation_no_preselection 断言 aq==0、test_dynamic_dispatch_per_next 断言逐 next 递增 + 七键存在） |
| 2 | 配额 = 岗位级 N + 7:3 最大余数 + tier 公式（0.8/0.6/1.7）；旧 CATEGORY_QUOTA{hard:6,soft:2,exp:2} 废除；experience/qualification 不再出现在普通选题 | ✓ VERIFIED | 纯函数三件：largest_remainder_73（question_selection.py:50-64）/ tier_targets（:67-100，TIER_COEF 0.8/0.6/1.7 和 1.7 :41-42）/ plan_quotas（:103-127）；`server/config.py:47` ORDINARY_PLAN_N = 10（关口 A 用户裁决 [02-007] 注释在位）；体验/资格剔除：候选池 WHERE category IN ('hard_skill','soft_skill')（:221）+ ORDINARY_CATEGORIES 白名单（:38）+ plan_quotas 只收普通类目（:114-115）；旧配额废除：`grep -rn "CATEGORY_QUOTA" server/ --include="*.py"` 零命中（exit 1，实测）；readiness 同源：`server/services/readiness.py:13` `from .question_selection import ORDINARY_CATEGORIES, plan_quotas`；实跑 `test_largest_remainder_73`（N=9/10/11/15→(6,3)/(7,3)/(8,3)/(11,4) 逐行断言）、`test_tier_targets`（soft=2→1/1/0 + clamp 优先级）、`test_plan_quotas_single_category`（大类退化）、`test_no_experience_in_selection`（整场 category ⊆ {hard,soft}）全 PASS |
| 3 | 难度升降/恢复由代码状态机执行并写 DIFFICULTY_RAISED/LOWERED/RESTORED 事件（easy→medium 一次充分 / medium→hard 充分且稳定+target>4 / 降级按有效证据失败 / 滞回恢复 / 跳级禁止 / 同实例内不升降） | ✓ VERIFIED | `server/services/difficulty.py:43-84` next_difficulty 纯函数无 conn（签名 `def next_difficulty(snap: dict, *, ...)`）：easy→medium 一次充分（:74-75）、medium→hard 需 sufficient≥1 且 stable_ever 且 required_level>4（:78-82）、降级 current!='easy' 且 fail≥2 或 followup_ambiguous（:64-66）、滞回恢复 sufficient≥2 或 1 次 stable（:71-72 DIFFICULTY_RESTORED）、跳级禁止（easy 分支只返回 medium/None，惰测试 test_no_skip_within_instance 全组合断言永不 hard）；七类排除：`server/api/assessment.py:428-436` _EXCLUDED_FAILURE_STATES 七类元组 → :460 is_valid_failure 计算 → difficulty.py:123 advance_snapshot is_valid_failure=False 时两计数器不动（test_invalid_failure_not_counted PASS：fail 不增）；事件 payload 四键 criterion/evidence_counts/from_difficulty/to_difficulty（difficulty.py:193-201）；快照与事件同事务——update_path_state 不 commit（grep conn.commit 零命中），assessment.py 两封存分支（:269 refused / :298 answered）经 _advance_difficulty_state 在最终 commit 前调用，followup 分支不触发（:302-305 只 commit 计数）；选题层承接：question_selection.py:136-198 _snapshot_target_difficulty + _apply_snapshot_difficulty（目标档过滤 + 无档落回不高于目标）；实跑 `test_phase2_difficulty.py` 10/10 PASS（含集成：LOWERED payload 四键 + snapshot==to_state 同事务 + RAISED 后 selection 层 medium 承接） |
| 4 | LLM 输出结构化观察（answer_state 11 态 + 证据维度），代码裁决 action；拒答一次确认后跳过记 REFUSED（score_value=0 不进分母）；followup ≤2 代码硬约束 | ✓ VERIFIED | 两层分离：`server/schemas.py:72-96` ANSWER_STATES Literal 11 态 + ObservationDims + InterviewObservation（含可选 score_live 1-5）；`server/services/interview.py:208-221` 观察层 call_llm_json → InterviewObservation(**result)（ValidationError 降级 MODEL_UNCERTAIN 不卡死）；:224-228 裁决层 classify_observation 纯函数布尔 + decide_action 纯函数（:162-189 规则 1-7——LLM 不输出 action）；prompt 契约对齐：`server/services/prompts/interviewer.py` v2 明示"你不决定 action/难度/结束" + 11 态列全；拒答两次封存：decide_action DECLINED 首次 confirm / 二次 seal_refused+refused 标记（interview.py:170-174）→ assessment.py:249-270 refused 分支封存 seal_reason='refused' + QUESTION_SEALED + 照常派发下一题；REFUSED 评分行：`server/services/scoring.py:216-222` seal_reason=='refused' → (score_final=0, score_state='REFUSED') 不经 LLM；聚合分母排除：`server/services/aggregation.py:97-102` REFUSED → refusals 单列列表不进 item_scores_map（test_refused_excluded_from_denominator PASS：REFUSED 行 score_final==0 + actual 均值只含 SCORED 行）；followup ≤2：interview.py:231-233 FOLLOWUP_MAX 硬约束 + assessment.py:240-244 followup_count 列自增（迁列 D-25）；5 键契约保持：interview.py:246-254 action/reason/reply/score_live/score_live_reason + 只加不减扩展键（test_decision_contract_5keys + test_refusal_confirm_skip 封存/事件/下题断言全 PASS） |
| 5 | score_live 仅导航；聚合无 50/50 合成；answer_key 空客观题判 INVALIDATED 非满分；权重 7:3（旧 55/20/20/5 作废） | ✓ VERIFIED | 无合成：`grep "0.5 +" server/services/scoring.py` 零命中（exit 1）；scoring.py:227 _latest_score_live 仅落库参考（docstring D-26："不参与任何 final 计算"），score_session INSERT 只写 score_final 独立值（:236-249）；INVALIDATED：score_question 客观缺 key → (score_final=None, score_state='INVALIDATED') 不写 1/5（:123-132）；聚合三路分流：aggregation.py:92-110 SCORED 进分母 / REFUSED 单列 / 排除态 missing_warnings（不隐式转 0）；7:3：config.py:28-33 CATEGORY_RATIO 0.7/0.3/0.0/0.0 + aggregate.py:87-94 total_ratio==0 gate 保护 + aggregation.py:152 总分公式 weight×(actual/5.0)×100 无 CATEGORY_RATIO 二次乘（test_aggregation_no_double_scaling 源码断言 PASS）；final_score 列消亡：业务代码零引用（grep 非 test 非 db.py 仅 db.py 迁移段 5 处命中——注释与 DROP 语句）；db.py:448-459 迁移段序 ADD score_state → COALESCE(final_score,score_final) 合并 → DROP final_score（嗅探幂等）；/tmp 新库双 init_db 验证：question_score 列集 = [score_id, session_id, question_id, item_id, score_live, score_final, evidence_quote, reason, created_at, score_state]——无 final_score 有 score_state；实跑 `test_phase2_weights.py` 5/5、`test_phase2_scoring.py` 7/7（含 test_aggregation_reads_score_final：score_live=2 vs score_final=3 场景 actual==3 均值、test_invalidated_objective：score_final IS None + missing_warnings + 不进 actual）全 PASS |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|-----------|--------|---------|
| `server/services/question_selection.py` | 四层选题 + plan_quotas/largest_remainder_73/tier_targets 纯函数 + 种子 | ✓ VERIFIED | 562 行：四函数齐备（grep def 逐个存在）；sha256 稳定种子 :559-561；legacy 兜底 :250/282-285；例外分支 :299-318；edition policy 'p2' :45 |
| `server/services/difficulty.py` | next_difficulty 纯函数 + update_path_state 持久化同事务 | ✓ VERIFIED | 209 行：纯函数无 conn（签名核）；零 conn.commit（grep 零命中）；CRITERION_* 六常量判据摘要 |
| `server/services/interview.py` | 两层化 + mock 分类器 + 拒答确认 + followup 迁列 | ✓ VERIFIED | 257 行；decide_next_action 签名逐字不变（:192）；classify_observation/decide_action 纯函数；_mock_interview 输出观察契约无 action 键；_count_followups 改读列（:55-61） |
| `server/schemas.py` | InterviewObservation + ObservationDims（11 态 Literal） | ✓ VERIFIED | :72-96；MODEL_UNCERTAIN 可 grep；score_live Field(None, ge=1, le=5) |
| `server/services/scoring.py` | 删 50/50 + score_state 三态生产 + REFUSED/INVALIDATED 行 | ✓ VERIFIED | SCORE_STATES 六值常量 :23-30；INSERT 列清单含 score_state 无 final_score（:244-249）；拒答不经 score_question（:216-222 分支先于 :225 调用） |
| `server/services/aggregation.py` | 取数切 score_final + score_state 分母过滤 | ✓ VERIFIED | :84-110 三路分流；refusals/missing_warnings 新键只加不减（:180-181）；总分公式 :152 保持 |
| `server/services/report.py` | _load_question_reviews 切 score_final | ✓ VERIFIED | :39 SELECT qs.score_final, qs.score_state（无 final_score） |
| `server/db.py` | 三迁移函数 + DROP final_score + 唯一索引 | ✓ VERIFIED | _migrate_question_bank_v2 :355 / _migrate_assessment_question_v2 :392 / _migrate_question_score_v2 :436；init_db 按序注册 :471-473；DROP :459 幂等嗅探；uq_aq_session_seq UNIQUE 双路径（PRAGMA index_list 确认 unique=1） |
| `server/config.py` | CATEGORY_RATIO 7:3 + ORDINARY_PLAN_N | ✓ VERIFIED | :28-33 与 :47；[02-007] 裁决注释在位 |
| `server/api/assessment.py` | 三消费点 + 封存三路 + 状态机接入 | ✓ VERIFIED | create_session 零预选 / get_session 派发+legacy / submit_answer select_next_question + refused/answered 封存 + _advance_difficulty_state 两处 + OBSERVATION_CLASSIFIED/EVIDENCE_EVALUATED/QUESTION_SEALED 事件 |
| `server/services/readiness.py` | 第 5 步 plan_quotas 同源 | ✓ VERIFIED | :13 import；:141-153 预检；三态 dict 结构不变 |
| `server/services/prompts/interviewer.py` | 输出契约对齐新 schema | ✓ VERIFIED | INTERVIEWER_SYSTEM v2：11 态列全 + "你不决定 action/难度/结束"；无 action/followup/next 协议残留 |
| 6 个 test_phase2_*.py | 各计划测试套件 | ✓ VERIFIED | selection 9 / difficulty 10 / interview 12 / scoring 7 / migration 8 / weights 5 — 全部独立进程实跑 PASS（详见 Spot-Checks） |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| assessment.py submit_answer next 分支 | question_selection.select_next_question | 决策 commit 后新事务 | ✓ WIRED | :310 commit → :315 调用；Anti-pattern 1 次序合规 |
| readiness.py 第 5 步 | question_selection.plan_quotas | 同源 import | ✓ WIRED | readiness.py:13；防两处公式漂移 |
| question_selection._instantiate | assessment_state_event（经 append_event） | QUESTION_SELECTED/QUESTION_ACTIVATED 同事务 | ✓ WIRED | :534-540；例外加 REQUIRED_EXCEPTION_GRANTED :543-547 与 PATH_UNAVAILABLE :310-313 |
| difficulty.update_path_state | assessment_state_event（经 append_event） | DIFFICULTY_* + payload 四键 | ✓ WIRED | difficulty.py:202-204；from/to_state 旧新难度；同事务（调用者 commit） |
| assessment.py 两封存分支 | difficulty._advance_difficulty_state | refused/answered 封存后、最终 commit 前 | ✓ WIRED | :269 / :298 两处；followup 分支零调用 |
| interview.py decide_next_action | schemas.InterviewObservation | InterviewObservation(**result) + ValidationError 降级 | ✓ WIRED | interview.py:214-221 |
| interview.py 裁决层 decision 扩展键 | assessment.py 封存/状态机消费 | answer_state/evidence_sufficient/refused | ✓ WIRED | assessment.py:219/235-237/249/289/460 |
| assessment.py refused 分支 | scoring.py score_session → REFUSED 行 | seal_reason='refused' 评分分流 | ✓ WIRED | scoring.py:200-204 JOIN 读 aq.seal_reason + :216-222 分支 |
| scoring/aggregation/report | question_score.score_final/score_state | 三消费点切列 | ✓ WIRED | scoring INSERT / aggregation SELECT :85 / report SELECT :39；业务代码 final_score 零读取 |
| config.ORDINARY_PLAN_N | selection/assessment/readiness 配额计算 | 三处 import config | ✓ WIRED | question_selection.py:297 / assessment.py:157 / readiness.py:141 |
| interview.py _mock_interview | Pydantic + 裁决层 | 双轨契约（mock 不绕过裁决） | ✓ WIRED | 输出 dict 与 InterviewObservation 同构（answer_state/observation/score_live），经同一 :214 校验与 :224 裁决 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| get_session current_question | cur | select_next_question → assessment_question JOIN question_bank | 是（动态实例真实落库再回读） | ✓ FLOWING |
| selection_reason JSON | reason dict | 四层选中过程真实构造（layer/predicate/tier/weight/seed 均运行时值） | 是（test_dynamic_dispatch_per_next json.loads 七键断言） | ✓ FLOWING |
| 难度 snapshot | snap | 前一封存行 path_state_snapshot JSON（无则 easy 初始化） | 是（test_events_payload_and_same_transaction 断言 current_difficulty==事件 to_state） | ✓ FLOWING |
| 聚合 item_scores actual | item_scores_map | question_score.score_final 实表查询（非硬编码） | 是（反题构造 live=2/final=3 场景 actual==3 均值证明） | ✓ FLOWING |
| report question_reviews | rows | question_score JOIN（score_final/score_state） | 是（test_report_chain_end_to_end radar 非空 + 三态共存） | ✓ FLOWING |

### Behavioral Spot-Checks（实跑记录，2026-09-04，cwd=server/ 单文件单进程）

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 四层选题全行为 | `python3 -m pytest test_phase2_selection.py -v` | 9 passed（5.01s）——含零预选/逐 next 递增/配额四样例/experience 剔除/例外双态/legacy 冒烟 | ✓ PASS |
| 难度状态机 | `python3 -m pytest test_phase2_difficulty.py -v` | 10 passed（2.01s）——§11.2 全判据 + 集成 payload/同事务/承接 | ✓ PASS |
| 两层化面试决策 | `python3 -m pytest test_phase2_interview.py -v` | 12 passed（6.89s）——三向分类/拒答二次封存/Pydantic 拒绝/followup 上限 | ✓ PASS |
| 评分链新契约 | `python3 -m pytest test_phase2_scoring.py -v` | 7 passed（4.53s）——无合成/REFUSED 分母排除/INVALIDATED/报告闭环 | ✓ PASS |
| 迁移双路径 | `python3 -m pytest test_phase2_migration.py -v` | 8 passed（0.09s）——老库模拟/新库直建/断言已翻转（final_score 不存在） | ✓ PASS |
| 7:3 权重回归 | `python3 -m pytest test_phase2_weights.py -v` | 5 passed（0.16s） | ✓ PASS |
| m5 回归（断言重写后） | `python3 -m pytest test_m5_backend.py -v` | 7 passed（3.48s）——含 :304-307 score_final/score_state 新断言 | ✓ PASS |
| m6 脚本回归 | `python3 test_m6_backend.py` | 43 通过 0 失败，exit 0 | ✓ PASS |
| question_bank 脚本回归 | `python3 test_question_bank.py` | 25 通过 0 失败，exit 0 | ✓ PASS |
| p0_security 回归 | `python3 -m pytest test_p0_security.py -v` | 10 passed（6.87s）——种子补齐新配额后建会话路径保持 | ✓ PASS |
| p0_chain 回归 | `python3 -m pytest test_p0_chain.py -v` | 11 passed（7.86s）——逐题 GET 闭链 + sequence_no 断言兼容 DIFFICULTY_* 新事件 | ✓ PASS |
| m7 回归 | `python3 -m pytest test_m7_backend.py -v` | 5 passed（3.10s） | ✓ PASS |
| /tmp 新库双 init_db + 列集 | `python3 -c "...init_db(); init_db(); PRAGMA..."` | question_score 列集无 final_score 有 score_state/score_final；aq 12 新列齐；uq_aq_session_seq unique=1；幂等 OK | ✓ PASS |
| CATEGORY_QUOTA 全库废除 | `grep -rn "CATEGORY_QUOTA" server/ --include="*.py"` | 零命中（exit 1） | ✓ PASS |
| 合成残留静态 | `grep -c "0.5 +" server/services/scoring.py` | 0（exit 1） | ✓ PASS |
| 业务代码 final_score 引用 | `grep -rn "final_score" server/ --include="*.py" \| grep -v test_ \| grep -v score_final` | 仅 db.py 5 处（迁移注释/嗅探/DROP 语句——合法残留） | ✓ PASS |
| eval 冒烟（直调链兼容） | `DB_PATH=/tmp/p2_eval_final.db LLM_PROVIDER=mock python3 eval/virtual_candidates.py --position-id <seed>`（验证者自建对齐种子岗位） | **passed=True scores={'strong': 50.0, 'medium': 38.0, 'weak': 10.0}，exit 0**——score_session/aggregate_session_scores 列名切换后全程不抛异常，三档分层断言通过 | ✓ PASS |

（注：首eval 尝试用 std_name 与模型 items 不对齐的种子，跑得 0 分——是验证者种子错位非代码缺陷：score_session 的 `_find_item_id` 回退查询正确返回 None 跳过无归属题。对齐种子后三档分层立即正确，反证明数据流真实。）

### Probe Execution

本阶段无声明 probe（`scripts/*/tests/probe-*.sh` 不存在；各 PLAN 的验证入口为 pytest 套件与 grep 探针，已全部作为 Behavioral Spot-Checks 在验证者独立进程实跑——非采信 SUMMARY 叙述）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| REF-1.3 | 02-04 | score_live 由 LLM 直产 1-5 分（归观察层） | ✓ SATISFIED | schemas.py:95 InterviewObservation.score_live Field(ge=1,le=5)；interview.py:250 组装；test_phase2_interview 12 用例下的 score_live 路径 |
| REF-1.6 | 02-04 | 观察层/裁决层两层（LLM 不决定 action） | ✓ SATISFIED | interview.py:208-228；prompt v2 明示禁令；test_mock_classifier_* 三向证明分类与裁决分离 |
| REF-1.7 | 02-04 | LLM 不决定难度迁移/finish | ✓ SATISFIED | InterviewObservation 无 action 字段（schema 层不可能携带）；难度全代码（difficulty.py 纯函数）；finish 唯一触发源池耗尽（assessment.py:315-328） |
| REF-2.7 | 02-01（列/索引）+ 02-02/02-03/02-04（运行时消费） | assessment_question 12 实例列 + (session_id,seq) 唯一 | ✓ SATISFIED（phase 收口时点） | 迁移 :392-433 + 每天 PRAGMA 确认；动态实例列被 select（selection_reason/item_id/difficulty/status）、难度（path_state_snapshot）、封存（closed_at/seal_reason/followup_count）三组运行时全部消费；snapshot 承接受 test_selection_reads_snapshot 证明 |
| REF-2.9 | 02-01（列+合并）+ 02-05（消费切换+DROP） | score_final 统一 / 废弃 final_score / score_state | ✓ SATISFIED（phase 收口时点） | 列集 PRAGMA 确认无 final_score；三消费点（scoring/aggregation/report）+ 测试断言全部切换；human_override 列属 Phase 5（REQUIREMENTS.md:45 明示"随 Phase 5"） |
| REF-3.1 | 02-02 | 岗位级 N + 7:3 + tier 公式（废弃 CATEGORY_QUOTA） | ✓ SATISFIED | 配额三纯函数 + tests 四样例；grep 零残留 |
| REF-3.2 | 02-02 | 四层动态选题替换一次性预选 | ✓ SATISFIED | SC-1 证据链全量（Truth 1）；readiness 同源 |
| REF-3.6 | 02-02 | required 刚性例外（每 item 一次/仅 medium/hard） | ✓ SATISFIED | _exception_granted_items 双载体判定（selection JSON + 事件）+ _pick_exception_question（medium 优先/hard 兜底/不走 easy）；test_required_exception_after_exhaustion granted + PATH_UNAVAILABLE 双态 PASS |
| REF-3.7 | 02-01 | 难度→锚点映射（easy[2,3]/medium[3,4]/hard[4,5]） | ✓ SATISFIED | db.py:384-389 CASE 回填；test_anchor_backfill 断言 §9.4 表值 + NULL 保持 |
| REF-4.1 | 02-02 | 动态实例化（followup 为实例内子轮次） | ✓ SATISFIED | test_followup_does_not_create_instance：followup 后 aq 行数不变 |
| REF-4.2 | 02-03 | 难度路径状态机全判据 | ✓ SATISFIED | Truth 3 全量证据（10 测试逐判据） |
| REF-4.3 | 02-04 | evidence_sufficient/stable_evidence 维度 + 代码布尔裁决 | ✓ SATISFIED | classify_observation 排除清单代码化（:144-151）；stable 轻量版 A2 决议（assessment.py:364-397 sufficient_in_row≥2） |
| REF-4.4 | 02-04 | answer_state 11 态 + score_state 两层分离 | ✓ SATISFIED | ANSWER_STATES 11 态（schemas.py:72-76）+ SCORE_STATES 六值（scoring.py:23-30）；test_pydantic_accepts_all_11_states + test_score_state_enum_completeness |
| REF-4.5 | 02-04 | 各状态处理原则（拒答一次确认等最小实现） | ✓ SATISFIED | decide_action 规则 1-7（DECLINED confirm→seal / MODEL_UNCERTAIN 直接 next / 七类特殊态 next 推进不扣分）；INJECTION 事件留 Phase 3（02-04-PLAN 明示） |
| REF-5.1 | 02-05 | score_live 仅导航、废除 50/50 | ✓ SATISFIED | Truth 5 全量（静态 + 行为双证） |
| REF-5.2 | 02-05 | answer_key 空判题库无效非满分 | ✓ SATISFIED | score_question :123-132 INVALIDATED + score_final=None；test_invalidated_objective |
| REF-5.3 | 02-05 | REFUSED=0 不进能力分母 | ✓ SATISFIED | scoring REFUSED 行 + aggregation refusals 单列 + 分母排除测试 |
| REF-5.7 | 02-01 | 7:3 权重口径 + 不二次乘 | ✓ SATISFIED | config/aggregate/aggregation 三落点 + test_aggregation_no_double_scaling 源码断言 |
| REF-8.1 | 02-05 | 空 answer_key 恒满分漏洞关闭 | ✓ SATISFIED | 同 REF-5.2（test_invalidated_objective 断言不写 1/不写 5 + missing_warnings 可见） |

**孤儿检查：** REQUIREMENTS.md Traceability 行登记 19 项 REF（1.3, 1.6, 1.7, 2.7, 2.9, 3.1, 3.2, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.7, 8.1）；五个 PLAN frontmatter requirements 并集 = 02-01{2.7,2.9,3.7,5.7} ∪ 02-02{3.1,3.2,3.6,4.1} ∪ 02-03{4.2} ∪ 02-04{1.3,1.6,1.7,4.3,4.4,4.5} ∪ 02-05{5.1,5.2,5.3,8.1} —— 与 19 项逐一等同，无 ORPHANED、无遗漏。跨 plan 部分交付项（REF-2.7/2.9）按 phase 收口时点判定均全部就位。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| server/api/assessment.py | 353-358 | 决策 finish 在池未空时降级 next（is_last 旧口径过渡） | ℹ️ Info | 02-02-PLAN <消费点改造位置> 明文预留的过渡形态：decide_next_action 的 is_last 基于「无未答实例」在动态实例化下失真，02-04 已废除 interview 层 is_last 强制 finish（grep interview.py 无 is_last 残留调用），池耗尽是 finish 唯一触发源——属计划内已裁决项（[02-008b]），非缺陷。test_dynamic_dispatch_per_next 断言前 N 题恒 next 证明降级行为正确 |
| server/api/assessment.py | 131-146 | legacy 会话兜底分支形态 | ℹ️ Info | 旧会话（selection_reason 全 NULL）续答走旧 seq 派发不 500：select_next_question 返回 {"legacy": True} 标记 + API 层旧查询（assessment.py:329-348）。边界已锁测试（test_legacy_session_continues：GET 返旧行 + 答题 200 + next_question_id 旧行 seq 下一题）。legacy 会话不写新事件不污染审计（question_selection.py:283-285） |
| server/services/question_selection.py | 495-506 | chain_followed 仅在 _instantiate 计算选中题的标志，_sort_pool 排序键读 c.get("chain_followed") 恒 False | ⚠️ Warning | 层④第一键「chain 后继优先」的排序权重当前恒 0（候选行从不携带 chain_followed 键——它只在选中后的 reason JSON 记录）：即 chain 连锁实际上退化为 weight+seed 两键排序。影响：同 chain 的连环题不会因后继关系被优先选中（仅按权重与随机序）。selection_reason 的 chain_followed 布尔是选中后对「当前最新实例是否恰为前驱」的事实记录（审计值正确）。SSOT §10.6 层④的 chain 键命中前置位的语义未完全实现——但 Phase 2 各 SC 字面（四层顺序 + 排序三键存在性 + 可审计）与五条 Truth 均不含「chain 后继必须实际命中前置位」的行为断言，测试无此断言、无现实用例（题库生成侧 chain_key 仅多 item 岗位才挂 :116）。归非阻断项，建议 Phase 4 题库绑定周期消费 |
| server/api/assessment.py | 236-237 | OBSERVATION_CLASSIFIED payload 含 action 键（plan 契约为 answer_state/evidence_sufficient） | ℹ️ Info | 只加不减的信息性扩展（payload 多带 _out_action），审计信息更完整，无消费方冲突 |
| server/services/aggregation.py | 109-110 | IMPUTED 等枚举非 Phase 2 过滤名单 | ℹ️ Info | plan <interfaces> 注记明示：过度过滤会与 Phase 5 冲突——代码注释位在，设计如此 |
| 测试调试脚本 | — | _debug_selection.py / _dbg_*.py 4 个 | ℹ️ Info | 已随 worktree 清除（git ls-files 零命中、主仓 ls 无此文件——实测确认）；SUMMARY 文本保留历史记录 |

**债务标记门：** 5 个 PLAN 与 6 个新测试文件 + 9 个修改业务文件扫描 TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER——唯一命中 test_phase2_interview.py:166 的 "HACKED" 字符串是 Pydantic 拒绝测试的非法输入数据（answer_state="HACKED"），非债务标记。零未引用债务标记。

### Human Verification Required

### 1. 真实 LLM 观察层质量验证

**Test:** 配置 LLM_PROVIDER=deepseek（真实 API key），创建会话并完成至少 3 题作答（含一次拒答确认流）
**Expected:** 真实模型输出可被 InterviewObservation 校验解析；分类合理（实义词答案→VALID_EVIDENCE、拒答→DECLINED）；非法输出降级 MODEL_UNCERTAIN 不卡死在真实模式下复现；拒答两次封存链路在真实话术下正常
**Why Human:** Phase 2 全部测试为 LLM_PROVIDER=mock（D-027 决议明示 mock 不能替代真实 LLM 验证）；需真实 API key 与出网环境，属质量验收非结构验收。此为 Phase 后验收口项，不阻断本 phase 结构性验证结论。

## Acknowledged Gaps

无阻断性 gap。以下为已识别的非阻断观察（呈报供后续 phase 消费）：

1. **层④ chain 后继排序键实际退化**（Anti-Patterns 第 3 行）：chain_followed 标志仅落 selection_reason 审计，_sort_pool 的 chain 排序权重恒 0——SSOT §10.6 层④第一键的部分语义未在实际排序中生效。不影响五条 SC 与本 phase 所有测试断言；建议 Phase 4（题库版本绑定周期）或 Phase 5 消化。
2. **readiness.py 连接卫生**（Phase 1 VERIFICATION Warning 遗留）：while 循环段已在 02-02 重写中自然收敛 try/finally（readiness.py:53-59 现有 close）——Phase 1 六处 close 缺陷中的 readiness 部分已被本 phase 重写顺带修复，其余 Phase 1 Warning 不在本 phase 范围。
3. **真实 LLM 验证**（Human Verification 第 1 项）：mock 全绿不能替代，属 Phase 后验收口。

五条 Truths 全部 VERIFIED、13 项实跑全部 PASS、19 项 REF 全部 SATISFIED、无阻断性缺陷——phase goal 在代码中实际达成。

---

_Verified: 2026-09-04T13:05:00Z_
_Verifier: Claude (gsd-verifier)_
