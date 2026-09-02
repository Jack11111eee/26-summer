---
phase: 1
slug: p0
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-02
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + FastAPI TestClient（httpx）；脚本式 test_m6/question_bank 为 plain python |
| **Config file** | none — 默认收集；单文件单进程纪律靠约定（无 pytest.ini/conftest.py，Phase 6 REF-7.4 才统一） |
| **Quick run command** | `cd server && python -m pytest test_p0_security.py -v`（受影响单文件） |
| **Full suite command** | 逐文件：`python -m pytest server/test_p0_security.py -v` → `test_p0_chain.py` → `test_m5_backend.py` → `test_m7_backend.py`；脚本式：`python server/test_m6_backend.py`、`python server/test_question_bank.py`（**不得**一次 pytest 收多文件） |
| **Estimated runtime** | ~60–120 seconds（mock 模式离线，逐文件串行） |

---

## Sampling Rate

- **After every task commit:** Run 受影响单测试文件（<30s，mock 模式离线）
- **After every plan wave:** Run 全套件逐文件（m5/m7/m6/question_bank + 两个新 p0 文件）
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | REF-1.1/1.2 | IDOR | 越权矩阵：candidate↔candidate 读写 8 路由全 404；admin 读豁免/写拒绝 | integration | `python -m pytest test_p0_security.py -v` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | REF-1.1 | IDOR | route guard admin 例外修复（meta 调整） | integration | `python -m pytest test_p0_security.py -v` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | REF-1.5/2.2 | Repudiation | append-only 触发器拒绝 UPDATE/DELETE；from/to 必填；actor_type 校验 | unit+integration | `python -m pytest test_p0_security.py -v` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | REF-1.5 | Repudiation | 现有状态迁移点接入事件写入 | integration | `python -m pytest test_p0_security.py -v` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 2 | REF-5.10 | — | 主链串行：API 完成答题→POST /report→question_score>0 + 雷达非空 | integration | `python -m pytest test_p0_chain.py -v` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 2 | REF-8.2 | Tampering | completed 再调 /score、/report → 409（服务层） | integration | `python -m pytest test_p0_chain.py -v` | ❌ W0 | ⬜ pending |
| 01-04-01 | 04 | 2 | REF-3.5/8.5 | Tampering | 开考检查三状态 409 + error_code + 不建会话 + todos 新键 | integration | `python -m pytest test_p0_chain.py -v` | ❌ W0 | ⬜ pending |
| 01-04-02 | 04 | 2 | REF-3.5 | — | question_bank_task 表 + confirm 插行 + 存量种子不误伤 | integration | `python -m pytest test_p0_chain.py -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*注：Task ID 为预映射占位——planner 产出实际 PLAN.md 后以实际 task/wave 为准核对，执行前由 checker/executor 对齐。*

---

## Wave 0 Requirements

- [ ] `server/test_p0_security.py` — 越权矩阵 + append-only 触发器拒绝 + actor_type 校验（REF-1.1/1.2/1.5/2.2）
- [ ] `server/test_p0_chain.py` — 主链串行 + completed 护栏 + 开考检查三态 + todos（REF-5.10/8.2/3.5/8.5）
- [ ] `server/test_m5_backend.py` — 修改而非新建：257-258 评分断言改 409（Pitfall 4）
- [ ] `server/test_m6_backend.py` — 修改而非新建：直调断言按护栏语义核对/重写（D-09；已核 seed 为 in_progress，多数断言不受影响，需逐条过）
- [ ] 无需安装框架（pytest/TestClient 均已在环境中）——现有基础设施覆盖其余阶段需求

*既有回归文件（m5/m6/m7/question_bank）已存在，仅按护栏语义改断言，不新建。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| UI 真实链路：完成测评→直达报告页含真实雷达/逐题评分 | REF-5.10 | 浏览器内 SSE 轮询 + ECharts 渲染无法在 TestClient 级全真覆盖（CONTEXT specifics 要求真实 UI 验证） | dev 起 server+web，候选人账号完整走完测评→报告页；核对雷达非 no_data、逐题分存在；admin trace 可查 |

*其余阶段行为均有自动化验证（API 级 TestClient 覆盖主链串行/护栏/开考检查）。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
