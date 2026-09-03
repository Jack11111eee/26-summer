# 非 Prompt 设计继续收敛讨论稿：未决事项、建议方案与对齐问题

> **文档性质：讨论稿，不是 SSOT，不是实施方案。**  
> **日期：2026-09-01**  
> **依据：** `design/checkpoint-2026-09-01-项目全貌与设计收敛状态.md`，并参考现有总设计文档、需求文档、模块设计文档及当前代码静态核对结果。  
> **用途：** 将 checkpoint 中所有仍需继续细化、部分收敛或尚未收敛的事项集中列出，供后续逐项讨论和确认。  
> **处理规则：** 本文中的“建议”“推荐”“候选方案”均不是用户已经确认的设计；在用户确认前，不修改 SSOT，不修改业务代码，不把本文作为实施依据。Prompt 的具体内容仍按既定安排暂缓，本稿只处理非 Prompt 的边界、契约和工程问题。

---

## 0. 阅读说明与总体判断

checkpoint 中已经收敛的是总体方向：

```text
JD / 能力模型
→ 有界动态测评
→ 证据与终局评分
→ 人才画像报告
→ trace、反馈、评测与人工复核
```

尚未收敛的主要不是“要不要做动态测评”，而是能否把方向落实为可执行、可审计、可测试的：

- 数量公式；
- 配额与覆盖规则；
- 难度状态机；
- 综合题评分；
- 缺失状态和聚合数学；
- 数据库字段及事件契约；
- 表单与计时协议；
- 证据链；
- 权限、安全、公平和上线验收标准。

本稿把事项分为：

- **A 类：文档治理和范围边界**；
- **B 类：题量、题库和动态路径**；
- **C 类：评分、综合题、缺失和证据**；
- **D 类：状态事件、数据库和 API**；
- **E 类：表单、计时、恢复和上下文**；
- **F 类：安全、权限、隐私、公平和人工复核**；
- **G 类：异步任务、部署、测试和上线验收**。

每一项均使用以下结构：

1. 当前已经确认的边界；
2. 尚未收敛之处；
3. 我的建议；
4. 需要我们对齐的问题。

---

# A. 文档治理和范围边界

## A1. SSOT 路径和版本分叉

### 当前已知

checkpoint 约定的 SSOT 是：

```text
design/总设计文档.md
```

但仓库同时存在 `design/final-design/` 下的定稿文档，且旧总设计文档与最新讨论结果已有多处冲突。

### 尚未收敛

- 新总设计文档最终使用哪个路径；
- `final-design/` 是正式文档、阶段副本还是视觉定稿目录；
- 旧文档在新文档完成前是否冻结；
- 多份文档的优先级如何避免再次漂移。

### 我的建议

新总设计文档开始撰写前，先确定一个唯一正式路径。建议继续使用：

```text
design/总设计文档.md
```

若保留 `final-design/`，应在目录或文件名中明确标为历史/阶段副本，不再与 SSOT 并列。

在新 SSOT 获授权前，旧 SSOT 不再继续追加新的设计决策；新的讨论只写入临时讨论稿或本稿的后续版本。

### 需要对齐

1. 唯一 SSOT 是否确定为 `design/总设计文档.md`？
2. `final-design/` 的正式语义是什么？
3. 是否接受“新 SSOT 完成前冻结旧 SSOT”的规则？

---

## A2. 里程碑“实现、契约完成、验证完成”的状态定义

### 当前已知

代码中已经有 M1–M7 的不少功能，但动态状态机、评分链、表单、任务可靠性等仍未完全兑现。文档变更日志的“已落地”和章节中的“待实施/部分落地”不一致。

### 我的建议

每个里程碑分别记录四个维度：

```text
implemented          已存在代码
contract_complete    已满足正式设计契约
verified              已通过测试和验收
production_ready     已满足上线要求
```

例如某模块可以是：

```text
implemented = true
contract_complete = false
verified = false
production_ready = false
```

这样“有页面/有接口”不会被误解为“已经完成设计和上线验证”。

### 需要对齐

是否接受以后所有里程碑均使用上述四维状态，而不再只写“已完成/未完成”？

---

## A3. 系统范围和招聘决策边界

### 当前已知

系统只提供：

- 能力项评分；
- 人才画像报告；
- 测评证据；
- 过程和异常记录；
- 人工复核支持。

系统不做：

- 最终录用判断；
- 最终录用排序；
- 自动通过/淘汰；
- 代替企业作出最终招聘决定。

### 尚未收敛

旧文档中仍有“录用结论”“排序”“门槛判断”等可能超出范围的表述。这里需要区分：

- `qualification gate` 的资格事实核验；
- 报告中的风险/缺失提示；
- 系统是否自动给出招聘结论。

### 我的建议

可以保留结构化资格核验和报告警告，但明确：

```text
gate_result = 事实核验结果
report_warning = 测量完整性/资格信息提示
hiring_decision = 系统不产生
```

即使 gate 未满足，也只生成“资格事实未满足/待人工核验”的结果，不生成自动淘汰或录用决定。

### 需要对齐

是否接受将所有“录用判断/排序”改写为“事实核验、能力画像、人工复核信息”？

---

# B. 题量、题库和动态路径

## B1. 普通主问题目标数量 `N`

### 当前已确认

- `N` 是普通题计划数量的概念；
- hard/soft 基础数量按 7:3 分配；
- required 例外、综合题、followup 单独统计；
- 综合题最多两题；
- followup 不计普通主问题数量。

### 尚未收敛

- `N` 是固定值还是岗位级策略；
- 是否随普通能力项数量和最低覆盖生成；
- 是否存在系统最小值/最大值；
- `N` 与 40 分钟上限如何协调；
- 题库不足时是否允许缩减或阻止开考。

### 我的建议

将 `N` 设为**岗位级测评策略配置**，同时由系统提供硬边界：

```text
ordinary_plan_count = N_policy
ordinary_exception_count = E
integrated_plan_count = I
followup_count = F
```

不要简单使用“能力项数量乘固定倍数”，因为岗位模型规模、required 数量和题库完整性差异很大。

岗位策略可给出目标范围，代码负责检查：

1. required 最低覆盖是否可满足；
2. 题库是否足量；
3. 是否超出系统允许的普通题数量范围；
4. 是否有合法综合题槽位。

`N` 的默认值可以后续用真实体验和 40 分钟测试确定，当前不建议在未测量前把某个数字写成普遍真理。

### 需要对齐

1. `N` 是否由岗位策略配置？
2. 是否设置系统 `N_min/N_max`？
3. required 最低覆盖是否允许使实际普通题数超过 `N`？
4. `N` 不可行时，是阻止创建 session，还是允许带不完整状态开始？

我的推荐是：**岗位级目标 + 系统硬边界 + required 例外独立增加 + 不可行时阻止正常开考。**

---

## B2. hard/soft 7:3 的整数配额

### 当前已确认

```text
hard_skill : soft_skill = 7 : 3
```

同时作用于：

1. 普通 item 的最终权重总和；
2. 普通主问题的基础数量比例。

### 尚未收敛

- `N` 为奇数时如何取整；
- 某一大类不存在有效 item 时如何处理；
- 有 item 但无合法题库时是否转移题量；
- 转移是否需要告警和事件。

### 我的建议

对正常存在的两个大类使用最大余数法：

```text
raw_hard = 0.70 × N
raw_soft = 0.30 × N
```

先取整数部分，再将剩余题量分配给小数部分较大的类别。例如：

| N | hard | soft |
|---:|---:|---:|
| 8 | 6 | 2 |
| 9 | 6 | 3 |
| 10 | 7 | 3 |
| 11 | 8 | 3 |
| 12 | 8 | 4 |

这只是取整算法建议，表中的数值不是另行确认的固定题量。

边界建议：

- 没有某大类有效 item：现有大类重新归一化；
- 有 item 但题库不足：默认不静默转移，应报告题库/模型不可测；
- 若产品确实允许转移，必须是岗位策略明确允许，并记录 `quota_transfer` 原因。

### 需要对齐

1. 是否接受最大余数法？
2. 有 item 但题库不足时，默认阻止开考还是允许转移？
3. 如果允许转移，是否必须写入事件和报告警告？

---

## B3. `required/preferred/plus` 类内配额

### 当前已确认

三层影响：

- 原始重要性；
- 题量配额；
- 覆盖优先级。

三层不再额外乘最终分数；最终业务权重由 `item.weight` 表达。

### 尚未收敛

- required 是否每个至少一题；
- preferred 是否有最低覆盖；
- plus 是否允许零题；
- 类内配额按 tier 固定比例还是按 item.weight；
- required 最低覆盖与基础配额冲突时的精确优先级。

### 我的建议

采用两阶段策略：

**第一阶段：刚性覆盖**

对每个有合法普通题的 required item，至少安排一次普通题测量机会。

**第二阶段：剩余资源分配**

在剩余普通题配额中，根据：

```text
item.weight
+ tier 优先级
+ 未覆盖程度
+ 题库质量
+ 当前路径状态
```

分配其他题。

我的建议性优先级是：

```text
required：刚性最低覆盖
preferred：策略级软最低覆盖
plus：剩余资源优先覆盖，允许零题
```

如果 required 最低覆盖超过基础配额，允许触发 `required_quota_exception`，但例外要有独立上限。

### 需要对齐

1. 每个有效 required item 是否至少一题？
2. preferred 是否需要最低覆盖？
3. plus 是否允许零题？
4. tier 内分配是否参考 `item.weight`？
5. required 例外是否一定计入 `ordinary_exception_count`？

---

## B4. 题库不足、模型版本隔离和开考前可行性

### 当前已知

当前实现可能出现：模型已确认但题库仍在异步生成，session 已创建且题目为零；题库还可能没有明确绑定模型版本，导致新模型复用旧题。

### 尚未收敛

- 题库生成状态如何表达；
- session 创建前检查哪些条件；
- 题库部分成功时如何处理；
- required item 无题时是否允许开考；
- confirmed 模型更新后旧题是否必须重新生成。

### 我的建议

增加开考前的“可测量性检查”：

```text
confirmed model
→ question bank readiness
→ quota feasibility
→ form schema readiness
→ session can start
```

至少检查：

- position 处于可用状态；
- 模型版本为 confirmed；
- 题库绑定正确的 model/version；
- required item 有合法普通题；
- hard/soft 配额可满足，或策略明确允许转移；
- 综合题目标有合法题目；
- qualification 所需 schema 已可用。

不可开考时使用明确状态，例如：

```text
ASSESSMENT_NOT_READY
QUESTION_BANK_GENERATING
QUESTION_BANK_INCOMPLETE
MODEL_NOT_MEASURABLE
```

而不是创建一个表面上 `in_progress`、实际上没有题的 session。

### 需要对齐

1. 是否接受“未通过可测量性检查不得创建正常测评 session”？
2. required 题库不足是否一律阻止开考？
3. confirmed 新模型版本是否必须独立生成/使用题库？
4. 题库部分成功时是否允许管理员手工发布可用子集？

---

## B5. 动态选题的执行顺序

### 当前已确认

总体原则是：合法性过滤、required 优先、配额、难度、chain、权重和题目质量共同参与。

### 尚未收敛

这些条件的绝对优先级还没有形成伪代码和边界测试，尤其是：

- chain 是否让位给 required；
- 配额已满但 required 未覆盖时怎么处理；
- 当前 item 需要降级时能否选其他 item；
- 题库无合法候选时如何转入异常状态。

### 我的建议

不要把所有条件混成一个大排序函数，分为四层：

```text
第一层：合法性过滤
第二层：硬约束过滤
第三层：覆盖优先级
第四层：候选题排序
```

伪代码方向：

```text
candidates = all_active_questions()
candidates = filter_version_and_stage(candidates)
candidates = filter_unused_question_instances(candidates)
candidates = filter_current_question_closed(candidates)
candidates = filter_path_legal(candidates)

if uncovered_required_exists:
    required_candidates = keep_required_targets(candidates)
    if required_candidates:
        candidates = required_candidates
    else:
        trigger_exception_or_incomplete()

candidates = apply_category_and_tier_policy(candidates)
candidates = apply_chain_policy(candidates)
return deterministic_rank(candidates)
```

chain 是候选关系，不是无条件最高优先级；不能改变普通/综合题槽位，不能绕过 path 护栏。

### 需要对齐

是否接受“过滤器 → 硬约束 → 覆盖优先级 → 排序”的选题架构？

---

## B6. required 刚性例外

### 当前已确认

required 未获得有效普通测量时，可以超过基础配额增加普通主问题；不改变 `item.weight`，并必须留痕。

### 尚未收敛

- 同一 item 的例外次数上限；
- 例外题起始难度；
- 是否能沿完整 easy→medium→hard 路径；
- 是否可以使用综合题；
- 例外耗尽后的报告状态。

### 我的建议

把例外定义为有限的受控机会，而不是“无限重试”：

1. 普通计划结束后检查 required 覆盖；
2. 未形成有效普通测量的 required item 才可进入例外；
3. 例外仍必须是普通题；
4. 例外从该 item 当前合法路径开始；未成功激活时通常从 easy；
5. 不能因异常直接跳到 hard；
6. 例外耗尽后进入明确状态，例如 `REQUIRED_UNMEASURED`；
7. 生成带警告报告并创建人工复核任务。

综合题不能替代普通题最低测量要求。例外题是否允许升级，取决于最终路径状态机，但不能借例外绕过 hard 的可观测等级限制。

### 需要对齐

1. 每个 required item 最多几次例外？
2. 是否默认最多增加一次普通主问题？
3. 例外是否必须从 easy 开始？
4. 例外能否继续走 medium/hard？
5. 例外耗尽后是否采用 `REQUIRED_UNMEASURED`？

---

## B7. 等值备用题

### 当前已确认

等值备用题必须具备测量意义等值，相关参与权重字段一致；不同难度题不能直接视为等值题。

### 尚未收敛

- 等值字段清单；
- 审核方式；
- 离线验证标准；
- 综合题与普通题是否能等值替换。

### 我的建议

第一阶段采用显式人工确认，不做自动推断：

```text
equivalence_group_id
equivalence_status: pending | approved | rejected
equivalence_approved_by
equivalence_approved_at
```

同一组至少保证：

- 主 item 一致；
- difficulty 一致；
- measurement target 一致；
- rubric version 一致；
- evidence requirement 一致；
- 参与权重语义一致。

难度不同的替代题单独标记为 `difficulty_alternative`，不放入等值组。综合题与普通题第一阶段不建立等值关系。

### 需要对齐

是否接受第一阶段只支持人工批准的显式等值组，而不是自动判断题目等值？

---

# C. 难度状态机、评分和综合题

## C1. 难度路径和阶段边界

### 当前已确认

普通能力 item 的路径是：

```text
easy → medium → hard
```

综合题是普通阶段完成或合法封存后的独立阶段，不是普通难度第四级。

### 尚未收敛

- 每一级何时结束；
- 是否每个 item 都尝试 hard；
- hard 结束后的综合阶段入口；
- 题库缺 medium 时是否允许跳级。

### 我的建议

把“普通阶段结束”和“某个 item 达到最高难度”分开：

- 一个 item 不必强制走完三层；
- hard 是有条件的高等级测量阶段；
- 普通计划的 required 覆盖、配额和合法封存完成后，session 统一进入综合阶段；
- 综合题不自动接在某一个 item 的 hard 题之后。

题库缺少中间难度时默认不静默跳级。只有在模型/rubric 明确声明可跳级、并且报告记录实际路径时才允许；否则进入 `PATH_UNAVAILABLE` 或人工处理。

### 需要对齐

1. 是否接受 hard 为有条件阶段而非每个 item 必经？
2. 中间难度缺失时是否默认禁止运行时跳级？
3. 普通阶段的入口条件是否为“普通计划完成或合法封存”？

---

## C2. `evidence_sufficient` 的结构化定义

### 当前已知

候选条件包括：相关性、rubric 必需点、具体行为/事实、原始 span、非拒答/非跑题、无题目无效和模型不确定。

### 尚未收敛

- 这些条件如何机器判定；
- LLM 输出和代码判断的边界；
- 缺少一个条件时是否一定为 false；
- 证据冲突如何处理。

### 我的建议

不要只信任一个 `sufficient: true/false`。使用结构化观察字段：

```text
relevance
required_points_covered
specificity
attribution
source_span_available
contradiction_detected
uncertainty
```

由 LLM/规则提供观察，由代码按固定条件计算最终的 `evidence_sufficient`。LLM 不直接推进状态。

建议把以下情况明确排除：

- 明确拒答；
- 仅表达态度；
- 复述题目；
- 与 target 无关；
- 只有泛泛理论、没有可归因事实；
- 没有可追溯原文 span；
- 题目无效或模型不确定。

### 需要对齐

是否接受“结构化观察 + 代码最终裁决”，而不是 Prompt 直接控制状态迁移？

---

## C3. `stable_evidence` 的定义和独立观察

### 当前已知

候选方向是：两次独立有效观察，或一次高难度强证据；证据不矛盾、不是同一回答重复切片、版本可追溯。

### 尚未收敛

- “独立观察”的精确定义；
- 高难度强证据是否可以独立满足稳定条件；
- 冲突证据处理；
- 是否需要人工复核。

### 我的建议

独立观察应至少来自：

- 两个不同的普通 `assessment_question` 实例；或；
- 综合题中不同 measurement target 的独立证据，但不能把同一段复制视为独立观察。

稳定性依据：

```text
观察独立性
+ target 覆盖一致性
+ 行为锚点一致性
+ 无重大矛盾
+ rubric/version 一致
```

若证据矛盾，不应简单平均，建议：

```text
stable_evidence = false
→ MODEL_UNCERTAIN 或 HUMAN_REVIEW_REQUIRED
```

### 需要对齐

1. 是否接受两个不同主问题实例才算两次普通独立观察？
2. 一次 hard 强证据是否可单独达到稳定条件？
3. 证据冲突是否默认人工复核？

---

## C4. 升级、降级和降级后恢复

### 当前已知

- 充分证据可触发升级；
- 连续两道同 item、同难度的有效失败可以触发降级；
- followup 后仍模糊/错误/不足可以封存或降级；
- 技术故障、拒答、题目无效、模型不确定、流程质疑和表达风格不应被当成普通答错；
- 最低难度不能继续降级。

### 尚未收敛

- easy→medium 需要几次充分证据；
- medium→hard 是否必须稳定证据；
- “连续失败”精确定义；
- 降级后恢复条件；
- 是否允许恢复后再次降级；
- 是否设置最大震荡次数。

### 我的建议

采用滞回机制：恢复条件比首次升级更严格。

候选状态规则方向：

```text
首次升级：达到该级的充分证据条件
medium → hard：要求充分且稳定的证据
降级：只统计两个不同实例的有效候选人证据失败
降级后恢复：一次稳定证据，或连续两次充分证据
```

一次题实例内部不能发生升降级；难度变化在实例封存后由下一个实例承载。

以下不计入连续失败：

```text
REFUSED
TECHNICAL_OR_ACCESS_BARRIER
ITEM_INVALID
MODEL_UNCERTAIN
PROCESS_CHALLENGE
CONDUCT_EVENT
```

是否允许恢复后再次降级可以保留，但必须由事件和最大路径变更次数保护，避免震荡。

### 需要对齐

1. easy→medium 是否一次充分证据即可？
2. medium→hard 是否必须稳定证据？
3. 降级后恢复是否需要两次连续充分证据？
4. 是否设置 item 级路径变更上限？

---

## C5. 最高难度题和 `observable_level_max`

### 当前已确认

- 难度不直接作为最终权重；
- hard 题答好可支撑更高能力等级，但必须满足题目 rubric；
- 低难度题不能单独支撑超过自身可观测上限；
- 最高难度题只给最终有机会达到高等级的 item。

### 尚未收敛

- `observable_level_max` 属于题目、rubric 还是 item；
- easy/medium/hard 和 1–5 的具体映射；
- `required_level` 如何影响最高难度；
- hard 是否必须尝试；
- 没有 hard 题时报告如何解释。

### 我的建议

`observable_level_max` 应属于题目绑定的 rubric/测量配置版本，随题目实例快照保存，不能在运行中由模型修改。

能力模型可以保存：

```text
required_level / target_level
```

题目 rubric 保存：

```text
observable_level_max
```

最终分数仍是统一的能力等级，难度只限制“这条证据最多能支持什么等级”，不改变 item.weight。

hard 不是必经阶段。是否进入 hard 由：

```text
岗位/rubric 允许的最高等级
+ 前序证据是否使高等级测量有意义
```

共同决定。

### 需要对齐

1. 是否接受 `observable_level_max` 归属于题目/rubric 版本？
2. 是否接受 hard 为条件阶段而非所有 item 必考？
3. 高等级机会是否由岗位/rubric 与过程表现共同决定？

---

## C6. 多道普通题合并成 item 分

### 当前尚未收敛

同一 item 可能有不同难度和多个题实例，但目前没有明确采用：

- 平均；
- 最高分；
- 最近分；
- 证据裁决；
- 人工复核。

### 我的建议

不要按难度额外加权，也不要简单平均。采用“局部评分 → 证据裁决 → item 聚合”的两层结构：

1. 每个题实例产生受 `observable_level_max` 限制的局部能力等级；
2. 代码收集有效证据、覆盖点、稳定性和冲突；
3. 只有稳定且完整的高等级证据才允许 item 达到该等级；
4. 单个 hard 题不能绕过 rubric 必需点；
5. 低难度题不能把上限外等级抬高；
6. 有重大矛盾时进入保守结果或人工复核。

可以采用：

```text
item_final_level ≤ 最高可信、可复核且满足上限的证据等级
```

但具体冲突时取低值还是转人工，仍需确认。

### 需要对齐

1. 是否接受证据裁决而非简单平均？
2. hard 强证据是否可以支撑最高等级？
3. 多题矛盾时默认保守取低值，还是直接人工复核？

---

## C7. 综合题是否产生整体分

### 当前已确认

综合题可以绑定多个 item，但每个 item 必须有独立 measurement target、证据和评分状态；综合题不能自动完成所有绑定 item。

### 我的建议

综合题最终应产生逐 item 结果：

```text
integrated_question_result
├── item_result_1
├── item_result_2
└── overall_process_result（可选）
```

最终画像分数只使用各 item 的独立结果。整体分如果保留，只用于过程分析或展示，不能进入能力总分，否则会产生“整体分重复计算”问题。

### 需要对齐

是否接受综合题以“一题多 item 评分记录”为主，不以一个整体分直接参与总分？

---

## C8. 综合题多 item 证据拆分和共享 span

### 尚未收敛

- 一个回答如何拆分到多个 item；
- 同一 span 是否允许被多个 item 引用；
- 共享证据是否造成重复计分；
- 综合题是否能提供最高等级证据。

### 我的建议

每个绑定 item 必须拥有独立输出：

```text
item_id
measurement_target
rubric_mapping
evidence_spans[]
coverage
score_value
score_state
reason
```

同一 span 不应默认禁止共享。如果一段话确实同时包含两个 target 的独立证据，可以被两个 item 引用，但必须满足：

- 两个 item 的 target 不同；
- 两个 item 各自有独立解释；
- 共享 span 不能自动带来相同分数；
- 报告标明这是共享证据；
- 不能仅机械复制引用。

综合题可以提供高等级证据，但仍受该综合 target 的 rubric 和证据完整性限制。

### 需要对齐

1. 是否允许“有条件共享 span”？
2. 共享 span 是否必须在报告中显式标记？
3. 综合题是否可以成为某 item 的最高等级证据来源？

---

## C9. 综合题第二题及整体无效

### 当前已确认

- 每个 session 最多两道综合题；
- 第二题由代码策略决定，不由 LLM 自由增加；
- 综合题不能绕过普通题最低测量。

### 我的建议

第二题触发条件以“剩余合法联合 measurement target”为主：

```text
if remaining_targets
and second_question_available
and integrated_count < 2
and session_allows_more:
    activate second integrated question
else:
    close integrated stage
```

不建议仅因第一题分数低就自动出第二题。

如果综合题整体 `ITEM_INVALID`：

- 所有绑定 item 的综合结果无效；
- 不进入正常分母；
- 不计有效测量；
- 不自动变成拒答；
- 普通最低测量不足时进入人工/不完整。

如果综合题整体有效但某 item 证据不足，其他 item 仍可独立评分。

### 需要对齐

1. 第二题是否以剩余联合 target 为主触发条件？
2. 综合题整体无效时是否所有绑定 item 一律无效？
3. 第二题是否允许因为第一题整体无效而触发？

---

# D. 状态、缺失、拒答和聚合

## D1. `answer_state` 与 `score_state` 分离

### 当前已知

已有两组候选状态，但最终枚举及映射还未收敛。

### 我的建议

至少分为三层：

```text
answer_state             回答/过程事实
score_state              单次或 item 评分结果
report/completeness_state 报告可发布性
```

候选 `answer_state`：

```text
VALID_EVIDENCE
NEED_CLARIFICATION
OFF_TOPIC
NO_RECALL
DECLINED
PROCESS_CHALLENGE
CONDUCT_EVENT
TECHNICAL_OR_ACCESS_BARRIER
PROMPT_INJECTION
MODEL_UNCERTAIN
ITEM_INVALID
```

候选 `score_state`：

```text
SCORED
REFUSED
INSUFFICIENT_EVIDENCE
NOT_ADMINISTERED
INVALIDATED
INCOMPLETE
HUMAN_REVIEW_REQUIRED
IMPUTED
```

代码不能把任意回答状态直接映射为 0 分；系统错误、题目无效和模型不确定必须保持独立。

### 需要对齐

是否接受这三层状态职责分离，并在正式设计中建立完整映射表？

---

## D2. 拒答和有效回答同时出现

### 当前已确认

明确拒答采用：

```text
score_value = 0
score_state = REFUSED
```

拒答必须留痕，不能与能力量表 1 分混淆。

### 尚未收敛

如果同一 item 后续又有有效回答：

- 拒答是否让 item 最终为 0；
- 拒答是否作为一次特殊观察值参与聚合；
- 拒答后是否还允许继续测该 item。

### 我的建议

优先考虑将拒答作为一次特殊的可计数观察，而不是永久覆盖 item：

```text
item_has_refusal = true
item_score_state = SCORED（如果后来有合格证据）
```

拒答 0 仍可按用户确认方向参与该 item 的聚合，但后续有效观察也应保留。报告单独显示拒答次数和发生位置。

这里有一个必须明确的产品语义：

- **方案 A：拒答是 item 级终局 0。** 简单，但一次拒答会覆盖所有后来证据；
- **方案 B：拒答是特殊观察值 0。** 保留后续证据，信息更完整；
- **方案 C：拒答后结束该 item，但不把后续综合结果覆盖拒答。** 状态最清晰，但测量资源利用率较低。

我的推荐是方案 B，但不将其当作已确认结论。

### 需要对齐

明确拒答后，后续有效回答能否改变 item 的最终能力等级？拒答 0 是 item 终局值，还是一次特殊观察值？

---

## D3. 各评分状态是否进入分母

### 我的建议

建议默认规则：

| 状态 | 正常观察分母 | 是否产生缺失/警告 |
|---|---:|---:|
| `SCORED` | 是 | 否 |
| `REFUSED` | 需按 D2 的决定 | 是，单独记录 |
| `INSUFFICIENT_EVIDENCE` | 否 | 是 |
| `NOT_ADMINISTERED` | 否 | 是 |
| `INVALIDATED` | 否 | 是 |
| `MODEL_UNCERTAIN` | 否 | 是 |
| `INCOMPLETE` | 否 | 是 |
| `IMPUTED` | 不作为原始观察 | 是 |

系统错误和题目无效不能被转成普通低分。没有任何有效观察时不能通过补算制造一个确定分数。

### 需要对齐

1. `REFUSED` 是否进入普通 item 聚合分母？
2. `INSUFFICIENT_EVIDENCE` 是否只产生缺失而不参与分数？
3. 没有任何有效观察是否一律不能 `IMPUTED`？

---

## D4. 普通非 gate item 的比例补算

### 当前已确认

普通非 gate 能力项允许按观察比例补算，并标记 `IMPUTED`；required 和 qualification 不适用该补算。

### 尚未收敛

- 有效观察集合 `O` 的精确定义；
- 拒答是否进入 `O`；
- 没有任何有效观察时的处理；
- 补算值是否进入雷达图和总分；
- 补算比例过高时报告如何标记。

### 我的建议

先定义：

```text
O = 允许作为真实观察的评分结果集合
M = 缺失集合
```

`O` 至少包括 `SCORED`；拒答是否包含由 D2 的最终选择决定。以下不进入：

```text
INSUFFICIENT_EVIDENCE
NOT_ADMINISTERED
INVALIDATED
MODEL_UNCERTAIN
SYSTEM_ERROR
```

如果 `O = ∅`：

```text
不能补算
→ NO_VALID_OBSERVATION / HUMAN_REVIEW_REQUIRED
```

如果 `O ≠ ∅`，可以按已确认方向做比例补算，但报告同时显示：

- 真实观察数量；
- 缺失数量；
- 观察覆盖率；
- 补算标记；
- 补算不能等同于直接测量。

雷达图可以显示补算值，但必须用不同视觉标记；总分应同时提供完整度信息。具体“补算占比超过多少就不能正常发布”仍需确认。

### 需要对齐

1. 拒答是否进入 `O`？
2. `O = ∅` 时是否禁止任何补算？
3. `IMPUTED` 是否参与总分？
4. 补算比例达到某值时是否强制人工复核/临时报告？

---

## D5. required 缺失和临时报告

### 当前已确认

- required 缺失不做普通比例补算；
- 可以生成带警告的临时画像报告；
- 必须触发人工复核；
- 不触发补测；
- 系统不做最终录用判断。

### 我的建议

报告生命周期与评分状态分离：

```text
report_status:
GENERATING
PROVISIONAL
READY
HUMAN_REVIEW_REQUIRED
PUBLISHED
FAILED
```

required 缺失时可以是：

```text
report_status = PROVISIONAL
review_status = REQUIRED
```

报告必须列出：

- 缺失的 required item；
- 缺失原因；
- 是否曾拒答；
- 是否题目无效/系统错误/模型不确定；
- 是否有普通非 gate 补算；
- 哪些结论尚未经人工确认。

### 需要对齐

1. 是否接受 `PROVISIONAL + HUMAN_REVIEW_REQUIRED` 的双层状态？
2. required 缺失的报告是否允许展示完整雷达图？
3. 是否需要另一个最终名称，例如 `REQUIRED_UNMEASURED`？

---

## D6. 人工复核覆盖和版本

### 当前已知

人工复核应具有实际查看证据和覆盖结果的能力，且反馈不会自动改分。

### 尚未收敛

- 人工能修改哪些字段；
- 覆盖后原始结果是否保留；
- 是否需要二次审核；
- 报告是否自动重新生成。

### 我的建议

人工覆盖采用追加记录，不直接擦写原始结果：

```text
original_score
original_score_state
human_override_score nullable
human_override_state nullable
override_reason
reviewer_id
reviewed_at
```

人工可以覆盖：

- score value；
- score state；
- evidence validity；
- gate result；
- report completeness/release state。

每次覆盖写事件。是否需要双人复核，可按风险等级配置；至少 required、模型不确定和重大证据冲突应可被标记为高风险。

### 需要对齐

1. 人工是否可以修改分数、状态和证据有效性？
2. 是否保留原始结果并以 override 叠加？
3. 哪些场景需要二次人工确认？

---

## D7. 终局评分失败时报告发布条件

### 我的建议

不能让报告服务在没有可信 `question_score` 时生成看似完整的 0 分报告。

建议：

```text
全部终局评分成功 → READY/PUBLISHED
部分评分失败但结果可解释 → PROVISIONAL + HUMAN_REVIEW_REQUIRED
评分任务失败且没有可信结构化结果 → FAILED
```

报告生成必须先检查：

- session 是否达到可评分终态；
- 题目和回答是否已封存；
- question_score 是否完成或有明确异常状态；
- 聚合是否成功；
- 引用和数字校验是否通过。

### 需要对齐

是否接受“报告生成不能隐式代替评分，并且空评分不能生成正常报告”？

---

# E. 证据链和审计链

## E1. 严格证据链的最终形态

### 当前目标

```text
report
→ session
→ model/version
→ question
→ message
→ trace
```

### 尚未收敛

- trace 是否直接关联业务实体；
- report 是否保存模型版本快照；
- 综合题多 item 如何锚定；
- evidence quote 如何防止模型编造；
- 报告发布前的最小证据要求。

### 我的建议

每条终局评分至少能沿以下链路直接或确定性地回溯：

```text
report_id
→ session_id + model_id/model_version snapshot
→ assessment_question_id + bank_question/version
→ assessment_message_id
→ raw_hash + source span
→ scoring trace_id
```

可以选择：

1. 在各业务表增加直接 trace 外键；或；
2. 建统一的 `trace_link` 关联结构。

无论采用哪种方式，都不应只依赖自由文本 `ref_id`。

### 需要对齐

1. 是否要求评分 trace、报告 trace、题库生成 trace 都能直接关联业务实体？
2. 是增加直接外键，还是建立统一 trace link？
3. 报告发布是否必须通过证据链完整性检查？

---

## E2. evidence span 和原文/精炼文本

### 当前已知

原文和 hash 应保留，精炼只用于上下文压缩，不能替代原始证据。

### 我的建议

证据引用不要只存自由文本 `evidence_quote`，至少存：

```text
source_message_id
source_content_type: raw | refined
start_offset
end_offset
quote_hash
```

偏移定义建议采用 Unicode code point offset，并同时保存 quote hash。原文不可变，精炼文本可重新生成；精炼失败不能影响评分回捞原文。

### 需要对齐

1. 是否接受保存 message/span/hash 的结构化引用？
2. 偏移是否采用 Unicode code point？
3. 报告是否同时展示 quote 和原始来源定位？

---

## E3. 报告发布前的一致性校验

### 我的建议

在报告从生成中变为可发布前，代码至少检查：

- 每个数字都能从结构化评分重新计算；
- item.weight 总和和聚合结果一致；
- 报告引用的 question/message 属于该 session；
- 引用的 model/version 与 session 快照一致；
- 无效题和系统错误不在正常分母；
- `IMPUTED`、`REFUSED`、required 缺失警告与结构化状态一致；
- 文案没有声称系统做了录用判断。

自然语言生成只能表达已经通过校验的结构化结果，不能新增数字、事实或能力结论。

### 需要对齐

是否接受报告发布前必须有结构化数字/引用一致性检查？

---

# F. 状态事件、数据库和 API

## F1. `assessment_state_event` 的职责和不可变性

### 当前已确认

新增事件表，覆盖 session、题目、回答、分类、followup、难度迁移、拒答、技术重试、暂停恢复、Tools、人工介入、评分和报告任务等事件。当前状态字段和事件历史同时保存，状态与事件写入同一事务。

### 尚未收敛

- 最终字段；
- 事件枚举；
- `from_state/to_state` 的使用范围；
- 幂等键；
- 回放和修复规则；
- 管理端轨迹 API。

### 我的建议

事件表采用 append-only：

```text
不能修改旧事件
不能删除历史事件
纠正通过补偿事件完成
```

建议固定查询列包括：

```text
id
session_id
assessment_question_id nullable
assessment_message_id nullable
event_type
from_state nullable
to_state nullable
actor_type
actor_id nullable
sequence_no
idempotency_key nullable
created_at
```

版本/关联列：

```text
policy_version nullable
model_version nullable
question_bank_version nullable
correlation_id nullable
causation_event_id nullable
```

其余不稳定内容放 `payload_json`。是否加入 `correlation_id/causation_event_id` 可根据实现复杂度决定，但对审计和重试很有帮助。

### 需要对齐

1. 是否接受 append-only 事件？
2. 是否需要 `sequence_no`？
3. 是否加入 correlation/causation 字段？
4. 哪些事件必须有 from/to，哪些允许为空？

---

## F2. 事件类型分组

### 我的建议

事件类型不要按每一个自然语言动作无限扩张，可以按领域分组：

```text
SESSION_*       session 生命周期
QUESTION_*      选题、激活、封存、迁移
MESSAGE_*       回答、追问、助手话术
OBSERVATION_*   分类、证据评估、不确定
POLICY_*        选题、升级、降级、例外
CONTROL_*       暂停、恢复、超时、终止
FORM_*          表单渲染、提交、校验、gate
TASK_*          评分、报告、题库、评测任务
REVIEW_*        人工查看、覆盖、发布
TOOL_*          工具调用和 fallback
```

具体枚举应与状态机和报告查询需求一起收敛，不建议现在凭空把所有候选名称拍死。

### 需要对齐

是否接受“按领域分组、每个动作有稳定枚举、避免无限细分”的方向？

---

## F3. 幂等键和并发控制

### 当前问题

answer、form submit、score、report、后台任务都存在重复请求或并发触发风险。

### 我的建议

幂等键按资源作用域定义，而不是只做全局字符串：

```text
session_id + endpoint + idempotency_key
```

答题还应带：

```text
question_instance_id
expected_question_revision
client_attempt_id
```

重复请求的行为必须是：

- 返回第一次请求的持久化结果；
- 不重复写 message；
- 不重复增加 followup；
- 不重复扣题量；
- 不重复启动任务。

同时使用数据库事务/乐观版本号防止两个并发请求都通过“当前题未回答”检查。

### 需要对齐

1. 是否接受所有会改变测评状态的 POST 都要求幂等键？
2. 答题是否必须带 question revision/instance id？
3. 幂等记录保存多久、何时可清理？

---

## F4. 数据库表职责和核心字段

### `question_bank`

建议保存静态题目和发布版本信息：

```text
position_id
model_id/model_version
item_id nullable
question_type
measurement_stage
category/tier nullable
difficulty nullable
stem
answer_key nullable
rubric
rubric_version
measurement_target
evidence_requirement
equivalence_group_id nullable
status
```

综合题的多 item 绑定第一阶段可以保存结构化 JSON，并在发布和实例化时校验、快照；未来统计复杂后再引入关系表。

### `assessment_question`

建议保存动态实例：

```text
session_id
bank_question_id
sequence_no
question_type
measurement_stage
item_id nullable
difficulty nullable
status
activated_at
answered_at
closed_at
followup_count
selection_reason
selection_policy_version
path_state_snapshot
binding_snapshot_json nullable
```

每个不同题面一个实例，followup 不创建新实例。

### `assessment_message`

只保存不可变通信记录和过程事实：

```text
question_id
role
sequence_no
raw_content/raw_hash
refined_content nullable
action/reason
client_request_id
created_at
```

过程观察不应和最终评分混在一个字段中。

### `question_score`

只保存单题/单 item 的终局评分：

```text
question_id
item_id
score_state
score_value
score_final
measurement_target
rubric_version
evidence_spans
scorer_version
human_override...
```

综合题一题多 item 时允许同一 question_id 对应多条 item 评分记录。

### 需要对齐

1. 是否接受静态题库和动态实例分层？
2. 综合题第一阶段是否采用绑定 JSON + 实例快照？
3. `question_score` 是否允许 `(question_id, item_id)` 多记录？
4. 原文和精炼内容是否分列？

---

## F5. 表单 schema、`user_profile` 和迁移

### 表单 schema

建议第一阶段：

```text
代码定义 schema
+ form instance 创建时保存不可变 schema snapshot
```

未来若需要管理员配置，再建立独立 `form_schema` 表。

### `user_profile`

建议本轮不为了“表完整”而立即建立。登录身份、简历事实、测评报告和人工复核资料不应混在 user 表；当用户档案拥有独立生命周期、隐私权限和多来源合并需求时，再建立独立表。

### SQLite 迁移

即使暂时保留 SQLite，也建议建立：

```text
schema_version
migration_id
applied_at
```

每次迁移要有：

1. 备份；
2. 事务；
3. 外键和 schema 校验；
4. 失败回滚；
5. 迁移记录；
6. 兼容旧数据的测试。

建议索引覆盖：

```text
assessment_session(user_id, status)
assessment_question(session_id, sequence_no)
assessment_message(question_id, sequence_no)
question_score(question_id, item_id)
assessment_state_event(session_id, created_at)
assessment_state_event(session_id, event_type)
report(session_id)
```

### 需要对齐

1. `user_profile` 是否继续延后？
2. 第一阶段是否接受代码 schema + instance snapshot？
3. SQLite 是否只作为单机演示/单实例部署，还是本期也要支持上线并发？
4. 是否把迁移版本、备份和回滚列为上线前硬门槛？

---

## F6. API 资源所有权和接口一致性

### 当前高风险现状

候选人测评相关接口按 ID 取资源，但资源级所有权检查不完整，可能造成跨用户读写 session、报告、反馈和表单。

### 我的建议

所有候选人资源接口都使用统一授权规则：

```text
candidate → 只能访问本人资源
admin → 按管理权限访问管理资源
```

每一个 session/report/form/feedback 操作都必须通过资源归属或授权查询，而不能只检查“ID 存在”。

还需要统一检查：

- position 是否 active；
- model 是否 confirmed；
- session 是否属于当前候选人；
- feedback 的 item 是否属于该 report 对应模型；
- form instance 是否属于该 session；
- report 是否已达到允许生成的状态。

前端路由角色也应与后端一致，不能只依赖 localStorage 中的 user 信息。

### 需要对齐

1. 是否采用“candidate 只能本人、admin 按权限”的统一资源授权模型？
2. admin 是否可以读取候选人原始回答和 trace 全文？如果可以，哪些角色可以？
3. 是否需要管理员分级权限？

---

# G. 表单、Tools、计时、恢复和上下文

## G1. `render_form`、`get_form_schema`、`submit_form`

### 当前已确认

- qualification 等固定表单优先由代码触发；
- LLM 只能提出请求；
- schema 不能由 LLM 任意决定；
- submit 由候选人前端和服务端执行；
- gate 由代码计算；
- 需要版本和幂等。

### 我的建议

`render_form` 请求：

```text
session_id
form_type
schema_id
schema_version
trigger_reason
```

响应：

```text
form_instance_id
schema_snapshot
form_status
```

候选人只读取已激活 instance，不任意读取内部 schema。

`submit_form` 请求：

```text
form_instance_id
schema_version
idempotency_key
payload
```

服务端校验：

- 所有权；
- session 状态；
- form type 是否允许；
- schema 版本；
- 类型、必填项、枚举和长度；
- 重复提交语义。

建议同一 instance 的修订采用不可变 revision，而不是覆盖原始提交。

### 需要对齐

1. 是否接受 `form_instance` 作为表单生命周期实体？
2. 同一 instance 是否允许修订？
3. 重复 submit 是返回第一次结果、拒绝，还是创建新 revision？
4. schema 是只读 instance 快照，还是每次动态读取？

---

## G2. `extract_form_facts` 和 gate

### 当前已确认

只抽取事实，不直接通过/拒绝 gate；抽取结果要保留证据和不确定状态。

### 我的建议

事实结果至少包含：

```text
fact_type
normalized_value
source_document
source_span
confidence
status
```

状态可包括：

```text
EXTRACTED
UNCERTAIN
CONFLICTING
CANDIDATE_CONFIRMED
HUMAN_REVIEW_REQUIRED
```

简历/自由文本与候选人结构化填写冲突时保留两者，不静默覆盖；最终 gate 使用代码和人工确认后的事实。

### 需要对齐

1. 候选人结构化填写是否优先于自动抽取？
2. 发生冲突时是否一律人工复核？
3. gate 是否只接受 `CANDIDATE_CONFIRMED/HUMAN_CONFIRMED` 事实？

---

## G3. 全场和单题计时器

### 当前已确认

- 全场活跃测评不超过 40 分钟；
- 单题计时器不超过 20 分钟；
- 时间不用于提前筛掉合法题目或动作；
- 技术等待、系统重试和合理便利不应扣有效测评时间；
- followup 仍受每题最多两次约束。

### 尚未收敛

- 全场起点；
- 单题起点；
- 系统等待如何排除；
- 页面关闭和恢复；
- 单题/全场超时后的精确状态；
- 服务端与客户端权威关系。

### 我的建议

全场计时从：

```text
候选人确认开始测评，且首题成功激活
```

开始，而不是创建 session 时开始。

单题计时从：

```text
题目已成功激活并发送给候选人
```

开始；followup 使用同一个题实例计时器，不每次重新获得 20 分钟。

服务端使用 UTC 时间和服务端记录的有效计时区间作为权威，客户端只展示倒计时。

以下不计入候选人活跃时间：

```text
系统排队
模型调用等待
服务端处理
网络重试
技术故障暂停
合理便利暂停
人工等待
```

单题超时：封存当前题，进入评分/缺证据/人工流程；全场超时：停止新增主问题，进入收尾、评分和必要人工处理。

### 需要对齐

1. 是否接受上述全场和单题起点？
2. followup 是否共用同一个 20 分钟上限？
3. 页面关闭是否默认不暂停，只在显式 pause 或技术状态下暂停？
4. 单题超时是否封存并继续下一题？
5. 全场超时是否立即停止新增题并进入评分？

---

## G4. 暂停、恢复和便利信息

### 我的建议

暂停至少区分：

```text
CANDIDATE_REQUESTED
TECHNICAL_FAILURE
ACCESSIBILITY_ACCOMMODATION
ADMINISTRATIVE
```

候选人可直接请求暂停；LLM 只能建议。暂停/恢复写入事件，并记录有效计时区间。便利原因等敏感信息与普通能力分析隔离，不进入评分 Prompt 或画像维度。

### 需要对齐

1. 哪些暂停类型不计入 40 分钟？
2. 便利信息由谁可见？
3. 是否允许管理员代为暂停/恢复？

---

## G5. 页面关闭、会话恢复和重复计数

### 当前问题

当前 GET session 没有完整返回历史消息，前端刷新或重进会话可能丢失对话；答题响应丢失后重试又可能遇到“题已答”而无法恢复。

### 我的建议

恢复接口返回：

- 授权后的 session 当前快照；
- 当前题和题实例版本；
- 服务端计时状态；
- 当前状态事件 cursor；
- 最近消息或分页消息；
- 当前 pending action/task；
- 恢复所需的幂等信息。

可以拆分为：

```text
GET /sessions/{id}
GET /sessions/{id}/messages?cursor=...
GET /sessions/{id}/events?cursor=...
```

恢复必须保证：

- 不重复调用模型；
- 不重复增加题数；
- 不重复计 followup；
- 不重复扣时长；
- 不重复插入 assistant 消息。

页面关闭不应依赖客户端时间戳改变服务端计时；短暂断线保留 pending 状态，长时间无活动再按策略处理。

### 需要对齐

1. 是否接受消息/事件分页或 cursor 恢复？
2. 是否以服务端 pending 状态解决响应丢失后的重试？
3. 页面关闭是否采用显式 pause，而不是自动无限暂停？

---

## G6. P-refine、滑窗和结构化导航摘要

### 当前已确认

三层分工：

```text
原始证据层：不可覆盖
交互上下文层：滑窗和必要历史
导航摘要层：item 覆盖、难度、chain、异常、待处理
```

### 尚未收敛

- 滑窗按消息数还是 token 数；
- 结构化摘要字段；
- 摘要生成方式；
- 摘要失败回退；
- P-refine 的实际 token 阈值；
- 恢复时如何重建摘要。

### 我的建议

即使当前不设置硬 Token 上限，也应预留配置：

```text
context_window_policy
refine_policy
summary_version
```

导航摘要应优先由结构化当前状态生成，而不是完全依赖 LLM 自由总结。LLM 摘要失败时回退到：

- 当前 session/question 快照；
- 已持久化的 item 覆盖信息；
- 最近必要消息。

P-refine 只影响 interviewer 上下文，不覆盖原文；终局评分永远回捞原文和稳定 span。

### 需要对齐

1. 滑窗未来以 token 数还是消息数为主？
2. 摘要是否采用结构化字段优先、LLM 文本可选？
3. 摘要失败是否一律回退到数据库状态而不阻塞测评？
4. 是否继续暂不设置硬数值，但保留配置接口？

---

# H. 安全、隐私、公平和人工治理

## H1. 资源级授权和 IDOR

### 当前高风险现状

候选人接口存在按 ID 访问其他 session/report/form/feedback 的风险；feedback 还需要校验 item 是否属于对应报告模型。

### 我的建议

所有查询和写入都使用资源归属过滤：

```text
WHERE resource.user_id = current_user.id
```

或通过统一资源授权服务判断。不能先按 ID 查出资源再只检查存在。

必须测试：

- candidate A 访问 candidate B session；
- candidate A 代答 B 的题；
- candidate A 读取 B 的报告/原文；
- candidate A 提交 B 的表单；
- candidate A 给 B 的报告提交 feedback；
- admin 与 candidate 的权限边界。

### 需要对齐

是否把资源所有权校验列为 P0 上线阻断项？

我的建议是必须列为 P0。

---

## H2. 认证、Token 和前端会话

### 当前风险

当前存在弱默认 JWT secret、弱密码校验、登录限速缺失、Token 撤销/轮换未定，以及前端 localStorage 保存 token 的 XSS 风险。

### 我的建议

上线前至少要求：

- 生产环境禁止默认 secret；
- secret 缺失时启动失败；
- 统一校验 JWT 的 `sub/exp/issuer/audience`；
- 明确 token 过期、登出、停用账号后的行为；
- 登录限速和失败锁定策略；
- API 密码强度、用户名格式和长度校验统一；
- 前端优先考虑 HttpOnly/Secure/SameSite cookie，或明确 localStorage 的风险缓解和 CSP；
- 前端启动时以服务端 `fetchMe` 为权威，而不是只信 localStorage；
- `/docs`、`/redoc`、OpenAPI 是否在生产关闭或受保护。

### 需要对齐

1. 本期是否仍采用单一 JWT secret，还是需要 key rotation？
2. 是否迁移 HttpOnly cookie？
3. 是否把登录限速和生产 secret 校验列为上线阻断？
4. 生产 API 文档是否关闭/内网保护？

---

## H3. LLM、Trace 和敏感数据

### 当前已知

trace 需要可审计，但完整 prompt/response 可能包含 JD、候选人原文和个人信息，当前访问、脱敏、保留期限和第三方供应商处理边界尚未细化。

### 我的建议

建立数据分级：

```text
公开配置
内部测评元数据
候选人个人信息
原始回答/JD
Prompt/模型响应/trace
人工复核敏感信息
```

明确：

- 哪些字段可全文保存；
- 哪些字段需要脱敏或加密；
- 哪些管理员角色可读原文；
- 查看 trace 是否写访问审计；
- 数据保存、导出、更正、删除和备份策略；
- 第三方 LLM 是否接收个人信息；
- 数据驻留和供应商处理约束。

Trace 的审计性不能成为无限制暴露候选人原文的理由。

### 需要对齐

1. trace 是否保存完整 prompt/response，还是保存脱敏版本并保留受控原文？
2. 哪些角色能查看 raw answer 和 trace？
3. 是否本期定义保留/删除/导出机制？
4. 真实 LLM 供应商和数据驻留是否需要明确？

---

## H4. 输入、文件和 Prompt Injection 防护

### 当前已知

候选人回答和外部文本是不可信数据，正式测评不使用 Web Search；但上传和输入边界还不完整。

### 我的建议

对 JD、简历、表单、候选人回答和模型输出分别设置：

- 文件类型和大小限制；
- 行数、字段、字符长度和编码限制；
- 内容解析失败的事务回滚；
- 恶意内容/异常格式处理；
- LLM 输入预算和超时；
- 候选人文本永远作为 data，不作为 instruction；
- 工具返回内容也作为 data，不改变系统指令；
- LLM 输出必须 schema 校验，非法输出进入失败/人工状态；
- 工具调用二次授权和阶段白名单。

### 需要对齐

1. 文件和自由文本上限采用统一策略还是按输入类型配置？
2. 是否要求所有 LLM 输出使用严格 Pydantic schema 校验？
3. 工具失败时是降级为规则流程还是暂停并人工接管？

---

## H5. 公平性、无障碍和偏差评估

### 当前缺口

现有设计已确认“不根据口音、停顿、打字速度、表情、语气或不自信外观推断能力”，但还没有量化的公平性设计：

- 群体切片；
- 敏感属性治理；
- 代理变量；
- 语言/背景差异；
- 无障碍场景；
- 阈值和人工复核。

### 我的建议

本系统即使不做最终录用判断，仍应评估测评过程和评分是否存在系统性不利影响。建议至少定义：

1. 哪些敏感属性不进入评分输入；
2. 哪些属性只能用于离线公平性评估，且与业务报告隔离；
3. 语言、表达风格、停顿、技术条件和合理便利是否造成差异；
4. 各状态（拒答、缺证据、技术故障）在不同群体的发生率；
5. 人工复核和申诉是否有公平性检查；
6. 公平性测试的样本、指标、阈值和失败处理。

本期是否收集敏感属性、如何合法收集，是需要单独确认的产品/合规决定，不能自行假设。

### 需要对齐

1. 是否把公平性评估列为正式上线门槛，而不是可选测试？
2. 是否允许在脱敏、隔离环境中使用群体属性做离线评估？
3. 哪些属性绝对禁止进入评分和 Prompt？
4. 无障碍处理是否作为独立测评协议，而非“候选人表现异常”？

---

## H6. 人工复核和异议流程

### 当前已确认

候选人可以提出能力项异议；管理员审核 feedback/bad case；反馈不自动改分。

### 尚未收敛

- 异议状态机；
- 人工查看哪些证据；
- 处理时限和升级；
- 是否自动重新生成报告；
- 人工修改的权限和审计。

### 我的建议

建立独立 review 状态：

```text
OPEN
IN_REVIEW
NEED_MORE_EVIDENCE
OVERRIDDEN
REJECTED
CLOSED
```

review 必须关联：

```text
report/session/item
original result
evidence reviewed
reviewer
review note
reviewed_at
outcome
```

人工修改结果要通过 override 和事件保留，不能静默覆盖。

### 需要对齐

1. 是否接受独立异议状态机？
2. 候选人的异议是否能触发重新人工评分？
3. 人工覆盖是否需要二次审核？

---

# I. 异步任务、API 传输和可靠性

## I1. 任务执行模型

### 当前问题

当前使用 FastAPI `BackgroundTasks`，进程重启、多 worker、重复触发、异常可观测性和任务恢复都不足。题库、报告、评测等任务可能丢失或静默失败。

### 我的建议

区分演示模式和上线模式：

```text
演示/单进程：BackgroundTasks 可以保留
上线：持久化 task/job 状态 + 可恢复 worker/队列
```

每个任务应有：

```text
task_id
task_type
resource_id
status: queued/running/succeeded/failed/cancelled
attempt_count
last_error
started_at
finished_at
retry_at
```

任务状态必须可查询，失败不能表现为永久 404 或一直轮询。

### 需要对齐

1. 本期真实上线是否仍接受单进程 BackgroundTasks？
2. 如果不接受，选择持久队列还是先实现数据库任务表+单 worker？
3. 是否要求进程重启后任务可恢复？

---

## I2. 任务幂等、重试、超时和部分失败

### 我的建议

每种任务定义：

- 幂等 key；
- 最大尝试次数；
- 退避规则；
- 单次超时；
- 可重试错误；
- 不可重试错误；
- 取消语义；
- 部分成功语义。

例如报告生成不能采用“删除旧 report 再插入新 report”的竞态方式；应使用 generation/version 或唯一 session report 约束，并保留历史版本。

题库生成失败不能静默；JD pipeline 失败不能留下无法解释的半成品状态。

### 需要对齐

1. 报告是否允许同一 session 多个历史版本？
2. 重试是否覆盖原任务，还是创建新的 generation？
3. 部分题库/部分评分成功是否可以发布？
4. 任务错误是否向候选人显示，还是只显示可理解的失败状态？

---

## I3. JSON、Function Call 和 SSE 契约

### 当前问题

设计目标提到决策非流式 function call + 话术 SSE，但当前实现主要是同步 JSON，前端有 SSE 兼容层，后端尚未形成完整协议。

### 我的建议

在 Prompt 讨论前先确定传输层边界，不必现在写 Prompt：

- 如果本期需要 SSE，定义事件类型、顺序、事件 ID、断线恢复、心跳、错误和结束事件；
- 如果本期暂时使用 JSON，应明确记录为阶段性契约，不保留“假 SSE”作为不确定实现；
- Function/tool call 需要严格 name/input/output schema 和服务端二次校验；
- SSE 断线不能导致重复答题或重复任务。

候选人至少能恢复：

```text
decision/reply/current state/next question/event cursor/error
```

### 需要对齐

1. 本期正式契约选择真实 SSE，还是明确采用 JSON 延后 SSE？
2. Function call 是否只作为内部 LLM adapter，不直接暴露业务 API？
3. 是否需要事件 ID/cursor 支持断线续传？

---

# J. 测试、评测、部署和上线验收

## J1. 测试收集和统一入口

### 当前已知

现有测试包含 pytest、脚本测试和 eval，但部分函数只在 `__main__` 执行，部分 `test_*` 函数带参数会被 pytest 错误收集；当前没有统一全量入口和 CI 门禁。

### 我的建议

先建立清晰分层：

```text
unit
integration
api/security
migration
contract
end_to_end
eval
```

统一入口应明确：

- pytest 自动收集哪些文件；
- 脚本如何作为测试运行；
- eval 是否单独数据库；
- mock、固定 transcript 和真实 LLM 测试如何区分；
- 失败是否让 CI 失败。

所有测试要避免 import 时修改全局配置和共享数据库。

### 需要对齐

1. 是否把现有脚本测试重构为可收集的 pytest 或明确独立命令？
2. eval 是否永远使用独立数据库/临时数据库？
3. 是否建立 CI 作为正式验收入口？

---

## J2. 设计中已确认的 eval 及其缺口

### 已确认目标

- 固定 transcript 重跑，`score_final` 分差满足已有容差；
- strong/medium/weak 虚拟候选人端到端排序；
- 短板识别符合预设；
- trace、反馈和 bad case 可回溯；
- 黄金集本期推迟。

### 尚未收敛

- 样本规模；
- transcript 数量和覆盖维度；
- 强中弱输入；
- 短板预设；
- 随机性、模型和环境固定方式；
- 失败判定、重跑和统计依据；
- “联调全绿”的具体定义；
- eval 的 CI 集成。

### 我的建议

每项 eval 建立：

```text
fixture/input
expected invariant
metric
threshold
failure action
model/prompt/version
run metadata
```

一致性测试至少固定：

- model/provider/version；
- temperature；
- transcript；
- rubric/model snapshot；
- 随机种子（若适用）。

虚拟候选人不能只断言总分排序，还应验证：

- 预设能力项短板；
- required 覆盖；
- 缺失/拒答状态；
- 证据引用；
- 报告状态。

### 需要对齐

1. 一致性分差容差是否仍为已有设计中的 ≤1？
2. strong/medium/weak 的短板预设由谁建立？
3. “联调全绿”是否定义为所有 P0/P1 集成测试通过？
4. 是否允许 mock eval 作为工程回归，但不能代替真实 LLM 质量验证？

---

## J3. 自动 bad case

### 当前已确认

设计方向包含：当 `score_live` 与 `score_final` 严重背离时进入 bad case 候选；当前约定 `score_live` 不参与最终分，但仍可用于偏差分析。

### 尚未收敛

- 背离阈值；
- 逐题还是 item 级；
- 自动候选是否直接创建 feedback；
- 管理员如何确认；
- 模型不确定和缺失是否排除。

### 我的建议

将自动 bad case 设计为“候选”，而不是自动判错：

```text
if comparable_live_and_final
and abs(live - final) >= configured_threshold:
    create bad_case_candidate
```

排除：

- 题目无效；
- 模型不确定；
- 系统错误；
- 状态不可比；
- live 仅有导航估计而非同尺度评分。

生成候选后由管理员审核，不自动改分。

### 需要对齐

1. 是否保留自动 bad-case 候选机制？
2. 阈值按 1–5 等级差还是其他规则？
3. 是否需要 `bad_case_candidate` 独立表/状态？

---

## J4. M1 回归和业务验收

### 尚未收敛

M1 核心链虽然已有实现，但缺少足够回归：

- JD 清洗边界；
- 抽取 schema 异常；
- 词典消歧和排除项；
- 多 JD 聚合；
- 权重尾差；
- 等级冲突失败到 stalled；
- confirmed 不可静默覆盖；
- 版本和 diff；
- 管理员权限。

### 我的建议

后续 M5–M7 修改前，先建立 M1 回归基线，尤其是 confirmed model 作为后续题库和 session 的前置依赖。

### 需要对齐

是否把 M1 回归测试作为后续动态测评实施前的硬前置，而不是最后补测？

---

## J5. 性能、并发、迁移和部署验收

### 当前缺口

没有明确：

- 并发答题和 SQLite 锁测试；
- LLM 超时和重试压力；
- 题库/报告任务并发；
- 迁移前后数据一致性；
- 备份恢复；
- RTO/RPO；
- 前端 E2E；
- SPA 深链和生产反向代理。

### 我的建议

上线级验收至少覆盖：

```text
功能正确性
权限与安全
数据完整性
任务可靠性
并发和性能
迁移与回滚
前端关键流程
证据可追溯
公平性与无障碍
```

当前单机 SQLite + 单进程可以作为演示基线，但如果“真实上线”包含并发、多副本或持久任务，应单独决定是否迁移 PostgreSQL 和 worker 架构。

### 需要对齐

1. 本期目标是演示上线还是实际生产上线？
2. 是否接受 SQLite 只支持单实例演示？
3. 是否需要定义最低并发、响应时间、任务完成率和恢复时间指标？
4. 是否把迁移回滚和备份恢复列为上线硬门槛？

---

## J6. 前端 E2E 与关键用户流程

### 当前已知

前端页面大体存在，但没有组件测试、E2E 或完整主流程验收；当前还存在：

- 完成测评后未明确先终局评分再生成报告；
- 刷新/恢复消息不完整；
- 表单 schema 请求缺失；
- 前端角色状态依赖 localStorage；
- SSE/JSON 恢复契约不完整；
- 静态 prototype 不能替代实际 web 验收。

### 我的建议

至少建立真实 web 流程：

```text
注册/登录
→ candidate 看到 active position
→ 创建可用 session
→ 首题展示
→ answer + followup
→ 难度/状态变化
→ 表单提交
→ 完成并评分
→ 报告生成
→ 查看证据
→ 提交异议
```

另测：

- 刷新恢复；
- 响应丢失后重试；
- 网络中断；
- 超时；
- candidate 越权；
- admin 查看 trace/review；
- report 任务失败和重试。

prototype 仅作为视觉参考，不作为交互和 API 验收。

### 需要对齐

是否接受将候选人端完整流程 E2E 作为 M5–M7 真正 verified 的必要条件？

---

# K. 建议的收敛顺序

为了避免字段先定、公式后改，建议按依赖关系推进：

## 第一阶段：先锁定不可争议边界

1. 唯一 SSOT 路径；
2. 系统不做最终录用判断/排序；
3. candidate/admin 资源权限；
4. 里程碑状态定义；
5. 普通题、综合题、表单的测量隔离。

## 第二阶段：锁定题量模型

1. `N` 的来源、范围；
2. 7:3 整数分配；
3. tier 内配额；
4. 题库不足；
5. required 例外；
6. 综合题目标数量。

## 第三阶段：锁定路径和评分语义

1. `evidence_sufficient`；
2. `stable_evidence`；
3. 升级、降级、恢复；
4. hard 和 observable level；
5. 多题 item 聚合；
6. 综合题拆分；
7. 缺失、拒答和 `IMPUTED`。

## 第四阶段：锁定状态和数据契约

1. 状态枚举和映射；
2. `assessment_state_event`；
3. question/message/score 字段；
4. evidence span；
5. form instance/schema；
6. task/job；
7. trace 直接锚定。

## 第五阶段：锁定时间、恢复和传输协议

1. 40/20 分钟起止；
2. 暂停/恢复/超时；
3. 幂等和并发；
4. session 恢复；
5. 滑窗和摘要接口；
6. JSON/SSE/function call 边界。

## 第六阶段：锁定上线治理

1. 隐私和数据分级；
2. 公平性指标；
3. 人工复核；
4. 任务可靠性；
5. 迁移/备份/部署；
6. 测试和 E2E；
7. 上线门槛。

## 第七阶段：Prompt 模块

待上述非 Prompt 契约收敛并经用户授权写入正式设计文档后，再逐项讨论：

- Prompt 是否必要；
- 输入输出 schema；
- 失败和不确定性；
- trace 和版本；
- 人工接管；
- 哪些位置最终由规则替代。

---

# L. 本轮希望用户优先回答的核心问题

如果一次回答全部细节负担过重，建议先回答下面这些会决定后续其余设计的问题：

## 题量

1. `N` 是否采用“岗位级策略配置 + 系统上下限”？
2. 7:3 整数分配是否采用最大余数法？
3. required 是否每个有效 item 至少一次普通题？
4. preferred 是否有软最低覆盖，plus 是否允许零题？
5. 题库不可满足 required 时是否阻止开考？
6. required 例外是否采用有限次数、仍走普通题路径？

## 难度和评分

7. hard 是否为有条件阶段，而不是所有 item 必经？
8. 是否接受结构化证据维度 + 代码裁决 `evidence_sufficient`？
9. 降级后恢复是否采用更严格的滞回条件？
10. 多题 item 是否采用证据裁决而非简单平均？
11. 综合题是否只按 item 独立评分，不使用整体分参与最终总分？
12. 综合题第二题是否以剩余联合 target 为主要触发条件？

## 缺失和拒答

13. 拒答 0 是 item 终局值，还是一次特殊观察值？
14. `INSUFFICIENT_EVIDENCE`、无效题、模型不确定是否均不进入正常分母？
15. 普通非 gate item 在无任何有效观察时是否禁止 `IMPUTED`？
16. required 缺失是否采用 `PROVISIONAL + HUMAN_REVIEW_REQUIRED`？

## 数据和运行

17. 是否接受 append-only `assessment_state_event`？
18. 是否接受静态题库、动态题目实例、消息、评分结果分层？
19. 是否接受 form instance + schema snapshot？
20. 候选人资源所有权校验是否列为 P0？
21. 40/20 计时是否采用服务端权威、激活开始、followup 共用单题计时器？
22. 真实上线是否仍接受 SQLite + BackgroundTasks，还是只作为演示模式？

## 质量和公平

23. 是否把公平性、隐私、安全、迁移、E2E 和任务恢复列为正式上线门槛？
24. 是否接受“实现/契约完成/验证完成/生产就绪”四维里程碑状态？
25. 是否接受在非 Prompt 设计完全收敛后，再授权撰写新的总设计文档？

---

# M. 明确不属于本稿的内容

本稿不做以下事项：

- 不写具体 Prompt；
- 不替用户拍板尚未确认的数字、阈值和状态；
- 不修改旧讨论稿；
- 不修改总设计文档；
- 不修改业务代码；
- 不把当前静态代码问题直接变成实施计划；
- 不把建议的安全/合规做法当作已经获得的法律结论；
- 不把静态原型当作运行页面验收结果。

待用户逐项回答后，下一轮只记录用户明确确认的内容，并继续处理仍未回答的分支；全部非 Prompt 内容收敛后，再由用户明确授权撰写新的总设计文档。
