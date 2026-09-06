# 05-DISCUSSION-LOG.md — Phase 5 讨论记录（人工审计用，非下游消费）

**Gathered:** 2026-09-05
**Mode:** auto（章程 §1——例行关口代确认，逐条依据 = SSOT/既定决策/代码现状）

## 域边界

证据链（evidence_spans 结构化 + trace_link 审计链闭合 + 旧 ref_id 导入）+ 报告契约（item_measurement 裁决 + IMPUTED 补算 + required 缺失 PROVISIONAL + 报告状态机/七项校验/版本化/发布 + 失败可见）+ 反馈字段补全。九 REF：REF-2.3/2.10/5.4/5.5/5.6/5.9/7.3/8.3/8.7。

## 灰区与推荐项（auto 选取，未向用户逐条提问）

| 灰区 | 可选方向 | 选取 | 依据 |
|------|----------|------|------|
| evidence_spans 的 offset/hash 来源 | A LLM 直接输出 offset / B 代码定位（LLM 给 quote 文本） | B | D-003「LLM 不碰数字」——offset 是确定性代码计算，LLM 只给文本 quote 防幻觉 |
| evidence_quote 与 evidence_spans 关系 | A 替换（删 evidence_quote）/ B 并存（quote 展示 + spans 权威） | B | 展示后向兼容 + 前向结构化；§12.4 只加 evidence_spans_json 不删 evidence_quote |
| item_measurement 形态 | A 新表 / B 内存中间结构 | B | D-018「21 张表」清单无 item_measurement；§19 pseudocode 是裁决记录非持久实体 |
| item 等级计算 | A 按题数均分（现状）/ B item_measurement adjudicate | B | REF-5.4 明令废弃按题数均分；§19 裁决规则（不按来源加权不按题数重复乘） |
| 报告版本化 key | A report_id 每版本新行 / B (session_id, version) 复合主键 | A | 现行 PK=report_id + feedback FK→report_id 天然防外键断裂；读最新已 ORDER BY DESC LIMIT 1 |
| 重复生成语义 | A 409 拒绝（现状）/ B 允许重生成新版本 | B | REF-5.9 SC-3「重复生成不再 DELETE 覆盖」；409 仅保留 GENERATING 进行中防并发 |
| 报告失败可见落点 | A report_status=FAILED 行 + B TASK_FAILED 事件 | A+B | REF-8.3「FAILED 态可见」+ 事件留痕双落点；替代超时猜测 |
| 发布流程前端范围 | A 后端优先+最小前端 / B 完整 admin 发布 UI | A | Phase 4 [04-010] 前端零破坏先例；后端状态机完整 + 前端轮询读 report_status |
| trace_link trace_id 取值 | session 级关联 / llm_trace.trace_id / 合成 audit id | planner 定 | §13.3 只定 DDL+枚举，未定 trace_id 语义——Claude's Discretion |
| 旧 ref_id 导入 entity_type 推断 | 按 call_type 映射 / 统一按实体表命中 | 命中实体表为准 | get_session_traces 现状「ref_id IN 并集」——命不中的保留 ref_id 不拆 |

## Claude's Discretion（无用户裁量，交 planner 定实现细节）

- trace_link 各环节写点与 trace_id 取值
- evidence_spans 定位算法（子串定位/多命中策略/hash 算法）
- item_measurement 中间结构字段命名与 adjudicate 具体裁决规则
- 报告版本号生成规则、七项校验实现形态、request_report 409 精确边界
- 测试组织（test_phase5_* 单文件单进程三件套）

## 开放参数（关口包呈报项，非本 phase 决定）

- **补算复核阈值（§31-3）**：IMPUTED 补算比例超阈值 → 临时报告 + 人工复核。plan 落 config 占位 + 常量注释，数值不代决（同 N=10 / MAX_CONTEXT_TOKENS 先例）。

## Deferred Ideas（登记不排期）

- trace 保留期/脱敏（§31-5）——Phase 6 数据治理
- 综合题 integrated measurement_source 实现（REF-3.9 延后）
- score_live/score_final 双分背离 bad case 自动候选（REF-5.11）——Phase 6
- 完整 admin 报告发布/人工复核 UI（若本 phase 仅最小前端，随 Phase 6 E2E 收口）
- 报告版本历史浏览/对比 UI（VersionHistory.vue 是否并入属 Phase 6 裁量）

---

*Phase: 5-证据链与报告契约*
*Mode: auto（章程 §1）*
