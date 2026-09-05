---
phase: 05-evidence-report-contract
plan: 05-05
title: 前端 IMPUTED 标记 + 覆盖率展示收口（gap closure）
status: complete
commits:
  - fb4d139
---

# 05-05 执行摘要：前端 IMPUTED 标记 + 覆盖率展示收口

## 结果

SC #2 前端展示缺口已闭合（gap closure），后端数据契约「数据已就位、前端已接线」。

## 落地清单

| 任务 | 文件 | 内容 | 验证 |
|------|------|------|------|
| 1 | `server/services/report.py:183` | `radar_data.indicators` 补 `imputed: bool(it.get("imputed"))` | `test_phase5_report.py` 11 passed |
| 2a | `web/src/views/assessment/Report.vue` | 明细表能力项加「补算 · 加权估算」amber 徽标（`v-else-if` 与 gate/no_data 互斥） | 前端 build 通过 |
| 2b | 同上 | SECTION 3 下加覆盖率摘要（观察覆盖率 % / 真实观察 / 可测量 / 补算数 / 缺失原因逐条） | 前端 build 通过 |
| 3 | 同上 `renderRadar()` | imputed 轴 name 追加「（补算）」后缀（逐 indicator 生效） | 前端 build 通过 |
| 4 | 同上 `itemReason()` | 改 `q.item_id === itemId` 精确匹配，删陈旧注释与冗余 item 反查 | 前端 build 通过 |

## 验证结果

- 后端：`test_phase5_report.py` 11 passed / `test_phase5_evidence.py` 6 passed / `test_phase5_feedback.py` 3 passed / `test_m6_backend.py` 44 passed 0 failed —— 全绿，无回归。
- 前端：`npm run build` ✓ built in 6.22s（仅 chunk-size 提示，既有）。无前端单测基建，视觉呈现待人工目验（见 VERIFICATION「Human Verification」）。

## 边界遵守

- 未触碰 SSOT、未触碰业务库 `data/app.db`、未改后端计算逻辑、未改 FAILED/GENERATING/ready 三分支与发布/异议流。

## 遗留（非阻断，记档）

- 缺失原因 `reason` 为内部 score_state 码（INVALIDATED/INCOMPLETE/INSUFFICIENT_EVIDENCE/NOT_ADMINISTERED）或「qualification 缺失（不补算）」中文串，前端按原样展示，未做码→中文映射。如需中文文案可后续收口（非 SC 契约，SSOT 仅要求「展示缺失原因」已满足）。
