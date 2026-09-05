---
phase: 06-migration-test-closure
plan: 06-02
subsystem: testing
tags: [pytest, github-actions, ci, requirements]

# Dependency graph
requires:
  - phase: 06-migration-test-closure
    provides: server/conftest.py mock 三件套 + session 级临时 DB fixture（Wave 0 linchpin）
provides:
  - pytest 可收集的 test_question_bank.py（check_* 改名）+ test_m6_backend.py（_test_* → test_* + ctx fixture）
  - server/requirements.txt 的 pytest>=8 依赖声明
  - .github/workflows/ci.yml（backend pytest + frontend build 并行）
affects: [06-migration-test-closure]

# Tech tracking
tech-stack:
  added: [pytest>=8, GitHub Actions]
  patterns: [conftest session fixture 复用, check_* 改名规避 fixture 误判, _test_* → test_* + session ctx fixture 保脚本顺序]

key-files:
  created: [.github/workflows/ci.yml]
  modified: [server/test_question_bank.py, server/test_m6_backend.py, server/requirements.txt]

key-decisions:
  - "带参 test_* 改名 check_*（保留 __main__）消 3 个 fixture 误判（D-69）"
  - "test_m6 _test_* → test_* + session 级 ctx fixture 保顺序（脚本语义保持，D-69/PATTERNS）"
  - "CI = GitHub Actions，backend pytest + frontend build 两 job 并行（D-70）"
  - "9.5/24.5 断言口径保持不动（D-72）"

patterns-established:
  - "check_* 命名：带参脚本式测试函数改 check_* 前缀避免 pytest 误判 fixture"
  - "session ctx fixture：顺序依赖的脚本式测试转 pytest 时用 session fixture 单次 seed + 顺序复用"

requirements-completed: ["REF-7.4"]

# Metrics
duration: 11min
completed: 2026-09-05
---

# Phase 6 Plan 02: 测试统一 pytest + CI 收口 Summary

**两个脚本式测试模块改造为 pytest 可收集（question_bank 带参 test_* 改名 check_* + test_m6 _test_* 转 test_* + session ctx fixture），并补齐 pytest>=8 依赖与 GitHub Actions CI 测试闭环。**

## Performance

- **Duration:** 11 min
- **Started:** 2026-09-05T14:30:30Z (approx)
- **Completed:** 2026-09-05T14:41:03Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `test_question_bank.py` 3 个带参 `test_*` 改名 `check_*`，消除 pytest 执行的 3 个「fixture 'pid' not found」错误；无参 `test_prompts` 保留
- `test_m6_backend.py` 4 个 `_test_*` 转 `test_*`（新增 session 级 `ctx` fixture 保顺序），pytest 收集 4 个测试
- 两个文件 `__main__` runner 保留，`python test_x.py` 仍可单跑（25/44 全过）
- `server/requirements.txt` 补 `pytest>=8`；`.github/workflows/ci.yml` 落地（backend pytest + frontend build 并行）

## Task Commits

Each task was committed atomically:

1. **Task 1: 消除收集期 3 errors — 带参 test_* 改名 + _test_* 改名** - `77c13a8` (test)
2. **Task 2: requirements.txt 补 pytest + GitHub Actions CI** - `4e73035` (chore)

**Plan metadata:** see final `docs` commit (SUMMARY + STATE + ROADMAP).

## Files Created/Modified

- `server/test_question_bank.py` - `test_generation`/`test_idempotent`/`test_selection` → `check_*`；`__main__` 调用点同步
- `server/test_m6_backend.py` - `_test_*` → `test_*`（4 个）；新增 session `ctx` fixture；`__main__` 调用点同步
- `server/requirements.txt` - 追加 `pytest>=8`
- `.github/workflows/ci.yml` - 新建 GitHub Actions（backend pytest + frontend build 两 job 并行）

## Decisions Made

- 带参脚本式函数改 `check_*` 前缀（保留 `__main__` 单跑），无参 `test_prompts` 保留 `test_*` —— 对齐 D-69
- test_m6 顺序依赖（dual_scoring→aggregation→report→feedback）用 session 级 `ctx` fixture 单次 seed + 顺序复用保持脚本语义，避免 4 个新 fixture 误判 —— D-69 / 06-PATTERNS
- CI = GitHub Actions `on: push/pull_request`，backend（`python -m pytest . -q`）与 frontend（`npm ci && npm run build`）两 job 并行 —— D-70
- 9.5/24.5 断言数值保持不动（D-72，mock=3 确定性口径正确）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] test_m6 改名后 `ctx` 参数会引入 4 个新 fixture 误判，补 session `ctx` fixture**
- **Found during:** Task 1
- **Issue:** 计划 action 只写「`_test_*` → `test_*`」，但 4 个函数都带 `ctx` 参数；若只改名，pytest 会把 `ctx` 当 fixture 报「fixture 'ctx' not found」，反而新增 4 个收集错误，破坏「收集干净」目标。
- **Fix:** 新增 session 级 `ctx` pytest fixture（依赖 conftest 的 `_session_db`，单次 `_seed_full_chain()`），4 个 `test_*` 经 fixture 注入顺序复用 ctx，脚本顺序语义保持；`__main__` 仍直接 `_seed_full_chain()` 后传 ctx。
- **Files modified:** server/test_m6_backend.py
- **Verification:** `python -m pytest test_question_bank.py test_m6_backend.py -q` → 5 passed；`python test_m6_backend.py` → 44 通过 exit 0
- **Committed in:** 77c13a8

---

**Total deviations:** 1 auto-fixed (Rule 2 - missing critical functionality)
**Impact on plan:** 必要的正确性补齐——不改会破坏「收集干净」目标；无范围蔓延。

## Issues Encountered

- 计划文本称「收集期 3 errors」，实测为「执行期 3 errors」（pytest 9.1.1 `--collect-only` 不报 fixture 错，执行时报）。改名后两者均消除。
- `grep -c "_test_"` 剩余 1 处命中为 `tempfile.mkdtemp(prefix="m6_test_")`（临时目录前缀，非测试函数名），属计划预期内的「非测试名」。

## User Setup Required

None - no external service configuration required.（GitHub Actions 为仓库内 YAML 配置，无外部服务；本地 `npm run build` 等价验证前端）

## Next Phase Readiness

- 统一收集入口已通：`cd server && python -m pytest . --collect-only -q` 收集 200 测试，无 fixture 误判
- 06-03（M1 回归）、06-04（E2E）、06-05（eval 隔离/安全）可在统一收集 + CI 入口上继续
- CI 干跑不可本地执行，以 yml 静态 grep + 前端本地 `npm run build` 等价验证（见 06-02-PLAN verification）
- `REQ-e2e-demo-deliverables`（plan frontmatter 列示）本计划仅推进「统一 pytest 收集 + CI」半程，候选人端完整 E2E 由 06-04 交付，故未标记 complete

## Self-Check: PASSED

- `.planning/phases/06-migration-test-closure/06-02-SUMMARY.md`、`.github/workflows/ci.yml`、`server/requirements.txt` 均存在于磁盘
- Task 提交 `77c13a8`（Task 1）与 `4e73035`（Task 2）均存在于 git 历史

---
*Phase: 06-migration-test-closure*
*Completed: 2026-09-05*
