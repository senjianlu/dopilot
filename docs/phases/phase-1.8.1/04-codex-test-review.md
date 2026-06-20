# Phase 1.8.1 Codex Test Review

## Result

After Claude's review fixes, Codex reran the narrow verification suite and it
passed. Codex then broadened to the repository Python suite because phase 1.8.1
changes protocol, server, agent, and scheduling contracts.

## Failing Command

```text
.venv/bin/pytest
```

Result:

```text
367 passed, 1 failed
FAILED apps/server/tests/test_executions_pagination.py::test_get_tasks_spider_filter
```

Failure:

```text
AssertionError: {"code":"command.unknown_spider","message_key":"errors.unknownSpider","detail":{"spider":"alpha","spiders":["phase1"]}}
assert 400 == 200
```

## Finding

`P1` The pagination HTTP test helper still creates an artifact with the default
spider list (`["phase1"]`) while trying to create templates for arbitrary
spiders (`alpha`, `beta`).

- `apps/server/tests/test_executions_pagination.py:14`
- `apps/server/tests/test_executions_pagination.py:120`

The implementation behavior is correct: server-side artifact spider membership
now rejects commands whose spider is not exposed by the bound artifact. The test
seed data should be updated so the artifact used by `_run_artifact(..., spider)`
advertises that spider.

## Required Fix

Update the test helper or call sites so the seeded build artifact includes the
requested spider. Then rerun:

```bash
.venv/bin/pytest
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check apps packages
```
