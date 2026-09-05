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
