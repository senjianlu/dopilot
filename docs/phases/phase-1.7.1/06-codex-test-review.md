# 06 · Codex test review

Date: 2026-06-20

## Final Commands

Passed:

- `.venv/bin/pytest apps/server/tests packages/protocol/tests` -> 222 passed.
- `.venv/bin/ruff check apps packages` -> all checks passed.
- `corepack pnpm --filter web test` -> 8 files / 22 tests passed.
- `corepack pnpm --filter web build` -> passed.
- `git diff --check` -> passed.
- Alembic offline SQL:
  `cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot ../../.venv/bin/alembic -c alembic.ini upgrade head --sql`
  -> passed.

The offline SQL includes:

```sql
ALTER TABLE tasks ADD COLUMN spider VARCHAR;
UPDATE tasks SET spider = params ->> 'spider'
WHERE spider IS NULL AND params ->> 'spider' IS NOT NULL;
CREATE INDEX ix_tasks_spider ON tasks (spider);
```

## Review Findings Rechecked

- Existing task history is backfilled into `tasks.spider` during `0006`.
- Dashboard stats now aggregates with SQL `GROUP BY` instead of streaming every
  timestamp to Python.
- Template involved-node selector excludes configured-but-unseen rows with
  `id == null`.
- The stale implementation-report statement about combined pytest is corrected
  by `03-claude-review-response.md` and by this Codex test review.

## Warnings / Residual Risk

- Vue tests emit `Failed to resolve directive: loading` warnings from Element
  Plus directive stubs. The suite passes; these are test-harness noise.
- Vite emits the existing chunk-size warning for the web bundle.
- Alembic was validated by offline PostgreSQL SQL generation, not by applying to
  a live PostgreSQL instance in this session.

## Decision

No unresolved blocking test gaps remain.
