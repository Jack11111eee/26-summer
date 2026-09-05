---
status: partial
phase: 05-evidence-report-contract
source: [05-VERIFICATION.md]
started: 2026-09-05T11:53:39Z
updated: 2026-09-05T11:53:39Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. IMPUTED 特殊视觉标记与覆盖率展示

expected: 打开一份含补算 item 的候选人报告，逐项明细中 imputed 项显示「补算 · 加权估算」amber 徽标，SECTION 3 下覆盖率摘要（观察覆盖率 % / 真实观察 / 可测量 / 补算数 / 缺失原因逐条），雷达图 imputed 轴带「（补算）」后缀；IMPUTED 项与真实观察项视觉可区分，覆盖率数字与后端 coverage 字段一致。
result: [pending]

### 2. 管理员发布按钮流程

expected: 测试中心对 READY/PROVISIONAL 报告点击「发布报告」，二次确认后状态变 PUBLISHED 且不可再发；HUMAN_REVIEW_REQUIRED 未 CONFIRMED 时被 409 拦截并提示；候选人权限被 403 拦截。
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
