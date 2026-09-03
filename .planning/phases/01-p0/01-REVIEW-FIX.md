---
phase: 01-p0
fixed_at: 2026-09-03T10:59:18Z
review_path: .planning/phases/01-p0/01-REVIEW.md
iteration: 1
findings_in_scope: 20
fixed: 20
skipped: 0
status: all_fixed
---

# Phase 01 (p0): Code Review Fix Report

**Fixed at:** 2026-09-03T10:59:18Z
**Source review:** .planning/phases/01-p0/01-REVIEW.md
**Iteration:** 1
**Branch:** feature/m5-assessment (fix commits made via temp worktree branch, fast-forwarded)

## Summary

- Findings in scope: 20 (5 Critical + 15 Warning; Info findings excluded by invoking command)
- Fixed: 20
- Skipped: 0

All fixes committed atomically (one commit per finding, 20 commits total: 333e9f9..ce2d6dc).
Validation after every fix: python `ast.parse` syntax check + targeted functional verification
+ full test suites (pytest: test_p0_chain/test_p0_security/test_m5_backend/test_m7_backend;
script: test_m6_backend/test_question_bank) + `vite build` for web changes. All suites green
throughout: 33 pytest passed, 41 + 25 script checks passed, frontend build OK.

## Fixed Issues

### CR-01: 客观题 answer_key 为 NULL 时空正则恒命中（任何回答得 5 分）

**Files modified:** `server/services/scoring.py`, `server/services/question_bank.py`
**Commit:** 333e9f9
**Applied fix:** `_score_objective` 对空/空白 answer_key 直接按最低分（1 分）记，不再落入
`re.search('', ...)` 恒命中路径；`generate_question_bank` 入库前对缺 answer_key 的
objective 题降级为 subjective，从源头阻断脏题入库。验证：空/None/纯空格 key 全部
返回 1 分；既有 'def'/'REPEATABLE'/'docker build' 行为不变。

### CR-02: 题库生成 FAILED 后无重触发入口，岗位被永久锁死

**Files modified:** `server/api/admin/models.py`
**Commit:** a8ff107
**Applied fix:** 新增 `POST /api/admin/question-bank-tasks/{task_id}/retry` 路由：仅
FAILED 行可重试（409/404 语义），新插一行 QUEUED task（保留旧行审计）并后台重跑
`generate_question_bank`（与最新行判定口径 D-12 一致）。验证：FAILED 重试 200、
新行 SUCCEEDED；非 FAILED 409；未知任务 404。

### CR-03: review_position reject 遇子表数据 IntegrityError → 500

**Files modified:** `server/api/admin/positions.py`
**Commit:** ff0b28c
**Applied fix:** reject 前检查 competency_model / question_bank_task /
assessment_session 三张子表占用，命中返回 409 可解释错误（引导改用下架处理），
不再直接 DELETE 撞 FK。验证：三种占用形态均 409；干净 reject 仍正常删除 +
JD 归 NULL。

### CR-04: readiness 配额不考虑模型类目构成，整类目缺失的合法模型被锁死

**Files modified:** `server/services/readiness.py`
**Commit:** 6cf1398
**Applied fix:** 配额按模型实际类目需求计算——`needed_categories` 取自该模型
gate=0 的 competency_item DISTINCT category，模型不含的类目不做配额要求
（与 SSOT §8「某大类无有效能力项→归一」一致）。验证：纯软技能岗、纯硬技能岗
通过；混合岗配额仍强制（hard 1/6 → INCOMPLETE）。

### CR-05: JWT_SECRET 公开默认值 + 缺 sub 的 token 500

**Files modified:** `server/main.py`, `server/core/security.py`
**Commit:** 24bd24e
**Applied fix:** `main.py._startup` 启动期 fail-closed——JWT_SECRET 为空或公开默认值
`change-me-in-.env` 时 raise RuntimeError 拒绝启动；`_current_user` 改用
`payload.get("sub")`，缺失返回 401 而非 KeyError→500。验证：默认密钥启动抛错、
test-secret 启动放行、无 sub token 401。测试文件已显式设 JWT_SECRET=test-secret
不受影响。

### WR-01: assessment 路由族 409 detail 两种形态

**Files modified:** `server/api/assessment.py`, `web/src/utils/sse.js`,
`web/src/views/assessment/Report.vue`, `server/services/readiness.py`（docstring 措辞）
**Commit:** d53f0ae
**Applied fix:** score/report/answer/重复作答四处 409 的 detail 统一为
`{"error_code": ..., "message": ...}`（SESSION_NOT_COMPLETED /
REPORT_ALREADY_EXISTS / SESSION_NOT_IN_PROGRESS / QUESTION_ALREADY_ANSWERED），
与 readiness 三态同构；前端 sse.js 与 Report.vue 的 detail 提取改为
`d?.message || d` 兜底，避免新消费方显示 [object Object]。

### WR-02: submit_answer 校验不 strip，纯空格过检

**Files modified:** `server/api/assessment.py`
**Commit:** ddc7160
**Applied fix:** answer 提取改为 `raw.strip() if isinstance(raw, str) else ""`，
纯空格/非字符串/缺失统一 422；正常回答 strip 后照常接受。

### WR-03: generate_question_bank 幂等粒度太粗，残缺链条永不补齐

**Files modified:** `server/services/question_bank.py`
**Commit:** 9785018
**Applied fix:** 幂等判定下沉到 plan 的 (std_name, category, difficulty) 档位粒度
（difficulty=None 的通用题按 std_name+category）——重触发只补缺失档，不再整
item 跳过。验证：easy 存在/medium+hard 缺失的场景重触发后三档齐全；全档已有
时幂等不变（两次运行题数稳定）。

### WR-04: confirm_model task 行插入在主事务外，失败无补偿

**Files modified:** `server/api/admin/models.py`
**Commit:** 061a457
**Applied fix:** UPDATE confirmed 与 INSERT task 行合并为同一事务（单次 commit），
插行失败时 confirmed 一并回滚，消灭「confirmed 但无 task 行」的中间态。验证：
模拟 INSERT 抛 OperationalError 后模型保持 draft、无 task 行残留；正常路径
两行原子共存。

### WR-05: get_report_by_session 存在性 oracle

**Files modified:** `server/api/assessment.py`
**Commit:** 37198cd
**Applied fix:** 采用评审给的第二个方案——两处 404 统一文案「报告不存在」，
不区分「未生成」与「已生成但属他人」。（第一个方案 join user_id 会破坏
test_p0_security 明确断言的 admin by-session 读豁免，测试翻红后回退改用
文案统一方案，oracle 同样关闭。）

### WR-06: submit_feedback item_id 全表校验可挂无关模型

**Files modified:** `server/api/assessment.py`
**Commit:** aaa0e16
**Applied fix:** item 校验改为 `competency_item ci JOIN assessment_session s ON
s.model_id=ci.model_id JOIN report r ON r.session_id=s.session_id WHERE r.report_id=?
AND ci.item_id=?`——只允许本报告会话锚定模型的能力项。验证：同模型 201、
跨模型 404 且不落库、不存在 404。

### WR-07: update_model 裸 dict 无结构校验 → KeyError/ValueError 500

**Files modified:** `server/api/admin/models.py`
**Commit:** 2ca9877
**Applied fix:** 定义 `ModelItem`/`ModelUpdateBody` Pydantic 模型（std_name
min_length=1、category 枚举 pattern、weight float ge=0、gate int），schema 复用
schemas.py 风格；存库 model_json 用 model_dump 保留前端透传的额外字段。
验证：缺 std_name/非数字 weight/坏 category/非数字 gate/空 items 全部 422；
权重和 400、confirmed 409、404 语义保留。

### WR-08: trigger_aggregate 不检查岗位 status（CR-03 可达路径）

**Files modified:** `server/api/admin/models.py`
**Commit:** 9e3dcfb
**Applied fix:** `pos["status"] != "active"` 时 409「仅上架岗位可触发聚合」，
与自动链（pipeline 只在 active 时聚合）保持一致。验证：pending 409、active 200。

### WR-09: PositionAssess.vue loadModel 无 catch

**Files modified:** `web/src/views/assessment/PositionAssess.vue`
**Commit:** 6999d87
**Applied fix:** loadModel 增加 catch 分支 `ElMessage.error(e.response?.data?.detail
|| '加载岗位模型失败')`，404（无 confirmed 模型）不再空白页 + 未处理 rejection。

### WR-10: get_confirmed_model 不校验岗位 active

**Files modified:** `server/api/assessment.py`
**Commit:** 50080cb
**Applied fix:** 查询 join position 并加 `p.status='active'`，未上架岗位模型
对任意登录用户 404，与列表接口的 active 过滤一致。验证：active 200、
pending_review 404、未知 404。

### WR-11: check_session_readiness 失败分支连接不关闭

**Files modified:** `server/services/readiness.py`
**Commit:** 4d0dd65
**Applied fix:** 主体逻辑抽为 `_check_session_readiness_locked`，外层
`conn = get_conn(); try: ... finally: conn.close()`——所有 return 分支（含失败三态）
都确定性释放连接。验证：用 wrapper conn 观察早退分支与成功分支均调用 close。

### WR-12: _update_task_status 的 finished_at CASE 无 ELSE + 排序无 tie-break

**Files modified:** `server/services/question_bank.py`
**Commit:** 239e723
**Applied fix:** `finished_at=CASE WHEN ? IN ('SUCCEEDED','FAILED') THEN ?
ELSE finished_at END`（非终态更新不再抹时间戳）；取最新行排序补 `, rowid DESC`
作 created_at 并列 tie-break。验证：RUNNING 更新保留 finished_at、终态更新
照常盖章、旧行不动。

### WR-13: eval 占位题污染生产题库

**Files modified:** `eval/virtual_candidates.py`
**Commit:** 42bb54c
**Applied fix:** 造题改写 `status='eval_seed'` 隔离态（question_bank.status 无
CHECK 约束，无需迁移）；工具自身的存量判定与会话选题 WHERE 同步加
`status IN ('active','eval_seed')`。真实候选人选题（question_selection）与
readiness 计数口径均为 status='active'，占位题天然隔离。验证：种子题全部
eval_seed；select_questions_for_session 与 readiness 均不含占位题；
三档跑分与幂等不受影响。

### WR-14: answer_key 直接作正则，ReDoS 与误匹配

**Files modified:** `server/services/scoring.py`
**Commit:** f79cec3
**Applied fix:** 按 key 形态分流——仅含显式正则结构（`|` 分支、字符类、
带量词的分组）的 key 走 `re.search`（非法正则退化子串），其余（含裸量词
如 "C+"、"V*"）一律字面匹配，杜绝 "C+" 这类 key 静默匹配任何含 C 的回答；
key 限长 512、回答截断 64KB 收窄灾难性回溯面。验证："C+" 字面语义、
alternation 正则保留、病态模式 (a+)+$ 对 70KB 回答毫秒级返回；
test_m6（numpy|pandas|NumPy|Pandas alternation key）不回归。

### WR-15: 「最新 confirmed 版」双实现，排序随 version 漂移

**Files modified:** `server/api/assessment.py`
**Commit:** ce2d6dc
**Applied fix:** 新增 `_latest_confirmed_model(conn, position_id)` 共享查询
（相关子查询 MAX(version)），create_session 复用；列表接口改为
`WHERE m.version=(SELECT MAX(version) ...)` + `ORDER BY p.created_at DESC`
（Python 去重与 version 全局排序移除）。验证：两版本岗位只列最新版、
排序按岗位创建时间、_latest_confirmed_model 与预览接口一致取 v2。

## Skipped Issues

None — all 20 in-scope findings were fixed.

## Notes

- WR-05 初版按评审首选方案（join user_id 限权）实现后 test_p0_security 的
  admin by-session 读豁免断言翻红（该豁免是 01-01 交付的明确行为），按评审
  提供的备选方案改为统一 404 文案，oracle 同样关闭且不破坏既有契约。
- 全部 fix 未触碰 .planning/ 与 design/；未经授权未修改 SSOT。
- 前端验证：vite build 通过（worktree 内临时 symlink 主仓 node_modules，
  该 symlink 在 git ignore 范围内且位于 /tmp 临时 worktree，随 worktree 清理）。

---

_Fixed: 2026-09-03T10:59:18Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
