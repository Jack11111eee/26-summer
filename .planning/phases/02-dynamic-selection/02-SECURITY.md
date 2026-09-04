---
phase: 02
slug: dynamic-selection
status: verified
audited: 2026-09-04
threats_total: 25
threats_verified: 25
threats_open: 0
critical_open: 0
asvs_level: 1
---

# Phase 02 (dynamic-selection) — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Audited at HEAD 0c608c4（含 code-review merge b6399e6：CR-01/CR-02 + WR-01~08 修复后形态）。

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| 老业务库 data/app.db → 迁移函数 | 生产数据被 ALTER/UPDATE/DROP 修改（D-15 授权范围，D-14/D-15/D-16 决议） | question_bank/assessment_question/question_score 三表 |
| 候选人答题 API → 选题服务 | 每次答题触发纯代码选题（无 LLM 输入面） | session_id、题库行 |
| LLM 输出 → Pydantic 校验 | 不可信结构化观察（伪造 answer_state/维度）进入处理链 | InterviewObservation dict |
| observation 结果 → 难度状态机 | LLM 观察仅以布尔入参进入状态机（裁决在 02-04 代码层完成） | evidence_sufficient/stable/is_valid_failure 布尔 |
| score_state 生产 → 聚合分母 | 状态枚举值决定分数是否进分母 | question_score 行 |
| Phase 1 既有 IDOR 边界 | load_owned_session/load_owned_report 在 Phase 2 新增/改动路由中保持 | session/report 资源 ID |

---

## Threat Register

### 02-01（迁移与权重）

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-02-01 | Tampering | _migrate_* 对业务库的 ALTER/UPDATE | mitigate | db.py:365/401/445 PRAGMA table_info 列集合嗅探幂等早退（表不存在 :366/:402/:446 return；列存在跳过）；db.py:421-430 (session_id,seq) 重复检测 raise RuntimeError 附行明细（不静默去重）；test_phase2_migration 8/8 绿（test_duplicate_seq_blocks_migration 断言 RuntimeError） | closed |
| T-02-02 | Repudiation | score_final 合并丢数据 | mitigate | db.py:452-456 COALESCE(final_score, score_final) 保序合并（final_score 优先，:453 注释「终局评分历史事实」）；test_score_final_merge 断言 final_score=3 覆盖 score_final=2 | closed |
| T-02-03 | Tampering | 存量模型 weight 被 7:3 重算 | mitigate | aggregate.py 全文件零 `UPDATE competency_item`（grep 唯一命中 :91 为注释；weight 只随 INSERT 新 model 写入 :183-191）；CATEGORY_RATIO 7:3 只对新聚合模型生效（config.py:28），存量行不动；test_legacy_columns_not_touched 绿 | closed |
| T-02-04 | DoS | 纯 gate 模型 total_ratio=0 除零 | mitigate | aggregate.py:88-94 `if total_ratio == 0` 全部 weight=0.0 + return（跳过尾差吸收，注释注明防 drift=1.0 压给单个 gate item）；test_weight_gate_items_zero 断言纯 gate 模型不抛 ZeroDivisionError 且全 0 | closed |
| T-02-05 | Tampering | 迁移中途失败留半态 | accept | init_db（db.py:462-477）逐迁移函数独立嗅探幂等——重跑即收敛；三迁移函数均「列存在即跳过」形态（AR 记录值见 Accepted Risks Log） | closed |

### 02-02（动态选题）

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-02-06 | Tampering | 动态 WHERE 拼接 SQL 注入 | mitigate | question_selection.py 全部 9 个 execute（:144/:212/:225/:253/:283/:377/:390/:544/:576）值全走 ? 参数化；列名/表名只以字面量进 SQL；Phase 2 无新增值插值（grep f-SQL 零命中，db.py:382/420 的 f-string 仅模块内常量列名 decl 拼接非用户输入）；唯一动态拼接 _collect_evidence_quotes（report.py:77-81）placeholder 由 `",".join("?" * len(item_ids))` 生成 + 值元组传参（Phase 1 既有） | closed |
| T-02-07 | Repudiation | 选题不可审计/不可重放 | mitigate | 选择理由七键 JSON（question_selection.py:555-564，含 seed 值）落 selection_reason；同会话同 seed（:610-612 sha256(session_id) 前 8 hex）；QUESTION_SELECTED 事件 payload 全量镜像（:586-588）；test_dynamic_dispatch_per_next 断言七键全在 | closed |
| T-02-08 | Tampering | LLM 输出进入选题决策 | mitigate | question_selection.py import 区无 llm 模块（:27-35 仅 hashlib/json/random/math/config/db/pipeline/state_events）；select_next_question 全程纯代码四层；CATEGORY_QUOTA grep 全库零残留 | closed |
| T-02-09 | DoS | 旧会话续答 500 | mitigate | _session_instance_state（:247-261）is_legacy 判定（selection_reason 全 NULL）→ :292-295 返回 {"legacy": True}；assessment.py:335-354 legacy 分支走旧 ORDER BY seq 派发 + 行耗尽 finish；test_legacy_session_continues 端到端证明 200 不 500 | closed |
| T-02-10 | Elevation | 题量配额被绕过（例外滥用） | mitigate | _exception_granted_items（:369-401）双载体（selection_reason JSON layer='exception' + REQUIRED_EXCEPTION_GRANTED 事件兜底）→ :313 pending 过滤即每 item 至多一次；_pick_exception_question 只取 medium/hard；PATH_UNAVAILABLE 事件留痕不静默（:321-324）；test_required_exception_after_exhaustion 双态（granted + unavailable）断言 | closed |

### 02-03（难度状态机）

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-02-11 | Tampering | LLM 操纵难度（输出"升级"指令） | mitigate | next_difficulty（difficulty.py:46-87）纯函数只收布尔/整数入参，快照计数器由代码推进；LLM 输出（InterviewObservation）无难度字段（schemas.py:89-96），无输入面 | closed |
| T-02-12 | Repudiation | 降级/升级不可解释 | mitigate | DIFFICULTY_* 事件 payload 判据摘要四键 criterion/evidence_counts/from_difficulty/to_difficulty（difficulty.py:215-223）；WR-05 fix 后复合触发输出组合态常量（:100-102 CRITERION_TWO_BELOW_AND_FOLLOWUP）；snapshot 持久化计数器（:228-231）；test_events_payload_and_same_transaction 断言四键 | closed |
| T-02-13 | Tampering | 事件与快照不同事务（口径漂移） | mitigate | update_path_state 模块零 conn.commit（difficulty.py 全文件 grep commit 零命中）——snapshot UPDATE（:228）+ append_event（:224）同调用者事务；assessment.py 两封存分支（:275/:304）在统一 commit 之前调 _advance_difficulty_state；test_events_payload_and_same_transaction 断言 snapshot current_difficulty == 事件 to_state | closed |
| T-02-14 | DoS | 降级误触发（非候选人源性失败计入） | mitigate | _EXCLUDED_FAILURE_STATES 七类元组（assessment.py:429-437）→ is_valid_failure 布尔传入；advance_snapshot（difficulty.py:137-142）is_valid_failure=False 时两计数器均不动；test_invalid_failure_not_counted 断言 fail 不增 | closed |

### 02-04（面试两层化）

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-02-15 | Elevation | LLM 输出 action/难度/finish 越权 | mitigate | InterviewObservation schema（schemas.py:89-96）无 action/难度/finish 字段——LLM 输出结构上不可能携带；action 由 decide_action 代码纯函数决定（interview.py:162-189）；INTERVIEWER_SYSTEM v2 明示「你不决定 action/难度/结束」 | closed |
| T-02-16 | Tampering | 非法 answer_state 注入 | mitigate | ANSWER_STATES Literal 11 态白名单（schemas.py:72-76）；ValidationError 降级 MODEL_UNCERTAIN（interview.py:222-230）；CR-01 fix 后 RuntimeError 亦降级（:216-221）——双降级不卡死不采纳；test_pydantic_rejects_invalid_state（literal_error）+ test_llm_failure_degrades_model_uncertain 双证明 | closed |
| T-02-17 | Tampering | 前端契约破坏（action 键变更) | mitigate | decision dict 5 基础键（interview.py:255-263）+ 扩展键只加不减；refused 内部值 API 层置换 _out_action="next"（assessment.py:226）；test_decision_contract_5keys + test_decision_extended_keys 锁定 | closed |
| T-02-18 | Repudiation | 观察结果无留痕 | mitigate | OBSERVATION_CLASSIFIED 每决策后落（assessment.py:239-243，payload answer_state/evidence_sufficient/action）；EVIDENCE_EVALUATED 封存时机落（:269-272/:297-300）；test_observation_events + test_evidence_evaluated_event_on_seal 断言 | closed |
| T-02-19 | DoS | 拒答死循环/会话卡死 | mitigate | decide_action 规则 1/2（interview.py:170-174）：首次 DECLINED → confirm，二次 → seal_refused 封存推进（D-24 一次性确认）；MODEL_UNCERTAIN 直接 next（:176-177）不卡死；WR-07 fix 后超长输入 422（assessment.py:181-183）不直达 LLM；test_refusal_confirm_skip + test_llm_failure_degrades_model_uncertain 证明会话不中断 | closed |
| T-02-20 | Tampering | mock 绕过裁决压测试真实度 | mitigate | _mock_interview（interview.py:93-132）输出与真实模式同构 dict → 同一 InterviewObservation Pydantic 校验 → 同一 classify_observation/decide_action 裁决链（D-23）——mock 模拟观察非绕过；四个 mock 分类测试走全链 | closed |

### 02-05（评分链）

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-02-21 | Tampering | 空 answer_key 客观题恒满分 | mitigate | score_question（scoring.py:124-133）空 key → score_final=None + score_state=INVALIDATED（不写 1 不写 5）；test_invalidated_objective 断言 None + missing_warnings 含 item + 不进 actual 平均 | closed |
| T-02-22 | Tampering | REFUSED 题被算低分拉低能力分 | mitigate | score_session（scoring.py:217-223）seal_reason='refused' → score_final=0 特殊状态值不经 LLM；aggregation.py:97-102 REFUSED 不进 item_scores_map、只进 refusals 列表；test_refused_excluded_from_denominator 对照同构会话断言均值只含 SCORED 行 | closed |
| T-02-23 | Repudiation | DROP final_score 丢历史分数 | mitigate | db.py:452-459 次序合同：COALESCE 合并（:455）先于 DROP（:459）同函数相邻执行；幂等嗅探 "final_score" in cols 才执行；_DDL 已去列（db.py:199-211 无 final_score）；test_score_final_merge 断言合并值落 score_final 且列已 DROP；git 原子 commit 存在回退基线 | closed |
| T-02-24 | Tampering | 聚合静默吞排除态 | mitigate | aggregation.py:92-108 三路分流：SCORED 进分母 / REFUSED 进 refusals / 四排除态进 missing_warnings（结构化列表 item_id+std_name+reason，不隐式转 0 不静默 D-28）；返回 dict 只加不减（:180-181）；test_invalidated_objective + test_report_chain_end_to_end 断言 | closed |
| T-02-25 | Information Disclosure | INVALIDATED 细节泄露内部阈值 | accept | reason 文本仅「题库无效：客观题缺 answer_key（REF-5.2/8.1）」等定性文案（scoring.py:131）——grep 无阈值/锚点数值；前端 web/src 全目录零消费 INVALIDATED 明细（报告展示属 Phase 5 契约） | closed |

*Status: closed · open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-02-05 | T-02-05 | 迁移中途失败半态——init_db 每函数独立幂等（嗅探早退），重跑即收敛；SQLite ALTER 逐列原子性由事务提交粒度保证；演示数据允许重跑（D-15） | user（plan 02-01 定案） | 2026-09-04 |
| AR-02-25 | T-02-25 | INVALIDATED reason 文本无敏感阈值——现有文案为定性描述；报告展示层契约属 Phase 5 | user（plan 02-05 定案） | 2026-09-04 |

*Accepted risks do not resurface in future audit runs.*

---

## Code-Review Fix Overlays（审计时序注记）

Threat model 写于计划期；执行期 code-review（02-REVIEW.md）修复 10 项（merge b6399e6）。以下威胁的缓解形态被 fix 强化/覆盖，本审计按 HEAD 代码验证：

| Threat | Fix 影响 | 验证结论 |
|--------|----------|----------|
| T-02-14/T-02-06/T-02-11 | CR-02：update_path_state 迁移段清零档内计数（difficulty.py:210-214）——七类排除的难度承接正确性收口 | 强化，无回退 |
| T-02-16/T-02-19 | CR-01：call_llm_json RuntimeError 降级 MODEL_UNCERTAIN（interview.py:216-221）——修复原 500 面（决策已 commit 但 assistant/事件全丢） | 强化，500 面已消除（test_llm_failure_degrades 200 断言） |
| T-02-13 | WR-01：封存点三 helper（_question_item_id/_instance_followup_count/_stable_evidence_light）改接调用方主 conn（assessment.py:370-423）——消除事务内双连接交错窗口 | 强化，同事务契约真实闭合 |
| T-02-07 | WR-02（total_count 例外计数单源 exception_granted_items）+ WR-03（difficulty_source 审计键） | 强化，可审计性增强 |
| T-02-10 | WR-04：例外路径 §10.5/§11.2 张力仅落 exception_tension_note 可观测性注记（question_selection.py:569-570），不改刚性行为——SSOT 裁决留 Phase 3 硬关口（02-DECISIONS [02-013]） | 已在位（张力注记 + 决议留档），非 open |

---

## Security Audit Trail

| Audit Date | Threats Total | Verified | Open | Run By |
|------------|---------------|----------|------|--------|
| 2026-09-04 | 25 | 25 | 0 | gsd-secure-phase (gsd-security-auditor verification @ 0c608c4) |

Audit method: register authored at plan time（五份 PLAN 均含 `<threat_model>` 块，25 威胁）；逐项核对 HEAD 实现证据（代码位置见 Mitigation 列，grep 计数 + 通读 question_selection/difficulty/interview/scoring/aggregation/assessment/readiness 全量）；全部测试在 tempfile 库逐文件运行——migration 8 + weights 5 + selection 9 + difficulty 13 + interview 13 + scoring 7 + p0_security 10 + p0_chain 11 + m5 7 全绿，m6 脚本 43 通过、question_bank 脚本 25 通过（合计 151 项）。未触碰 data/app.db；未修改实现文件（工作树仅新增本文件）。

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)（23 mitigate + 2 accept）
- [x] Accepted risks documented in Accepted Risks Log（AR-02-05/AR-02-25）
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-04
