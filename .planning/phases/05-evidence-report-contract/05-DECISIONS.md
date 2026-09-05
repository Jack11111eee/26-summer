# 05-DECISIONS.md — Phase 5 决策留痕

## 代确认记录（章程 §1/§4：auto 模式，事后留痕）

每条 = 日期时间 / 所在步骤 / 决定内容 / 依据。

| ID | 日期 | 步骤 | 决定 | 依据 |
|----|------|------|------|------|
| [05-001] | 2026-09-05 | discuss（auto） | D-55 evidence_spans 结构化 = LLM 给 quote 文本、代码定位 offset/hash；evidence_quote 并存（展示+后向兼容） | D-003「LLM 不碰数字」+ §12.5 + score.py P-score 现状 |
| [05-002] | 2026-09-05 | discuss（auto） | D-56 trace_link 新表（§13.3 DDL 照抄）+ link_role 代码校验；写点/trace_id 交 planner | §13.3 + N11 + D-020 |
| [05-003] | 2026-09-05 | discuss（auto） | D-57 旧 ref_id 导入 trace_link（按实体表命中推断 entity_type，命不中保留原值） | REF-8.7 + admin/trace.py get_session_traces 现状 |
| [05-004] | 2026-09-05 | discuss（auto） | D-58 item_measurement = 内存中间结构（非新表），adjudicate 替换按题数均分 | D-018 21 表清单 + §19 + REF-5.4 |
| [05-005] | 2026-09-05 | discuss（auto） | D-59 IMPUTED 补算（§20.1 公式 + 覆盖率 + O=∅ NO_VALID_OBSERVATION）；阈值 = §31-3 关口包呈报 | §20.1 + REF-5.5 + §31-3 |
| [05-006] | 2026-09-05 | discuss（auto） | D-60 required 缺失 → PROVISIONAL + HUMAN_REVIEW_REQUIRED | §20.2 + REF-5.6 |
| [05-007] | 2026-09-05 | discuss（auto） | D-61 report 表演进（report_status/review_status/version/发布字段），DELETE+INSERT → 不可变版本化 | §21.1 + REF-5.9 |
| [05-008] | 2026-09-05 | discuss（auto） | D-62 版本化 key = report_id 每版本新行，feedback FK 防外键断裂；重复生成允许新版本（409 仅 GENERATING 进行中） | REF-5.9 SC-3 + feedback DDL FK→report_id |
| [05-009] | 2026-09-05 | discuss（auto） | D-63 七项一致性校验代码执行，任一失败 → FAILED | §21.1 + §17「评分失败→FAILED」 |
| [05-010] | 2026-09-05 | discuss（auto） | D-64 发布流程 = POST publish 端点 + 前端最小化（零破坏，Phase 4 [04-010] 先例） | §21.1「明确点击发布」+ REF-5.9 |
| [05-011] | 2026-09-05 | discuss（auto） | D-65 报告生成失败显式可见 = FAILED 行 + TASK_FAILED 事件 | REF-8.3 + _generate_report_task 现状静默 |
| [05-012] | 2026-09-05 | discuss（auto） | D-66 feedback 补 user_id/note/reviewer/reviewed_at + admin note 持久化 + question_reviews 补 item_id | REF-7.3 + feedback.py note 丢弃现状 |
| [05-013] | 2026-09-05 | discuss（auto） | D-67 REVIEW_* 事件（FEEDBACK_RECEIVED / REPORT_PUBLISH_CONFIRMED）落地 | §13.2 + D-031 |

## 边界/观察（非代确认，记档）

- **submit_feedback item 归属校验已做**：assessment.py:1124-1130 已 JOIN report→session→competency_item 校验 item 属于对应模型——REF-7.3 该条已满足，本 phase 保留不动（D-66 只补字段 + note 持久化）。
- **report 覆盖生成的 FK 断裂风险**：现行 generate_report `DELETE FROM report WHERE session_id=?` 若 SQLite FK 开启会连带/阻断 feedback（feedback.report_id FK→report）——版本化（旧行保留）根治，与「报告不可变版本化」同一动作。

## 开放参数（SSOT §31 类，关口包呈报）

- **补算复核阈值（§31-3）**：IMPUTED 补算比例超阈值 → 临时报告 + 人工复核。plan 落 config 占位，数值不代决。

## 硬关口 A 用户裁决

| 开放项 | 用户裁决 | 落点 |
|--------|----------|------|
| 总分归一化公式（§20.1 vs §20.3） | **统一 `(score−1)/4`**（选择 A，作废 `score/5`） | 05-02 `_normalize_score` 两分支 + 主循环；附带 SSOT §20.3 补公式（另走 §14 原子 commit） |
| 补算复核阈值（§31-3） | **`0.2`**（coverage_ratio > 0.2 → PROVISIONAL + 人工复核） | 05-02 `IMPUTE_RATIO_THRESHOLD = 0.2` |
| 存量 report 行回填默认值 | **`PUBLISHED` + `NONE` + `version=1`** | 05-03 `_migrate_report_phase5` 回填 |

附注（非硬关口，已定值透明记录）：review_status 六值并集（D-60 `HUMAN_REVIEW_REQUIRED` 并入 §21.1 五值）；七项校验「录用判断」词表 = D-002 红线词表（Phase 6 bad case 收口）。

## code-review + fix 记录（§1 代确认：Critical/Warning 自动 --fix）

| ID | 日期 | 步骤 | 决定 | 依据 |
|----|------|------|------|------|
| [05-014] | 2026-09-05 | code-review --fix（auto） | 12 发现（1 Critical CR-01 + 6 Warning WR-01~06 + 5 Info IN-01~05）；自动 fix Critical+Warning 共 7 条，Info 搁置记档 | 章程 §1「Critical/Warning 自动 --fix」「Info 搁置不跑 --all」 |

修复落地（7 条，原子 commit，`05-REVIEW-FIX.md` status=all_fixed）：
- CR-01 冲突 human_review 传导 PROVISIONAL/HUMAN_REVIEW_REQUIRED（aggregation.py）
- WR-01 coverage_ratio 分子分母同口径 + 补算复核改 imputed 比例
- WR-02 校验①改用未四舍五入内部分（展示层才 round）
- WR-03 publish 同步 review_status=CONFIRMED
- WR-04 report trace 导入回退映射到 assessment_session
- WR-05 复用 GENERATING 占位行（不残留孤儿占位、不污染版本号）
- WR-06 红线校验⑦只扫 LLM 文案（strengths/weaknesses/suggestions），不扫候选人答案/题干

## verify 硬关口停车（§2 类阻断缺口，非 §1 可代确认）

| 项 | 内容 |
|----|------|
| ID | [05-015] |
| 日期 | 2026-09-05 |
| 步骤 | verify（gsd-verifier）|
| 结果 | **gaps_found**，4/5 must-haves（成功率 4/5）|
| 缺口 | SC #2 前端展示缺口：`web/src/views/assessment/Report.vue` 未渲染 IMPUTED 特殊视觉标记、未展示 coverage 字典（观察覆盖率/真实观察数/缺失原因）。后端 `imputed=True` + `coverage{observed_count/imputed_count/total_measureable/coverage_ratio/missing_reasons}` 已完整透传进 report_data，「数据已就位、前端未接线」 |
| 契约依据 | SSOT §20.1「IMPUTED…必须特殊视觉标记 + 展示观察覆盖率/真实观察数/缺失原因」、§21.1「雷达图 IMPUTED 特殊标记」；Phase 5 SC #2 |
| 处置 | **停车等用户裁决**。闭合需 gap-closure 计划（→ 触及 §2.1 plan 审查硬关口）+ 存在 UI 呈现歧义（标记形态/覆盖率展示布局）。关联非阻断 Info：IN-02（itemReason std_name 匹配）可与本缺口同任务收口 |
| 关联需求 | REF-5.5（PARTIAL，仅前端展示缺）|

后端测试全绿（evidence 6 / report 11 / feedback 3 / m6 44 / m7 5）；`test_p0_chain.py::test_completed_session_guardrail` 为既有 [04-011] 题库版本化涟漪（缺种子题），非本 phase 回归，记档待 Phase 6。

## gap-closure 计划审查 + 执行记录（§2.1 计划审查硬关口：用户批准）

| ID | 日期 | 步骤 | 决定 | 依据 |
|----|------|------|------|------|
| [05-016] | 2026-09-05 | plan 审查（硬关口） | 05-05 gap-closure 计划（IMPUTED 标记 + 覆盖率展示 + 雷达标记 + IN-02）经用户明确「批准」 | §2.1 计划审查 |
| [05-017] | 2026-09-05 | execute（05-05） | 4 任务落地：report.py 雷达 indicators 补 imputed；Report.vue 明细表补算徽标 + coverage 摘要 + 雷达轴「（补算）」后缀 + itemReason 改 item_id 匹配 | 后端测试全绿 + `npm run build` 通过 |

执行落地 commit `fb4d139`；`05-05-SUMMARY.md` status=complete。

遗留（非阻断）：缺失原因 `reason` 为内部 score_state 码（INVALIDATED 等）或「qualification 缺失（不补算）」中文串，前端按原样展示未做码→中文映射，SSOT「展示缺失原因」契约已满足。
