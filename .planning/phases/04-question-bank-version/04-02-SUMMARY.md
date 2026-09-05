---
phase: 04-question-bank-version
plan: 02
subsystem: api
tags: [fastapi, pydantic, sqlite, pytest, orphan-route, field-validation, nan-validation, model-edit]

# Dependency graph
requires:
  - phase: 04-question-bank-version
    provides: 题库版本绑定口径基座 + get_todos question_bank_failed 明细（04-01 已落）
  - phase: 02-dynamic-selection
    provides: test_phase2_selection.py 三件套头（tempfile DB_PATH + LLM_PROVIDER=mock + JWT_SECRET + init_db()）+ _q 只读 helper
  - phase: 03-forms-sse-idempotency-timing
    provides: _ensure_admin（passlib CryptContext bcrypt 建 role=admin）+ admin 登录头模式
provides:
  - GET /api/admin/jds/orphan 迁入 jds.py 并置于 /jds/{jd_id} 之前（字段口径锁定选项 B）
  - ModelItem 字段级校验：weight Field(ge=0, le=1, allow_inf_nan=False) / required_level Field(ge=1, le=5) / importance Literal / years Field(ge=0, allow_inf_nan=False)
  - update_model 同 category 重复 std_name 拒绝（400），保留 Σ=100% 校验
affects: [06-migration-test-closeout]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FastAPI 同文件声明序修复参数路由吞字面量：/jds/orphan 与 /jds/{jd_id} 同文件声明在前"
    - "NaN/∞ 用 Pydantic v2 allow_inf_nan=False 解析期拒绝，不在 Σ 聚合级补救（sum([nan,...]) 恒绕过 abs>0.005）"
    - "单文件单进程测试纪律：test_phase4_orphan.py / test_phase4_model_edit.py 各自独立三件套"

key-files:
  created:
    - server/test_phase4_orphan.py
    - server/test_phase4_model_edit.py
  modified:
    - server/api/admin/jds.py
    - server/api/admin/positions.py
    - server/api/admin/models.py

key-decisions:
  - "orphan 字段口径锁定【[04-009] 选项 B 现有实现】= 字段子集 jd_id/job_title/company/source_type/status/created_at + WHERE position_id IS NULL AND status != 'failed'（与 get_todos 孤儿计数一致）"
  - "NaN/∞ 用 allow_inf_nan=False（Pydantic v2 解析期 422），绝不在 Σ 聚合级补救"
  - "重复判重键 (std_name, category) 对齐 competency_item 主键与 diff_models 的 std_name|category 对齐键"
  - "测试侧 raise_server_exceptions=False：importance='bad' RED 阶段撞 DB CHECK 时断言 422 而非崩在异常"

patterns-established:
  - "TestClient(app, raise_server_exceptions=False)：把撞 DB CHECK 的非法枚举变成可断言的 500（RED）→ 422（GREEN），而非让测试崩在 sqlite3.IntegrityError"

requirements-completed: [REF-7.1, REF-7.2]

# Metrics
duration: 5min
completed: 2026-09-05
---

# Phase 04 Plan 02: orphan 路由修复 + 模型编辑校验 Summary

**管理员 /jds/orphan 路由前置修复（参数路由不再吞掉 orphan 恒 404）+ ModelItem Pydantic 字段级校验（NaN/∞/越界/非法枚举/同 category 重复 std_name 服务端拒绝）**

## Performance

- **Duration:** 5 min
- **Started:** 2026-09-05T06:58:55Z
- **Completed:** 2026-09-05T07:03:46Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- GET /api/admin/jds/orphan 迁入 jds.py 并置于 /jds/{jd_id} 之前，FastAPI 按声明序匹配，`jd_id="orphan"` 不再落到 jd_detail 返回 404「JD 不存在」（REF-7.1）
- positions.py 移除被遮蔽的重复 orphan 路由，get_todos 的 orphan_jds 计数保留（与 orphan 列表口径一致：position_id IS NULL AND status != 'failed'）
- ModelItem 字段级校验：weight `Field(ge=0, le=1, allow_inf_nan=False)`、required_level `Field(ge=1, le=5)`、importance `Literal["required","preferred","plus"]`、years `Field(ge=0, allow_inf_nan=False)`——NaN/∞/越界/非法枚举解析期 422（REF-7.2）
- update_model 同 category 重复 std_name 拒绝（400），保留 Σ=100% 校验（容差 0.005）

## Task Commits

Each task was committed atomically (TDD 红→绿):

1. **Task 1: 新建 test_phase4_orphan.py + test_phase4_model_edit.py（先红）** - `35f4959` (test)
2. **Task 2: /jds/orphan 迁入 jds.py 并置于 jd_detail 之前 + 移除 positions.py 重复路由** - `4b28ef9` (fix)
3. **Task 3: ModelItem 字段级校验强化 + update_model 重复 std_name 拒绝** - `c5dcf8a` (fix)

**Plan metadata:** final docs commit (SUMMARY.md + STATE.md + ROADMAP.md + REQUIREMENTS.md)

## Files Created/Modified
- `server/test_phase4_orphan.py` - 1 test：/jds/orphan 返回 200 列表（非 404），字段集合恰为 6 列（选项 B），failed 孤儿排除、非 failed 孤儿包含
- `server/test_phase4_model_edit.py` - 10 tests：ModelItem parse_obj 拒绝 NaN/∞ weight+years；HTTP 层 weight>1 / required_level 越界 / importance 非法枚举 / years 负数（422）、重复 std_name（400）、Σ=100% 保留（400）、合法编辑（200 + competency_item 重建）、NaN 拒绝且不落库
- `server/api/admin/jds.py` - 新增 `@router.get("/jds/orphan")` list_orphan_jds 置于 jd_detail 之前
- `server/api/admin/positions.py` - 移除 list_orphan_jds（保留 get_todos orphan_jds 计数）
- `server/api/admin/models.py` - `from typing import Literal` + ModelItem 字段强化 + update_model 重复 std_name 拒绝

## Decisions Made
- orphan 字段口径锁定【[04-009] 选项 B 现有实现】= 字段子集 6 列 + `WHERE position_id IS NULL AND status != 'failed'`，与 get_todos 孤儿计数同源，未改 D-52 字面全字段口径
- NaN/∞ 用 Pydantic v2 `allow_inf_nan=False` 解析期拒绝，绝不在 Σ 聚合级补救（`sum([nan,...])` 恒绕过 `abs>0.005`）
- 重复判重键 `(std_name, category)` 对齐 competency_item 主键与 diff_models 的 `std_name|category` 对齐键
- 测试侧 `TestClient(app, raise_server_exceptions=False)`：使 importance='bad' 在 RED 阶段撞 DB CHECK（IntegrityError）时返回可断言的 500（而非让测试崩在异常上），GREEN 阶段断言 422

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] NaN/∞ HTTP 层 422 断言不可达（Starlette JSONResponse 无法序列化 input=nan/inf）**
- **Found during:** Task 1（新建 test_phase4_model_edit.py）
- **Issue:** 计划 `<behavior>` 要求「NaN weight（422）」的 HTTP 断言，但实测 Starlette `JSONResponse.render` 用 `json.dumps(..., allow_nan=False)`，FastAPI 的 RequestValidationError 处理器在渲染 `{"input": nan/inf}` 时抛 `ValueError: Out of range float values are not JSON compliant`——NaN/∞ 的 422 响应恒退化为 500，HTTP 层无法断言 422。httpx `json=` 参数对 NaN/∞ 同样抛 ValueError（allow_nan=False），故「改走 float('inf')」也被堵死。
- **Fix:** 遵循计划约束 #7 的 fallback：NaN/∞ 走 `ModelItem.model_validate(...)` parse_obj 单测（weight 与 years 各 NaN/∞），HTTP 层保留一个 NaN 用例用 raw content 提交 NaN 字面量、断言「非 200 且 competency_item 不被污染」。未为求绿放宽断言。
- **Files modified:** server/test_phase4_model_edit.py
- **Verification:** `python -m pytest test_phase4_model_edit.py -v` 10 passed（GREEN）
- **Committed in:** 35f4959（Task 1 红）→ c5dcf8a（Task 3 绿）

**2. [Rule 3 - Blocking] importance='bad' RED 阶段撞 DB CHECK 致测试崩在异常**
- **Found during:** Task 1（新建 test_phase4_model_edit.py）
- **Issue:** 现网 ModelItem `importance: str | None` 不校验枚举，importance='bad' 穿透 Pydantic 后在 competency_item INSERT 撞 `CHECK(importance IN ('required','preferred','plus'))` 抛 IntegrityError；TestClient 默认 `raise_server_exceptions=True` 会 re-raise，使 RED 阶段测试「ERROR」而非「FAILED」（计划要求红、非 collection error）。
- **Fix:** `TestClient(app, raise_server_exceptions=False)`——把撞 CHECK 的 IntegrityError 变成可断言的 500（RED）→ 422（GREEN）。非放宽断言，反而强化「非法枚举不 500 泄漏」的验证。
- **Files modified:** server/test_phase4_model_edit.py
- **Verification:** `python -m pytest test_phase4_model_edit.py -v` RED 7 failed / GREEN 10 passed
- **Committed in:** 35f4959（Task 1）→ c5dcf8a（Task 3）

---

**Total deviations:** 2 auto-fixed（均为 NaN/∞ 序列化 + DB CHECK 崩溃的处理路径，非功能缺陷）
**Impact on plan:** 无 scope creep；两处均为计划约束 #7 与「红、非 collection error」的既定执行口径，未放宽任何断言。

## Issues Encountered
- 无。5 个测试文件均需单文件单进程运行（DB_PATH import 时读取冲突），最终串行验证全绿：test_phase4_orphan.py 1 passed、test_phase4_model_edit.py 10 passed、test_phase4_binding.py 4 passed、test_phase4_fail_visible.py 2 passed、test_phase2_selection.py 9 passed。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- 04-02 完成：模块一管理端两处已知缺陷（orphan 路由顺序 + 模型编辑字段校验）收口，Phase 4（题库版本绑定与模块一收口）全部计划完成
- 无阻断项。后续 Phase 5（证据 span + trace_link / 报告发布校验 / 报告版本化）与 Phase 6（迁移体系 + 测试闭环收口）可推进。

---

*Phase: 04-question-bank-version*
*Completed: 2026-09-05*

## Self-Check: PASSED

- SUMMARY.md exists at `.planning/phases/04-question-bank-version/04-02-SUMMARY.md`
- Modified files exist: server/api/admin/jds.py, server/api/admin/positions.py, server/api/admin/models.py, server/test_phase4_orphan.py, server/test_phase4_model_edit.py
- Task commits verified: `35f4959` (test), `4b28ef9` (fix), `c5dcf8a` (fix)
