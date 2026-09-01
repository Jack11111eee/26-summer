# 第三轮临时讨论稿：题库配额、难度测量、缺失处理与 Prompt 清单

> **文档性质：第三轮临时讨论稿，非 SSOT，不代表已拍板设计。**  
> **日期：2026-09-01**  
> **与前两轮关系：本文件为新一轮讨论文件，不修改、不覆盖前两份临时讨论稿。**  
> **当前状态：用于继续讨论和形成实施依据；未获明确授权前，不修改《design/总设计文档.md》及业务代码。**

---

## 0. 本轮已确认内容、待确认内容与冲突说明

### 0.1 本轮已明确接受的方向

根据用户本轮回复，以下方向可以作为后续设计的候选基线，但仍需在正式 SSOT 中统一表述后才能实施：

1. `hard_skill`、`soft_skill` 是对话题库的两个大类；`experience`、`qualification` 不进入普通对话题库的 `required / preferred / plus` 分层；
2. `qualification` 只走结构化表单，不占普通对话主问题配额；
3. `experience` 通过表单/简历检测，不占普通对话主问题配额；
4. 普通题只允许绑定一个主评分能力项；综合题可以绑定多个能力项，并单独建立综合题库；
5. 普通题库使用逻辑树、物理扁平表；暂不为复杂题目关系新建关系表，但必须保留未来扩展记录/接口；
6. session 采用动态实例化方案 A：每次策略选中题目时，创建 `assessment_question` 实例；
7. 选题策略由当前服务加明确的领域状态机实现，不立即引入通用 Agent 框架；
8. 使用 Tools 概念，但关键状态转移由代码控制；不设计 Web Search；
9. `followup` 是当前题内追问，不增加主问题数量；每题最多两次追问；
10. `score_live` 只作为过程性挑题和难度导航证据，不参与最终分数计算；
11. 难度不作为最终分数的第三层权重；
12. 回答状态、脚手架事件、拒答、无效题、模型无法判断、系统错误等都要独立留痕；
13. 明确拒答采用 `score_value=0 + score_state=REFUSED` 的特殊状态方案，不把整个 1–5 能力量表改为 0–5；不提供测评末尾补答机会；
14. 网络中断属于系统范围错误，必须重试/恢复，不扣分；无法恢复则人工介入；
15. 缺失证据触发补测并进入人工复核；普通非 gate 能力项允许按观察比例补算，并标记 `IMPUTED`；
16. `required` 和 `qualification` 不适用普通缺失项比例补算；required 缺失时允许出带警告的临时报告，但不能仅靠补算得出最终录用结论；
17. 全场活跃测评时间不超过 40 分钟，单题计时器不超过 20 分钟；时间不是题目筛选优先级，也不是拒绝执行 chain、升级或降级的依据；
18. 暂不启用全会话 Token 硬上限、模型输出 Token 硬上限和 24 小时自动数据删除，但预留配置/实现接口；
19. P-refine 继续负责单条回答压缩；另行增加会话级滑动窗口和结构化状态摘要；
20. 新增一张 `assessment_state_event` 表承载所有会话状态事件；不新增多张专用事件表；
21. 下一轮需要逐项讨论所有需要 LLM Prompt 的场景，由用户拟定 Prompt，再进行收敛和实现设计。

### 0.2 本轮尚未足够明确、不能直接进入实现的内容

以下问题仍需继续对齐：

- 大类 `hard_skill : soft_skill = 7 : 3` 的精确含义，是最终能力权重比例、题量预算比例，还是两者都使用但各自有不同计算；
- `required / preferred / plus` 在 hard/soft 中如何从 item 权重计算子类配额；
- 静态难度是否参与题目数量划分；
- 难度答对的“更高奖励”如何体现而不成为第三层权重；
- 从低难度升级到高难度的充分证据标准；
- 降级后重新升级的独立条件；
- required 刚性例外如何增加题目，同时保持总分和权重语义稳定；
- 普通缺失项比例补算与 required 缺失临时报告/最终排序的边界；
- `item.weight` 的最终定义、来源、是否按 hard/soft 7:3 重算；
- 新增状态事件表的字段、事件类型、幂等和当前状态快照如何分工；
- Prompt 场景清单及每个 Prompt 的输入、输出、允许影响范围。

### 0.3 本轮识别出的潜在冲突

#### 冲突一：难度不加权，但高难度答对应有更高奖励

“难度不作为第三层最终权重”与“高难度答对奖励更高”并不必然矛盾，但必须把“奖励”定义为以下三者之一：

1. 难度影响同一能力项的可达能力等级/行为锚点上限；
2. 难度影响证据充分性和置信度；
3. 难度直接参与最终数值分数。

第 3 种会重新把难度变成第三层权重，与已确认方向冲突。当前建议优先讨论第 1 或第 2 种。

#### 冲突二：required 刚性例外与大类配额

如果 hard/soft 大类配额已由 7:3 或 item 权重决定，但 required 能力未覆盖时允许临时增加题目，则需要明确：

- 增加的是测量机会，还是增加该类最终分数权重；
- 是否从 preferred/plus 回收题量；
- 如果没有可回收题，额外题目是否导致总题量超过原计划；
- 额外题目是否改变总分分母。

当前建议：required 刚性例外增加的是测量机会，不改变已确认的 `item.weight`；所有例外及其原因进入事件和报告。若因新增 required 项导致观察覆盖变化，最终聚合按固定岗位模型权重计算，不因题目数量变化而二次加权。

#### 冲突三：required 缺失允许排序，但不能仅靠补算得出录用结论

这可以拆成两个不同动作：

- **展示/分析排序**：允许将带 `required_missing` 警告的临时报告放入候选人比较列表；
- **最终录用决定**：不得只依据含补算或缺失 required 的 AI 结果自动通过/淘汰，必须人工复核并确认。

是否接受这个解释，需要用户确认。

---

# 1. 题库结构与岗位权重

## 1.1 题库的最终逻辑结构

普通对话题库建议采用以下逻辑结构：

```text
position
└── approved competency model version
    ├── hard_skill
    │   ├── required
    │   │   └── ordinary questions (one main item per question)
    │   ├── preferred
    │   │   └── ordinary questions
    │   └── plus
    │       └── ordinary questions
    └── soft_skill
        ├── required
        │   └── ordinary questions
        ├── preferred
        │   └── ordinary questions
        └── plus
            └── ordinary questions

position
└── approved competency model version
    ├── integrated question bank
    │   └── integrated questions (may bind multiple items)
    └── structured fact collection
        ├── experience form/resume facts
        └── qualification form facts
```

### 普通题

普通题：

- 只能绑定一个主评分能力项；
- 必须绑定一个 `category` 和一个 `tier`；
- 必须有 `difficulty`、`qtype`、`rubric_version`；
- 可以有非评分标签，例如涉及的技术栈、业务场景、STAR 维度；
- 可以属于某个 chain；
- 不允许通过“辅助字段”偷偷给第二个能力项计分。

### 综合题

综合题：

- 单独属于 `integrated_question_bank` 逻辑范围；
- 可以绑定多个能力项；
- 每个绑定项必须配置独立的 `measurement_target` 和评分映射；
- 只有最终阶段才可被策略选中，除非岗位配置明确允许提前使用；
- 每次 session 默认最多一题，是否允许两题由测评策略根据覆盖情况决定；
- 一道综合题的总分贡献不能把同一回答重复乘算到多个完整 item 权重；需要定义综合题内部的证据拆分和贡献上限；
- 综合题必须在报告中逐个列出其覆盖的能力项和证据片段。

综合题是本轮新增的模型复杂点，不能简单复用普通题的单 item 评分逻辑。

## 1.2 `experience` 与 `qualification` 的非题库通道

### qualification

确认方向：

- 不占普通对话主问题配额；
- 通过版本化结构化表单收集；
- 代码按字段、枚举和 gate 规则判定；
- 不因表单字段缺失而调用 LLM 猜测；
- 如果候选人对资格事实提供补充文本，文本只能作为辅助证据，不能覆盖结构化字段的校验结果；
- 资格问题本身存在歧义时，进入人工复核，不自动把资格缺失算成普通能力项缺失。

### experience

确认方向：

- 通过表单/简历检测；
- 不进入普通对话的 `required / preferred / plus` 子类；
- 经验年限、项目经历、证书等事实需要记录来源和证据；
- 如果未来使用行为题验证经验，应作为单独的 experience verification 模式，不混入普通 hard/soft 题量和权重，除非重新定义评分模型。

### 需要继续确认

当前模型一中的 competency item 可能已经把 experience/qualification 当作 category 保存。实施前必须决定：

1. 是保留这两类模型项作为 gate/事实目标，但从普通题库选择器排除；还是
2. 从 competency model 的能力项集合中完全拆出，分别进入 `experience_requirement` 和 `qualification_requirement` 逻辑。

当前推荐第一种：保留模型可追溯性，但用 `measurement_mode=form` 标明它们不参与普通对话选题。

---

# 2. `hard_skill : soft_skill = 7 : 3` 的精确定义

## 2.1 不能直接把 7:3 同时当作所有东西

用户提出 7:3，需要明确它至少可能指：

- 最终分数中 hard 与 soft 的权重比例；
- 普通主问题数量比例；
- 每类的题库生成数量比例；
- 题目选择时的优先级比例。

如果四者都使用 7:3，可能产生重复加权。例如 hard item 自身已有 `item.weight`，再在最终聚合时乘 0.7，会把 hard 重要性计算两次。

## 2.2 推荐的定义

当前建议把 7:3 定义为：

> **在普通 hard/soft 能力项的最终岗位模型权重中，先将 hard 总权重归一到 0.70，将 soft 总权重归一到 0.30；再在各大类内部按能力项重要性分配。**

设：

- `H`：hard 能力项集合；
- `S`：soft 能力项集合；
- `r_i`：模型为能力项计算出的相对重要性原始值；
- `R_H = Σ(i∈H) r_i`；
- `R_S = Σ(i∈S) r_i`。

如果两类都存在有效项：

```text
item.weight_i = 0.70 × r_i / R_H,  i ∈ H
item.weight_i = 0.30 × r_i / R_S,  i ∈ S
```

如此：

```text
Σ item.weight_i = 1.00
Σ hard item.weight_i = 0.70
Σ soft item.weight_i = 0.30
```

如果某一大类没有有效能力项，不能简单保留空的 0.7 或 0.3：

- 只有 hard：hard 重新归一到 1.00；
- 只有 soft：soft 重新归一到 1.00；
- 两类都有但某一类没有可用题目：模型仍保留该类权重，但 session 进入题库覆盖不足/人工复核，不静默把题目权重转移到另一类；
- 是否允许在模型确认阶段阻止“有 item 但没有可测题库”的岗位确认，需要继续确认。

**注意：上述是推荐公式，不是用户已经确认的最终公式。**

## 2.3 类内 `required / preferred / plus` 如何影响最终权重

推荐不要再使用一个独立的 3 层权重常数去乘 item.weight，因为模块一当前可能已经把必备度纳入 importance 和 item.weight。

建议：

1. `tier` 是模型来源和选题配额维度；
2. `item.weight` 是最终分数唯一的业务权重；
3. required 对测量覆盖有硬约束；
4. preferred/plus 在配额不足时按权重和策略降级/跳过；
5. 如果产品确实要求 tier 直接影响最终分数，必须重新定义模型聚合公式并重新验证，不能在题目选择器中隐式实现。

需要用户确认：

> 7:3 是否只定义 hard/soft 的最终 item 权重总量，`required/preferred/plus` 只影响 item 原始重要性、选题配额和覆盖优先级，而不再额外乘最终分？

---

# 3. 大类、子类、难度与题量配额

## 3.1 推荐把“最终权重”和“测量资源配额”分开

最终分数使用 `item.weight`；题量配额使用独立的 `quota`。两者相关但不相同：

- 权重表达岗位重要性；
- 配额表达在有限测量机会中如何覆盖能力；
- 难度表达测量路径；
- chain 表达题目关系；
- 追问表达当前题补证据。

因此不要从题目数量反推最终权重，也不要因为增加一题就给该能力增加分数权重。

## 3.2 配额计算建议

### 输入

配额计算需要使用：

- 普通 hard/soft 能力项集合；
- 每个 item 的 `item.weight`；
- `category` 和 `tier`；
- item 是否 required；
- 每个 item 可用题目数量；
- 每个 item 的难度层级覆盖；
- 是否存在有效 chain；
- 测评全局主问题数量策略；
- 40 分钟只作为 session 计时器和终止条件，不作为题目筛选权重/预先排除条件。

### 第一层：大类配额

如果保留目标主问题总量 `N`，推荐初始大类配额：

```text
hard_quota = round(0.70 × N)
soft_quota = N - hard_quota
```

但 `N` 不能在本轮凭空固定；应由岗位模型中需要覆盖的 item 数量、题库可用量和策略配置决定。若 `N` 未定义，7:3 只能作为权重比例，不能直接得到题目数。

### 第二层：类内 tier 配额

对每个大类 `c`，先计算该类各 tier 的原始权重和：

```text
R(c,t) = Σ raw_importance_i, i 属于 category=c 且 tier=t
```

再按可用能力项和 required 覆盖约束分配：

```text
tier_quota(c,t) = allocation(c_quota, R(c,t), required_floor(c,t), availability(c,t))
```

`allocation` 必须是确定性整数分配算法，不能由 LLM 决定。推荐使用：

1. 先满足 required 能力的最小覆盖；
2. 剩余名额按 `R(c,t)` 比例分配；
3. 小数名额按最大余数法转成整数；
4. 没有可用题目的 tier 不占用已分配名额，名额转入同类可用 tier 或形成覆盖不足事件；
5. 不允许因为 tier 题多就自动提高该 tier 的最终分数权重。

### 第三层：item 与具体题

在 `category × tier` 配额内：

1. 先找未覆盖的 required item；
2. 再按 item `item.weight` 从高到低选择尚未达到测量目标的 item；
3. 同一 item 内先选符合当前难度状态的题；
4. 同分时使用固定随机种子或稳定排序，不用 LLM 自由挑题；
5. 题目必须满足题库版本、rubric 版本和岗位模型版本一致。

## 3.3 `N` 的问题需要单独确定

现有设计曾有总题量 10–12，但本轮提出 40 分钟计时器且不再用时间预算参与选题。两者并不冲突，但必须确定：

- `N` 是岗位策略生成的目标数量；
- 还是按 hard/soft item 数量及每个 item 的最低测量机会计算；
- 还是继续保留 10–12 作为默认上限。

当前建议：

- `N` 是岗位级策略配置生成的目标主问题数量；
- 题库计划在 session 创建时计算并冻结；
- 运行时只动态激活符合计划的题；
- required 刚性例外可以增加 `N` 的实际执行数量，但必须记录 `quota_exception`；
- 不能让时间计时器反向改变原始权重或配额公式。

这需要用户确认。

---

# 4. 固定优先级与下一主问题选择

## 4.1 “固定优先级”不是一个模糊的分数排序

固定优先级应定义成**代码可执行的词典序规则**：每个候选题按多个离散/数值字段形成排序键，代码按从左到右比较，而不是让 LLM 产生一个“重要性分数”。

推荐排序键：

```text
P0  是否触发安全/技术/人工状态（不再选普通题）
P1  是否需要完成当前题的合法 followup（需要则不选主问题）
P2  是否能覆盖尚未覆盖的 required item
P3  是否满足当前 category 的剩余配额
P4  是否满足当前 tier 的剩余配额
P5  是否满足当前 item 的难度状态和升级/降级策略
P6  是否是当前 chain 的合法后继
P7  item.weight（高到低）
P8  题目质量/状态/版本有效性
P9  稳定随机种子 tie-break
```

但是 P2–P7 的先后需要与配额策略保持一致。推荐最终实现为两阶段，而不是一个巨大排序键：

### 阶段一：过滤

按硬条件过滤：

- 当前 session 可用的岗位模型/题库版本；
- 普通题或综合题模式；
- category/tier 尚有配额；
- item 未达到当前测量目标；
- 题目未失效；
- chain 前置条件满足；
- 当前难度路径允许；
- 不处于暂停、人工、完成或系统错误状态。

### 阶段二：词典序选择

在过滤后的集合中按：

```text
required 未覆盖
→ 当前 chain 合法后继
→ 当前 item 的目标难度
→ item.weight 降序
→ 题目质量等级降序
→ 稳定随机 tie-break
```

这样“固定优先级”可解释、可测试，也不会因一个综合分数把 required 约束冲掉。

## 4.2 当前题 followup、chain 和难度的关系

推荐决策顺序：

```text
当前题仍允许且需要补证据
→ followup（仍是同一题）

当前题已结束
→ 若 required 未覆盖，优先 required

在目标 item 内
→ 按难度状态选择当前允许难度

若该题属于 chain 且后继条件满足
→ 选择 chain 后继

否则
→ 按 category/tier 剩余配额和 item.weight 选择其他题
```

chain 不是无条件优先；如果继续 chain 会挤掉尚未覆盖的 required item，则 required 优先。

## 4.3 时间不参与选择拒绝

本轮确认：不以“剩余时间不足以完成下一题”作为选题过滤条件，也不因时间预算不足拒绝执行 chain、升级或降级。

时间只作为一个独立的计时器：

- 单题达到 20 分钟：终止当前题的继续交互并封存；
- 全场达到 40 分钟：终止新增交互并进入收尾/评分/人工流程；
- 时间耗尽时未完成的题按状态记录，不自动改写为普通答错；
- 时间停止/暂停、系统等待和人工处理须独立记录。

---

# 5. 静态难度：升级、降级与“高难度奖励”

## 5.1 难度的三种可能语义

为了避免再次混淆，静态难度可以影响：

### 语义 A：导航难度

只决定下一道题的挑战程度，不改变最终分数。高难度答对只体现在报告的能力证据描述中。

优点：最容易保持分数可比；缺点：不能直接体现高难度答对的数值奖励。

### 语义 B：能力等级证据门槛（当前推荐）

难度不直接乘权，但不同难度题对应不同能力等级上限/证据锚点：

- 低难度题充分答对：证明基础能力，不足以单独证明高等级；
- 中难度题充分答对：支持中等等级；
- 高难度题充分答对：才支持最高等级；
- 低难度题答错不能简单与高难度题答错等价；
- 最终 `score_final` 仍由 rubric 将证据映射到同一 1–5 能力等级，再乘固定 `item.weight`。

优点：高难度答对的“奖励”通过可证明的能力等级体现，不产生第三层权重；缺点：需要为每个 item 编写难度与行为等级的映射。

### 语义 C：难度直接加分/加权

例如高难度答对乘 1.2。该方案会把难度变成最终分数因素，与本轮已确认方向冲突，当前不推荐。

## 5.2 推荐的难度—能力等级映射

不能假设所有岗位和能力项都适用相同映射，建议题库中为每个题配置：

```text
difficulty
measurement_target
observable_level_min
observable_level_max
rubric_version
```

例如：

```text
题目 difficulty = easy
observable_level_max = 3

题目 difficulty = medium
observable_level_max = 4

题目 difficulty = hard
observable_level_max = 5
```

这不是“做 hard 题自动得高分”，而是：

- 回答质量仍需达到对应行为锚点；
- easy 题即使回答很好，也不能单独支撑超过其 `observable_level_max` 的结论；
- hard 题回答不好，仍然可能得到低分；
- 最高等级需要高难度题的有效证据，或题库/rubric 明确允许的等价证据；
- 所有上限必须由岗位和能力项的 rubric 版本预先定义。

## 5.3 从最低难度到更高难度：升级条件

本轮用户要求从最低难度开始，并细化“答多少题低难度才能答高难度”。推荐不要以单纯题数决定，而采用“至少一次 + 稳定证据”的组合：

### 第一级：尝试最低难度

- 每个进入测量的 item 首先尝试最低可用难度；
- 如果最低难度题回答有效且达到该题最低证据阈值，允许尝试高一级；
- 如果回答信息丰富但尚未覆盖全部考察点，可以先 followup，不算升级失败。

### 从最低到中等

满足以下全部条件时允许升级一次：

1. 当前最低难度题是有效题；
2. 候选人完成了非拒答的有效回答；
3. 证据覆盖了该题 `measurement_target` 的最低必需集合；
4. 终止状态不是 `OFF_TOPIC`、`DECLINED`、`MODEL_UNCERTAIN`、`ITEM_INVALID`；
5. 该题的 `score_live` 达到预设“导航达标”阈值，或代码根据结构化 coverage 判定达标；
6. 没有发生尚未解决的系统/无障碍错误。

推荐初始值：最低难度一次充分证据即可尝试中等难度，不连续答两题才升级。但具体阈值和是否需要两题仍需用户确认。

### 从中等到最高

建议比低→中更严格：

- 至少一次中等难度有效且充分证据；
- 且满足以下之一：
  - 中等题 score_live 达到更高导航阈值；
  - 同一 item 在最低和中等两个难度均达到各自最低证据阈值；
- 每次最多跨一级；
- 题库没有中等难度时，允许最低直接到最高，但必须记录题库路径缺口。

### 升级不是最终评分

升级只表示“允许尝试更高难度”，不是给候选人加分，也不是判定候选人已达到更高能力等级。最终等级必须由独立评分器根据所有有效证据和 rubric 判断。

## 5.4 降级条件

保留上一轮已确认的触发方向，但将“答错”严格定义为有效回答未达到当前难度题的最低行为锚点：

1. 跳过；
2. 同一 item、同一 difficulty 连续两道有效题未达到最低锚点；
3. 当前难度不是最低难度；
4. followup-1 和 followup-2 后仍然模糊；
5. followup 后仍然错误或证据不足。

以下不能触发普通降级：

- 技术故障；
- 无障碍问题；
- 题目无效；
- 模型无法判断；
- 合理流程质疑；
- 明确拒答（拒答按 `REFUSED=0` 留痕，但不是“答错”）；
- 仅仅因为紧张、停顿或语言风格。

### 降级执行

- 非最低难度：下一道同一 item 的题降一级；
- 最低难度：保持最低，不再降；
- 降级不改变 item.weight；
- 降级不自动扣额外分；
- 记录触发事件、证据和新难度；
- 若没有同一 item 的低一级有效题，不伪造降级，进入保持/人工路径。

## 5.5 降级后重新升级：必须是独立条件

降级后不能因为下一题“答得还可以”就立即来回震荡。建议：

### 状态变量

每个 `session × item` 维护：

```text
current_difficulty
highest_reached_difficulty
last_transition
consecutive_valid_failures
consecutive_valid_successes
post_demotion_successes
```

### 重新升级条件

从降级后的难度向上恢复，必须同时满足：

1. 至少一题有效回答达到当前难度最低证据阈值；
2. 该回答不是拒答、跑题、技术错误或模型不确定；
3. 若刚发生过一次降级，至少累计两次连续有效充分证据，或一次达到 rubric 明确的强证据阈值；
4. 每次只恢复一级；
5. 恢复后仍要重新完成该级别题的证据判定，不能沿用降级前分数；
6. 如果恢复后再次失败，回到降级后的难度并清零恢复计数。

### 关于“答多少题”

推荐初始规则：

```text
正常低→中：1 次充分有效证据
正常中→高：1 次充分中难度证据 + 低/中路径至少一项稳定记录
降级后恢复一级：2 次连续充分有效证据，或 1 次强证据
```

这些数值是可执行的初始策略，不是行业标准；需要后续题库实验和公平性评估确认。

## 5.6 “稳定证据”和“证据充分”的操作化

### 证据充分（evidence_sufficient）

建议定义为代码可校验的结构化条件，而不是一句自然语言：

- 回答与当前题 `measurement_target` 相关；
- 至少覆盖该题 rubric 标记的必需考察点集合；
- 包含足以归因给候选人的具体行为/事实，而不是泛泛观点；
- 没有被判为拒答、跑题、纯复述题目或纯态度表达；
- 证据可定位到原始回答文本片段/时间范围；
- 未触发 `MODEL_UNCERTAIN` 或 `ITEM_INVALID`；
- 评分器输出的 evidence sufficiency 不低于当前题配置阈值。

可以落成：

```json
{
  "sufficient": true,
  "covered_targets": ["..."],
  "missing_targets": [],
  "evidence_spans": [{"message_id": "...", "start": 12, "end": 78}],
  "confidence": "high"
}
```

### 稳定证据（stable_evidence）

稳定证据不是“说得长”或“模型觉得不错”，而是：

- 同一 item 的至少两次独立有效观察，或一次高难度强证据；
- 两次观察覆盖的关键目标不互相矛盾；
- 证据来自具体情境/行动/结果或题目定义的等价行为结构；
- 不是同一次回答被重复切片；
- 没有依赖未经批准的内容提示；
- 评分器对证据状态的置信度达到策略阈值；
- 两次观察的难度和 rubric 版本均可追溯。

代码应保存 `evidence_coverage` 和 `stability_basis`，而不是只保存一个布尔值。

---

# 6. 最高难度题覆盖与公平性

## 6.1 当前确认的含义

“必须确保有一定数量的最高难度题”本轮确定为：

> **只对最终有机会达到高等级的能力项问最高难度题。**

这不是每个 session 固定问相同数量，也不是所有 required item 都必须问最高难度。

## 6.2 如何定义“最终有机会达到高等级”

建议在岗位模型/题库计划中为每个 item 配置：

```text
required_level
highest_observable_level
high_level_candidate_rule
hard_question_available
hard_question_min_count
```

一个 item 进入最高难度候选集合，需要满足：

1. item 的岗位要求等级高于基础等级，或 rubric 定义存在高等级区分价值；
2. 题库存在经批准的最高难度题；
3. 该题与 item 的 measurement_target 和 rubric 版本匹配；
4. 候选人在较低难度路径上没有出现已足以停止该 item 的终止条件；
5. 该 item 不是仅通过表单即可完成的 experience/qualification 项。

### 仍需用户确认

“有机会达到高等级”可以有两种定义：

- **岗位要求驱动**：`required_level >= 4` 的 item 才问最高难度；
- **过程表现驱动**：候选人在低/中难度证据达到阈值才问最高难度。

当前推荐两者取交集：

```text
high_level_candidate(item)
= (岗位要求或 rubric 允许高等级)
  AND (候选人低/中难度达到进入条件)
```

## 6.3 最高难度题数量

不建议现在给一个全局固定数字。推荐按 item 配置：

```text
hard_question_min_count(item) ∈ {0, 1}
```

当前初始建议：每个进入 `high_level_candidate` 的 item 至少尝试 1 道最高难度题；同一 item 是否需要 2 道由题库/rubric 配置决定，但不得默认无限追加。

这与“每个 session 至少若干道最高难度题”不同：岗位和能力结构不同，最高难度题数量自然不同。

## 6.4 没有最高难度题时

- 不用中难度题冒充最高难度；
- 标记 `QUESTION_BANK_COVERAGE_GAP`；
- 该 item 的最高等级结论不能仅凭低难度题得出；
- 如果 item 是 required，触发人工复核/题库修订；
- 报告可给出已观察等级，但标注最高等级未充分测量。

---

# 7. required 刚性例外：题量、权重和报告

## 7.1 触发条件

当某个大类或 tier 配额已经达到，但仍有 required item 没有获得有效测量机会时，代码按以下顺序处理：

```text
1. 检查该 required item 是否确实属于当前岗位模型版本；
2. 检查是否存在有效且未使用的题目；
3. 检查是否是拒答、缺证据、题目无效、模型不确定或系统错误；
4. 若是系统/题目问题，先进入对应修复或人工状态；
5. 若是尚未测量且有有效题，触发 required_quota_exception；
6. 创建动态 assessment_question 实例；
7. 记录原配额、例外前剩余配额、触发 item、题目和原因；
8. 继续测量，不改变岗位模型权重。
```

## 7.2 例外不应改变 item.weight

推荐原则：

```text
item.weight = confirmed competency model snapshot 中的固定权重
```

无论某个 item 因 required 例外问了一题还是两题：

- 该 item 的最终业务权重不变；
- 同一 item 多题证据先在 item 内聚合；
- 不因多问一次而把该 item 乘两次权重；
- 额外题只增加证据覆盖/稳定性，不增加岗位重要性。

## 7.3 例外导致的实际主问题数量

设：

- `N_plan`：session 开始时的计划主问题数量；
- `E`：required 例外新增的主问题数量；
- `N_actual = N_plan + E`；
- `Q_exception`：例外记录集合。

则：

```text
N_actual = N_plan + |Q_exception|
```

但需限制：

- 例外只对 required；
- 同一 required item 的例外次数需有配置上限；
- 没有有效题不能为了凑覆盖制造题目；
- 例外不能绕过单题/全场计时器；
- 时间到达后仍未测量，进入缺失/人工路径，而不是继续无限增加题目。

这里“时间不作为选题筛选标准”与“时间到达后会话终止”并不矛盾：前者是不提前根据剩余时间拒绝某个合法动作，后者是计时器到点后的全局安全终止。

## 7.4 required 缺失时总分如何计算

推荐区分三层结果：

### A. 观察分（observed score）

只使用有效、非补算的评分项：

```text
S_observed = Σ(i∈O) item.weight_i × score_i
```

### B. 普通缺失项补算分

只对普通非 gate、允许补算的缺失项集合 `M_normal`：

```text
r = S_observed / Σ(i∈O) item.weight_i
imputed_score_j = r, j∈M_normal
```

并标记 `is_imputed=true`。

### C. required 缺失状态

对于 required 缺失集合 `M_required`：

- 不使用普通比例补算作为“已测 required 证据”；
- 可以生成临时报告；
- 临时报告显示 `required_missing=true`、缺失项、原因和覆盖率；
- 是否将临时报告的展示分数放入排序列表，需要单独定义排序标签；
- 不得仅靠该分数自动得出最终录用结论；
- 必须进入人工复核或补测任务。

### 当前仍需确认的数值口径

用户确认“允许用于最终录用排序”，同时确认“不能仅靠补算得出最终录用结论”。我暂时将其解释为：

```text
允许：带 required_missing 警告的临时分参与人工使用的候选人排序
不允许：系统仅凭该临时分自动通过/淘汰
```

如果用户的意思是“允许自动排序但最终仍由人点选”，需要进一步确认人工介入的最低要求。

---

# 8. `normalized_item_score` 的具体含义

## 8.1 为什么需要归一化

当前设计使用 1–5 能力评分，而最终总分需要按 0–1 或百分制聚合。因此：

```text
normalized_item_score = (score_final - score_min) / (score_max - score_min)
```

如果正式能力量表仍为 1–5，则：

```text
normalized_item_score = (score_final - 1) / 4
```

这样：

- 1 分 → 0.00；
- 3 分 → 0.50；
- 5 分 → 1.00。

如果拒答使用特殊 `score_value=0`，不能直接套入这个公式后当作普通能力量表分；应由 `score_state=REFUSED` 单独决定其聚合贡献。

## 8.2 难度不加权时如何体现高难度奖励

当前推荐方案是：

1. 所有有效题最终都映射到同一能力等级 1–5；
2. 难度通过 `observable_level_max` 限制低难度证据能支持的最高等级；
3. 高难度题只有在回答满足其行为锚点时，才允许支持更高等级；
4. 高难度答错仍可得低等级；
5. 最终只乘固定 item.weight。

示例：

```text
item.weight = 0.20

候选人 A：easy 题答得很好，但 easy 的 observable_level_max=3
→ item score 最高只能支持 3/5
→ normalized = (3-1)/4 = 0.50
→ item contribution = 0.20 × 0.50 = 0.10

候选人 B：hard 题答得很好，达到 5/5
→ normalized = 1.00
→ item contribution = 0.20 × 1.00 = 0.20
```

这不是“hard 题乘一个额外系数”，而是高难度题提供了达到更高岗位能力等级所需的证据。

### 需要注意

如果某岗位要求等级只有 3，那么不应为了“奖励 hard 题”强迫候选人达到 5；`observable_level_max`、`required_level` 和最终评分映射必须由岗位 rubric 决定。

## 8.3 拒答 0 的聚合语义

建议：

```text
score_value = 0
score_state = REFUSED
```

在普通能力项中，拒答作为该项的明确负面结果参与聚合：

```text
refused_normal_score = 0.0
```

但报告同时显示：

- 该项为拒答，不是行为锚点 1 分；
- 拒答发生在哪道题；
- 是否已告知可跳过；
- 是否属于合规/隐私质疑而被转人工。

如果拒答发生在 required item：

- 可以记录 0 并生成警告；
- 仍需人工复核其是否能用于最终录用结论；
- 不能把拒答和“低能力有效证据”混为一谈。

---

# 9. 表单、Tools 和模型知识不足的实施细化

## 9.1 表单工具与代码触发边界

### `render_form`

- 固定资格表单由代码在进入资格核验阶段时触发；
- LLM 只能提出 `request_form` 建议，不能决定任意 schema；
- 代码校验岗位、模型版本、session 状态和表单类型；
- 同一 session/schema 幂等；
- 记录 `form_instance_id`、schema 版本、触发原因、展示事件和状态。

### `get_form_schema`

- 由前端/服务端读取已批准的 form instance；
- 返回字段类型、required、枚举和校验规则；
- schema 展示后不可静默改变；
- 不能把内部 gate 阈值暴露给不必要的客户端或 LLM。

### `submit_form`

- 只由前端/服务端接收候选人填写结果；
- 服务端校验所有权、schema 版本、字段类型、枚举、幂等键；
- 保存 raw payload、normalized payload、错误和 gate 结果；
- LLM 不得代候选人提交，也不得直接修改 gate 结果。

### `extract_form_facts`

- 只负责从简历/自由文本抽取候选事实；
- 每个字段附原文证据和不确定状态；
- 不直接通过或拒绝 gate；
- 最终 gate 由代码和人工确认决定；
- 抽取结果不能覆盖候选人明确填写的结构化值，除非走修订流程。

### `request_pause`

- 候选人可直接触发；
- LLM 只能建议；
- 代码进入 `PAUSED_*` 状态并停止有效计时；
- 敏感便利信息单独隔离；
- 暂停、恢复、失败和人工处理全部记录。

## 9.2 模型知识不足

当前不使用 Web Search。运行时区分：

### 题目超出批准知识边界

- 标 `ITEM_INVALID` 或 `MODEL_UNCERTAIN`；
- 不向外部互联网查询；
- 不改变 rubric；
- 人工审查题目是否需要禁用或补充批准参考资料。

### 评分器无法判断证据

- 尝试一次不引入知识的中性澄清；
- 仍无法判断则暂停不利评分；
- 标 `MODEL_UNCERTAIN`；
- 进入人工复核；
- 不自动降分、不自动结束整场。

### 评分器输出不符合 schema

- 代码拒绝不合法结果；
- 记录原始响应和错误；
- 按有限次数重试；
- 重试失败进入人工复核；
- 不把 schema 失败归因于候选人。

---

# 10. 会话上下文落地方案：P-refine、滑窗和摘要

## 10.1 三种内容分层

### 原始证据层

保存：

- 候选人原始回答；
- 原文 hash；
- 消息时间和题目实例；
- 技术/暂停/重试关联。

该层不可被摘要覆盖。

### 交互上下文层

供 interviewer 生成当前回复，包含：

- 当前系统策略和不可违反规则；
- 当前题题面、rubric 的必要部分；
- 当前题最近若干轮原始/精炼消息；
- 当前题追问次数；
- 当前 session 状态和预算；
- 已完成题的结构化摘要。

不再每轮无条件拼接整个 session 全量历史。

### 导航摘要层

保存：

- 每个 item 已覆盖 target；
- 未覆盖 target；
- 已尝试难度；
- 成功/失败稳定证据；
- 当前 chain 状态；
- 状态事件计数；
- 待人工处理标记。

摘要只用于导航，不作为最终评分唯一依据。

## 10.2 P-refine 与会话摘要的边界

| 机制 | 粒度 | 目的 | 是否替代原文 |
|---|---|---|---|
| P-refine | 单条回答 | 压缩长回答、过滤无关内容 | 否 |
| 滑动窗口 | 多轮消息 | 控制 interviewer 上下文长度 | 否 |
| 结构化摘要 | 已完成题/item | 支持下一题导航和状态恢复 | 否 |

P-refine 的精炼内容不能变成唯一评分来源；评分器始终回捞原始回答和可定位证据。

## 10.3 滑动窗口实施建议

在本轮暂不启用硬 Token 限额的前提下，可以先按消息数量/结构分层实现：

```text
保留：系统规则 + 当前题全部消息 + 最近 K 个已完成题摘要
可选：最近 L 轮历史消息
移除出 prompt：更早题目的完整长文本
保留在数据库：全部原文和 trace
```

其中 `K/L` 先作为可配置接口，不在本轮假设具体数值。上下文达到未来配置阈值时，才启用 Token 估算/裁剪。

## 10.4 摘要生成失败

- 不得静默丢失导航状态；
- 可回退到结构化数据库字段重建摘要；
- 若无法重建当前题状态，进入 `MODEL_UNCERTAIN` 或系统人工状态；
- 最终评分不使用失败摘要替代原文。

---

# 11. `assessment_state_event` 事件表设计

## 11.1 建表理由

本轮选择使用一张专门表承载会话状态事件，以支持：

- 动态选题；
- followup；
- 难度升降级；
- 拒答、跑题、暂停、技术重试；
- Tools；
- 预算快照；
- 人工介入；
- 补测和重算；
- 审计查询和状态回放。

## 11.2 推荐字段

```text
id
session_id
assessment_question_id nullable
assessment_message_id nullable
event_type
from_state nullable
to_state nullable
actor_type（system/llm/candidate/admin）
actor_id nullable
policy_version
model_version nullable
question_bank_version nullable
payload_json
idempotency_key nullable
created_at
```

### 字段职责

- `event_type`：事实发生了什么，例如 `QUESTION_SELECTED`、`FOLLOWUP_REQUESTED`、`DIFFICULTY_DOWNGRADED`；
- `from_state/to_state`：领域状态怎样变化；
- `actor_type`：谁触发或执行；
- `payload_json`：该事件特有的参数，不把所有业务字段重复拆列；
- `policy_version`：当时使用的策略版本；
- 外键字段：把事件锚定到具体 session/question/message；
- `idempotency_key`：重试不能重复制造事实事件。

## 11.3 推荐事件类型初稿

```text
SESSION_CREATED
SESSION_RESUMED
SESSION_PAUSED
SESSION_RESUMED_AFTER_PAUSE
SESSION_TIMEOUT
QUESTION_SELECTED
QUESTION_ACTIVATED
ANSWER_RECEIVED
ANSWER_CLASSIFIED
FOLLOWUP_REQUESTED
FOLLOWUP_LIMIT_REACHED
QUESTION_COMPLETED
QUESTION_SKIPPED
QUESTION_REFUSED
SCAFFOLD_SHOWN
CHAIN_ADVANCED
CHAIN_TERMINATED
DIFFICULTY_UPGRADED
DIFFICULTY_DOWNGRADED
REQUIRED_QUOTA_EXCEPTION
FORM_RENDERED
FORM_SUBMITTED
FORM_VALIDATION_FAILED
TOOL_REQUESTED
TOOL_SUCCEEDED
TOOL_FAILED
MODEL_UNCERTAIN
ITEM_INVALID
TECHNICAL_RETRY
HUMAN_REVIEW_REQUESTED
MAKEUP_ASSESSMENT_REQUESTED
SCORING_STARTED
SCORING_COMPLETED
SCORING_FAILED
REPORT_GENERATION_STARTED
REPORT_GENERATION_COMPLETED
REPORT_GENERATION_FAILED
```

事件类型应保持有限、稳定；不应把候选人自由文本直接拼成事件类型。

## 11.4 当前状态与事件历史的分工

事件表不能成为每次读取当前状态的唯一来源。建议：

- `assessment_session.status` 保存当前会话状态；
- `assessment_question.status/current_difficulty/followup_count` 保存当前题状态；
- `assessment_state_event` 保存不可变历史；
- 写状态和写事件必须在同一数据库事务中完成；
- 恢复时先读当前状态，必要时用事件历史审计或修复；
- 不允许只改当前状态而不写事件。

## 11.5 未来复杂关系的保留记录

本轮暂不创建 `question_bank_relation` 表，但应在设计和代码中留下扩展点：

```text
if relation_type grows beyond simple chain_id/chain_seq/equivalence_group_id:
    introduce question_bank_relation
```

触发条件包括：

- 多后继分支；
- 条件路由；
- 复杂 fallback；
- 非分组型等值关系；
- 一个题在多个版本/关系图中复用。

同理，表单 schema 和 `user_profile` 也保留未来独立表的扩展记录，不在当前阶段过度建模。

---

# 12. 实施差距登记：本轮只细化，不授权修复

以下问题全部保留为后续修复/重构工作，当前不实施：

## 12.1 动态选题

当前：创建 session 时一次性按固定配额选完题目。  
目标：session 创建时冻结岗位/模型/题库计划，运行时逐题动态实例化，并记录选择原因、配额快照、难度路径和 policy 版本。

需要后续明确：

- 计划 `N` 的生成公式；
- 7:3 的权重/配额边界；
- tier 配额整数分配；
- chain 后继检查；
- required 例外；
- 综合题最后阶段选择。

## 12.2 `finish` 护栏

当前：非末题模型直接返回 `finish` 时未完全拦截。  
目标：

```text
if action not in {followup,next,finish}:
    reject schema / retry / human fallback

if action == finish and unfinished_required_or_main_questions_exist:
    code overrides to next or followup according to policy

if action == finish and no legitimate finish condition:
    record illegal_finish_attempt
    do not end session
```

合法 finish 条件至少应包括：

- 已完成计划中的普通主问题；
- required 能力已覆盖，或已触发 required 例外并处理；
- 综合题阶段已完成或被合法标记；
- 没有待处理的技术/人工状态；
- 未处于表单必填未完成状态；
- 未处于补测/恢复流程。

## 12.3 状态分类和 mock 面试官

当前：mock 主要按回答长度判断。  
目标：

- 先做规则/LLM 结构化分类；
- 分类结果进入白名单；
- 状态与 action 解耦；
- 同一状态按固定策略处理；
- mock 也模拟状态分类和边界，而不是仅模拟字数。

需要后续写清：

- 分类器输入输出 schema；
- 规则优先级；
- 冲突时人工/安全 fallback；
- 每种状态允许的 followup 数；
- 报告如何展示状态事件。

## 12.4 情绪支持

当前：没有独立情绪状态或标准化支持协议。  
目标：

- 只响应候选人明确表达和可观察流程事件；
- 不做情绪能力推断；
- 支持话术固定、版本化、可审计；
- 支持不改变题意、不暗示答案；
- 计时暂停/恢复独立处理；
- 合理便利信息隔离。

## 12.5 证据链和评分主链

当前：底层证据组件存在，但正常 UI 未自动执行终局评分再生成报告。  
目标：

```text
finish
→ SCORING_PENDING
→ score_final
→ item aggregation
→ missing/refused/imputed policy
→ report
→ human review where required
```

`score_live` 只保留为导航与分析证据，不参与最终数值。

## 12.6 表单接口

当前：有提交入口和前端 FormCard，但缺完整 schema 获取、严格校验、幂等和固定触发链。  
目标：

- 注册表单 schema；
- 创建 form instance；
- `render_form` 代码触发；
- `get_form_schema` 读取；
- `submit_form` 严格校验并幂等；
- gate 由代码计算；
- 事件表记录展示、提交、校验、修订和人工覆盖。

## 12.7 网络、系统错误和计时器

当前：重试、暂停计时、断线恢复和影响范围记录不完整。  
目标：

- 请求幂等键；
- 服务端防重复写入；
- 网络失败重试；
- 活跃计时器只计算 `ACTIVE`；
- 技术/人工等待不扣有效测评时间；
- 无法恢复进入人工状态；
- 失败不映射为拒答或答错。

## 12.8 难度路径

当前：题库有静态难度，但没有 session item 难度状态、升级/降级、最高难度覆盖和恢复条件。  
目标：

- 从最低难度开始；
- 按证据充分/稳定条件逐级升级；
- 按明确有效失败条件降级；
- 降级后独立恢复；
- 难度不改变 item.weight；
- 高难度通过 observable level/rubric 体现更高能力证据；
- 最高难度只对有机会达到高等级的 item 尝试。

## 12.9 缺失、拒答、无效题和补算

当前：聚合器未完整区分这些状态。  
目标：

- `REFUSED`：特殊 0，记录拒答事件；
- `INSUFFICIENT_EVIDENCE`：补测/人工复核；
- `NOT_ADMINISTERED`：未实施，不自动 0；
- `INVALIDATED`：题目/系统无效，不进入普通分母；
- `MODEL_UNCERTAIN`：暂停不利评分，人工处理；
- `IMPUTED`：仅普通非 gate 项可按观察比例补算；
- required 缺失：带警告临时报告，不能仅凭补算自动得出最终录用结论；
- 每种状态进入报告和事件表。

## 12.10 会话恢复和上下文

当前：GET session 不完整返回历史 messages，interviewer 可能拼接全量历史。  
目标：

- 读取状态快照和必要消息；
- P-refine、滑窗、结构化摘要分工；
- 恢复后不重复计数、不重复扣预算、不重复执行工具；
- 摘要失败可从结构化字段恢复；
- 原文永不被摘要覆盖。

## 12.11 所有权与审计锚定

当前：候选人 session/report 资源所有权校验不足，trace 与业务实体多为间接关联。  
目标：

- session/report/question/message/form/tool 统一所有权检查；
- 事件表外键锚定 session/question/message；
- trace 与具体调用上下文关联；
- admin 的跨候选人访问显式授权并记录；
- 不能仅靠客户端 ID 作为权限依据。

---

# 13. 下一轮 Prompt 讨论清单

用户要求下一轮找出所有需要 LLM Prompt 的场景，由用户拟定 Prompt，再共同收敛。以下清单先作为完整候选目录，下一轮逐项确认哪些需要 LLM、哪些应由规则/代码替代。

## 13.1 模块一：JD 与胜任力模型

### P1：JD 原子能力抽取

- 输入：清洗后的 JD；
- 输出：岗位标题、原子能力项、类别、原文证据、required/preferred/plus、要求等级候选；
- 必须：严格 schema、原文引用、不得凭空补充；
- 代码负责：格式校验、去重、持久化和失败重试。

### P2：能力词典消歧/归一

- 输入：原始能力名、词典候选、定义、别名、排除项；
- 输出：匹配条目/新条目/无法判断及理由；
- 代码负责：候选 top-k、唯一性、排除项和回退。

### P3：能力等级冲突裁决

- 输入：同一能力在多个 JD 中的等级要求和证据；
- 输出：1–5 等级、理由、引用；
- 代码负责：只在冲突时调用、范围校验、失败进入 stalled。

### P4：题库生成

- 输入：岗位模型版本、item 定义、tier、目标难度、measurement_target、rubric 模板；
- 输出：题面、题型、难度、chain、考察点、答案/评分依据、版本元数据；
- 代码负责：题目结构校验、item 单绑定约束、重复检测、版本和入库。

### P5：综合题生成

- 输入：多个能力项及其联合测量目标；
- 输出：综合题面、多个 item 的独立 measurement_target、证据拆分规则、难度、最后阶段标记；
- 代码负责：最多绑定范围、权重贡献不重复、题库审核。

## 13.2 测评运行时

### P6：候选人回答状态分类

- 输入：当前题、题目目标、候选人回答、必要上下文；
- 输出：`VALID_EVIDENCE / NEED_CLARIFICATION / OFF_TOPIC / NO_RECALL / DECLINED / PROCESS_CHALLENGE / CONDUCT_EVENT / TECHNICAL_OR_ACCESS_BARRIER / PROMPT_INJECTION / MODEL_UNCERTAIN`；
- 代码负责：枚举校验、优先级、敏感状态升级、状态迁移和预算。

### P7：证据覆盖判断

- 输入：当前题 rubric、候选人原始回答及历史回答；
- 输出：covered targets、missing targets、evidence spans、sufficient、confidence；
- 代码负责：span 合法性、原文一致性、最低覆盖规则和冲突处理。

### P8：追问意图/探针选择建议

- 输入：缺失考察点、当前题、已用追问次数、状态策略；
- 输出：建议的 probe 类型或模板变量；
- 代码负责：决定是否允许 followup、模板白名单和次数上限；
- 注意：LLM 不得自由改变题意或增加提示线索。

### P9：追问/澄清话术生成

- 输入：批准的 probe 类型、题面、缺失 target、固定话术边界；
- 输出：一条简短中性追问；
- 代码负责：长度、禁止泄露答案、题意一致性和敏感内容检查。

### P10：脚手架话术生成

- 输入：`NO_RECALL` 状态、允许的 scaffold level、题面；
- 输出：不含答案线索的结构化回答脚手架；
- 代码负责：等级、次数、统一模板、事件留痕和评分影响标记。

### P11：情绪/流程支持话术

- 输入：候选人明确表达或流程事件；
- 输出：标准化、简短、中性的支持话术；
- 代码负责：触发资格、固定模板、暂停状态和不改变 rubric。

### P12：主问题过渡/收尾话术

- 输入：代码已决定 `next` 或 `finish`；
- 输出：礼貌、简短的过渡或结束文案；
- 代码负责：不得改变 action、不得提前结束、不得添加评分结论。

### P13：模型不确定说明

- 输入：代码判定 `MODEL_UNCERTAIN` 或题目异常；
- 输出：对候选人的固定说明或对管理员的结构化说明；
- 代码负责：暂停不利处理、人工任务和错误状态。

## 13.3 表单/资料处理

### P14：简历/自由文本事实抽取

- 输入：候选人简历或自由文本；
- 输出：experience/qualification 候选事实、原文证据、置信状态；
- 代码负责：不直接通过 gate、字段校验和人工确认。

### P15：表单异常解释（可选）

- 输入：服务端字段校验错误；
- 输出：对候选人的易懂修正说明；
- 代码负责：真实错误字段和合法修复范围；
- 若固定模板足够，则不需要 LLM。

## 13.4 终局评分

### P16：逐题终局评分

- 输入：原始回答证据、题目、item rubric、难度和 scaffold 元数据；
- 输出：score_final、score_state、evidence_quote、reason、confidence、observable level；
- 代码负责：schema、引用校验、1–5 范围、拒答/缺失/无效分支和持久化。

### P17：综合题多 item 评分

- 输入：综合题回答、各 item measurement_target 和 rubric；
- 输出：每个 item 的独立证据、分数、理由和覆盖状态；
- 代码负责：防止一段证据被无依据复制给所有 item、总贡献上限和缺失状态。

### P18：证据一致性/反幻觉校验

- 输入：评分器输出和原始回答；
- 输出：引用是否存在、是否改变否定/条件含义、是否有幻觉；
- 建议优先使用代码和字符串校验，LLM 仅在复杂语义冲突时辅助。

### P19：缺失项补算解释

- 输入：观察项得分、权重、缺失原因；
- 输出：原则上不需要 LLM；
- 代码负责：公式计算、`IMPUTED` 标记和警告。

## 13.5 报告生成

### P20：优势/短板/建议文案

- 输入：已确定的 item 分数、排序、证据、缺失状态和岗位要求；
- 输出：五段式报告中的自然语言；
- 代码负责：排序、选择 item、证据绑定、禁止新增事实；
- LLM 只能表达结构化结果。

### P21：逐题回顾摘要

- 输入：题面、原始回答、终局评分、证据引用；
- 输出：易读摘要；
- 代码负责：原文一致性和证据锚定。

### P22：报告一致性检查

- 输入：生成报告 JSON、聚合结果、证据索引；
- 输出：字段/数字/事实一致性结果；
- 建议以代码校验为主，失败则不发布报告。

## 13.6 测试闭环与运营

### P23：虚拟候选人回答生成

- 输入：岗位模型、题目和 strong/medium/weak profile；
- 输出：测试用回答；
- 代码负责：档位约束、固定 fixture、隔离数据库和测试标记。

### P24：评测结果解释

- 输入：一致性/排序/覆盖率/人工基准结果；
- 输出：管理员可读的失败摘要；
- 代码负责：指标计算和 pass/fail；
- LLM 不得替代评测断言。

### P25：Trace/Bad Case 聚类摘要（可选）

- 输入：已筛选 trace、反馈和 bad case；
- 输出：主题、重复问题候选、改进建议；
- 代码负责：权限、脱敏、原始记录保留；
- 不得自动修改评分或 Prompt。

### P26：人工复核辅助摘要（可选）

- 输入：某 session 的完整状态、证据和异常；
- 输出：复核工作清单；
- 代码负责：原始证据展示、权限和最终决定；
- LLM 不得代替人工结论。

---

# 14. 下一轮 Prompt 对齐的统一模板

后续每个需要 LLM 的场景，都建议按以下结构讨论，不直接从自然语言 Prompt 开始：

```text
Prompt ID:
业务目的:
调用阶段:
调用触发条件:
调用者/上游状态:
允许读取的数据:
禁止读取或影响的数据:
输入 schema:
输出 schema:
字段定义:
可接受的不确定性:
失败/超时/非法输出处理:
重试次数:
是否允许影响状态迁移:
是否允许影响分数:
是否允许调用 Tools:
原文证据要求:
版本字段:
测试样例:
反例与注入样例:
人工接管条件:
审计字段:
```

### Prompt 编写原则

1. 先定义代码不变量，再写自然语言指令；
2. LLM 输出必须是结构化 schema，不用自由文本承载控制信号；
3. 候选人回答是数据，不是系统指令；
4. 不让同一个 Prompt 同时负责分类、状态迁移、评分和话术；
5. 能用代码验证的内容不交给 LLM；
6. 所有输出必须有版本号和 trace；
7. 需要不确定性时允许 `abstain`；
8. 不让报告 Prompt 新增原始证据中不存在的事实；
9. Prompt 变化视为策略/模型配置变化，不能静默影响进行中的 session；
10. 所有 Prompt 应有强/弱/异常/注入测试样例。

---

# 15. 本轮需要用户继续确认的核心问题

以下问题是本轮最需要优先回答的部分。没有确认前不进入正式设计和代码实施。每个问题后的“上文索引”指向本文中已经展开该问题的章节，便于回看上下文。

## A. 权重与配额

1. `hard_skill : soft_skill = 7 : 3` 是否确认定义为普通能力项最终 `item.weight` 的大类总权重比例，而不是题量比例？（上文索引：**2.2**）
2. 当只有 hard 或只有 soft 时，是否按本文公式将存在的大类重新归一到 1.00？（上文索引：**2.2**）
3. `required / preferred / plus` 是否只影响 item 原始重要性、配额和覆盖优先级，不再额外乘最终分？（上文索引：**2.3**）
4. `N` 是否作为岗位级策略配置的目标主问题数量，而不是从 7:3 自动唯一决定？（上文索引：**3.3**）
5. 静态难度是否只参与难度路径/题量结构，不参与最终 item.weight？（上文索引：**5.1、5.2**）

## B. 题目关系与综合题

6. 是否确认普通题单主评分 item、综合题单独题库且只在最后阶段出现？（上文索引：**1.1**）
7. 综合题默认每 session 最多一题，必要时最多两题，是否接受？（上文索引：**1.1**）
8. 是否确认 `qualification`/`experience` 保留为模型可追溯项，但通过 `measurement_mode=form` 排除普通对话选择？（上文索引：**1.2**）
9. 是否确认暂不建立 `question_bank_relation` 表，只保留扩展记录/接口？（上文索引：**11.5**）

## C. 难度与证据

10. 是否接受难度采用“能力等级证据上限”语义，而不是难度直接加分？（上文索引：**5.1、5.2**）
11. 是否接受 `easy → medium` 一次充分证据、`medium → hard` 一次充分证据加稳定路径记录？（上文索引：**5.3**）
12. 是否接受降级后恢复需要两次连续充分证据，或一次强证据？（上文索引：**5.5**）
13. `evidence_sufficient` 是否采用覆盖 target、具体可归因行为、原文可定位、无异常状态等条件？（上文索引：**5.6**）
14. `stable_evidence` 是否采用两次独立有效观察或一次高难度强证据？（上文索引：**5.6**）
15. “有机会达到高等级”是否采用岗位/rubric允许高等级与低/中难度达到进入条件的交集？（上文索引：**6.2**）
16. 每个满足条件的 item 至少尝试一题最高难度题，是否接受？（上文索引：**6.3**）

## D. required 例外、缺失与总分

17. required 刚性例外是否只增加测量机会，不改变 `item.weight`？（上文索引：**7.1、7.2**）
18. 是否接受 `N_actual = N_plan + required_exception_count` 的记录方式？（上文索引：**7.3**）
19. 拒答是否确认 `score_value=0 + score_state=REFUSED`，且参与该普通项聚合？（上文索引：**8.3**）
20. 缺失项比例补算是否只针对普通非 gate 项并标记 `IMPUTED`？（上文索引：**7.4**）
21. required 缺失时，是否接受“可生成带警告临时报告，可供人工排序参考，但不得仅凭其自动得出最终录用结论”的解释？（上文索引：**7.4**）
22. 缺失 required 是否必须触发补测/人工复核，即使临时报告已经生成？（上文索引：**7.4**）
23. `normalized_item_score=(score_final-1)/4` 是否作为 1–5 到 0–1 的基础归一化？（上文索引：**8.1**）

## E. 状态、计时与上下文

24. 是否确认时间不参与选题过滤，只由全场 40 分钟和单题 20 分钟计时器终止交互？（上文索引：**4.3、13.1**）
25. 是否确认全局追问不设独立上限，但每题最多两次且受计时器熔断？（上文索引：**13.1**）
26. 是否接受 P-refine、历史滑窗、结构化导航摘要三层分工？（上文索引：**10.2、10.3**）
27. 是否确认新增一张 `assessment_state_event` 表，并与当前状态字段在同一事务更新？（上文索引：**11.1、11.4**）
28. 是否确认暂不设置 Token 数值上限，但保留接口？（上文索引：**13.5**）

## F. Prompt

29. 下一轮是否按第 13 节的 P1–P26 清单逐项确定“需要 LLM / 代码替代 / 暂不做”？（上文索引：**13.1–13.6**）
30. Prompt 是否由用户先拟定初稿，我再负责 schema、边界、测试和与状态机的对齐？（上文索引：**14**）
31. 是否将 `evidence_sufficient`、`stable_evidence` 和 `answer_state` 的输出作为 Prompt 对齐的优先场景？（上文索引：**5.6、7.2、13.2（P6–P7）**）

---

# 16. 文档与代码处理规则

1. 本文件只作为第三轮讨论载体；
2. 不修改前两轮临时讨论稿；
3. 不修改 SSOT；
4. 不修改业务代码；
5. 本轮确认的内容先继续讨论，不能直接视为正式设计；
6. 用户明确授权后，先更新 `design/总设计文档.md` 正文和 §13 变更日志；
7. 正式设计更新完成后，再另建修复/重构实施文档，逐项拆分代码、数据库迁移、测试和验收标准；
8. 所有需要 LLM 的 Prompt 在实施前必须完成输入输出 schema、失败策略、版本、trace、测试样例和人工接管条件；
9. 数据库新增字段/表前必须检查是否能复用现有结构，避免重复表达同一事实；
10. 任何“暂不做”项目应留下明确扩展点和后续触发条件，但不提前实现复杂方案。
