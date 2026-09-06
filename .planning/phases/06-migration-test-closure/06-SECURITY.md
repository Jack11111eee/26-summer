---
phase: 06-migration-test-closure
threats_total: 21
threats_open: 0
verified: 2026-09-06
---

# 06-SECURITY — Phase 6 威胁缓解核验

核验对象：06-01 ~ 06-05 五份 PLAN 的 `<threat_model>` STRIDE Threat Register（共 21 条，含 5 条 T-06-SC）。
核验方法：对每条 `mitigate` 威胁，在缓解计划引用的实现文件中 grep 到具体缓解代码（file:line）；对每条 `accept` 威胁，确认「零新包」表述仍准确。实现文件只读，未改动任何实现。

## 核验结论

全部 21 条威胁 CLOSED（16 条 mitigate 缓解落地 + 5 条 T-06-SC 供应链处置准确）。`threats_open = 0`。

## Threat Verification

### 06-01（迁移登记簿 / set_db_path / conftest）

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-06-01 | Tampering | mitigate | `server/db.py:943-953` 登记簿查重（applied 集合 + `INSERT INTO schema_version` + 逐迁移 commit）；`:915-927` `_backup_before_migration` 用 `conn.backup()` 备份；`:470`/`:498` 两个 DDL 重建迁移保留 `"'report'"`/`"'bad_case'"` 幂等嗅探（Pitfall 4 belt-and-suspenders） |
| T-06-02 | Tampering | mitigate | `server/test_migration.py:29-43` `test_fresh_replay` 用 `re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _DDL)` 动态提取表名集合，与 sqlite_master 表名集合做相等 + 计数断言（parity，不硬编码表数） |
| T-06-03 | Integrity | mitigate | `server/db.py:11` `_DB_PATH_OVERRIDE` 模块级进程内覆盖；`:14-17` `set_db_path(None)` 复位；`:20-22` `_resolve_db_path()` 取 override or DB_PATH（不落盘、不改 env） |
| T-06-04 | Tampering | mitigate | `server/conftest.py:15-17` `os.environ.setdefault` 三件套（不覆盖已设值）+ `tempfile.mkdtemp(prefix="gsd-test-")` 临时库，不触碰 data/app.db |
| T-06-SC | Tampering | accept | 本计划零新包（仅 stdlib `sqlite3`/`tempfile`/`re`），无供应链风险面 |

### 06-02（CI / requirements）

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-06-05 | Tampering | mitigate | `.github/workflows/ci.yml:13-24` backend 走 `pip install -r server/requirements.txt`、frontend 走 `npm ci`（`web/package-lock.json` 存在），依赖锁定 |
| T-06-06 | Info Disclosure | mitigate | `.github/workflows/ci.yml` 无任何 `env` secret 注入；测试走 06-01 conftest mock 三件套（`server/conftest.py:15-17`） |
| T-06-SC | Tampering | mitigate | `.github/workflows/ci.yml:13-24` `pip install -r`/`npm ci` 走 requirements/lockfile；`server/requirements.txt:11` 新增 `pytest>=8`（官方测试框架，无 SLOP 风险） |

### 06-03（M1 回归 / §31-4 占位 / 13 文件双列）

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-06-07 | Tampering | mitigate | `server/config.py:84-85` `DICT_MATCH_THRESHOLD = None`、`TITLE_CLEAN_WORDS: list[str] = []`，两行均含 `# 实施期校准 — 待用户裁决`（不臆造默认值，红线兑现） |
| T-06-08 | Tampering | mitigate | 13 个会话类测试文件（m5/m6/m7/p0_chain/p0_security/phase2_difficulty/interview/scoring/phase3_forms/sse/timer/idempotency/misc）的 `INSERT INTO question_bank` 列清单均补 `model_id` + `model_version`（逐文件 grep 命中） |
| T-06-09 | Repudiation | mitigate | `server/test_m1_regression.py:14-16` 模块 docstring 记档 mock interviewer `_mock_score` 恒返 score=3（b 方差恒 0 / c 靠客观题区分）的已知局限，防误读 |
| T-06-SC | Tampering | accept | 本计划零新包（纯测试文件 + config 占位），无供应链风险面 |

### 06-04（E2E / get_session / submit-v2）

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-06-10 | Elevation | mitigate | `server/api/assessment.py:146` get_session 首行 `load_owned_session(conn, session_id, user)`；`server/core/security.py:63-81` 按 `session_id AND user_id` 归属加载，非 owner 返回 404（D-01 统一不存在）；`server/test_e2e_full_chain.py:293-296` 断言跨用户 404 + 非管理员 403 |
| T-06-11 | Tampering | mitigate | 服务端：`server/schemas.py:118-124` `FormSubmitRequest` 校验 `form_instance_id`(min_length=1) + `expected_revision`(ge=1) + `payload`；`server/api/assessment.py:950-958` 幂等前置 `check_idempotency` + `validate_and_submit(..., form_instance_id, payload, expected_revision)`。前端：`web/src/api/index.js:47-51` `submitForm` 打 `submit-v2`；`web/src/components/FormCard.vue:110` 新签名 `submitForm(sessionId, formId, {...model}, expectedRevision)` |
| T-06-12 | Info Disclosure | mitigate | `server/api/assessment.py:201-205` messages 查询 `WHERE session_id=?`，且在 `load_owned_session`（`:146`）校验之后，仅返回当前登录用户自己的 session |
| T-06-SC | Tampering | accept | 本计划零新包（`web/package.json`/`package-lock.json` 无变更，git status 干净），无供应链风险面 |

### 06-05（eval 隔离 / bad case / 输入限额 / secret）

| Threat ID | Category | Disposition | Evidence |
|-----------|----------|-------------|----------|
| T-06-13 | Tampering | mitigate | `eval/consistency_test.py:24-44` 与 `eval/virtual_candidates.py:32-52` `_run_isolated`：业务库 `src.backup(dst)` 只读快照到 `gsd-eval-` 临时库 → `set_db_path(tmp)` → `finally: set_db_path(None)`；`server/api/admin/eval.py:56-66` `_run` 同样 `set_db_path(_build_temp_db())` → `finally` 复位 → `_save_result`（复位后经业务库连接）写回 eval_results |
| T-06-14 | Tampering | mitigate | `server/services/report.py:161-198` `_detect_bad_case_divergence` 仅 `INSERT INTO bad_case_candidate`（status='pending'），只 SELECT question_score、永不 UPDATE score（D-031）；`config.BAD_CASE_DIVERGENCE_THRESHOLD is None` 时 `:170-171` 直接 return 0 |
| T-06-15 | DoS | mitigate | 限额常量集中 `server/config.py:71-73`（MAX_JD_LENGTH/MAX_JD_FILE_LINES/MAX_PAGINATION_LIMIT 均 None 占位）；`server/services/input_limits.py:10-23` 校验纯函数在 None 时放行（未决值不生效）；已决值沿用 `server/services/scoring.py:39` MAX_ANSWER_LEN=64*1024（`:58` 截断生效）、`server/config.py:59` MAX_CONTEXT_TOKENS=8000（`services/interview.py:236` 生效） |
| T-06-16 | Info Disclosure | mitigate | `server/main.py:16` `_INSECURE_JWT_DEFAULTS = {"", "change-me-in-.env"}`；`:63-66` `_startup` 命中默认值即 `raise RuntimeError`（fail-closed-always，严于 D-77）；`server/test_secret_gate.py` 锁定默认值 raise + test-secret 放行 |
| T-06-SC | Tampering | accept | 本计划零新包（eval 脚本 + db/report/config + 测试），无供应链风险面 |

## Accepted Risks（已接受风险，核验准确）

以下 4 条 T-06-SC 均为 `accept`（「本计划零新包」），核验确认表述准确——各计划仅新增/修改测试文件、config 占位常量、前端接线与 eval 脚本，唯一新依赖 `pytest>=8` 归属 06-02（其 T-06-SC 为 `mitigate`，已走 requirements.txt 锁定）：

| Threat ID | 计划 | 接受内容 | 核验 |
|-----------|------|----------|------|
| T-06-SC | 06-01 | 零新包（stdlib sqlite3 conn.backup） | `server/requirements.txt` 无新增；`web/package.json` 无变更 |
| T-06-SC | 06-03 | 零新包 | 同上 |
| T-06-SC | 06-04 | 零新包（不引新依赖） | `web/package.json`/`package-lock.json` git status 干净 |
| T-06-SC | 06-05 | 零新包 | 同上 |

## 观察项（不阻塞，非威胁缺口）

1. **T-06-15 接口层接线延后（文档化 defer）**：`server/services/input_limits.py` 的 `validate_jd_length`/`clamp_pagination_limit` 目前仅被 `test_input_limits.py` 引用，尚未接线到任何 API 端点（code-review WR-02 记档「死代码，按设计」）。因限额值全部为 None 占位（[06-009] 用户裁决「维持占位默认」），校验函数 None 时放行，接线留待用户裁决限额值后进行——与缓解计划「未决值占位不生效」一致，属有意 defer 而非遗漏。
2. **T-06-10 越权状态码口径**：威胁模型写「断言 401/403」，实现为跨用户读 session 返回 **404**（`core/security.py:64` D-01 统一「不存在」，避免泄露 session 存在性，严于 403）+ 非管理员访问 admin 路由 403（`test_e2e_full_chain.py:293-296`）。拒绝语义完全落地，仅状态码措辞与威胁模型略有偏差。
3. **JWT 方向锁定（REF-6.1，非威胁寄存器条目）**：`06-05` Task 0 决议 D-76 = jwt-cookie-migrate（方向锁定，实际迁移为 Phase 6 外后续计划）。核验确认本期未迁移：`web/src/utils/sse.js:25` 仍 `Authorization: Bearer localStorage`；`server/api/auth.py`/`server/core/security.py` 无 Set-Cookie/HttpOnly 代码（git log 显示这些文件最近改动在 Phase 1，非 Phase 6）。Bearer + localStorage 的 XSS 暴露面为已登记、已定向但未迁移的既有风险，非本期新攻击面。
4. **WR-01 备份文件名含 `:`/`+`**（`datetime.now(timezone.utc).isoformat()`）：Windows NTFS 下崩溃的移植性隐患，本机 macOS 不受影响，code-review 已记 defer；不削弱 T-06-01 备份缓解本身（备份实际产生）。
