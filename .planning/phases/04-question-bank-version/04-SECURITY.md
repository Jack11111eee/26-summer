# SECURITY.md — Phase 04 (04-question-bank-version)

**Phase:** 4 — 题库版本绑定 + 模块一管理端收口（orphan 路由 + 模型编辑字段校验）
**Audited:** 2026-09-05
**ASVS Level:** 1
**Threat register source:** 2× `<threat_model>` blocks（04-01 / 04-02 PLAN.md），register authored at plan time.
**Result:** SECURED — 6/6 resolved（4 mitigate verified in code，2 accept documented below）。

## Threat Verification

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-04-01 | Information Disclosure | mitigate | `services/question_bank.py:189` 落库截断 `error_msg=str(e)[:200]`；`services/readiness.py:100` SELECT status, error_msg、`:108-112` FAILED 分支 `detail += f"（{task['error_msg'][:200]}）"` 只拼截断 error_msg，不附原始异常对象/堆栈/内部路径；`api/admin/positions.py:29-34` question_bank_failed 原样返回已截断 error_msg |
| T-04-02 | Elevation of Privilege | accept | `api/admin/positions.py:8` `router = APIRouter(..., dependencies=[Depends(require_admin)])`（get_todos 所在 router）——见 Accepted Risks |
| T-04-03 | Tampering | mitigate | `services/readiness.py:24`/`:37`/`:146`（_question_count_by_category / _covered_std_names / tier LEFT JOIN）三处 + `services/question_selection.py:234`（_load_candidate_rows）一处，全部 `AND model_id=? AND model_version=?`（readiness 带 qb. 前缀、selection 带 b. 前缀）；grep `IS NULL` 在两文件零残留（去 NULL 放行） |
| T-04-04 | Tampering | mitigate | `api/admin/models.py:22` `weight: float = Field(ge=0, le=1, allow_inf_nan=False)` Pydantic v2 解析期拒绝 NaN/∞ |
| T-04-05 | Tampering | mitigate | `api/admin/models.py:23` `required_level: int \| None = Field(default=None, ge=1, le=5)`；`:24` `importance: Literal["required", "preferred", "plus"] \| None = None`；`:25` `years: float \| None = Field(default=None, ge=0, allow_inf_nan=False)` |
| T-04-06 | Elevation of Privilege | accept | `api/admin/jds.py:11` + `api/admin/models.py:13` 两 router 均 `dependencies=[Depends(require_admin)]`——见 Accepted Risks |

## Accepted Risks Log

| Threat ID | Risk | Rationale |
|-----------|------|-----------|
| T-04-02 | get_todos 返回 `question_bank_failed` 明细（含 error_msg）至管理员 | 已在 router 级 `require_admin` 下（positions.py:8），本 phase 不新增权限面、不改权限模型（ASVS V4 现有控制）；error_msg 入库时已 `str(e)[:200]` 截断（question_bank.py:189） |
| T-04-06 | GET /jds/orphan 与 PUT /models/{model_id} 仅受 `require_admin` 保护 | 已在 router 级 `require_admin` 下（jds.py:11 / models.py:13），本 phase 不新增权限面（ASVS V4 现有控制） |

## Unregistered Flags

None. SUMMARY files（04-01 / 04-02）无 `## Threat Flags` 段；`## Deviations from Plan` 所列 4 项均为测试基建/执行口径调整（种子修复、grep 字面量、NaN 序列化、DB CHECK 崩溃处理），非新攻击面。Register 完整，未扫描新威胁。

## Code-Review Cross-Validation

04-REVIEW.md（reviewed 2026-09-05，6 warning / 6 info / 0 critical）与威胁寄存器直接相关项：

- **WR-03（Warning，非阻断）**：readiness FAILED 分支把 `task["error_msg"]`（即 `str(e)[:200]`）拼进 detail，而 `check_session_readiness` 在 create_session 预检阶段由普通考生触发——截断后的 error_msg 仍可能携带 LLM provider 报错/内部路径/prompt 片段。T-04-01 声明的缓解（截断 + 只拼 `error_msg[:200]`）已在代码就位，但 WR-03 主张该缓解「不充分」属 design 充分性争议，非「声明缓解缺失」，不构成 BLOCKER（block_on=high，WR-03 为 warning 级）。建议后续收口：考生侧仅返回固定文案，内部细节保留在管理员侧 `todos.question_bank_failed`。
- **IN-02（Info）**：NaN/∞ 校验生效（数据被拒且不落库），但 HTTP 层因 Starlette `JSONResponse(allow_nan=False)` 序列化错误详情退化为 500 而非 422——不影响 T-04-04 防污染属性，仅状态码健壮性。
- 其余 WR-01/02/04/05/06 与 IN-01/03/04/05/06 为功能正确性/代码质量项（配额判定、todos 最新行口径、model_json 元数据丢弃、连接关闭、rubric 兜底、可变默认值等），不属本威胁寄存器声明的缓解缺失，不在此复述。

## Sign-Off

- [x] All threats have a disposition（4 mitigate + 2 accept）
- [x] Accepted risks documented（T-04-02 / T-04-06）
- [x] `threats_open: 0` confirmed
- [x] Implementation files untouched（仅新增本文件）
