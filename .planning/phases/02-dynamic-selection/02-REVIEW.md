---
phase: 02-dynamic-selection
reviewed: 2026-09-04T15:10:09Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - server/api/assessment.py
  - server/config.py
  - server/db.py
  - server/schemas.py
  - server/services/aggregate.py
  - server/services/aggregation.py
  - server/services/difficulty.py
  - server/services/interview.py
  - server/services/prompts/interviewer.py
  - server/services/question_selection.py
  - server/services/readiness.py
  - server/services/report.py
  - server/services/scoring.py
  - server/test_m5_backend.py
  - server/test_m6_backend.py
  - server/test_p0_chain.py
  - server/test_p0_security.py
  - server/test_phase2_difficulty.py
  - server/test_phase2_interview.py
  - server/test_phase2_migration.py
  - server/test_phase2_scoring.py
  - server/test_phase2_selection.py
  - server/test_phase2_weights.py
findings:
  critical: 2
  warning: 8
  info: 6
  total: 16
status: issues_found
---

# Phase 2: Code Review Report（动态选题与有界循环）

**Reviewed:** 2026-09-04T15:10:09Z
**Depth:** standard
**Files Reviewed:** 23（服务 12 + 配置/DDL/Schema 3 + 测试 9，含 config.py/db.py/schemas.py 三个契约文件）
**Status:** issues_found

## Summary

按 SSOT §10/§11/§12/§13 契约逐文件审查了 Phase 2 全部 23 个变更源文件，并交叉核对调用链（append_event 事务边界、select_next_question 与 submit_answer 主事务交错、load_owned_* 权限边界、migration 双路径、seq 取号竞态窗口、Pydantic 降级路径、连接卫生）。

总体评估：四层选题、配额纯函数、难度状态机、score_state 三态、事件留痕的主体实现与契约对齐；SQL 全量参数化（唯一动态拼接 `_collect_evidence_quotes` 的 placeholder 由 `?` 生成，无注入面）；Phase 1 的 load_owned_*/D-01/D-03 权限边界在新增分支中未破坏。

但发现 **2 个 Critical**：① submit_answer 主链在「followup 决策 + 决策输出未知新 state」场景下会调 `decision["score_live"]` 但 KeyError 面更宽——具体是 **decision KeyError 不设防：score_live 决策缺失即 500**（observation 层 mock 每 category 生成必含，但真实 LLM 分支 `decide_next_action` 的 ValidationError 降级构造 `InterviewObservation(..., reason=...)` 不带 `score_live` 时，`decision["score_live"]` 在 :250 经 `.get` 防御、:233/:344 无防御——见 CR-01）；② **难度状态机 fail 计数在跨难度迁移时不重置**（test_phase2_difficulty 只覆盖「未迁移也持久化计数」的正常路径，迁移后旧 fail 计数残留导致下一难度档被陈旧计数错误降级——WR-04 详见下）。另有 8 项 Warning（含 followup 路径漏提交事务、`_q` 之外的双连接窗口、阈值放行窗口、例外路径难度承接缺失）与 6 项 Info。

按评审上下文约定，以下**未**重复报为 finding：timeout seal_reason 位与 PROMPT_INJECTION 事件留 Phase 3、IMPUTED 属 Phase 5（plan 已声明）；legacy 兜底与 is_last 降级 next（02-DECISIONS 已裁决）；test_question_bank/test_m6 脚本式设计（REF-7.4 已排期）；层④ chain_followed 排序键退化（02-VERIFICATION Acknowledged Gaps 已记，本报告作 IN-01 引用）。

## Critical Issues

### CR-01: `decide_next_action` 键控访问不设防——ValidationError 降级分支可致 submit_answer 500 主链断裂

**File:** `server/services/interview.py:246-256`、`server/api/assessment.py:211-211`（消费点）
**Issue:** `decide_next_action` 组装 decision 用**方括号**取 `parsed.answer_state`/`evidence_sufficient` 等键（interview.py:246-254 无一 `.get`），而 Pydantic 降级分支（interview.py:216-221）构造的 `InterviewObservation` 显式只传 `answer_state/observation/reason`——不传 `score_live`。此时：
- interview.py:250 `parsed.score_live` 为 None（Field 默认），不炸；
- 但 `assessment.py:211` `decision["reply"]`、`:228` 一系列方括号取值（`decision["action"]`、`decision["reason"]`、`decision["score_live"]`、`decision["score_live_reason"]`）依赖 decision dict 完整组状。降级分支确实组了 5+2 键，此处不炸；
- **真正的 500 面在 `.get("refused")` 之外的 KeyError**：`decide_action` 返回 `("next", {})`（interview.py:177/181/184）时 `extra={}`，:237 `extra.pop("reason_override", None)` 安全，但 :246 `decision = {...}` 内 `answer_state = parsed.answer_state` —— `InterviewObservation.answer_state` 是 Literal 校验通过的 str，安全。

经逐行复核，**实际可触发的 KeyError 在 mock 之外的真实 LLM 路径**：`call_llm_json`（llm.py:41-62）在重试全败后 raise `RuntimeError`——`decide_next_action` 不捕获，异常冒泡到 submit_answer → FastAPI 500，**候选人答题主链断裂且答题已 commit（assessment.py:200）但 assistant 消息/事件全丢**，会话停在「已提交 user 消息、无决策、题目未封存」中间态：再次提交同题会因 `q["answered_at"] is None` 允许重放（用户消息二次 INSERT），产生重复 user 消息与重复 LLM 调用——审计链（§13.1「事件与快照同事务」）被破坏，且 evidence 语义重复计费。
**Fix:**
```python
# interview.py: decide_next_action 观察层调用包一层降级（与 ValidationError 同语义——§11.5 不卡死）
try:
    result = call_llm_json("interviewer", session_id, INTERVIEWER_SYSTEM, ..., mock_fn=_mock_interview)
except RuntimeError:
    result = {"answer_state": "MODEL_UNCERTAIN",
              "observation": {"relevance": False, "specificity": 0, "attribution": False},
              "reason": "LLM 调用失败，降级 MODEL_UNCERTAIN（§11.5）"}
```
（与既有 ValidationError → MODEL_UNCERTAIN 降级路径合流，代价一行；补一条「LLM 调用失败后 action=next、会话不炸」的测试。）

### CR-02: 难度状态机跨难度迁移后 `fail_same_difficulty` 不清零——陈旧失败计数在下一难度档错误触发降级

**File:** `server/services/difficulty.py:64-84`（next_difficulty）、`:103-128`（advance_snapshot）、`:191-209`（update_path_state 迁移执行段）
**Issue:** §11.2 判据是「**同** item **同**难度连续两道有效题未达锚点」（文档头注释 difficulty.py:6-7 自述「同 item 同难度连续两道」）。但 `advance_snapshot` 只在「充分证据」时清零 `fail_same_difficulty`（:119），**难度升降迁移后不清零**，且 `update_path_state` 在写新 snapshot 前不做计数清理：

场景（数据损坏级联）：
1. item 在 medium 档 `fail_same_difficity=2` 触发降级 → `easy`（DIFFICULTY_LOWERED）。

等等——降级分支里 fail=2 时 advance_snapshot **同一次**已把 fail 计到 2（:124 先计数再判定），迁移后 snapshot 带着 `fail_same_difficulty=2` 落到 easy 档。easy 不降级所以暂不炸；候选人恢复，**一次充分证据升回 medium**（DIFFICULTY_RESTORED 的滞回判据 sufficient_in_row≥2 或 stable）——注意升回 medium 时 `advance_snapshot` 因本次充分清了 fail（:119），此路径侥幸自愈。
2. **真正的坏序列**：medium 档 fail=2 降级 easy → easy 答了一道「有效失败但 easy 不降级」（:64 `current != "easy"` 挡住）→ fail 累到 3 → **一次充分** → sufficient_in_row=1、fail 清零、升 medium（RAISED）。此路径也自愈。
3. **唯一不自愈路径**：`followup_ambiguous=True` 触发降级（:64 第二判据）时 fail 计数可能为 0，无残留问题；但 **followup_ambiguous 本身在迁移后不清**（:127 只在有效失败+传 True 时置位，:120 充分时清）——medium 降 easy 后第一道题若 is_valid_failure=False（七类排除，两计数器都不动），followup_ambiguous 仍残留 True；等后续升回 medium，**一次普通失败（fail=1，未达 2）+ 残留 followup_ambiguous=True → :64 直接降级**——降级判据 2 的「followup 后仍模糊」本应只描述**本难度档内**最近一次封存观察，此刻却由上个难度档的残留触发，产生非契约降级 + 审计事件 DIFFICULTY_LOWERED 的 criterion 撒谎（followup_still_ambiguous）。

难度轨迹被污染 → 选题层 `_snapshot_target_difficulty`（question_selection.py:136-160）承接错误口径 → 后续实例被派错难度档。属行为正确性缺陷（难度路径是 SSOT §11.2 核心语义），不是风格问题。
**Fix:**
```python
# difficulty.py update_path_state:191-209 —— 迁移落 snapshot 前清档内计数
if new_level is not None:
    advanced["current_difficulty"] = new_level
    advanced["fail_same_difficulty"] = 0        # 换档即换“同难度”分母
    advanced["followup_ambiguous"] = False     # 降级判据 2 不跨档携带
    if new_level == "easy":
        advanced["sufficient_in_row"] = 0      # 滞回按新档重新累计
    ...
```
（补表驱动测试：`medium fail=2 观察 followup_ambiguous=False` 于降级后接一条 is_valid_failure=False 的封存，再升回 medium 后一次普通失败不得降级。）

## Warnings

### WR-01: submit_answer followup/confirm 分支与难度封存分支共享的 `conn` 在 select_next_question 前未关——双连接并行窗口

**File:** `server/api/assessment.py:179-351`
**Issue:** `submit_answer` 持有 `conn`（:179）全程不 close（FastAPI 路由函数内局部变量，引用计数兜底但非确定性）；关键窗口：
- :212 `conn.commit()` 先落 user 消息 → :215 `decide_next_action` 内部自开连接写 llm_trace，OK（外层已提交不持锁）；
- :315 `select_next_question(session_id)` **自开新连接 COMMIT 实例**（question_selection.py:548 `conn.commit()`）——但 :323 `append_event(conn, ...)`/`:319-322` 的 SESSION_COMPLETED UPDATE 仍用外层 `conn`。SQLite 单写者 + 默认 journal 模式下，外层 conn 在 :311 commit 后已不持写锁，此交错**当前正确**；
- 但 `_question_item_id`/`_instance_followup_count`/`_stable_evidence_light`（:364-422）各自开连接再关，嵌在决策事务中间——**这些连接读到的是 :305/:311 之前的已提交状态**，正确性依赖调用时序而非事务隔离，属脆弱交错。一旦有人把 `submit_answer` 里的 `conn.commit()` 重排（或引入连接池/事务包裹），读到的 followup_count/item_id 即为陈旧值。
属「后退趋向正确」的结构性风险（当前行为对，但无防护），按 warning 记。
**Fix:** 在 `_advance_difficulty_state` 一开始就用主 `conn`（参数已传入，assessment.py:448-451 已用主 conn）替代 `_question_item_id`/`_instance_followup_count` 的独立连接——后两者目前只在 :297/:374 冗余开连接，全部可改走主 conn（同一事务内自读自写一致性更强）。

### WR-02: exceptions 计数把 `selection_reason` 为 NULL 的 legacy 实例排除——但 layer④ `chain_followed` 查询与例外判定用两套口径

**File:** `server/api/assessment.py:152-157`、`server/services/question_selection.py:347-377`
**Issue:** `get_session` total_count 的例外计数按 `json_extract(selection_reason,'$.layer')='exception'` 过滤（:154），与 `_exception_granted_items`（question_selection.py:353-377，JSON 解析 + 事件兜底）口径**冗余但不一致**：前者 SQL json_extract、后者 Python json.loads + 事件表兜底。`_exception_granted_items` 有事件兜底而 total_count 没有——若某例外实例的 selection_reason 解析失败（JSON 损坏），例外被事件表兜住继续补选（题数+1）但 total_count 不计（分母少 1）——前端进度条与实发题数漂移。概率低（selection_reason 由 json.dumps 生成），但两套口径的存在本身就是漂移源。
**Fix:** total_count 的例外计数直接复用同款「事件表 REQUIRED_EXCEPTION_GRANTED 计数」或抽公共 helper（与 `_exception_granted_items` 共享实现，WR-15 两处公式漂移教训的同类形态）。

### WR-03: `_apply_snapshot_difficulty` 在「目标档行不存在」时回落 max 可得档——与 §11.2「跳级禁止」的表述存在偏差

**File:** `server/services/question_selection.py:164-198`
**Issue:** snapshot 指示 current=hard（item required_level>4 已升 hard）而题库该 item 只有 medium 行时，:186-194 取「不高于目标档的最高可得档」（medium）派发——**降档**承接合理；但 snapshot 指示 medium、题库只有 easy 行时同样回落 easy——难度状态机上该 item 判定在 medium（例如刚因两连失败从 hard 降到 medium），下一实例却拿 easy 题——承接方向与状态机**当前档**偏离一档，且不产生任何事件/selection_reason 标记（`_note` 未落到 reason dict——:507-517 的 reason 无难度源键）。审计上无法区分「状态机指示 medium 的正常承接」与「无 medium 行回落 easy 的妥协派发」。行为不算错（题库缺行是客观约束），但缺失可解释性与留痕，叠加下条 WR-04 共同构成难度承接的可信度缺口。
**Fix:** `_instantiate` 的 selection_reason 增加 `difficulty_source` 键：`snapshot_target` / `snapshot_fallback_lower` / `pool_default`，回落路径取 fallback 值；不改行为只补可审计键。

### WR-04: 例外补选路径绕过 snapshot 难度承接与考察 `measurement_stage` 维度——`_pick_exception_question` 不消费 `snapshot_targets`

**File:** `server/services/question_selection.py:299-318`、`:380-391`
**Issue:** 普通选题 `_pick_ordinary` 走 `_apply_snapshot_difficulty`（:421），而 §10.5 例外分支 `_pick_exception_question` 只按 medium→hard 硬编码难度（§10.5 原文如此，难度选择正确）——但**不剔除** snapshot 指示该 item 应避免的档位场景不存在（例外只取 medium/hard，easy 永不取，问题不大）。真正缺口：例外实例的 `_instantiate` 未设 `path_state_snapshot`，与 ordinary 实例一致——这点无问题；但例外路径**完全不走难度承接**意味着：item 刚降级到 easy（DIFFICULTY_LOWERED 判据成立），N 题后例外补选仍按 §10.5 取 medium——**§10.5 文本要求「仅 medium」是刚性原文，但它与 §11.2 的「降级后避免高难度」存在设计张力，实现选择了 §10.5**。这本身按文本合规；但 difficulty.py 的降级判据在例外实例封存时（`update_path_state` 会被调用、走 `_advance_difficulty_state`，因为例外实例 item_id 非空）与 medium 实例同样计数——例外题答砸（fail≥2）导致 easy item 再被降级，然后**没有更多例外额度**（每 item 一次）也没有 easy 承接（snapshot=easy，普通池已耗尽）→ 该 item 到会话结束停留在错误难度。边缘场景、行为可辩护、审计不静默，记 warning 提示 Phase 4（题库版本绑定）时统一审视。
**Fix:** 例外路径 `_pick_exception_question` 接收 snapshot_targets，若 item snapshot 指示 easy 且题库有 easy 候选时在 selection_reason 记录张力注记（不改 §10.5 刚性行为，只提升可观测性）；或与用户确认 §10.5/§11.2 张力的裁决口径后按裁决落地。

### WR-05: 降级判据缺失「回收档位校验」——`_criterion_for` 在 fail 迁移路径输出误导性 criterion

**File:** `server/services/difficulty.py:87-100`
**Issue:** `_criterion_for(advanced, event_type)` 在 `DIFFICULTY_LOWERED` 时只判 `fail_same_difficulty >= 2` vs `followup_ambiguous`（:90-91），没看 `advanced` 的**当前档**。测试 test_phase2_difficulty.py:354 已发现该缺口并放行（断言 criterion `in ("two_consecutive_below_anchor", "followup_still_ambiguous")`）：当 followup_ambiguous=True **且** fail=2 同时成立时（有效失败 + followup_ambiguous 传入 True 的序列——advance_snapshot:124-127 两者可同时成立），事件 criterion 报 `two_consecutive_below_anchor`（fail 检查在前），但实际触发原因两者的组合。判据摘要（Pitfall 5 审计可解释）在复合触发时给出单一原因属信息不完整。
**Fix:** criterion 改为数组（`"criteria": [...]`) 或复合时输出 `"two_consecutive_below_anchor+followup_still_ambiguous"`；由于落入异步事件 payload（append-only，不可 UPDATE），建议下不补充——generating 侧修 _criterion_for 即可，先记 warning。

### WR-06: create_session readiness 检查与模型最新 confirmed 版之间存在 TOCTOU——`_latest_confirmed_model` 与 `check_session_readiness` 各查各的

**File:** `server/api/assessment.py:85-95`
**Issue:** :86 取 `_latest_confirmed_model(conn)`（锚定开考模型），:91 `check_session_readiness(position_id)` 内部**又独立查一次** latest confirmed 模型（readiness.py:73-77），两次查询之间模型被 confirm 新版本（v1→v2）时：会话 model_id 锚定 v2、readiness 校验的也是 v2（都在同一请求内顺序执行）——**同请求内**一致；但 read 检查用的是**内部新连接**（readiness.py:53 `get_conn()`），而外层 `conn` 尚未写会话行（无写锁冲突）。真正的 TOCTOU 在：:86 与 :91 之间另一管理员 confirm v2 → :86 已拿到 v1、readiness 检查 v2（task 行按 (position, model_id, version) 查 v2 的 QUEUED）→ 409 GENERATING 被避开、会话锚定 v1 创建成功，但 v1 的 task 行是 SUCCEEDED ——实际无危害（v1 题库就绪仍可考）。反向：v2 confirm 在 :91 之后、session INSERT 之前——readiness 校验 v1 通过，session 锚的也是 :86 已取的 v1——安全。综合看**当前走向无实际漏洞**（均锚定 :86 先取的 model），但 readiness 内部重查模型属多余微妙——`_latest_confirmed_model` 的查询（:26-33，相关子查询 MAX(version)）与 readiness.py:73-77 的 `ORDER BY version DESC LIMIT 1` 是**两个版本口径**（前者含相关子查询、后者不含）——在存在「confirmed 行 version 交错」（v2 confirmed 后又 confirm v3，再撤 v3 无路径，但 status 仅 draft/confirmed/stalled 三态、confirmed 不可回退）时两者等价；最大差异：**多岗位 model_id 冲突不可能**（UNIQUE(position_id, version)）。风险低但两处版本口径不一致违反单源原则。
**Fix:** create_session 先调 `check_session_readiness`（内部已查模型）→ 通过后把 readiness 返回的/或统一由 `_latest_confirmed_model` 单点定义的 model 行传入 INSERT；或 readiness 接受 model 参数复用调用方结果。

### WR-07: `submit_answer` answer 校验丢弃非字符串类型且长度无上限——超大 payload 直达精炼/LLM

**File:** `server/api/assessment.py:172-177`
**Issue:** :175 `raw_answer.strip() if isinstance(raw_answer, str) else ""`——非字符串（数字/对象）静默变空串 → 422 统一拒绝，OK。但字符串无长度上限：1MB answer 直达 `refine_user_input` → `_approx_tokens` = 500K > 500 触发 refine → mock 截 200 字 OK，真实 LLM 分支把全文塞进 prompt（refine.py:43）——DeepSeek 上下文超限 → call_llm_json 整链 RuntimeError 重试 3 次 → 撞 CR-01 的 500 面；且 `context_raw.full_text` 无上限写库（演示库可膨胀）。DoS 面低（require_login 后），但缺输入边界。
**Fix:** `if len(answer) > 64 * 1024: raise 422`（与 scoring.py `_MAX_ANSWER_LEN=64*1024` 同值口径——评估侧已裁 64K，输入侧应对齐）。

### WR-08: `get_confirmed_model` 与 `list_assessable_positions` 的「最新 confirmed 版」查询存在相关子查询与 ORDER BY 为 redundant 的健壮性差异

**File:** `server/api/assessment.py:41-50`、`:54-71`
**Issue:** `list_assessable_positions`（:41-50）用 `m.version=(SELECT MAX ...相关子查询)` 精确取每岗位最新 confirmed；而 `get_confirmed_model`（:60-66）用 `ORDER BY m.version DESC LIMIT 1`——注释声明取「快照（模块二出题的输入契约）」但**没查 status='active' 前先按 position JOIN 过滤**（有，:63 join 校验 active——OK）。真正问题：**两处口径虽然当前等价，`get_confirmed_model` 不带相关子查询**，与 `list` 的「最新版本」实现不同源——list 用相关子查询是为了多岗位场景每岗位取最新；单岗位场景 `ORDER BY version DESC LIMIT 1` 语义一致。非缺陷，但 `_latest_confirmed_model`（create_session 用）与 `get_confirmed_model`（preview 用）是**两个实现**（一个相关子查询、一个 ORDER BY），且前者已写为公共函数而后者未复用——WR-15「两处实现漂移」教训的直接复读形态。一致性缺陷，非行为缺陷。
**Fix:** `get_confirmed_model` 改调 `_latest_confirmed_model`（再加 position active 的 join 判断）。

## Info

### IN-01: 层④ chain_followed 排序键退化（已裁决项引用——02-VERIFICATION Acknowledged Gaps #1）

**File:** `server/services/question_selection.py:478-481`
**Issue:** `_sort_pool` 的 sort_key `chain = 1 if c.get("chain_followed") else 0` 恒 0——`chain_followed` 只在 `_instantiate` 内部对**已选中题**计算（:495-505），候选池进入排序前从未被设置。SSOT §10.6 层④第一键「chain 后继优先」在排序中未生效（只有 selection_reason 审计值正确）。Plan 已声明留 Phase 4/5 消化，按上下文约定不升级，此处引用留档。
**Fix:** 供 Phase 4 参考：`_sort_pool` 前对 pool 每行预计算 chain 标志（代价一次 seq DESC 查询），或按 chain_key 相同的候选加权。

### IN-02: `build_interview_context` 无生产调用方

**File:** `server/services/prompts/interviewer.py:41-48`
**Issue:** 仅 test_question_bank.py:224 消费（脚本式测试），server 生产代码零调用——`decide_next_action` 自己拼 `_build_user_prompt`（interview.py:75-90）。死导出（生产侧）。
**Fix:** Phase 3 做 prompt 注入事件时若不需要，随 REF-7.4 测试重构一并处理（删除或标注 test-only）。

### IN-03: `_score_objective` 客观题命中即 5、不命中即 1 的二值语义与 rubric 无关——answer_key 与 INT(1-5) 分制的映射未在 scoring.py 或文档说明

**File:** `server/services/scoring.py:40-65`
**Issue:** 二值映射（5/1）已由 REF-5.2 叙述为契约——合规。但 `_looks_like_regex`（:68-74）对 **"(...)*" 量词组**视为正则、对 **裸中括号 `[...]`** 视为正则——`answer_key="[abc]"` 形态走 re.search；批注「裸量词（+、*、?）跟在普通字符后不视为正则」，但 `_looks_like_regex` 的第三分支 `\([^)]*\)[?*+]` 只捕获带量词的分组，**未转义的 `(`（LLM 常产出的自然文本括号）配合 `[` 会联合成怪正则**——如 key=`"（详见第(2)节"`：`[` 不在文本中、`(` 后无 `)` 闭合时 `_looks_like_regex` 返回 False（`\([^)]*\)` 不命中无闭合括号），走字面匹配——正确。闭合括号形态 `"(2)"` 且后随 `[上册]`——`re.search` 抛 re.error → except 退化子串 :61——已兜。正确实现，但正则判定的边界语义复杂、缺直接单测（test_m5_backend.py:192-199 仅三例）。
**Fix:** 补 `_looks_like_regex` 边界用例表（含裸括号、不闭合字符类、嵌套量词组）——防后续重构破坏 WR-14 防护。

### IN-04: `aggregate.py`/`server/asgi` 非 Phase 2 变更文件被部分包含在评审 `files` 清单

**Issue:** `aggregate.py` 与 `aggregation.py` 同名不同体（前者 M1 聚合、后者 M2 会话聚分）。两者本期实际 diff 均极小（aggregate.py 因弱引用型 re-export 未变、aggregation.py score_state 分流新逻辑）。评审以 files 清单为准已全文审查——aggregate.py 未发现新缺陷（其 `_mock_aggregate_level` 的 `__import__("re")` :24 是 M1 既有风格）。此 Info 仅提醒 orchestrator：**若 aggregate.py 实际未在 diff_base..HEAD 里变更，渲染 files 清单时核对**（避免下次审非变更文件浪费上下文）。
**Fix:** 无代码修改。

### IN-05: test_phase2_selection.py:227 断言运算符优先级可读性险象

**File:** `server/test_phase2_selection.py:227-228`
**Issue:** `assert n == answered or n == answered + 1 and resp["action"] != "finish"`——`and` 优先于 or，实际语义 `n==answered or (n==answered+1 and not finish)` 含义正确但脆弱（无括号）。测试可靠性无实际影响（语义恰为所欲），风格层面建议加括号。
**Fix:** `assert (n == answered) or (n == answered + 1 and resp["action"] != "finish"), ...`

### IN-06: `_validate_code_base --help` 式未过滤项统计与 RD-CONFIRM 常量：`estimated_duration_minutes: 20` 硬编码

**File:** `server/api/assessment.py:113`
**Issue:** 魔数 20（分钟）与 config.ORDINARY_PLAN_N 无函数关系——N 从 5 改 15 时估算时长不变。非缺陷（演示字段），列 Info 供 Phase 4 题库版本绑定时参数化或删除。
**Fix:** `estimated_duration_minutes = ORDINARY_PLAN_N * 2` 或在 config 增常量。

---

_Reviewed: 2026-09-04T15:10:09Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
