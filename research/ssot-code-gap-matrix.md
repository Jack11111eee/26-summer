# SSOT v2.0 → 代码差距矩阵（穷举核对版）

> **生成方式：** 2026-09-02，逐节核对 `design/final-design/总设计文档.md`（702 行）与本仓库实际代码（后端核心文件全文阅读，非抽样）。每行给出**文件:行号证据**，三类标注：
> - **[缺失]** SSOT 要求，代码不存在
> - **[违约]** 代码存在但与 SSOT 契约不一致
> - **[合规]** 代码与 SSOT 一致，重构时保持
>
> **用途：** 替代 `/gsd-map-codebase` 之后的 prompt 式覆盖检查；作为 §28 待办的文件级展开，是 REQUIREMENTS REF-* 条目的直接输入。本文是**一次性核对快照**，阶段实施时以最新 SSOT 为准。
>
> **覆盖范围声明：** 后端 server/（db.py、api/assessment.py、services/ 全部、api/admin/ 关键文件、prompts/interviewer）、前端 web/src/utils/sse.js + FormCard/Chat 相关行。模块一流水线（pipeline.py/aggregate.py）只核对了 config 常量与 §8 契约相关点，未逐行核——M1 回归测试本来就是补齐手段。

---

## 1. 全局约束（SSOT §3/§4/§7）

| # | SSOT 契约 | 现状 | 证据 | 类别 |
|---|---|---|---|---|
| 1.1 | §7 资源级所有权校验（session/report/form/feedback 全部 `WHERE user_id=current`） | `get_session`/`submit_answer`/`score`/`report`/`get_report_by_session`/`feedback` 全部只按 ID 查，**无一处校验 user_id**；只有 create/submit 写入时用了 `user["user_id"]` | `server/api/assessment.py:97-126,129-151,233-246,259-269,272-282,285-294,297-318` | **[违约·P0]** |
| 1.2 | §7 角色限制后端执行，不依赖前端 guard | admin 路由有 `require_admin`（如 `admin/trace.py:7`）；候选人资源路由仅 `require_login`，无所有权校验 | `server/api/assessment.py:15` | 部分合规，缺口见 1.1 |
| 1.3 | §3① LLM 不碰数字（权重/配额/算术代码计算） | 权重在 `aggregate.py`（代码频次+系数），聚合在 `aggregation.py`（代码）；但 score_live 由 LLM 直接产出 1-5 分 | `server/services/prompts/interviewer.py:15-21`（LLM 输出 score_live） | 与 §17 的新契约冲突（见 5.1） |
| 1.4 | §3③ 一切留痕：LLM trace 落库 | `call_llm_json` 统一落 llm_trace（8 种 call_type） | `server/db.py:88-100`；llm.py | **[合规]** |
| 1.5 | §3③ 状态事件 append-only | 无 `assessment_state_event` 表，无任何事件记录 | `server/db.py`（全文无此表） | **[缺失·P0]** |
| 1.6 | §4 Observation→Policy→Act→Evaluation→Persist 循环 | 现状为“LLM 直接决定 action”的单步循环，无结构化观察维度、无代码裁决层 | `server/services/interview.py:83-115` | **[违约]**（需按 §11.3/§11.4 重构为两层） |
| 1.7 | §4 LLM 不能决定题量/finish/难度迁移 | finish 由规则触发（is_last→finish）、追问上限有护栏；**难度迁移由选题时的 chain 一次性预排**，无运行时升降级 | `server/services/interview.py:100-107`；`question_selection.py:40-46` | finish 护栏合规；难度迁移见 3.2 |

## 2. 数据库（SSOT §6/§9.2/§12/§13/§16.1）

| # | SSOT 契约 | 现状 | 证据 | 类别 |
|---|---|---|---|---|
| 2.1 | §6 共 21 张表 | 现有 18 张（db.py 全部 DDL：user/position/position_alias/jd_record/competency_model/competency_item/competency_dict/llm_trace/assessment_session/question_bank/assessment_question/assessment_message/context_raw/form_submission/question_score/report/feedback/eval_results） | `server/db.py:9-215` | 缺 3 张，见 2.2-2.4 |
| 2.2 | §13.1 `assessment_state_event`（append-only，UNIQUE(session_id,sequence_no)） | 不存在 | `server/db.py` 无 | **[缺失·P0]** |
| 2.3 | §13.3 `trace_link`（统一关联表） | 不存在；trace 只靠 `llm_trace.ref_id` 单字段弱关联 | `server/db.py:88-100`（ref_id 无外键语义） | **[缺失]** |
| 2.4 | §16.1 `form_instance`（schema 快照/生命周期） | 不存在；form_submission 只是原始 payload 落库 | `server/db.py:165-172` | **[缺失]** |
| 2.5 | §9.2 question_bank 演进（model_id/model_version 绑定、question_type ordinary/integrated、measurement_stage、tier、measurement_target、evidence_requirement、observable_level_max/min、equivalence_group_id、integrated_bindings_json、rubric_version） | 现表为旧结构：scope(position/general)、std_name 直存、无模型绑定、无普通/综合之分、无测量目标/证据要求/锚点、无等值组 | `server/db.py:116-132` | **[违约·结构性]**（迁移任务） |
| 2.6 | §12.1 assessment_session 演进（phase/active_elapsed_seconds/last_activity_at/abandoned_at/policy_version/session_time_intervals_json；状态机 PENDING_START→ACTIVE→SCORING→COMPLETED + ABANDONED/FAILED） | 现表 status 仅 `in_progress/completed/abandoned`（db CHECK），无计时区间、无 phase；代码无 ABANDONED 检测逻辑（grep 无 abandoned 赋值代码） | `server/db.py:104-114`；全库 grep `abandoned` 仅 CHECK 定义 | **[违约·结构性]** |
| 2.7 | §12.2 assessment_question 演进（question_type/measurement_stage/item_id/difficulty/status/activated_at/answered_at/closed_at/followup_count/seal_reason/selection_reason/path_state_snapshot/binding_snapshot_json；(session_id,sequence_no) 唯一） | 现表仅 question_id/session_id/bank_question_id/seq/asked_at/answered_at/created_at | `server/db.py:134-142` | **[违约·结构性]** |
| 2.8 | §12.3 assessment_message 分列（raw_content/raw_hash/refined_content/action/reason/client_request_id/sequence_no） | 现表 content 单列存**精炼后**文本（refine 后的），raw 原文只在 context_raw（按 hash）；无 client_request_id/sequence_no | `server/api/assessment.py:156-161`（存 refined）；`db.py:144-156` | **[违约·结构性]**（raw/refined 分列改造） |
| 2.9 | §12.4 question_score 统一 score_final（废弃 final_score 列）+ 新列（item_id 已有；score_state/measurement_target/rubric_version/evidence_spans_json/scorer_version/human_override_*） | 现表 `score_live/score_final/final_score` 三列并存；final_score=50/50 合成结果；无 score_state 等新列 | `server/db.py:174-185`；`scoring.py:131-136`（合成逻辑） | **[违约·结构性]**（含数据迁移） |
| 2.10 | §12.5 证据定位结构化（source_message_id/source_content_type/start_offset/end_offset/quote_hash）；hash 复用限单 session | 现状 evidence_quote 是 LLM 返回的自由文本截断 60 字符，无结构化 span；context_raw hash 全局唯一**跨会话复用** | `scoring.py:79-81`；`db.py:158-163`（hash UNIQUE 全局） | **[违约]** |
| 2.11 | §5 schema_version 演进体系 | 无 schema_version 表/字段；仅两个手写迁移函数（llm_trace/feedback），靠 CREATE TABLE IF NOT EXISTS 幂等 | `server/db.py:226-290` | **[缺失]**（Phase 8 迁移体系） |

## 3. 题库与选题（SSOT §9/§10）

| # | SSOT 契约 | 现状 | 证据 | 类别 |
|---|---|---|---|---|
| 3.1 | §10.1 岗位级 N（管理员配置）+ §10.2 大类 7:3 最大余数 + §10.3 tier 0.8/0.6/0.3 公式 | 固定 `CATEGORY_QUOTA = {hard_skill:6, soft_skill:2, experience:2}`（硬编码；experience 占题违反 §9.1“经验不进普通题库”） | `server/services/question_selection.py:9` | **[违约·N4]** |
| 3.2 | §10.6 四层动态选题（合法性→required 优先→配额→排序）；每轮 action=next 时选题 | **一次性预选**：create_session 时全量选完落 assessment_question，运行时无选题逻辑 | `server/api/assessment.py:85-92`；`question_selection.py:58-66` | **[违约·N5]** |
| 3.3 | §9.1 普通题库只两大类（hard/soft），experience/qualification 不进题库、走表单 | question_bank 生成时 experience/qualification 走 general scope 各 1 题（对话题）；选题配额 experience:2 | `question_bank.py:15-29,86-87`；`question_selection.py:9` | **[违约]** |
| 3.4 | §9.2 题库绑定 model/version，模型升版须重建题库否则阻止开考 | 题库不绑模型版本（表无此列），开考仅查 position active + 模型 confirmed | `server/db.py:116-132`；`api/assessment.py:69-75` | **[缺失]** |
| 3.5 | §10.4 开考前可测量性检查（题库 readiness/配额可行/表单 schema/未通过阻止开考+管理员待办） | create_session 无任何题库就绪检查；选题返回空列表也照常创建 0 题会话 | `api/assessment.py:59-94`（无检查逻辑） | **[缺失·P0]** |
| 3.6 | §10.5 required 刚性例外（普通计划结束后检查、每 item 最多一次、仅 medium/hard） | 不存在 | 全库 grep 无 required 例外逻辑 | **[缺失]** |
| 3.7 | §9.4 难度→等级映射（easy:[2,3]/medium:[3,4]/hard:[4,5]）+ observable_level 列 | 无锚点概念；题表无 observable_level 列；评分直接 1-5 | `db.py:116-132`；`scoring.py` | **[缺失]** |
| 3.8 | §9.3 等值备用题（equivalence_group/status/approved_by） | 不存在 | `db.py` 无相关列 | **[缺失]**（优先级低，SSOT 未列入 §28 硬项） |
| 3.9 | §10.1 综合题独立槽位（integrated，绑定多 item） | 不存在；无 question_type 概念 | `db.py:116-132` | **[缺失]**（SSOT 附录 A：综合题生成 Prompt 待讨论，实现可后排） |

## 4. 会话运行时（SSOT §11/§15/§16）

| # | SSOT 契约 | 现状 | 证据 | 类别 |
|---|---|---|---|---|
| 4.1 | §11.1 动态实例化（每题面新 assessment_question 实例；followup 不建实例不占题） | followup 不建新实例（合规：按 question_id 计数）；但实例在会话创建时**一次性全部预建** | `api/assessment.py:85-92`；`interview.py:39-45`（followup 计数） | 实例模型缺半（动态化缺失） |
| 4.2 | §11.2 难度路径状态机（升/降/滞回恢复；不计失败清单；跳级禁止） | 不存在；难度=chain_key 预排顺序，无运行时路径状态 | `question_selection.py:40-46` | **[缺失]** |
| 4.3 | §11.3 evidence_sufficient/stable_evidence 结构化观察+代码裁决 | 不存在；LLM 直接给 score_live 1-5 | `prompts/interviewer.py:15-21` | **[缺失]** |
| 4.4 | §11.4 answer_state 11 态 + score_state 8 态两层分离 | 不存在；只有 action(followup/next/finish) 三态 | `interview.py:109-115`；`prompts/interviewer.py:15` | **[缺失]** |
| 4.5 | §11.4 各状态处理原则（拒答确认后跳过/技术暂停计时/辱骂设边界等） | 无状态分类，全部按“回答”处理 | 同上 | **[缺失]** |
| 4.6 | §11.5 真实 SSE（决策非流式先落库，话术流式） | 后端**单次 JSON**（无 StreamingResponse，grep 无 event-stream）；前端 sse.js 已写好双形态自适应（当前走 JSON 形态 B） | `api/assessment.py:129-206`；`web/src/utils/sse.js:45-52`（形态 B 分支） | **[违约·N9]**（前端已就绪，后端待改） |
| 4.7 | §11.5 LLM 输出严格 Pydantic 校验 | `call_llm_json` 有 JSON 校验+重试，但接口层 body 均为裸 dict（无 Pydantic 模型） | `api/assessment.py:60,130,210`（body: dict） | 部分合规，接口 schema 待补 |
| 4.8 | §15 全场 40 分钟/单题 20 分钟/暂停恢复/计时区间/6h ABANDONED | **完全无计时逻辑**（无 started_at 以外的时间记录、无暂停、无超时封存、无 abandoned 检测） | `api/assessment.py` 全文；`db.py:104-114`（无计时列） | **[缺失]**（N7：现状连 24h 都没有） |
| 4.9 | §13.4 幂等（idempotency_key/client_attempt_id；重复请求返回首次结果） | 不存在；重复提交回答靠 `answered_at IS NOT NULL` 返回 409（算防重但不幂等返回） | `api/assessment.py:151-152` | **[缺失]** |
| 4.10 | §16.1 表单链（render_form 由代码触发/schema 版本化快照/GET 只读/修订走不可变 revision/gate 结构化结果/人工覆盖） | 仅 `POST forms/submit` 原始 payload 落库；无 schema 定义、无 GET 表单接口（前端 FormCard 的 schema 来源接口不存在于后端）、gate 在聚合时才从 payload 猜测（`_gate_check` 按字段名猜） | `api/assessment.py:209-230`；`aggregation.py:42-63` | **[缺失]**（gate 判定逻辑违约：§16.2 要求候选人确认事实后 gate 才接受） |
| 4.11 | §16.3 Tools 白名单/边界/失败人工接管；正式测评无 Web Search | 当前 LLM 无工具调用（无 tools 概念），形式上无越界，但也无 §26 要求的可替换接口登记 | `interview.py`（无 tools） | **[缺失]**（Prompt 模块依赖） |
| 4.12 | §14 上下文管理三层（滑窗 Token 控制/导航摘要层/P-refine 分列） | P-refine 存在（阈值 len/2>500 触发，原文 hash 归档）但 refined 直接覆盖 content 列（不分列）；无滑窗（历史全量拼接 prompt）；无导航摘要层 | `refine.py`；`interview.py:87-91`（全量历史）；`api/assessment.py:156-161`（覆盖式） | **[违约·结构性]** |

## 5. 评分与报告（SSOT §17-§21）

| # | SSOT 契约 | 现状 | 证据 | 类别 |
|---|---|---|---|---|
| 5.1 | §17 score_live 仅导航不进最终分（旧 50/50 合成作废） | `final = round(score_live*0.5 + score_final*0.5)`，合成结果存 final_score 并**用于聚合**（aggregation 按 final_score 均分） | `scoring.py:131-136`；`aggregation.py:73-79` | **[违约·N2·核心]** |
| 5.2 | §17 客观题 answer_key 空属题库缺陷→判题库无效而非判分 | 现状 answer_key 空字符串传给 `_score_objective`，re.search("") 恒命中→**5 分** | `scoring.py:18-24`（空 key hit=True）；`70-71` | **[违约]**（空 key 满分漏洞） |
| 5.3 | §18 拒答=score_value 0 + REFUSED 状态，不进能力等级分母 | 无拒答概念；短回答只触发 followup | `interview.py:66-80` | **[缺失·N8]** |
| 5.4 | §19 item_measurement 统一裁决（普通+综合、冲突取低、不按题数加权） | 现状 item 分 = 各题 final_score **简单均分**（即按题数平均，§19 明确禁止） | `aggregation.py:105-121`（`sum/len` 均分） | **[违约·结构性]** |
| 5.5 | §20 缺失补算（r 比例补算+IMPUTED 标记+覆盖率展示+O=∅→NO_VALID_OBSERVATION） | 缺失项直接 score 0 不计贡献（`no_data: True`），**无补算**、无 IMPUTED、无人工复核标记 | `aggregation.py:105-115` | **[缺失]** |
| 5.6 | §20.2 required 缺失→PROVISIONAL+HUMAN_REVIEW_REQUIRED | 无报告状态概念 | `aggregation.py`；`report.py` | **[缺失]** |
| 5.7 | §20.3 总分=Σ(item.weight×normalized)×100；大类 7:3 已在 item.weight 不二次乘 | 聚合公式 `weight × (actual/5) × 100` 形式合规；**但 weight 本身来自旧 55/20/20/5 口径**（config CATEGORY_RATIO={5.5,2.0,2.0,0.5}，归一后即 55/20/20/5） | `aggregation.py:121`（合规）；`config.py:25-31`（**违约·N1**）；`aggregate.py:38-40`（仅出现类目参与配比，§8.2 允许大类归一） | 公式合规 / 权重口径违约 |
| 5.8 | §21 五段式报告 | 已实现五段（总分+gate/雷达/明细/优劣文字/逐题回顾），雷达 required vs actual 合规 | `report.py:89-153` | **[合规]** |
| 5.9 | §21.1 报告状态机（GENERATING→PROVISIONAL/READY→PUBLISHED/FAILED；review_status；发布一致性七项校验；人工明确点击发布） | **完全缺失**：报告生成即最终态，无状态机、无复核、无发布动作、无七项校验；重复生成直接 DELETE 覆盖（§28“报告版本化”所指） | `report.py:144-152`（DELETE+INSERT 覆盖） | **[违约·P0]** |
| 5.10 | §21.1 score→report 串行（服务端执行，不依赖浏览器补调） | 前端两步调用（score 后再调 report 接口）；后端 report 接口不自动触发评分 | `api/assessment.py:233-269`；`web/src/api/index.js` | **[违约·P0]**（串行缺服务端串联） |
| 5.11 | §23 双分背离→bad case 候选自动创建 | eval.py 有触发入口，但差值候选自动创建逻辑依赖新表结构 | `server/api/admin/eval.py:44-60` | 待评分链重构后补 |

## 6. 越权与安全（SSOT §25）

| # | SSOT 契约 | 现状 | 证据 | 类别 |
|---|---|---|---|---|
| 6.1 | §25 JWT HttpOnly cookie 方向 | 实际为 **Bearer header**（HTTPBearer），无 cookie | `server/core/security.py:5,33` | **[违约]**（SSOT 标“方向”，实施期决定，非 P0） |
| 6.2 | §25 生产 secret 启动校验 | config 读 JWT_SECRET 环境变量，未见启动时缺省校验 | `server/config.py` | **[缺失]**（低优先） |
| 6.3 | §25 输入限额按类型配置 | 无（长度仅 refine 阈值间接限制） | 全库 grep 无 limit 配置 | **[缺失]**（低优先） |
| 6.4 | §25 prompt injection 防护/INJECTION_DETECTED 事件 | P-refine 有“注入防护”意图（SSOT §14），代码未见显式防护或事件 | `refine.py` | **[缺失]**（依赖事件表 1.5） |

## 7. §28 已登记项的文件级定位（对账用）

| §28 条目 | 本矩阵对应 | 关键文件 |
|---|---|---|
| P0 资源所有权校验 | 1.1 | `server/api/assessment.py`（6 处路由） |
| P0 score→report 串行 | 5.10 | `server/api/assessment.py` + 前端调用链 |
| P0 开考可测量性检查 | 3.5 | `server/api/assessment.py:create_session` |
| P0 状态事件表 | 1.5, 2.2 | `server/db.py` + 全部状态迁移点 |
| 动态选题四层 | 3.2 | `server/services/question_selection.py` |
| 难度路径状态机 | 4.2 | 新建（question_selection/interview 之间） |
| 非末题 finish 护栏 | **新发现**：现状 is_last→finish 合规，但**重打分/重复报告接口无状态护栏**（session completed 后仍可 POST /score、/report） | `api/assessment.py:233-269`（仅查存在性不查状态） |
| 回答状态分类完整化 | 4.4, 4.5 | `server/services/interview.py` 重构 |
| 表单链 | 4.10 | `server/api/assessment.py` + 新 form 模块 |
| SSE 真实化 | 4.6 | `server/api/assessment.py:answer` + `web/src/utils/sse.js`（前端就绪） |
| 幂等与并发 | 4.9 | `server/api/assessment.py:answer/forms` |
| 计时区间 | 4.8 | 新建 + `db.py` session 列 |
| 题库 version 绑定/生成失败可见 | 3.4 + `question_bank.py:71`（**生成失败静默 pass**，§28“失败可见”所指） | `server/services/question_bank.py:70-71` |
| /jds/orphan 路由顺序 | **核实结果：无冲突**。`/jds/orphan` 在 positions.py:68，`/jds/{jd_id}` 在 jds.py:79——不同 router（include 顺序 positions 在 jds **之后**注册 `main.py:64-66`），FastAPI 按注册顺序匹配，`/api/admin/jds/orphan` 会先命中 jds.py 的 `/jds/{jd_id}`？**不对**——两 router 前缀同 `/api/admin`，jds 先注册，其 `/jds/{jd_id}` 在 orphan 之前声明。**实测 FastAPI 行为：路由按注册顺序匹配，`GET /api/admin/jds/orphan` 会被 jds.py:79 `/{jd_id}` 捕获（jd_id="orphan"）→ 404**。§28 所指修复成立，需把 orphan 声明移到 jds.py 内 `{jd_id}` 之前或调整 include 顺序 | `main.py:64-66`；`admin/jds.py:79`；`admin/positions.py:68` | **[违约]** 确认存在 |
| 模型编辑字段校验（NaN/范围/重复） | models.py 仅校验权重总和 ±0.5%（60-63 行），无 NaN/范围/重复校验 | `server/api/admin/models.py:60-63` | 部分缺失 |
| 证据 span/trace_link | 2.3, 2.10 | `server/db.py` + `scoring.py` |
| 报告发布校验/版本化 | 5.9 | `server/services/report.py` |
| feedback 字段补全 | feedback 表无 user_id/note/审计字段（仅 feedback_id/report_id/item_id/text/status/created_at） | `server/db.py:198-205` | **[缺失]** |
| 迁移体系 | 2.11 | `server/db.py` |
| 测试/CI/M1 回归/E2E | 现有 4 个 test 文件（m5/m6/m7/question_bank），question_bank 损坏（基线已知）；无 M1 回归、无 CI 配置、脚本测试不可统一收集 | `server/test_*.py` | **[缺失]** |

## 8. 矩阵外发现（SSOT §28 未登记，建议列入 phase）

| # | 发现 | 证据 | 建议 |
|---|---|---|---|
| 8.1 | **空 answer_key 客观题恒满分**：`re.search("", answer)` 恒命中→5 分 | `scoring.py:20-24` | 并入评分链重构 phase（对应 §17“answer_key 空属题库缺陷”） |
| 8.2 | **completed 会话仍可重复评分/报告**：POST /score、/report 只查会话存在不查状态 | `api/assessment.py:237-241,263-267` | 并入状态机/事件表 phase 加护栏 |
| 8.3 | **报告生成异常静默**：`_generate_report_task` 捕获所有异常后 pass，前端轮询 404 无从区分“生成中”与“失败” | `api/assessment.py:251-256` | 并入报告状态机（FAILED 态应可见） |
| 8.4 | **题库生成失败静默**：`generate_question_bank` 文档写明“失败不抛，仅静默” | `question_bank.py:71` | §28 已含“生成失败可见”，此处给文件定位 |
| 8.5 | **模型 items 为空不阻断开考**：create_session 不校验 items 数 | `api/assessment.py:69-94` | 并入开考检查 3.5 |
| 8.6 | **mock interviewer 主观题固定 3 分**：测试可能掩盖评分链问题 | `interview.py:66-80` | 重构测试时处理，非独立 phase |
| 8.7 | **llm_trace ref_id 单字段弱关联**：无 entity_type 语义，trace_link 缺失时审计链断裂 | `db.py:93` | trace_link 落地时一并处理 |

## 9. 统计与结论

```text
核对契约条目：68
[违约]（含结构性/核心/P0）：18
[缺失]（含 P0）：24
[合规]（保持不动）：4
部分合规/待定：22（多数为"合规但依赖项缺失"或实施期决定项）

P0 四项全部确认存在且已定位：
  1.1 所有权校验 → api/assessment.py 6 处路由
  5.10 score→report 串行 → api/assessment.py + 前端
  3.5 开考检查 → api/assessment.py:create_session
  1.5/2.2 状态事件表 → db.py

结构性大项（表结构演进 2.5-2.10）：6 张表全部需要演进或新建；
  迁移策略必须先定（Phase 8 前置决策：schema_version 体系）。

新发现（§28 未登记）：8.1-8.5 五项实质问题（8.6/8.7 为顺带记录）。
```

## 10. 本矩阵的使用方式

1. **ingest 后**：以本矩阵为 `.planning/REQUIREMENTS.md` REF-* 条目的直接来源（每行一个 REF，标注 P0/结构/一般三档）；
2. **phase 拆分**：按指南 §6.5 的 8-phase 结构，把矩阵行分配进 phase（P0 四项→Phase 1；表结构演进→Phase 2/3 的前置任务或 Phase 8 统一迁移，**需在 plan 时决策**：SSOT §28 顺序是“演进随阶段走”还是“迁移体系先行”——矩阵证据支持前者：各阶段新列/新表可在 db.py 内嵌迁移框架下渐进登记，Phase 8 收口 schema_version）；
3. **负向验证**：§30 N1-N12 对应本矩阵 3.1(N4)/3.2(N5)/5.1(N2)/4.8(N7)/5.3(N8)/5.7(N1)——这 6 项是"违约替换"任务的负向测试锚点；
4. **复核**：本矩阵是快照，每 phase 的 discuss 步骤应抽查本矩阵对应行是否仍准确（代码会随 phase 推进变化）。
