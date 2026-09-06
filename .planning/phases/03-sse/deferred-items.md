# Deferred Items — Phase 03-sse

Out-of-scope discoveries logged during plan execution (not fixed — pre-existing / test-isolation issues unrelated to plan 03-01 changes).

> **2026-09-06 收口复核：本文件两个条目均已闭合**（06-01 conftest 统一注入 mock 三件套 + session 级临时 DB fixture，D-69）。复核命令 `cd server && python -m pytest test_phase2_migration.py test_question_bank.py -q` → **9 passed**；全量回归 236 passed（见 STATE.md）。

## 1. test_phase2_migration.py — full-suite isolation failure — **✅ CLOSED**

- **Symptom:** `IndexError` when run in the full `pytest server/` suite.
- **Standalone result:** passes (8 passed) when run alone.
- **Root cause:** "single file single process" test discipline — this file is not isolated from sibling test files' in-process DB state. Not caused by plan 03-01 changes.
- **Deferred to:** test-harness maintenance, not in plan 03-01 scope.
- **Closure（2026-09-06）:** 06-01 `server/conftest.py`（mock 三件套 env setdefault + session 级 `_session_db` fixture 统一临时库）收口，全量回归不再复现（236 passed）。

## 2. test_question_bank.py — pre-existing setup failure — **✅ CLOSED**

- **Symptom:** `sqlite3.OperationalError: no such table: user` (also standalone).
- **Root cause:** test file does not call `init_db()` before touching the `user` table — pre-existing setup gap, unrelated to any file touched by plan 03-01.
- **Deferred to:** test-harness maintenance, not in plan 03-01 scope.
- **Closure（2026-09-06）:** 同上（06-01 conftest — session 级 autouse fixture 显式 `init_db()`，TestClient 跳过 startup 也已有建表）；单独跑 + 全量均绿。
