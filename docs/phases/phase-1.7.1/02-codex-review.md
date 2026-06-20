# 02 · Codex review

Date: 2026-06-20

## Findings

### Blocking

1. Existing tasks are not backfilled into the new spider filter.

`apps/server/migrations/versions/0006_node_state_task_spider.py` adds
`tasks.spider`, but it never populates the column from existing `tasks.params`.
Any task created before the migration keeps `spider = NULL`, so
`GET /executions?spider=...` silently misses existing execution history. The
brief requires execution records to support spider filtering, and this is
especially visible immediately after upgrading from accepted Phase 1.7 data.

2. Dashboard daily stats loads the whole 30-day window into Python.

`apps/server/dopilot_server/services/stats.py` selects every task/execution
`created_at` since the cutoff and then buckets in Python. The user explicitly
called out tens of thousands of history rows per day; this dashboard endpoint
should not transfer hundreds of thousands or millions of timestamps per refresh.
Use database-side grouping for PostgreSQL and keep a SQLite-compatible fallback
or test path.

3. Template node selector allows configured-but-unseen nodes with `id == null`.

`apps/web/src/pages/TemplatesPage.vue` treats non-deleted, scheduling-enabled
nodes as selectable/schedulable even when `id == null`. Those rows are
configured-but-unseen endpoints and cannot be matched by backend selected-node
resolution, which matches only DB `id` or `agent_id`. A selected template could
persist an endpoint value that never dispatches, producing surprising
`no_target`. Exclude `id == null` rows from selectable and involved-node sets.

### Non-Blocking

4. Implementation report test-command note is stale.

Claude's report says the combined
`pytest apps/server/tests packages/protocol/tests` form could not run due to an
allowlist. Codex re-ran that exact command locally and it passed. Update the
report or add a review-response note so the final acceptance record is accurate.

## Verification Run By Codex

Passed:

- `.venv/bin/pytest apps/server/tests packages/protocol/tests` -> 221 passed.
- `.venv/bin/ruff check apps packages` -> all checks passed.
- `corepack pnpm --filter web test` -> 8 files / 22 tests passed.
- `corepack pnpm --filter web build` -> passed.
- `git diff --check` -> passed.

Warnings observed:

- Vue tests emit `Failed to resolve directive: loading` warnings from Element
  Plus directive stubs. Existing test style allows these warnings; they did not
  fail the suite.
- Vite build emits the existing large-chunk warning.

## Required Response

Ask Claude to fix the three blocking findings, add/adjust focused tests, and
write `03-claude-review-response.md` with exact changes and verification.
