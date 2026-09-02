# Phase 1: P0 安全与主链修复 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-02
**Phase:** 1-P0 安全与主链修复
**Areas discussed:** 越权语义与实现, 状态事件接入范围, 评分→报告串行, 开考检查裁剪
**Mode:** discuss + --analyze（每题先给权衡分析）

---

## 越权语义与实现

### Q1 越权返回状态码

| Option | Description | Selected |
|--------|-------------|----------|
| 404 统一（推荐） | 越权与不存在统一 404（单查询 + OR admin 读豁免）；实现最薄，不泄露存在性 | ✓ |
| 403 显式拒绝 | 先查存在再验归属；语义清晰但多一层分支 | |
| 读 404 / 写 403 | GET 404 隐藏存在性，POST 403 显式拒绝；双语义 | |

**User's choice:** 404 统一（推荐）
**Notes:** ROADMAP 原文"越权返回 403/404"有歧义，此题消歧为 404。

### Q2 所有权校验实现形态

| Option | Description | Selected |
|--------|-------------|----------|
| 共享 helper（推荐） | load_owned_session / load_owned_report，路由首调，返回行或抛 404；单点强制 | ✓ |
| 每路由内联 WHERE | diff 最小但 8 处分散，新路由易漏 | |
| Depends 注入 | 最符合 FastAPI 惯例但需独立连接，机制偏重 | |

**User's choice:** 共享 helper（推荐）
**Notes:** IDOR 典型失效模式是"漏掉一条路由"，单点强制优先于风格守旧。

### Q3 admin 写边界

| Option | Description | Selected |
|--------|-------------|----------|
| admin 只读（推荐） | 可读候选人资源，写操作一律 owner-only，admin 写同样拒绝 | ✓ |
| 读写全放行 | 字面"最高权限"；护栏需为 admin 开例外 | |
| 只读+评分豁免 | 额外豁免 POST /score、/report 触发权（为未来重试预留） | |

**User's choice:** admin 只读（推荐）
**Notes:** SSOT §7 只授"可读取"；串行化后评分/报告由服务端内部链触发，无 admin 代写需求。

### Q4 前端 route guard 缺陷是否顺带修

| Option | Description | Selected |
|--------|-------------|----------|
| 顺带修（推荐） | session/report 两条路由 meta 改 requiresAuth:true，与后端权限模型对齐 | ✓ |
| 留到 Phase 6 | 只做后端越权校验，守卫缺陷挂账 E2E | |

**User's choice:** 顺带修（推荐）
**Notes:** CONCERNS.md 已记录的已知缺陷（admin 完成测评被 route guard 弹回）；属权限模型一致性收尾而非新能力。

---

## 状态事件接入范围

### Q1 事件范围是否含串行链 TASK_* 事件

| Option | Description | Selected |
|--------|-------------|----------|
| 全量+链事件（推荐） | session/question 必接项 + 评分→报告后台链 TASK_* 与 SESSION_ENTERED_SCORING | ✓ |
| 仅必接项 | 只接成功标准硬性要求的迁移点；TASK_* 留 Phase 5 | |

**User's choice:** 全量+链事件（推荐）
**Notes:** "一切留痕"为 D-003 不可让步项；串行链是 P0 修复后的正常 UI 主链，不可无留痕。

### Q2 append-only 强制机制

| Option | Description | Selected |
|--------|-------------|----------|
| 触发器+helper（推荐） | BEFORE UPDATE/DELETE 触发器 RAISE ABORT + append_event() 单点封装 | ✓ |
| 仅触发器 | 物理强制但写入点各自手写取号 | |
| 仅代码纪律 | 无法满足"测试证明拒绝"字面要求 | |

**User's choice:** 触发器+helper（推荐）
**Notes:** 成功标准 #4 要求 UPDATE/DELETE "被测试证明拒绝"——只有 DB 层触发器能做到。

### Q3 actor_type 枚举

| Option | Description | Selected |
|--------|-------------|----------|
| 三值起步（推荐） | candidate/system/admin，helper 内代码校验（N11 无 DB CHECK），admin 值预留不写入 | ✓ |
| system 单值 | 全部写 system；回放时无法区分候选人主动作 | |

**User's choice:** 三值起步（推荐）
**Notes:** SSOT §13.1 定了列未定枚举——此题为枚举定值。

---

## 评分→报告串行

### Q1 串行落点

| Option | Description | Selected |
|--------|-------------|----------|
| B 入口链（推荐） | POST /report 的 background task 先调 score_session 再 aggregate/generate | ✓ |
| A finish 直调 | answer 端点 action=finish 时同步执行；两次 LLM 链有超时风险 | |
| C 服务内部 | generate_report() 首调 score_session；隐式副作用与 §21.1 措辞冲突 | |

**User's choice:** B 入口链（推荐）
**Notes:** 与现有 BackgroundTasks+轮询形态同构，前端不动；eval/CLI 直调服务层不受影响。

### Q2 POST /score 去留与护栏落点

| Option | Description | Selected |
|--------|-------------|----------|
| 保留+服务层护栏（推荐） | 端点保留；护栏写服务层入口（completed→409，in_progress→409），双路径都被护 | ✓ |
| 端点下线 | 转内部函数；破坏性改动无收益 | |
| 仅 API 层护栏 | 服务层直调绕过，不彻底 | |

**User's choice:** 保留+服务层护栏（推荐）
**Notes:** 护栏应护行为不护入口；test_m6_backend.py 直调断言随修复同步重写（不重构风格，统一 pytest 是 Phase 6）。

### Q3 串行链期间 session 快照状态口径

| Option | Description | Selected |
|--------|-------------|----------|
| 不加中间态（推荐） | finish 置 completed，链进度由 TASK_* 事件表达；SCORING 态留给 Phase 3 | ✓ |
| 提前加 SCORING | 需改 CHECK 约束（N11 反模式），越界 Phase 3 表演进 | |

**User's choice:** 不加中间态（推荐）
**Notes:** "表结构演进随阶段走"既定决策（REF-2.6 属 Phase 3）。

---

## 开考检查裁剪

### Q1 指向后期阶段的检查项处理

| Option | Description | Selected |
|--------|-------------|----------|
| 分层留扩展点（推荐） | §10.4 全链骨架一次成型；Phase 1 实现 4 项+旧配额口径；新配额/综合题/表单留 no-op 位 | ✓ |
| 只写现有项 | 后续 Phase 各自加；§10.4 无单一权威实现点 | |

**User's choice:** 分层留扩展点（推荐）
**Notes:** 扩展点对应已排期工作（Phase 2/3/4 各自填位），非投机配置；Phase 1 配额校验按现行 CATEGORY_QUOTA 口径。

### Q2 题库 readiness 判定载体

| Option | Description | Selected |
|--------|-------------|----------|
| A 任务表（推荐） | 新增 question_bank_task（position+model/version+status+时间戳）；三态真实可查 | ✓ |
| B 推断式 | 按题行数 vs items 数推断；生成中与缺题不可分 | |
| C 事件表复用 | 事件表 session_id NOT NULL，题库生成在 session 之外，破坏语义 | |

**User's choice:** A 任务表（推荐）
**Notes:** 三个失败状态名要求区分"生成中/缺题/就绪"；Phase 4 REF-8.4 失败可见直接复用此表。

### Q3 失败的待办与候选人端呈现

| Option | Description | Selected |
|--------|-------------|----------|
| 扩展聚合+409 码（推荐） | todos 增加不就绪岗位计数/列表；POST /sessions 返回 409+error_code+中文 detail | ✓ |
| 仅后端记录 | 不动 UI；不满足"产生管理员待办"可见性 | |

**User's choice:** 扩展聚合+409 码（推荐）
**Notes:** error_code 供测试矩阵机器断言，detail 供人读，与现有 409/422 惯例一致。

---

## Claude's Discretion

- helper 命名与放置位置（api 顶部 vs core/security.py）
- append_event 参数形状（未用 SSOT 列位填 NULL）
- question_bank_task 的 id 前缀与索引
- 越权测试矩阵用例组织与断言粒度（pytest 可收集纪律内自由编排）

## Deferred Ideas

None — 讨论未越出 Phase 1 范围（admin 代写/评分重试豁免等选项被否即弃，未登记延期）。
