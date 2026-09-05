# Phase 4: 题库版本绑定与模块一收口 - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning

<domain>
## Phase Boundary

把题库从「按岗位复用、一次生成终身有效」演进为「绑定 confirmed 模型版本」：question_bank 行的 model_id/model_version 列（Phase 2 `_migrate_question_bank_v2` 已落）在本 phase 真正填充并成为消费侧的强制过滤键；模型升版（re-confirm 更高 version）必须生成/绑定新题库，否则 readiness 阻止开考（REF-3.4「升版须重建题库否则阻止开考」）。题库生成失败从「落表但不对外可见」升级为「readiness 带 error_msg + 管理员待办含失败明细」（REF-8.4）。同时收口模块一管理端两处已知缺陷：`/jds/orphan` 路由顺序修复（REF-7.1）、模型编辑字段校验（NaN/范围/类别/重复 std_name，REF-7.2）。

对应 REQUIREMENTS.md：REF-2.5, REF-3.4, REF-7.1, REF-7.2, REF-8.4（5 项，支撑 REQ-jd-parse-model / REQ-dynamic-question-generation）。

**不在本阶段**：等值备用题组 equivalence_group_id（REF-3.8 延后）；综合题槽位 question_type='integrated'/integrated_bindings_json（REF-3.9 延后，question_type/measurement_stage 列 Phase 2 已落 DEFAULT 'ordinary' 不动）；measurement_target/evidence_requirement 的填充与消费（Phase 5 证据链）；schema_version 收口/pytest 统一（Phase 6）；M1 回归验收（Phase 6）；报告链、trace_link（Phase 5）。
</domain>

<decisions>
## Implementation Decisions

> D-47~D-54 为 Phase 4 编号（接续 03 的 D-29~D-46）。auto 模式（章程 §1）推荐项选取，逐条依据 = SSOT 条款/既定决策/代码现状三者之一，留痕见 04-DISCUSSION-LOG.md。

### 题库 model/version 绑定（REF-2.5/REF-3.4 主体，计划 04-01）

- **D-47: model/version 绑定 = 填充既有列 + 消费侧收紧，不改表结构。** question_bank 的 model_id/model_version/item_id 列已在 Phase 2 `_migrate_question_bank_v2` 落（§9.2 目标列除 equivalence_group_id/integrated_bindings_json 外全齐）。Phase 4 主体 = `generate_question_bank` 落库时写 model_id/model_version/item_id（循环内 `item["item_id"]` 可得），消费侧（selection + readiness）把 Phase 2 的「版本近似放行」收紧为「强制 model_id + model_version 匹配」。equivalence_group_id（等值组 REF-3.8）/integrated_bindings_json（综合题 REF-3.9）两列不落，延后。

- **D-48: 升版语义 = 旧题 status 保持 active，靠消费侧 model_version 过滤实现「旧题库不对新会话生效」。** SSOT §9.2「有效题目定义 = status='active' 且 model/version 匹配」——升版后新 session 绑 v2，selection/readiness 只取 v2 题，v1 题天然不命中（不改 status、保留审计/历史）。confirm(v2) → question_bank_task(v2) QUEUED/RUNNING → readiness `QUESTION_BANK_GENERATING` 拦开考；生成 FAILED → `QUESTION_BANK_INCOMPLETE` 拦开考（升版须重建题库否则阻止开考，REF-3.4）。

- **D-49: 幂等判重键升级 = (model_id, model_version, std_name, category, difficulty) 替换 (position_id, std_name, category, difficulty)。** 现状 WR-03 幂等按 (std_name+category+difficulty) 判重；升版后 v2 判重若仍看 v1 已 active 行会整链跳过——必须把 model_version 纳入判重键，使 v2 生成 v2 题而非「因 v1 题存在而跳过」。position_id 在版本维度退化（同岗位 v1/v2 的 position_id 相同），故以 model_id+model_version 区分代际。

- **D-50: 消费侧收紧点清单（全部 WHERE 加 model_version 过滤）。**
  - `readiness._question_count_by_category` / `_covered_std_names` / tier 计数 LEFT JOIN 三处 WHERE 加 `model_id=? AND model_version=?`；
  - `selection._load_candidate_rows` 的「版本近似」子句 `(b.model_id IS NULL OR ? IS NULL OR b.model_id=?)` 收紧为 `b.model_id=? AND b.model_version=?`（去掉 NULL 放行；函数签名补 model_version 入参）；
  - 通用题（scope='general'）同绑 model_version：同版本生成、跨岗位复用；版本内复用、跨版本重建。**注意**：现行 selection 已 `category IN ('hard_skill','soft_skill')` 排除 experience/qualification，故 general 题的版本绑定无功能性影响（生成但永不被选）——见 `<specifics>` 的 Phase 3 D-32 遗留观察。

### 生成失败可见（REF-8.4，计划 04-01 侧带）

- **D-51: 生成失败可见 = readiness FAILED 分支 detail 带 error_msg + admin todos 含失败明细。** 现状 `generate_question_bank` 已落 question_bank_task.status='FAILED' + error_msg（Phase 1 D-12），但 readiness FAILED 分支只给通用「题库不完整」、admin todos 只给计数。Phase 4：readiness 第 3 项 task 为 FAILED 时 detail 附最新 FAILED 行 error_msg（截断）；admin `positions.get_todos` 的 `question_bank_not_ready` 从计数扩展为「计数 + 失败任务明细（position/model_version/error_msg）」（D-13 已预留「admin 页展示留 Phase 4」）。前端零破坏（Vue 对未知键安全）。

### orphan 路由（REF-7.1，计划 04-02）

- **D-52: GET /jds/orphan 声明在 GET /jds/{jd_id} 之前（FastAPI 按声明序匹配），返回 position_id IS NULL 的 JD 列表。** 现状 `/jds/{jd_id}` 参数路由吞掉 `/jds/orphan` 恒 404（jd_detail("orphan") → 404）。修复 = 新增 `@router.get("/jds/orphan")` 置于其前，查询 `jd_record WHERE position_id IS NULL ORDER BY created_at DESC`，字段同 list_jds。纯路由顺序修复 + 查询，无 schema 改动。

### 模型编辑校验（REF-7.2，计划 04-02）

- **D-53: update_model 的 ModelItem Pydantic 强化（服务端拒绝非法值，保留 Σ=100% 校验）。**
  - weight：拒绝 NaN/∞（`allow_inf_nan=False` 或显式 `math.isfinite`），保留 `ge=0` + 新增 `le=1`（Σ=100% 已拦总量，per-item le=1 拦单 item 越界）；
  - required_level：`int | None`，范围 1-5（越界 400/422）；
  - importance：枚举 `{required, preferred, plus} | None`（越界类别拒绝；与 readiness 的 `COALESCE(ci.importance,'plus')` 口径对齐）；
  - years：`float | None`，`ge=0`；
  - 重复 std_name：同 category 内 std_name 重复 → 拒绝（competency_dict PRIMARY KEY(std_name,category) 对齐；diff 以 std_name|category 为键，重复会破坏 diff）；
  - category 越界已由 `pattern=^(hard_skill|soft_skill|experience|qualification)$` 拦（保留）。

### §9.2 低成本对齐（计划 04-01 侧带）

- **D-54: item_id 落库 + rubric_version 常量 "v1"。** generate_question_bank 落库时 item_id 一并填（循环内可得，§9.2 item_id 绑定对齐）；rubric_version 落常量 "v1"（rubric 每次生成，版本标记起步 v1）。measurement_target/evidence_requirement 留 NULL（Phase 5 证据链消费，本 phase 不填）。

### Claude's Discretion
- 幂等判重的具体 SQL 形态（`exists` 查询加 model_id/model_version 谓词；general 题无难度维度的判重同理加版本）
- readiness tier 计数 LEFT JOIN 的 model_version 谓词落点（`ci.model_id=?` 邻位）
- selection `_load_candidate_rows` 签名与调用点改造（`_session_instance_state` 已取 session 的 model_version，传入路径就近）
- admin todos 失败明细的字段命名与结构（`question_bank_failed` 新键 vs `question_bank_not_ready` 内嵌）
- 测试组织（新 test_phase4_* 文件——沿用单文件单进程 + tempfile + mock 三件套纪律）

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 设计权威（SSOT）
- `design/final-design/总设计文档.md` §9.2 — question_bank 表（演进后）：model_id/model_version/item_id 绑定、question_type/measurement_stage/rubric_version/measurement_target/evidence_requirement/observable_level_min/max；「有效题目 = status='active' 且 model/version 匹配」；「模型升版必须生成/绑定新题库，否则阻止开考」
- `design/final-design/总设计文档.md` §10.4 — 开考前可测量性检查：检查项含「题库绑定当前 model/version 且已生成完成」；三态 QUESTION_BANK_GENERATING/INCOMPLETE/MODEL_NOT_MEASURABLE + 管理员待办
- `design/final-design/总设计文档.md` §9.4 — 难度与 1–5 等级映射（锚点回填已在 Phase 2 完成，参考）
- `design/final-design/总设计文档.md` §28 — 六步实施顺序第 4 步（题库 model/version 绑定与生成失败可见 / /jds/orphan 路由顺序修复 / 模型编辑字段校验 NaN/范围/重复）

### 证据基线
- `research/ssot-code-gap-matrix.md` — 68 行契约核对（Phase 4 相关：矩阵 §2 的 2.5、§3 的 3.4、§7 的 7.1/7.2、§8 的 8.4）
- `.planning/intel/decisions.md` D-018（模型升版必须生成/绑定新题库否则阻止开考）、D-017（开考前可测量性检查）、D-012（score_live 仅导航——无关但同一 decision 卷）
- `.planning/phases/03-sse/03-CONTEXT.md` — Phase 3 已决（D-32 experience/qualification 出题库、D-46 存量端点 Pydantic 化延后 Phase 6）
- `.planning/phases/02-dynamic-selection/02-CONTEXT.md` — Phase 2 已决（D-14 question_bank v2 列迁移、§9.4 锚点回填）

### 代码现状（改造对象）
- `server/db.py` — question_bank DDL（v2 列已落）+ `_migrate_question_bank_v2`（Phase 2 迁移，幂等嗅探）
- `server/services/question_bank.py` — generate_question_bank（落库点：model_id/model_version/item_id 待填；幂等判重键待升级）
- `server/services/readiness.py` — check_session_readiness（第 3 项 task 状态 + 第 4/5 项题量计数待加 model_version 过滤 + FAILED 明细）
- `server/services/question_selection.py` — _load_candidate_rows（「版本近似放行」待收紧）
- `server/api/admin/models.py` — update_model（ModelItem Pydantic 待强化）/ confirm_model（升版触发点，已插 model_version 到 task 行）
- `server/api/admin/jds.py` — jd_detail 参数路由（/jds/orphan 吞掉点）
- `server/api/admin/positions.py` — get_todos（question_bank_not_ready 待扩展明细）
- `.planning/codebase/ARCHITECTURE.md` / `TESTING.md` — 分层纪律/SQLite 单写者两模式/测试纪律

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `question_bank_task` 表（Phase 1 D-12）已带 model_id/model_version/status/error_msg 列——版本绑定的「任务侧」已就绪，只差「题目行侧」填充 + 消费侧过滤
- `_migrate_question_bank_v2`（db.py:433）幂等嗅探式 ALTER——question_bank 的 model_id/model_version/item_id 列已在老库自动补齐，无需新迁移
- `confirm_model`（models.py:113）已插 model_version 到 task 行（`row["version"]`）——升版触发链完整，只差题目行绑定
- `_load_candidate_rows`（question_selection.py:219）「版本近似」注释已明示「Phase 4 REF-3.4 收紧为强制绑定」——过渡态设计者已预留收口点
- readiness 三态失败名 + 管理员待办（Phase 1 D-13）——FAILED 明细扩展的既有载体

### Established Patterns
- raw SQL + get_conn() per-call + 显式 commit；DDL 迁移幂等嗅探（PRAGMA table_info）
- N11 枚举代码校验（question_type/measurement_stage 无 DB CHECK，DEFAULT 'ordinary'）
- 「先 commit 再调 LLM」模式（generate_question_bank 逐 item commit——model_id/model_version 填充不破坏该模式）
- 消费侧过滤同源纪律：readiness 与 selection 的题库 WHERE 口径须一致（WR-15 教训——两处公式漂移）

### Integration Points
- `server/services/question_bank.py generate_question_bank` — 落库点（写 model_id/model_version/item_id + 判重键升级）
- `server/services/readiness.py` — 三处题量查询加 model_version 过滤 + FAILED detail
- `server/services/question_selection.py _load_candidate_rows` — 版本近似收紧
- `server/api/admin/models.py update_model` — Pydantic 校验强化
- `server/api/admin/jds.py` — orphan 路由前置
- `server/api/admin/positions.py get_todos` — 失败明细扩展

</code_context>

<specifics>
## Specific Ideas

- **Phase 3 D-32 遗留观察（非本 phase 动作）**：D-32 说「experience/qualification 出普通题库改走表单」，但现行 `generate_question_bank` 仍为 experience/qualification 生成 scope='general' 题（`_question_plan` 对二者返回 `[(None,"subjective")]`）。selection 已 `category IN ('hard_skill','soft_skill')` 排除、readiness 配额也只算 hard/soft，故这些 general 题「生成但永不被选/不被算配额」——无害但冗余。Phase 4 **不扩大范围**去删 general 题生成（那是 D-32 收尾，若要做属 Phase 3 补漏），只确保 general 题生成时同样绑 model_version（一致性）。
- 升版后 v1 题保留 active 但「失配」——审计/历史可查（不删不标 inactive），与 SSOT「有效题目 = active 且 model/version 匹配」字面一致。
- readiness FAILED 明细的 error_msg 需截断（现状 generate_question_bank 已 `str(e)[:200]`），detail 文案避免注入敏感堆栈。
- orphan 路由顺序修复须带回归测试（`GET /jds/orphan` 返回列表而非 404——FastAPI 声明序匹配的单元/集成断言）。

</specifics>

<deferred>
## Deferred Ideas

- 等值备用题组 equivalence_group_id（REF-3.8——SSOT 未列 §28 硬项，登记不排期）
- 综合题槽位 question_type='integrated' + integrated_bindings_json（REF-3.9——Prompt 待讨论 D-030）
- measurement_target / evidence_requirement 填充与消费（Phase 5 证据链 span + trace_link）
- schema_version 迁移登记簿收口（Phase 6——替换 DDL 字符串嗅探）
- M1 回归清单（Phase 6——清洗边界/抽取异常/消歧/权重尾差/冲突 stalled 等八项）
- scope='general'（experience/qualification）题生成的彻底移除（Phase 3 D-32 收尾，若需）
- rubric_version 的版本演进语义（本期 "v1" 常量起步，真实版本管理随 rubric 工程化再议）

</deferred>

---

*Phase: 4-题库版本绑定与模块一收口*
*Context gathered: 2026-09-05*
