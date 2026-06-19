# 03 · Codex review（Phase 1.7 packet 1）

## Findings

No unresolved blocking findings remain.

Codex found and fixed two review issues after Claude returned:

- Frontend build failure: `ExecutionStatus` added `no_target`, but
  `ExecutionDetailPage.vue` and `ExecutionsPage.vue` did not include
  `no_target` in their `Record<ExecutionStatus, tagType>` maps. Added
  `no_target: "warning"`.
- Alembic offline SQL generated invalid PostgreSQL syntax for column rename
  (`RENAME execution_id TO task_id`). Replaced Alembic `alter_column(...,
  new_column_name=...)` with explicit `ALTER TABLE ... RENAME COLUMN ...`
  statements in `0004_task_execution_rename.py`.

## Review Notes

- Redis/disk/agent seam is preserved: protocol fields still mean
  `execution_id=task id` and `attempt_id=atomic execution id`.
- No `apps/agent/**` files were changed.
- Public Web/API vocabulary remains the old `/executions` + `attempts[]` seam
  for packet 1. This is documented as a temporary public seam and is acceptable
  for this packet, because templates/schedules/public clean-cut are later
  packets.
- `no_target` support is schema/state-machine only in packet 1. The zero-node
  creation path still raises 409 and is intentionally deferred.

## Verification

Commands run by Codex:

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
DOPILOT_DATABASE_URL='postgresql+psycopg://user:pass@localhost/dopilot' \
  ../../.venv/bin/alembic -c alembic.ini upgrade head --sql
```

Results:

- `pytest`: 167 passed.
- `ruff`: all checks passed.
- `web test`: 5 test files / 7 tests passed.
- `web build`: passed. Vite emitted existing chunk-size and Rollup pure-comment
  warnings from dependencies.
- Alembic offline SQL to head: passed; 0004 emits valid
  `ALTER TABLE executions RENAME COLUMN execution_id TO task_id`.

## Residual Risk

- A live PostgreSQL migration was not run against a real database in this review;
  offline SQL generation passed.
- Compose smoke was not run because packet 1 is a domain rename without Docker
  runtime behavior changes. Later packets that touch templates/schedules should
  run compose smoke when end-to-end behavior is available.
