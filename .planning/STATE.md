---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: milestone
status: verifying
stopped_at: Completed 06-05-PLAN.md
last_updated: "2026-09-05T16:16:59.984Z"
last_activity: 2026-09-05
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 26
  completed_plans: 26
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-02)

**Core value:** 端到端可演示（JD 解析→测评框架→交互测评→画像生成）+ 全链可审计（LLM trace 留痕、状态事件 append-only、报告可回溯）
**Current focus:** Phase 06 — migration-test-closure

## Current Position

Phase: 06 (migration-test-closure) — EXECUTING
Plan: 5 of 5
Status: Phase complete — ready for verification
Last activity: 2026-09-05

- **工作分支**：`feature/m5-assessment`（当前分支，直接在此推进 M1 修复/重构流）
- **下一动作**：Phase 4 已完结 → 启动 Phase 5 discuss（证据链与报告契约）→ 停在 Phase 5 硬关口 A（plan 审查）
- **阶段顺序权威**：SSOT §28 六步（P0 四项 → 动态选题/状态机 → 表单/SSE/幂等/计时 → 题库版本 → 证据/报告契约 → 迁移/测试收口）；表结构演进"随阶段走"，Phase 6 收口 schema_version

## Performance Metrics

**Velocity:**

- Total plans completed: 7
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 04 | 2 | - | - |
| 5 | 5 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 02 P02 | 41min | 5 tasks | 9 files |
| Phase 04 P01 | 50min | 3 tasks | 7 files |
| Phase 04 P02 | 5min | 3 tasks | 5 files |
| Phase 05 P01 | 9min | 3 tasks | 5 files |
| Phase 05 P02 | 5min | 3 tasks | 3 files |
| Phase 05 P03 | 9min | 3 tasks | 12 files |
| Phase 05 P04 | 3min | 3 tasks | 5 files |
| Phase 06 P01 | 25min | 3 tasks | 3 files |
| Phase 06 P02 | 11min | 2 tasks | 4 files |
| Phase 06 P04 | 15min | 3 tasks | 5 files |
| Phase 06 P05 | 9min | 3 tasks | 11 files |
| Phase 06 P03 | 25min | 3 tasks | 15 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table (31 locked SSOT decisions D-001~D-031; full text: .planning/intel/decisions.md). Recent decisions affecting current work:

- [Init]: 路线图 6 阶段 = SSOT §28 六步 1:1 映射，不引入额外语义
- [Init]: 矩阵 68 行 → REQUIREMENTS.md REF-*（63 排期 + 2 保持 + 3 延后：等值组/综合题/Tools）
- [Init]: 表结构演进随阶段内嵌迁移，Phase 6 收口 schema_version（矩阵 §10 建议）
- [Init]: 开放参数（SSOT §31 六项）排"校准"任务，禁止臆造默认值
- [Phase ?]: [02-02] 层②uncovered required 优先须在配额剩余槽位内——否则 §10.5 例外分支不可达
- [Phase ?]: [02-02] 决策 finish 在池未空时降级 next（is_last 旧口径失真）——02-04 裁决层接管前的 API 层过渡
- [Phase ?]: [02-02] ORDINARY_PLAN_N=10 经关口 A 用户裁决 [02-007] 落地——Task 5 checkpoint 免停车
- [Phase 04]: [04-01] 落库绑定：_insert_question 写 model_id/model_version/item_id/rubric_version='v1'，判重键升级为 (model_id,model_version,std_name,category,difficulty)（D-47/D-49）
- [Phase 04]: [04-01] 消费侧强制双列匹配：readiness 三处 count/tier WHERE 与 selection _load_candidate_rows 均加 model_id+model_version 谓词，去 NULL 放行（D-50）
- [Phase 04]: [04-01] 失败可见：readiness FAILED 分支返回 QUESTION_BANK_INCOMPLETE + error_msg[:200]；get_todos 新增 question_bank_failed 明细（D-51/REF-8.4）
- [Phase 04]: [04-02] orphan 路由前置：/jds/orphan 迁入 jds.py 置于 /jds/{jd_id} 之前，字段口径锁定选项 B（字段子集 + status != 'failed'）（REF-7.1）
- [Phase 04]: [04-02] 模型编辑校验：ModelItem 字段级校验（allow_inf_nan=False/ge+le/Literal）+ update_model 同 category 重复 std_name 拒绝，保留 Σ=100%（REF-7.2）
- [Phase 05]: _locate_span 定位失败返回 None，调用方降级为 quote_hash-only span（source_message_id/offset 全 None）
- [Phase 05]: 旧 llm_trace.ref_id 经 _migrate_trace_link 按 call_type→候选表 probe 命中才拆 trace_link('source')，未命中保留原 ref_id
- [Phase 05]: score→trace 运行时写点仅主观题（客观/INVALIDATED 无 LLM trace，trace_id=None 不写 link）
- [Phase 05]: test 文件懒导入 _locate_span（Task 2 子集先可收集，Task 3 落地后三 span 测试可用）
- [Phase 05]: adjudicate 冲突阈值=2 取低留人工标记；_normalize_score 统一 (score−1)/4（关口 A 裁决，作废 score/5 两尺度混用）
- [Phase 05]: IMPUTE_RATIO_THRESHOLD=0.2；可测量普通 item = 非 gate 且 importance≠required 且 category≠qualification
- [Phase 05]: 测试纯函数懒导入 adjudicate/_impute_r/_normalize_score（Task 2 子集先可收集，Task 3 落地 _impute_r）
- [Phase 05]: aggregate 新增 coverage/review_status/observation_status/provisional；report.py 透传（状态机落库属 05-03）
- [Phase 05]: 05-03 存量回填 PUBLISHED+NONE+version=1；REVIEW_STATUSES 六值含 HUMAN_REVIEW_REQUIRED；HIRING_REDLINE_WORDS 六词表集中 report_checks.py（关口 A 裁决）
- [Phase 05]: 05-03 校验②改 agg-vs-DB weight 一致性（m6 种子 Σ=0.40，绝对值 Σ≈1.0 失真）；校验⑦加 report_text 参数扫红线词
- [Phase 05]: 05-03 report→trace 写点：generate_report 落 report 行后 link_entity reported(report)/source(session)，闭合 D-56 五要素
- [Phase 05]: feedback 审计列命名 = user_id/review_note/reviewer_id/reviewed_at（D-66 简写落为 plan 权威口径）
- [Phase 05]: 存量 feedback 行四审计列保持 NULL（迁移不虚构提交人/处理人）
- [Phase 05]: REVIEW_FEEDBACK_RECEIVED 事件 actor_type=candidate actor_id=user_id 与 feedback INSERT 同事务单 commit
- [Phase 06]: schema_version 登记簿取代 DDL 字符串嗅探：init_db 主判据查 schema_version 登记簿，13 迁移注册进 MIGRATIONS；两个 DDL 重建迁移（_migrate_llm_trace/_migrate_feedback_status）保留内部 'report'/'bad_case' 嗅探为 belt-and-suspenders 幂等 — D-68/REF-2.11
- [Phase 06]: set_db_path()/_DB_PATH_OVERRIDE 进程内覆盖 get_conn/init_db 的 DB 路径（不落盘不改 env），迁移前 stdlib conn.backup() 备份到 backups/；conftest.py mock 三件套 + session 级临时 DB fixture 落地为 Wave 0 linchpin — D-74/D-69
- [Phase 06]: test_m6 顺序依赖用 session ctx fixture 单次 seed + 顺序复用（_test_* 转 test_* 保脚本顺序语义）；带参 test_* 改 check_* 消 3 个 fixture 误判（D-69）
- [Phase 06]: CI = GitHub Actions：backend(pytest .) + frontend(npm ci 与 npm run build) 两 job 并行；requirements.txt 补 pytest>=8（D-70）
- [Phase 06]: E2E question_bank 直插种子写 model_id/model_version（Phase 4 消费侧收紧 D-50，readiness/选题按双列过滤）
- [Phase 06]: submit-v2 body 带 schema_version:'v1'（FormSubmitRequest.schema_version 必填，计划 body 规格遗漏）
- [Phase 06]: missing_reasons 渲染在 Report.vue 非 Chat.vue；报告失败重试 UI 已存在（D-79）
- [Phase 06]: 06-05 D-76 JWT 方向 = jwt-cookie-migrate（本期仅锁方向，迁移后续计划）[06-009]
- [Phase 06]: 06-05 REF-6.2 secret = secret-failclosed-keep（锁定 main.py fail-closed-always 现状，零生产改动）[06-009]
- [Phase 06]: 06-05 eval 隔离 = sqlite3 backup 全量业务库只读快照到临时库（RESEARCH Pattern 4）
- [Phase 06]: 06-05 bad_case 幂等 guard = question_id IS NULL-safe 比较，报告版本化不重复建候选

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1 前置]: 矩阵 5.10 实测为前端零步断裂（真实 UI 流程 question_score 恒空 → 报告 no_data），测试通过仅因 test_m6_backend.py Python 层直调 score_session 掩盖——Phase 1 修复后该测试断言需同步重写
- [全局]: 测试纪律——同一进程不得导入两个测试模块（DB_PATH import 时读取冲突）；新测试必须 pytest 可收集
- [全局]: SQLite 单写者——混 DB 写与 LLM 调用必须"先 commit 再调 LLM"或"内存算完单事务落库"两种既有模式之一
- [全局]: SSOT 任何修改须用户明确授权（agent 仅起草），先改 SSOT（正文 + §14）再动代码

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| 契约 | REF-3.8 等值备用题组（SSOT 未列 §28 硬项） | 登记不排期 | 2026-09-02 (Init) |
| 契约 | REF-3.9 综合题槽位（生成 Prompt 待讨论，D-030） | 登记不排期 | 2026-09-02 (Init) |
| 契约 | REF-4.11 Tools 白名单（本期无工具调用，接口登记随 Prompt 模块） | 登记不排期 | 2026-09-02 (Init) |
| 回归 | 13 个会话类测试文件（test_m5/m6/m7、test_p0_chain/security、phase2 difficulty/interview/scoring、phase3 forms/sse/timer/idempotency/misc）直插 question_bank 不写 model_id/model_version，Phase 4 消费侧收紧后失败 | 并入 Phase 6 M1 回归收口（[04-011]） | 2026-09-05 (Phase 4) |
| 代码质量 | code-review 6 warning（WR-01 配额守卫恒 False / WR-02 todos 全行口径 / WR-03 error_msg 进候选端 / WR-04 model_json 丢字段 / WR-05 conn 不 close / WR-06 rubric 兜底） | 候选清单随 Phase 6 收口按需处置（[04-016]，见 04-REVIEW.md） | 2026-09-05 (Phase 4) |

## Session Continuity

Last session: 2026-09-05T16:16:59.976Z
Stopped at: Completed 06-05-PLAN.md
Resume file: None
