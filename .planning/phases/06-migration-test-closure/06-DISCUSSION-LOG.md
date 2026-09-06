# Phase 6: 迁移体系与测试闭环收口 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-05
**Phase:** 6-迁移体系与测试闭环收口
**Areas discussed:** 迁移登记簿形态, 测试统一收集, CI 形态, M1 回归, mock 3分处置, E2E 形态, eval 隔离, bad case 候选, JWT 认证方向, secret 校验, 输入限额, 前端遗留收口范围, 开放参数

**模式：** auto（AUTOMATION-CHARTER §1「一个 phase 完结 → 开启下一 phase 的 discuss/plan，自动续跑，停在 plan 审查硬关口」）。以下每条「选定」为 auto 推荐项，留痕待计划审查硬关口用户确认。

---

## 迁移登记簿形态（REF-2.1/2.11）

| Option | Description | Selected |
|--------|-------------|----------|
| schema_version 表 + 有序迁移注册 | 替换 DDL 字符串嗅探，version 登记簿判断已迁移 | ✓ |
| 保留嗅探 + 加登记表 | 兼容但脆弱源仍在 | |

**选定（auto D-68）：** schema_version 表 + 有序迁移注册，替换 DDL 字符串嗅探。依据 = SSOT §8.1/矩阵 2.11「替换 DDL 字符串嗅探式迁移」+ CONCERNS「CHECK-constraint table-rebuild migrations 脆弱」。

## 测试统一 pytest 收集（REF-7.4）

| Option | Description | Selected |
|--------|-------------|----------|
| 脚本转 pytest + conftest 解 DB_PATH 冲突 | 一次性收集全部文件，per-session temp DB fixture | ✓ |
| 脚本保持独立命令 + 仅部分统一 | SC「全部后端测试 pytest 可统一收集」不满足 | |

**选定（auto D-69）：** 脚本转 pytest + conftest 解 DB_PATH 冲突。依据 = §24「统一 pytest 收集」+ TESTING.md「同一进程不得导入两测试模块」。

## CI 形态（REF-7.4）

| Option | Description | Selected |
|--------|-------------|----------|
| GitHub Actions | on push/PR，统一 pytest + npm build，全绿为验收 | ✓ |
| 本地脚本 / 无 CI | 不满足「CI 为正式验收入口」 | |

**选定（auto D-70）：** GitHub Actions。依据 = §24「CI 为正式验收入口」+ gh CLI 已可用。

## M1 回归清单（REF-7.5）

| Option | Description | Selected |
|--------|-------------|----------|
| 专测文件锁八项 + 补 13 会话测试 model/version | 逐项断言锁定 + [04-011] 修复 | ✓ |
| 依赖既有测试凑合 | 尾差/清洗边界/消歧无直测 | |

**选定（auto D-71）：** 专测文件 + [04-011] 修复。依据 = 模块一 §8 八项 + STATE Deferred「13 个会话类测试文件并入 Phase 6 M1 回归收口」。

## mock interviewer 3分处置（REF-8.6）

| Option | Description | Selected |
|--------|-------------|----------|
| 保持 mock 确定性 + 记档 | c 靠客观题区分，b 方差=0 记 mock-only | ✓ |
| 增强 mock 主观评分 | 破坏 test_m6 数值断言（total_score=31.4 等）大面积 | |

**选定（auto D-72）：** 保持 mock 确定性 + 记档。依据 = 数值断言依赖恒 3 + D-027「mock 回归不能替代真实 LLM 验证」。

## E2E 形态（REF-7.6）

| Option | Description | Selected |
|--------|-------------|----------|
| API/service 层脚本化 + 前端契约修复 | 无新依赖，刷新/断线/超时/越权均 API 层可测 | ✓ |
| Playwright 浏览器 E2E | 覆盖前端 JS 行为但引入重依赖 | |

**选定（auto D-73）：** API/service 层脚本化 + 前端契约修复。依据 = D-005 本地演示 + 前端零测试为已承认范围 + 场景均 API 层可脚本化。**注：若用户偏好浏览器级 E2E 可在计划审查改选。**

## eval 隔离（REF-8.8）

| Option | Description | Selected |
|--------|-------------|----------|
| DB_PATH 覆盖 + temp DB 种子 | eval 写临时库不污染业务库 | ✓ |
| 事务回滚 | SQLite 单写者 + BackgroundTasks 下复杂 | |

**选定（auto D-74）：** DB_PATH 覆盖 + temp DB 种子。依据 = §23「独立/临时数据库」+ §2.4 数据隔离。

## bad case 候选（REF-5.11）

| Option | Description | Selected |
|--------|-------------|----------|
| bad_case_candidate + 管理员审核不自动改分 | §2.3 伪码照做，阈值开放参数 | ✓ |
| 自动改分 / 自动淘汰 | D-002/D-031 红线禁止 | |

**选定（auto D-75）：** 候选 + 管理员审核不自动改分。依据 = §2.3 + D-031「异议只进人工永不触发改分」。

## JWT 认证方向（REF-6.1）— 关口包

| Option | Description | Selected |
|--------|-------------|----------|
| 迁移 HttpOnly cookie | 对齐 SSOT 方向、XSS 安全；churn 大 | ✓（auto 推荐） |
| 保持 Bearer 记档 | 非 P0、Vue 转义收敛；SSOT 方向未落实 | |

**选定（auto 推荐 D-76）：** 迁移 HttpOnly cookie（`Set-Cookie HttpOnly + SameSite=Lax`，前端 credentials 去 Authorization 头）。**此为设计取舍 + 前端/测试大面积 churn → 计划审查硬关口由用户确认**（备选 = 保持 Bearer）。

## secret 启动校验（REF-6.2）

| Option | Description | Selected |
|--------|-------------|----------|
| 默认 secret + 真实 provider → 拒绝启动 | fail fast；mock 放行 + warning | ✓ |
| 只告警不拒绝 | 真实部署可伪造 admin token | |

**选定（auto D-77）：** 默认 secret + 真实 provider 拒绝启动，mock 放行告警。依据 = CONCERNS「JWT secret defaults to a known constant」。

## 输入限额（REF-6.3）

| Option | Description | Selected |
|--------|-------------|----------|
| config 集中常量 + 接口校验 | 按类型配置；数值开放参数 | ✓ |
| 硬编码分散 | 不可维护、不可校准 | |

**选定（auto D-78）：** config 集中常量 + 接口校验，数值开放参数。依据 = §31 开放参数「禁止臆造默认值」。

## 前端遗留收口范围

| Option | Description | Selected |
|--------|-------------|----------|
| 主链必做项 + polish 延后 | Chat.vue/FormCard/missing_reasons 映射/失败重试 UI；版本对比 UI 延后 | ✓ |
| 全部前端遗留一并收 | 版本对比/完整复核 UI 超范围 | |

**选定（auto D-79）：** 主链必做项 + polish 延后。依据 = E2E 主链完整性 vs 打磨边界。

---

## 开放参数（关口包呈报——不 auto 代决数值）

§31-4 词典匹配阈值 + 清洗词表 / §31-5 trace 保留期/脱敏 / §31-6 幂等清理阈值 / REF-5.11 bad case 背离阈值 / REF-6.3 输入限额数值。plan 落 config 占位 + 常量注释「实施期校准」，若用户不裁决则维持占位默认。

## Claude's Discretion

- schema_version 迁移注册机制 / 测试 DB_PATH 冲突解法 / CI steps / M1 回归文件组织 / eval 隔离 DB 机制 / bad_case_candidate 表结构 / JWT CSRF 机制 / 输入限额校验落点 / 测试组织

## Deferred Ideas

- 等值备用题组（REF-3.8）、综合题（REF-3.9）、Tools 白名单（REF-4.11）、黄金集（§2.5）、真实 LLM 验证（D-027）、公平性（D-031）
- 报告版本对比 UI / admin 完整复核 UI（polish）
- 进程重启任务恢复 / 持久化 job 表
- 随机 secret 生成持久化
