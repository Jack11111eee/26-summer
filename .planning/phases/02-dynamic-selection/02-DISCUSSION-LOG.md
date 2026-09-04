# Phase 2: 动态选题与有界循环 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-03
**Phase:** 2-动态选题与有界循环
**Mode:** auto（章程 §1 授权代确认——无人值守段推荐项自动选取，逐条留痕；06-01 关口包回呈）
**Areas discussed:** 表结构演进的迁移策略, mock 模式与测试断言面, score_live 的留者身份, 难度状态机的数据载体, selection_reason 审计格式, 事件记录粒度, 题目质量代理（第四层排序）, 7:3 存量模型处置

---

## 表结构演进的迁移策略

| Option | Description | Selected |
|--------|-------------|----------|
| ALTER ADD COLUMN + 代码校验 | 新列直兼容，旧 CHECK 不动，业务库平滑直升 | ✓ |
| 表重建（rebuild） | 照 _migrate_llm_trace 惯例整表重建 | |
| DROP + 重装 | 演示项目直接重建库 | |

**User's choice:** [auto] 推荐项——ALTER（理由：业务库平滑直升；N11 新列避免 CHECK；Phase 6 schema_version 只登记）
**Notes:** 旧 question_score.final_score→score_final 合并在迁移函数内做一次（数据搬运归属 02-01 DDL 层）。

## mock 模式与测试断言面

| Option | Description | Selected |
|--------|-------------|----------|
| mock 双轨制（规则分类器共享 Pydantic 契约） | mock 模拟观察输出而非绕过裁决，分类语义可测试 | ✓ |
| mock 仅保底 action | 维持现行「长度→followup/next」绕过新分类 | |
| 真实 LLM 测试 | 离线演示断裂，违反 D-005 | |

**User's choice:** [auto] 推荐项——mock 双轨制
**Notes:** 旧测试只改断言不重构风格（Phase 1 D-09 前例）；统一 pytest 收集属 Phase 6 REF-7.4。

## score_live 的留者身份

| Option | Description | Selected |
|--------|-------------|----------|
| 保留列（导航 + 偏差分析） | 消费方=难度状态机输入 + Phase 6 双分背离候选 | ✓ |
| 删除列 | 彻底清除 score_live | |
| 移入独立表 | 过程性数据分离 | |

**User's choice:** [auto] 推荐项——保留（SSOT §12.4 演进后 DDL 明确保留 score_live 列；§17 差值仅用于偏差分析）
**Notes:** 只切断进入 final 的合成路径（50/50 废除，D-26）。

## 难度状态机的数据载体

| Option | Description | Selected |
|--------|-------------|----------|
| path_state_snapshot JSON 列 | §12.2 列名即承载意图，事件同事务写 | ✓ |
| 实时派生查询 | 从实例+事件实时计算 | |
| 独立难度状态表 | 新表 item_difficulty_state | |

**User's choice:** [auto] 推荐项——snapshot 列（不建新表；派生查询跨实例聚合不可审计）

## selection_reason 审计格式

| Option | Description | Selected |
|--------|-------------|----------|
| 结构化 JSON（四层命中记录） | 机器可解析，Phase 5/6 消费 | ✓ |
| 中文可读串 | 人类友好但不可解析 | |
| 双写 | 存储翻倍，中文报告层生成即可 | |

**User's choice:** [auto] 推荐项——JSON（SC-1 「可审计」逐字要求）

## 事件记录粒度

| Option | Description | Selected |
|--------|-------------|----------|
| SC 要求最小集 | QUESTION_SELECTED/ACTIVATED/SEALED + DIFFICULTY_* 三事件 + OBSERVATION_CLASSIFIED/EVIDENCE_EVALUATED | ✓ |
| 全枚举激活 | §13.2 可写事件全写 | |
| 仅状态迁移事件 | 只写 from/to 型 | |

**User's choice:** [auto] 推荐项——SC 最小集（Phase 1 QUESTION_ANSWERED 不改名；CONTROL_*/FORM_* 留 Phase 3）

## 题目质量代理（第四层排序）

| Option | Description | Selected |
|--------|-------------|----------|
| 显式禁用（三键排序） | chain→weight→稳定种子，已确定性可审计 | ✓ |
| 入库时间乱序代理 | 用生成时间作扰动因子 | |
| 质量=重写次数等启发式 | SSOT 无定义，臆造 | |

**User's choice:** [auto] 推荐项——禁用（§31 校准红线：无 SSOT 指标不臆造）
**Notes:** DECISIONS 记录禁用依据；未来 SSOT 校准后可独立小改动补回。

## 7:3 存量模型处置

| Option | Description | Selected |
|--------|-------------|----------|
| 存量不重算，新模型自动 7:3 | 分数是历史事实 D-003；confirmed 不被静默覆盖 §8.3 | ✓ |
| 全量重算存量 weight | 修改已确认模型 | |
| 存量模型立即阻断开考 | 过度激进，Phase 4 有升版路径 | |

**User's choice:** [auto] 推荐项——存量不动
**Notes:** **N 默认值 = 未决——SSOT §31 开放参数，关口包呈现用户裁决**（auto 模式不代决 SSOT §31 校准项，依据章程 §2.2 谨慎处理）。

---

## Claude's Discretion

- 新列默认值与迁移函数形态（对齐 _migrate_* 手写嗅探式惯例）
- path_state_snapshot JSON 内部字段结构
- 测试文件组织与断言粒度（pytest 可收集 + 单文件单进程纪律内）
- 7:3/tier 公式单元测试边界用例选择

## Deferred Ideas

- question_bank 列改造量若超大 → plan 层评估一次性重建 vs 纯 ALTER（D-001 无冲突）
- 综合题/等值组（REF-3.8/3.9）——登记不排期
- 「题目质量」真实指标——SSOT 校准后回补
- interviewer 真实 prompt 重构——Prompt 模块周期（D-030）
