# Web UI Follow-ups Brief

## Goal

Address five operator-facing UI gaps found after phase 2.2 / phase 2b:

- expose the row-level `schedules.enabled` timer gate in the Schedules UI;
- add a task status filter to the Tasks list;
- make task-detail log execution tabs deterministic by sorting by `agent_id`;
- remove the duplicate small `dopilot` label above the Sidebar menu;
- set the web favicon to the existing `logo.svg`.

## Context

Read before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-2.2/00-brief.md`
- `docs/phases/task-execution-log-selection/00-brief.md`
- shadcn Switch docs already checked by Codex:
  - `npx shadcn@latest info --json`
  - `npx shadcn@latest docs switch`

Relevant code:

- `apps/web/app/(app)/schedules/page.tsx`
- `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx`
- `apps/web/lib/api/schedules.ts`
- `apps/web/lib/api/types.ts`
- `apps/web/app/(app)/tasks/page.tsx`
- `apps/web/app/(app)/tasks/detail/page.tsx`
- `apps/web/app/(app)/tasks/__tests__/tasks.test.tsx`
- `apps/web/app/(app)/tasks/__tests__/task-detail.test.tsx`
- `apps/web/lib/api/tasks.ts`
- `apps/web/lib/i18n/locales/en.ts`
- `apps/web/lib/i18n/locales/zh.ts`
- `apps/web/components/layout/app-sidebar.tsx`
- `apps/web/app/layout.tsx`
- `apps/web/public/logo.svg`
- `apps/server/dopilot_server/api/v1/tasks.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/services/states.py`
- `apps/server/tests/test_executions_pagination.py`

## Architecture Constraints

- Do not fetch, vendor, copy, or import upstream scrapydweb code.
- Preserve the single-admin / single-server architecture.
- Keep schedule enable/disable on the existing `PUT /api/v1/schedules/{id}`
  endpoint; do not add `/enable` or `/disable` convenience endpoints.
- The task status filter must be a backend query filter, not client-side
  filtering of the current page, because task listing is backend-paginated.
- Use the existing shadcn `Switch` component from `apps/web/components/ui`.
- Keep changes scoped to UI/API typing and the narrow task-list query filter.

## In Scope

### Schedules UI

- Add `enabled` to the web `Schedule` and `CreateScheduleRequest` types.
- In the schedule create/edit dialog, add a `Switch` field for enabling timer
  firing.
- The create dialog should default to disabled, matching the backend.
- The edit dialog should prefill from the schedule row.
- Include `enabled` in create/update payloads.
- Add a table column showing enabled state with a compact `Switch` for quick
  enable/disable.
- Toggling from the table calls `updateSchedule(id, { enabled: next })`, reloads
  the table on success, and leaves `trigger-now` behavior unchanged.
- Prevent duplicate toggle submissions for the same row with a local pending id.

### Tasks Status Filter

- Add an optional `status` query param to `GET /api/v1/tasks`.
- Validate the status against known task statuses from
  `dopilot_server.services.states`. Use `TASK_ACTIVE | TASK_TERMINAL`, or add a
  derived `TASK_STATUSES` constant there and use it from the API/service.
  Invalid values should return 400 with a clear `task.invalid_status` code.
- Apply `status` together with existing `build_artifact_id` and legacy `spider`
  filters.
- Add `status?: TaskStatus | null` to `ListTasksParams` and include it in the web
  request query.
- Add a Tasks page status `Select` with an `All statuses` sentinel plus:
  `queued`, `running`, `finalizing`, `complete`, `failed`, `canceled`, `lost`,
  `no_target`.
- Changing either build-artifact or status filter should reset to page 1.
- Refresh, pagination, and page-size changes must preserve both filters.

### Task Detail Log Tab Ordering

- On the task detail page, sort executions only for display/log tab selection by
  `agent_id` ascending, then `id` ascending as a null/duplicate tie-breaker.
- Executions with null/empty `agent_id` sort after executions with an agent id,
  then by `id`.
- Use the same sorted order for the executions table, the default selected
  execution, and the log tab list.
- Do not mutate the API response object.

### Sidebar

- Remove the duplicate `SidebarGroupLabel` that renders `common.appName` above
  the nav menu. Keep the brand header with logo + app name.

### Favicon

- Set the Next.js metadata icon to `/logo.svg` in `apps/web/app/layout.tsx`
  using `metadata.icons`; do not also add a duplicate `app/icon.svg`.
- Reuse `apps/web/public/logo.svg`; do not introduce a new logo design.

## Out Of Scope

- Backend schedule API changes.
- New schedule enable/disable endpoints.
- Database migrations.
- Any agent, Redis protocol, executor, log consumer, or auth behavior changes.
- Reworking table layout beyond what is needed for the requested controls.
- Broad visual redesign.

## Acceptance Criteria

- A newly created schedule from the web remains disabled unless the modal switch
  is turned on.
- Editing a schedule preserves and updates its enabled state.
- The schedules table shows enabled state and can quickly enable/disable a row.
- Disabled schedules remain manually triggerable via the existing Trigger now
  action.
- Tasks can be filtered by status, with pagination totals reflecting the backend
  filtered result.
- Task status filtering composes with build-artifact filtering.
- Task detail execution/log selector order is stable by `agent_id`.
- Sidebar no longer shows the extra `dopilot` group label above menu items.
- The built web app advertises `/logo.svg` as the favicon.

## Required Tests

- Web unit tests:
  - schedules page renders and submits `enabled`, pre-fills edit state, and quick
    toggles a row through `updateSchedule`;
  - tasks page sends `status` in `listTasks` params and preserves it across
    refresh/pagination/page-size changes;
  - task detail orders log tabs/executions by `agent_id`.
- Server tests:
  - task list service filters by status and combines it with existing filters;
  - `GET /api/v1/tasks?status=<valid>` returns filtered rows;
  - `GET /api/v1/tasks?status=<invalid>` returns 400.
- Build verification:
  - web unit tests pass;
  - focused server tests pass, including the HTTP invalid-status case;
  - web build passes.

## Required Commands

```bash
.venv/bin/python -m pytest apps/server/tests/test_executions_pagination.py -q
corepack pnpm --filter web test
corepack pnpm --filter web build
```
