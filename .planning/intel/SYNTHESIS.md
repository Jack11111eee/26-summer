# SYNTHESIS — Ingest Intel Entry Point

- 生成：gsd-doc-synthesizer，2026-09-02（MODE=new）
- 入口：本文件是 `gsd-roadmapper` 的唯一读取入口；细节见各 per-type intel 文件。

## Doc counts by type

- 总计 7 份文档，全部消费完毕（7/7）。
- DOC：6（SSOT 总设计文档 @precedence 0；模块一~四设计 @1；技术方案概述 @2）
- PRD：1（需求文档-胜任力测评与人才画像系统 @2）
- SPEC / ADR：0（无该类型文档；SSOT 按 manifest 承担约束提取权威）
- UNKNOWN/low-confidence：0
- 分类依据：.planning/intel/classifications/*.json（manifest_override=true，precedence 以 .planning/ingest-manifest.yaml 为准）

## Cycle detection

- 已跑（DFS 三色标记）：无环阻断。SSOT↔模块摘录的互引为「主文—分块摘录」包含关系，按约定记为链接不记为环；出界引用（历史档案/临时讨论稿/checkpoint）在 ingest 边界终止。遍历深度 3 / 上限 50。

## Decisions

- 锁定级决策：31 条（D-001~D-031），全部源于 SSOT `design/final-design/总设计文档.md`（仓库唯一 SSOT v2.0；其权威等同 locked——任何其他来源不得自动覆盖，修改须用户授权 + §14 变更日志）。
- 文件：.planning/intel/decisions.md
- 关键簇：系统范围边界（D-002）、四条强约束（D-003）、有界测评循环（D-004）、7:3 权重（D-006）、配额公式（D-008）、动态实例化四层选题（D-009）、难度路径状态机（D-010）、score_live 仅导航（D-012）、REFUSED/IMPUTED 聚合（D-013/D-015）、21 张表（D-018）、append-only 事件（D-019）、SSE/幂等（D-021）、计时 6h ABANDONED（D-022）、表单/gate（D-023）、报告发布契约（D-025）、权限 P0（D-026）、评测契约（D-027）、Prompt 禁改清单（D-030）。

## Requirements

- 7 条（REQ-jd-parse-model / REQ-dynamic-question-generation / REQ-interactive-multiturn-assessment / REQ-talent-profile-report / REQ-data-compliance / REQ-e2e-demo-deliverables / REQ-iterative-loop）。
- 唯一 PRD 来源：design/需求文档-胜任力测评与人才画像系统.md（+ 技术方案概述的上游补充）。
- 每条均登记 PRD 原始验收 + SSOT 落定口径；单一 PRD，无 competing variants。
- 文件：.planning/intel/requirements.md

## Constraints

- 30 条（C-001~C-052 序列，实际 30 条目）：全局 nfr 4 + schema 11 + protocol 9 + 开放参数 1 + 模块摘录新增代码级约束 3。
- 类型分布：api-contract 约 4、schema 11、nfr 9、protocol 8（含混合标注）。
- 开放参数（SSOT §31 六项）单独登记为「禁止臆造默认值」清单。
- 文件：.planning/intel/constraints.md

## Context topics

- 10 个主题：项目背景与目标、参考架构（上游描述已被 SSOT 取代）、文档治理与身份、与旧版差异登记 N1–N12、当前实现状态基线、修复重构待办实施顺序、Prompt 登记与延后、开放问题、交付与考核、合规。
- 文件：.planning/intel/context.md

## Conflicts

- BLOCKERS：0
- competing-variants（WARNING）：0
- auto-resolved（INFO）：6（均为上游需求/技术方案与 SSOT 的粒度差异，SSOT 胜；含分类哈希后缀审计说明）
- 报告：.planning/INGEST-CONFLICTS.md
- 安全门状态：无 BLOCKER → 通过；无需用户裁决项。

## 下游提示（roadmapper）

1. 排程权威顺序：SSOT §28 六步实施顺序为最高优先级输入（P0 = 所有权校验 / score→report 串行 / 开考检查 / 事件表）。
2. M1 回归是动态测评实施前硬前置（SSOT §8.1/§24）；候选人 E2E 是 M5–M7 verified 必要条件。
3. 开放参数（§31）不得在规划中臆造数值——排任务「校准」而非「定值」。
4. 本期范围红线：不做录用判断/排序/自动淘汰（D-002）；保留不做：黄金集、浏览器插件、真实 JD 数据集（D-029）。
5. SSOT 修改须用户授权：任何规划输出若要求改设计，先起草 SSOT 变更（正文 + §14），不得直接写 design/。
