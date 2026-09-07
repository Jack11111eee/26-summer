# SSOT 修订稿（草案，待用户审阅——未写入任何权威文档）

> 提案编号：REV-20260907-05
> 目标文档：`design/final-design/总设计文档.md` §8.1（⑤ 聚合行）+ §6 配置常量；同步摘录 `design/final-design/模块一设计-岗位JD解析与胜任力模型构建.md` §3/§6
> 性质：agent 起草，**未经用户确认不得写入**；确认后以原子 commit 变更权威路径
> 日期：2026-09-07

---

## 一、修订动因（一句版）

工序⑤的 importance 映射在真实语料上失真：单 JD 内 LLM#1 将 80–89% 项标 `required`（招聘文案措辞泛滥），跨 JD 绝对阈值 `req ≥ 0.5` 又把主干能力卡在 0.27–0.47 无人区——22 个 n≥4 岗位实测旧口径平均仅 3.5 项 required（NLP 算法岗连「自然语言处理」都落 plus），权重坍塌至 required 项仅占本池 6%。

## 二、修订内容

### 改动点 1：§8.1 工序表 ⑤ 聚合行（SSOT + 模块一分册同款行）

**现有文本**：

> | ⑤ 聚合 | 代码频次(r/req) → importance 阈值映射 → level 冲突交 LLM#3（无自动取众数后门）→ 权重纯代码；LLM#3 重试 ×2 仍败 → `stalled` |

**拟改为**：

> | ⑤ 聚合 | 代码频次（r/req/occ —— req 为**条件口径**：「标 required 的 JD 数 ÷ 该能力**出现**的 JD 数」，绝对口径废弃）→ importance 三档映射：`required ⇔ 条件req ≥ REQ_THRESHOLD 且 occurrence r ≥ REQ_MIN_OCCURRENCE_RATIO 且 出现 JD 数 ≥ REQ_MIN_OCCURRENCE`；`preferred ⇔ 未达 required 且 r ≥ R_THRESHOLD`；否则 `plus` → level 冲突交 LLM#3（无自动众数后门）→ 权重纯代码；LLM#3 重试 ×2 仍败 → `stalled` |

**语义说明**（写入文档的「为什么」注记，紧跟公式）：

> required 的语义从「过半岗位把它列为必备」修正为「**岗位群体反复要求（出现率与出现数双门槛）且出现时多数按必备对待（条件口径）**」。三重判据各有职责：条件 req 修正单 JD 措辞泛滥（LLM#1 在单 JD 内将 80%+ 项标 required，绝对口径下被稀释）；r ≥ 0.25 保证是岗位共识而非孤立 JD 的孤证；出现 ≥ 3 条 JD 是统计证据下限（occ=2 时条件统计无意义）。裸条件口径（仅换分母不加门槛）已实测否决——条件 req 会放大单 JD 泛滥为 required 泛滥（图像算法岗 306 项中 271 项 required，77% 项「出现即全 required」）。

### 改动点 2：§6 可配置常量（SSOT 模块一常量段 + 模块一分册 §6）

**现有文本**：

> `IMPORTANCE_COEF={required:1.0, preferred:0.6, plus:0.3}`、`REQ_THRESHOLD=0.5`、`R_THRESHOLD=0.5`、…

**拟改为**（新增三个常量、改造一个）：

> `IMPORTANCE_COEF={required:1.0, preferred:0.6, plus:0.3}`、`REQ_THRESHOLD=0.5`（**语义变更：条件 req 口径阈值**）、`REQ_MIN_OCCURRENCE_RATIO=0.25`、`REQ_MIN_OCCURRENCE=3`（**新增**，出现率/出现数双支撑门槛）、`R_THRESHOLD=0.5`、…

### 改动点 3：§14 变更日志追加一行

> | 2026-09-07 | **模块一·聚合 importance 混合口径**：§8.1 工序⑤ 的 req 从绝对口径（标 required 的 JD 数 ÷ 岗位 JD 总数）改为条件口径（÷ 该能力出现的 JD 数），并加双支撑门槛（r ≥ 0.25 且出现 JD 数 ≥ 3）才可判 required；preferred/plus 判据不变。原绝对口径实测在 22 个 n≥4 岗位平均仅 3.5 项 required（NLP 算法岗的「自然语言处理」0.45 落 plus），required 项仅占本类目权重池 6%，权重坍塌 | 用户裁决（2026-09-07）：三个测试岗（SLAM/NLP/视觉）聚合产出「必备项过少、长尾严重」+ 第四岗验证（图像算法）+ 22 岗全量模拟（n≥7 段 1–3→7–11 项稳定修复；n∈[4,6] 段因 occ≥3 门槛从 4.2 微降至 3.4，证据薄弱项保守降档，by-design）；裸条件口径已实测否决（271/306 required 泛滥） | §8.1/§6/§14；《模块一设计》§3/§6；实施随代码落地：`server/config.py`、`server/services/aggregate.py`（`_map_importance` 签名与调用）、`server/test_m1_regression.py` 断言同步 |

## 三、验证证据摘要（支撑本次裁决的数据）

1. **旧口径失真**：22 个 n≥4 岗 required 均值 3.5（min 1）；SLAM 岗 r=0.36 的 ROS、NLP 岗 req=0.45 的 自然语言处理 等本命技能全部落 plus。
2. **新口径全量模拟**（22 岗，参数 0.5/0.25/3）：
   - n≥7 的 10 个主力岗（覆盖 67% JD）：required 1–3 → 7–11 项，名单语义全部成立（SLAM: ROS/IMU/VIO/视觉SLAM；NLP: 自然语言处理/机器学习/…）；
   - n∈[4,6] 的 12 岗：4.2 → 3.4（occ≥3 门槛挡下 occ=2 的弱证据项，保守方向，by-design——用户已知晓「NLP算法专家 vs NLP算法」行为差异源于证据下限而非口径分裂，两岗核心 required 交集 6/6 一致）；
   - 同族岗位核心收敛：NLP 系 6 项全交集、CV 系 4 项、SLAM 系 2 项。
3. **裸条件口径否决实验**：图像算法岗条件 req 直接判档 → 271/306 项 required（77% 项「出现即全 required」的泛滥传导）。

## 四、实现层影响（确认后派发，不随本修订稿执行）

- `server/config.py`：+`REQ_MIN_OCCURRENCE_RATIO=0.25`、+`REQ_MIN_OCCURRENCE=3`（`REQ_THRESHOLD` 值不变、语义变）
- `server/services/aggregate.py`：`_collect_items` 增记每项「出现 JD 数」（occ）；`_map_importance` 改混合判据（需传入 occ）；`occurrence` JSON 落库字段增补 `occ` 键（r/req 保留，req 语义注明条件口径）
- `competency_item.occurrence_json` 存量兼容：新旧模型同键并存无冲突（旧模型不含 occ 键，前端读旧模型不受影响）
- 重跑范围：22 个 n≥4 岗全量重聚（draft 覆盖，版本号自然递增）+ 三个已测岗对照验证

## 五、待用户裁决的开放点（随本稿一并确认）

1. **occ≥3 是否对 n<6 岗位放宽为 occ≥2**（自适应门槛）——本稿默认不放宽（简单优先，保守方向），如要放宽需在实现时加 n 条件分支并更新 §6 常量说明。
2. **软技能进 required 的接受度**——模拟中 沟通能力/团队合作 在多岗进 required（行业实情），若语义上 required 仅限技术项，需在判据加类目过滤断言。
3. 前端 P3 审核页证据面板是否展示条件 req 的三个组成数（required JD 数 / 出现 JD 数 / 岗位 JD 总数）——建议展示（一行三数），实现层小改。

---

**审阅栏**（用户填写）

- [ ] 改动点 1（§8.1 工序⑤行）：同意 / 修改意见：＿＿＿
- [ ] 改动点 2（§6 常量）：同意 / 修改意见：＿＿＿
- [ ] 改动点 3（§14 日志行）：同意 / 修改意见：＿＿＿
- [ ] 开放点 1（occ 门槛自适应）：不放宽 / 放宽
- [ ] 开放点 2（软技能 allowed）：允许 / 排除
- [ ] 开放点 3（证据面板三数）：展示 / 不展示
- [ ] 确认后授权写入 SSOT（原子 commit）：是 / 否
