# Codex Review: Phase 2a ID Naming Clean-Cut

## Scope Reviewed

- Brief: `docs/phases/phase-2a/00-brief.md`
- Claude report: `docs/phases/phase-2a/01-claude-implementation-report.md`
- Diff areas:
  - protocol schemas/tests under `packages/protocol/`
  - server models, migration, services, Redis, logs, API comments, and tests
  - agent state, Redis, runner, artifact cache, and tests

## Findings

### P0 / Blocking

- None.

### P1 / Must Fix

- None.

### P2 / Should Fix

- None.

## Review Notes

- The old seam fields were removed from non-migration source and tests:
  `rg -n 'attempt_id' apps packages` now matches only historical migrations and
  `0009`, where the old name is required for upgrade/downgrade DDL.
- Public HTTP/web behavior did not drift. `api/v1/tasks.py` and
  `api/v1/schemas.py` changed comments only; `apps/web/**` and
  `apps/server/tests/test_sse.py` were not edited.
- Legacy schema deletion is scoped correctly: `AgentStopRequest`,
  `CleanupResponse`, `TailRequest`, and `TailResponse` are gone; live schemas
  with seam fields were renamed. `AgentRunResponse` and `ScrapydRunner.run()`
  were kept because current runner tests still cover that method.
- Alembic migration `0009_id_naming_clean_cut.py` is additive, uses
  `down_revision = "0008"`, and does not edit older migrations.
- The running compose db container used for review verification was stopped
  after checks. The named database volume remains at head `0009`.

## Verification Re-run By Codex

```bash
.venv/bin/ruff check apps packages
.venv/bin/pytest packages/protocol/tests -q -p no:cacheprovider
.venv/bin/pytest apps/agent/tests -q -p no:cacheprovider
.venv/bin/pytest apps/server/tests -q -p no:cacheprovider
git diff --check
cd deploy/docker && docker compose config
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot ../../.venv/bin/alembic downgrade -1
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot ../../.venv/bin/alembic upgrade head
```

Results:

- `ruff`: passed.
- protocol tests: 65 passed.
- agent tests: 83 passed.
- server tests: 231 passed.
- `git diff --check`: passed.
- `docker compose config`: passed.
- Alembic `0009 -> 0008 -> 0009` round-trip against compose PostgreSQL: passed.
- PostgreSQL schema check after upgrade:
  - `command_outbox`: `task_id`, `execution_id`; no `attempt_id`.
  - `event_audit`: `execution_id`; no `attempt_id`.
  - `execution_log_files`: `task_id`, `execution_id`; no `attempt_id`.
  - indexes present: `ix_command_outbox_task_id`,
    `ix_command_outbox_execution_id`, `ix_event_audit_execution_id`.

## Test Gaps

- None requiring Claude follow-up. Phase 2a does not run a full compose smoke
  because the behavior under change is covered by protocol/server/agent suites
  plus the PostgreSQL migration round-trip.

## Architecture / Docs Gaps

- Phase 2a keeps `AttemptState` and `AttemptStatus` names because they describe
  the agent lifecycle/status concept and renaming them would be a wider internal
  naming cleanup. The persisted ids and wire fields are already unified.
- Phase 2b should decide whether to delete `ScrapydRunner.run()` and
  `AgentRunResponse`; phase 2a keeps them because current tests exercise the
  method.

## Required Claude Follow-Up

None.
