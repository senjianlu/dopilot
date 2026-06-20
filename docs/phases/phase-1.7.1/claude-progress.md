# Phase 1.7.1 · Claude progress log

Started: 2026-06-20.

## Estimated duration

Large packet (backend schema/API/service + 5 frontend pages + tests). Rough
estimate 1 working session of focused implementation. Update cadence: at each
of the 7 ordered checkpoints below.

## Likely long-running commands

- `corepack pnpm --filter web build` (Vite/vue-tsc build).
- `corepack pnpm --filter web test` (vitest).
- `pytest apps/server/tests packages/protocol/tests`.
- `ruff check apps packages`.

## Checkpoints

1. [done] Read brief + feasibility + all relevant code paths (server + web).
2. [done] Backend node scheduling-state + soft-delete migration/API/service.
3. [done] Backend dispatch selection excludes offline/deleted nodes.
4. [done] Backend execution pagination + spider filter + aggregate child counts.
5. [done] Backend dashboard stats + schedule next_run_at metadata.
6. [done] Frontend API/types/i18n updates.
7. [done] Frontend page updates (Nodes/Templates/Schedules/Executions/Dashboard).
8. [done] Tests added/updated + required commands run.

## Notes / decisions as they happen

- Node soft-delete + offline are separate columns: `scheduling_enabled`
  (+`scheduling_disabled_at`) and `deleted_at`. Health (`status`) stays an
  independent heartbeat-derived field; offline/deleted are scheduling states.
- Heartbeat upsert intentionally does NOT touch `deleted_at` /
  `scheduling_enabled`, so deleted nodes never resurrect and offline nodes keep
  reporting health.
- Spider filter uses a new task-level `tasks.spider` column populated at task
  creation from parsed Scrapy params; queryable + indexed.
- Schedule `next_run_at` computed from the trigger + now (interval = estimate,
  cron = APScheduler CronTrigger). A `POST /schedules/preview-next-run` endpoint
  backs the create-dialog estimate (works for cron too).
- 30-day stats bucket parent tasks + child executions per calendar day in the
  scheduler timezone; native SVG bar chart on the frontend (no chart dep).

## Final command outcomes

- `.venv/bin/pytest apps/server/tests -q -p no:cacheprovider` -> 192 passed.
- `.venv/bin/pytest packages/protocol/tests -q -p no:cacheprovider` -> 29 passed.
- `.venv/bin/ruff check apps packages` -> All checks passed (9 W292/import
  findings from the editing pass were auto-fixed with `--fix`).
- `corepack pnpm --filter web test` -> 8 files, 22 tests passed.
- `corepack pnpm --filter web build` -> built successfully (vue-tsc + vite).

Note: the combined `pytest apps/server/tests packages/protocol/tests` form is
not in the sandbox allowlist, so the two suites were run separately (same
coverage): 192 + 29 = 221 passed.</invoke>
