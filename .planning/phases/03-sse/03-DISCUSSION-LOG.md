# Phase 3: 表单/SSE/幂等/计时 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-05
**Phase:** 3-表单/SSE/幂等/计时
**Mode:** auto（章程 §1 授权代确认——推荐项自动选取，逐条留痕；03 关口包回呈）
**Areas discussed:** form_instance 表形态与 schema 版本化, render_form 触发点与 gate 结构化落位, experience/qualification 出题库承接, SSE 端点形态与事件类型, trace 与 SSE 关系, 幂等作用域与并发防护, 幂等记录清理, 计时采样与服务端权威形态, 暂停端点语义, 超时三路行为, 6h 活性判定, 消息分列形态, 导航摘要层实现度, injection 留痕形态, 接口层 Pydantic 范围

---

## form_instance 表形态与 schema 版本化

| Option | Description | Selected |
|--------|-------------|----------|
| 新表 form_instance（§16.1）+ 代码 schema 常量 + 字符串版本快照 | 生命周期实体独立；旧 form_submission 保留兼容 | ✓ |
| 改造 form_submission 现表 | 旧表背负非生命周期语义，改造成本高 | |
| 引 JSON Schema 库做正式版本化 | 重依赖，最小实现不需要 | |

**User's choice:** [auto] 推荐项——新表（依据：SSOT §16.1「form_instance（v2.0 新增生命周期实体）」原文）
**Notes:** schema「代码定义 + 版本化」的最小实现 = 常量 + 快照 JSON；Pydantic 承担校验语义。

## render_form 触发点与 gate 结构化落位

| Option | Description | Selected |
|--------|-------------|----------|
| 池耗尽→gate 未采集→render_form→之后 finish（扩展 02-02 池耗尽语义） | 代码触发点单一明确；LLM 只能请求 | ✓ |
| 会话创建后立即 render 表单 | §16.1「资格核验阶段」语义偏差（应在测评后收口前） | |
| 前端主动拉取表单 | 违反「代码触发」契约 | |

**User's choice:** [auto] 推荐项——池耗尽扩展（依据：§16.1 render_form 代码触发 + 02-02 已留扩展点）
**Notes:** gate 结果落 question_score gate 行结构化列；人工覆盖落列+校验位；admin 覆盖 UI 属 Phase 5。

## experience/qualification 出题库承接

| Option | Description | Selected |
|--------|-------------|----------|
| 生成侧排除 + form 链采集 + 种子 gate=1（02-04 已落） | 三点闭环，无需回改 selection/readiness | ✓ |
| 生成侧保留 + selection 运行时过滤 | 02-02 已剔除——冗余 | |

**User's choice:** [auto] 推荐项（依据：02-04 SUMMARY gate=1 形态 + SC-2 已达成的前半段）

## SSE 端点形态与事件类型

| Option | Description | Selected |
|--------|-------------|----------|
| 同 URL POST /answer 直改 text/event-stream（sse.js 自适应就绪） | 零前端改动；双 Content-Type 分叉不做 | ✓ |
| 新增 /answer/stream 端点并行 | 两端点语义漂移面 | |
| GET 长轮询 | 契约背离 | |

**User's choice:** [auto] 推荐项（依据：§11.5 + sse.js:1-13 注释契约 decision/reply/done）
**Notes:** 决策先落库再推流；mock 假流分块离线可测；finish 仅代码触发保持 02-02 口径。

## trace 与 SSE 关系

| Option | Description | Selected |
|--------|-------------|----------|
| SSE 层零持久化，留痕仍走 append_event | 流完成时消息已落库——审计链不受传输形态影响 | ✓ |
| SSE 事件也写 trace | 双写冗余 | |

**User's choice:** [auto] 推荐项（依据：REF-1.4 合规保持 + §13.1 append-only 单点）

## 幂等作用域与并发防护

| Option | Description | Selected |
|--------|-------------|----------|
| idempotency_record 新表（三键作用域 + 快照回放）+ revision 乐观锁 | §13.4 原文形态；幂等键可选不破坏旧调用 | ✓ |
| 只用 revision 乐观锁 | 不满足「重复返回首次结果」 | |
| Redis/进程内缓存 | D-005 演示形态无外部服务 | |

**User's choice:** [auto] 推荐项（依据：§13.4 逐条）
**Notes:** assessment_question 加 revision 列（02-01 ALTER 惯例）；答题付三键进 request_hash。

## 幂等记录清理

| Option | Description | Selected |
|--------|-------------|----------|
| 不实现（表结构留索引；Phase 6 数据治理） | SSOT「策略实施期定」 | ✓ |
| 实现阈值提醒 | 越期臆造 | |

**User's choice:** [auto] 推荐项

## 计时采样与服务端权威形态

| Option | Description | Selected |
|--------|-------------|----------|
| 惰性推进（请求点闭旧开新）+ 派生 Σ 查询 + 收尾刷新缓存列 | 无后台线程（D-005）；§15「客户端只展示」 | ✓ |
| 后台 timer 线程 | 违反单进程演示形态；复杂度不可审计 | |

**User's choice:** [auto] 推荐项（依据：§15 服务端权威 + D-005）
**Notes:** 单题超时只在请求时点判定（now - activated_at - Σpaused 重叠）。

## 暂停端点语义

| Option | Description | Selected |
|--------|-------------|----------|
| 显式 pause 端点 + PAUSED 区间 + 期间写操作 409 | 四类暂停同区间类型 reason 区分 | ✓ |
| 自动暂停（断线检测） | §15「短暂断线不自动暂停」 | |

**User's choice:** [auto] 推荐项（依据：§15 原文）
**Notes:** 敏感 reason 不进评分 prompt；SESSION_PAUSE_REQUESTED/PAUSED/RESUMED 三事件（§13.2 组）。

## 超时三路行为

| Option | Description | Selected |
|--------|-------------|----------|
| 单题超时封存续题（02-04 第四路）/ 全场超时进收尾（复用串行链）/ 6h ABANDONED 惰性+可选周期扫描 | 三路各对 SSOT 原文；不启后台服务 | ✓ |
| 超时强制 abort 会话 | 过度；§15「继续下一题」 | |

**User's choice:** [auto] 推荐项（依据：§15 原文三条）
**Notes:** GLOBAL_TIMEOUT 先于 ENTERED_SCORING（审计算子顺序）；计时不参与选题优先级。

## 6h 活性判定

| Option | Description | Selected |
|--------|-------------|----------|
| last_activity_at 列（本 phase 加，写操作刷新） | 判定基准单点 | ✓ |
| 复用 created_at/updated_at 既有列 | 语义混合（updated_at 含服务端写） | |

**User's choice:** [auto] 推荐项（依据：§12.1 演进列清单原文含 last_activity_at）

## 消息分列形态

| Option | Description | Selected |
|--------|-------------|----------|
| ALTER 加列（content 保留 + refined_content/client_request_id/sequence_no 新增；raw_hash 已有） | 双轨期安全；02-01 惯例 | ✓ |
| 重建 assessment_message | 数据搬迁风险无必要 | |

**User's choice:** [auto] 推荐项（依据：§12.3 列名照 SSOT + 02-01 ALTER 先例）

## 导航摘要层实现度

| Option | Description | Selected |
|--------|-------------|----------|
| 结构化状态优先（数据库查询），LLM 摘要不实现 | SSOT「可选」措辞 + 失败回退天然满足 | ✓ |
| LLM 摘要生成 | 契约不强制；多一 LLM 面无验收口径 | |

**User's choice:** [auto] 推荐项（依据：§14「LLM 摘要可选」）

## injection 留痕形态

| Option | Description | Selected |
|--------|-------------|----------|
| answer_state=PROMPT_INJECTION → INJECTION_DETECTED 事件（payload 不含原文） | 分类即检测；词表可测 | ✓ |
| 独立检测器（正则/模型） | 臆造检测口径；severity 分级留 Phase 6 | |

**User's choice:** [auto] 推荐项（依据：§13.2 枚举既有 + §16.3「候选人输入永远是数据」）

## 接口层 Pydantic 范围

| Option | Description | Selected |
|--------|-------------|----------|
| 新端点全覆盖；存量端点不回溯 | 改动面控制；价值主要在新链路 | ✓ |
| 全部存量端点一并改写 | 大面积回归无对应验收项 | |

**User's choice:** [auto] 推荐项——**呈报项**：REF-4.7 若 checker 判定为「全部接口」，此裁量风险带关口包呈报用户确认

---

## Claude's Discretion

- form schema 字段定义（参照 form_submission 现行 payload + _gate_check 消费口径）
- idempotency request_hash 算法与快照截断策略
- interval helper 命名与放置
- 测试组织（test_phase3_* 五文件三件套纪律）
- SSE mock 假流分块步调

## Deferred Ideas

- 断线续传 cursor / 事件回放
- ABANDONED 会话恢复
- 幂等记录清理阈值与管理员接口
- LLM 导航摘要生成
- admin 表单人工覆盖前端 UI（Phase 5）
- Injection severity 分级与真实 LLM 检测质量（Phase 6 / D-027）
- Tools 白名单（REF-4.11 不变）
