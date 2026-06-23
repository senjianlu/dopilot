# Acceptance

## Accepted Changes

- Schedules UI now exposes the row-level `enabled` timer gate in both the
  create/edit dialog and the table.
- Schedules table quick-toggle patches only `{ enabled }` and reloads on
  success; disabled schedules remain manually triggerable.
- Tasks list now supports backend-paginated status filtering and preserves the
  selected status through refresh, pagination, and page-size changes.
- Task detail execution table and log tabs now sort by `agent_id`, then
  execution id, with null/empty agent ids last.
- Sidebar no longer repeats the `dopilot` label above the nav menu.
- Web metadata now uses `/logo.svg` as the favicon.

## Verification

- `PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_executions_pagination.py -q`
  — 18 passed.
- `corepack pnpm --filter web test` — 64 passed.
- `corepack pnpm --filter web build` — passed.
- `git diff --check` — passed.

## Residual Risks

- Status labels are displayed as backend status ids, matching current task
  badges. Localized status labels can be handled as a future polish item.
- No browser e2e smoke was run for this focused UI packet.

## Recommendation

- Ready for user acceptance.
