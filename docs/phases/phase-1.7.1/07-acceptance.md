# 07 · Phase 1.7.1 acceptance

Date: 2026-06-20

## Decision

Phase 1.7.1 is accepted by Codex review.

## Accepted Scope

- Dashboard service health now renders Server/Agent/Redis/PostgreSQL as a
  three-column table with breathing status lights and notes.
- Dashboard includes a native SVG daily bar chart for recent task/execution
  counts, backed by `GET /api/v1/stats/tasks/daily`.
- Nodes support reversible offline/online scheduling state.
- Nodes support soft delete. Deleted nodes remain available for historical
  display but are excluded from scheduling.
- Node health and scheduling state are separate: offline/deleted nodes can still
  receive heartbeat and show real health.
- Node refresh reuses `GET /nodes`; the removed `POST /nodes/refresh` path is
  not reintroduced.
- Dispatch target selection excludes offline/deleted nodes.
- Execution list uses backend pagination with allowed page sizes
  `5, 10, 20, 50, 100`.
- Execution list supports spider filtering via an indexed `tasks.spider` column.
- Migration `0006` backfills `tasks.spider` from existing `tasks.params`.
- Template creation removes the user-facing Project input and derives
  project/version/spider from the selected artifact.
- Template involved-node selector follows badge/eligibility rules and excludes
  offline/deleted/unseen nodes from new selection.
- Schedules display trigger time and next-run metadata; create dialog shows a
  read-only next-run estimate.

## Final Verification

Passed:

- `.venv/bin/pytest apps/server/tests packages/protocol/tests` -> 222 passed.
- `.venv/bin/ruff check apps packages` -> all checks passed.
- `corepack pnpm --filter web test` -> 8 files / 22 tests passed.
- `corepack pnpm --filter web build` -> passed.
- `git diff --check` -> passed.
- Alembic offline SQL to head -> passed through `0006`.

## Residual Risks

- Alembic `0006` was validated by offline PostgreSQL SQL generation, not by
  applying against a live PostgreSQL database in this session.
- The schedule `next_run_at` for interval schedules is an estimate from current
  time, not persisted APScheduler last-fire state.
- Web test output still includes Element Plus `v-loading` directive warnings
  from test stubs; tests pass.
- Vite reports the existing large bundle chunk warning.

## Recommendation

Ready for human acceptance, with live PostgreSQL migration smoke as the main
remaining operational check before deployment.
