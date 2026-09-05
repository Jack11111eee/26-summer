# Deferred Items — Phase 03-sse

Out-of-scope discoveries logged during plan execution (not fixed — pre-existing / test-isolation issues unrelated to plan 03-01 changes).

## 1. test_phase2_migration.py — full-suite isolation failure

- **Symptom:** `IndexError` when run in the full `pytest server/` suite.
- **Standalone result:** passes (8 passed) when run alone.
- **Root cause:** "single file single process" test discipline — this file is not isolated from sibling test files' in-process DB state. Not caused by plan 03-01 changes.
- **Deferred to:** test-harness maintenance, not in plan 03-01 scope.

## 2. test_question_bank.py — pre-existing setup failure

- **Symptom:** `sqlite3.OperationalError: no such table: user` (also standalone).
- **Root cause:** test file does not call `init_db()` before touching the `user` table — pre-existing setup gap, unrelated to any file touched by plan 03-01.
- **Deferred to:** test-harness maintenance, not in plan 03-01 scope.
