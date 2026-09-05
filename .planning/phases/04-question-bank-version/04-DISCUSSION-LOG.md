# 04-DISCUSSION-LOG.md — Phase 4 讨论记录（人工审计用，非下游消费）

**Gathered:** 2026-09-05
**Mode:** auto（章程 §1——例行关口代确认，逐条依据 = SSOT/既定决策/代码现状）

## 域边界

题库绑定 confirmed 模型版本（升版须重建否则阻止开考）+ 生成失败可见 + orphan 路由修复 + 模型编辑校验。五 REF：REF-2.5/3.4/7.1/7.2/8.4。

## 灰区与推荐项（auto 选取，未向用户逐条提问）

| 灰区 | 可选方向 | 选取 | 依据 |
|------|----------|------|------|
| model/version 绑定机制 | A 消费侧过滤 / B 升版标旧题 inactive | A | SSOT §9.2「有效题目 = active 且 model/version 匹配」——旧题保留审计、靠 version 过滤 |
| 幂等判重键 | 原 (position_id, std_name, category, difficulty) / 升级加 model_version | 升级 | v2 判重看 v1 active 行会整链跳过（WR-03 逻辑 + 升版语义冲突） |
| general 题（experience/qualification）版本绑定 | 同绑 model_version / 忽略（永不被选） | 同绑（一致性） | 生成即绑，虽 selection 已排除无功能影响 |
| 生成失败可见落点 | A readiness detail + B admin todos 明细 | A+B | REF-8.4「状态 + 管理员待办可见」双落点 |
| rubric_version 取值 | "v1" 常量 / 模型版本号 / 留 NULL | "v1" | rubric 每次生成，版本标记起步 v1（真实版本管理随 rubric 工程化再议） |
| item_id 填充 | 落库一并填 / 留 NULL 靠 std_name 匹配 | 一并填 | 循环内可得，§9.2 item_id 绑定低成本对齐 |

## Claude's Discretion（无用户裁量，交 planner 定实现细节）

- 幂等判重 SQL 形态、readiness tier 计数 model_version 谓词落点
- selection `_load_candidate_rows` 签名改造与 model_version 传参路径
- admin todos 失败明细字段命名（`question_bank_failed` 新键 vs 内嵌）
- 测试组织（test_phase4_* 单文件单进程三件套）

## Deferred Ideas（登记不排期）

- 等值组 equivalence_group_id（REF-3.8）、综合题 integrated_bindings_json（REF-3.9）
- measurement_target/evidence_requirement 填充（Phase 5）
- schema_version 收口（Phase 6）
- general 题生成彻底移除（Phase 3 D-32 收尾，若需）
- rubric_version 真实版本演进语义

---

*Phase: 4-题库版本绑定与模块一收口*
*Mode: auto（章程 §1）*
