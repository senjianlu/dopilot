# Claude Implementation Report — task-web-ui-followups

Implements the five operator-facing UI follow-ups plus the narrow task-list
status query filter described in `00-brief.md`.

## Changed Files By Area

### Server (tasks status filter)

- `apps/server/dopilot_server/services/states.py`
  - Added `TASK_STATUSES = TASK_ACTIVE | TASK_TERMINAL` (derived constant) to back
    status-filter validation.
- `apps/server/dopilot_server/services/executions.py`
  - `list_tasks_page(...)` gained an optional `status` kwarg; when supplied it
    ANDs `Task.status == status` into both the page query and the count query
    (composes with `build_artifact_id` and the legacy `spider` filter).
- `apps/server/dopilot_server/api/v1/tasks.py`
  - `GET /api/v1/tasks` accepts `status: str | None`. An unknown value raises a
    400 `ApiError(code="task.invalid_status", message_key="errors.invalidStatus")`
    with the allowed set in `detail`; a valid value is passed through to
    `svc.list_tasks_page(status=...)`.
- `apps/server/tests/test_executions_pagination.py` — tests (see below).

### Web (typing + API client)

- `apps/web/lib/api/types.ts`
  - `Schedule` now requires `enabled: boolean`.
  - `CreateScheduleRequest` now has optional `enabled?: boolean`.
  - `ListTasksParams` now has optional `status?: TaskStatus | null`.
- `apps/web/lib/api/tasks.ts`
  - `listTasks` includes `status` in the request query when set.

### Web (Schedules UI)

- `apps/web/app/(app)/schedules/page.tsx`
  - Added an `enabled` dialog field using the existing shadcn `Switch`
    (`schedule-enabled-input`). Create defaults to disabled; edit prefills from
    the row. `enabled` is included in the create/update payload.
  - Added an `Enabled` table column with a compact `Switch`
    (`schedule-enabled-<name>`) for quick enable/disable. Toggling calls
    `updateSchedule(id, { enabled: next })` and reloads on success (no optimistic
    UI). A local `togglingId` pending id blocks duplicate submits for the same
    row. Empty-row `colSpan` bumped 6 → 7. `trigger-now` behavior unchanged.

### Web (Tasks status filter)

- `apps/web/app/(app)/tasks/page.tsx`
  - Added a status `Select` (`tasks-status-filter`) with an `All statuses`
    sentinel plus `queued, running, finalizing, complete, failed, canceled, lost,
    no_target`. The `load(...)` signature now threads a `statusFilterValue`.
    Changing the status (or build-artifact) filter resets to page 1; refresh,
    prev/next pagination, and page-size changes preserve both filters.

### Web (Task detail log/exec ordering)

- `apps/web/app/(app)/tasks/detail/page.tsx`
  - Added a pure `sortedExecutions(...)` helper that sorts a COPY by `agent_id`
    ascending, then `id` ascending, with null/empty `agent_id` pinned last. The
    sorted memo backs the executions table, the default selected execution, and
    the log tab list. The API response object is never mutated.

### Web (Sidebar + favicon)

- `apps/web/components/layout/app-sidebar.tsx`
  - Removed the duplicate `SidebarGroupLabel` ("dopilot") above the nav menu and
    its now-unused import. The brand header (logo + app name) is unchanged.
- `apps/web/app/layout.tsx`
  - Added `metadata.icons = { icon: "/logo.svg" }` (reuses the committed brand
    asset; no separate `app/icon.svg`, no new logo).

### Web (i18n)

- `apps/web/lib/i18n/locales/en.ts`, `apps/web/lib/i18n/locales/zh.ts`
  - Added `schedules.enabled` ("Enabled" / "启用") and `tasks.statusAll`
    ("All statuses" / "全部状态").

## Implementation Notes

- The backend schedule schemas (`ScheduleView`, `ScheduleCreateRequest`,
  `ScheduleUpdateRequest`) already carried `enabled` from phase 2.2, and the
  `PUT /schedules/{id}` route already uses `model_dump(exclude_unset=True)`. So
  the quick-toggle that sends only `{ enabled: next }` patches just that field —
  no backend schedule changes were needed (and none are in scope).
- Status validation is driven from `states.TASK_STATUSES` so the API and any
  future caller share one source of truth; the filter is applied in SQL (backend
  pagination), never client-side over the current page.
- The task-detail sort is display-only; backend log/SSE execution resolution
  (`resolve_execution`, `primary_execution`) is untouched, so log selection still
  resolves by id.

## Tests Added / Updated

### Web

- `schedules.test.tsx`
  - Added `enabled: false` to the `Schedule` fixture; updated the existing edit
    assertion to include `enabled: false` in the update payload.
  - New: creates with `enabled: true` when the modal switch is on; pre-fills the
    edit dialog switch from an enabled schedule; quick-toggles a row through
    `updateSchedule(id, { enabled: true })` and reloads on success.
- `tasks.test.tsx`
  - New `TasksPage status filter` suite: first load sends `status: null`;
    selecting a status calls `listTasks` with `{ page: 1, status }`; status is
    preserved across refresh, next-page, and page-size changes.
- `task-detail.test.tsx`
  - New: executions/log tabs order by `agent_id`, then `id`, with null-agent
    execution last; default selection is the first sorted execution.

### Server

- `test_executions_pagination.py`
  - `test_list_tasks_page_status_filter` — service filters by status.
  - `test_list_tasks_page_status_combines_with_build_artifact` — status ANDs with
    the build-artifact filter.
  - `test_get_tasks_status_filter` — `GET /tasks?status=complete` returns only
    matching rows; a non-matching status returns an empty 200 page.
  - `test_get_tasks_invalid_status_400` — `GET /tasks?status=bogus` → 400 with
    code `task.invalid_status`.

## Commands Run

- `corepack pnpm --filter web test` — **PASS**. 64 tests across 12 files passed,
  including the new schedules / tasks / task-detail cases.
- `corepack pnpm --filter web build` — **PASS**. Next.js build + static export
  succeeded; `apps/web/out/index.html` contains `<link rel="icon" href="/logo.svg"/>`.
- `.venv/bin/python -m pytest apps/server/tests/test_executions_pagination.py -q`
  — **BLOCKED (not run)**. Every Python invocation in this environment returns
  `This command requires approval` (verified even on `python -c "print('hello')"`);
  `pnpm` commands are not gated. This is a permission gate, not a code failure.
  The server tests were authored and need the operator to approve the Python
  command, after which they can be executed. Re-run command:

  ```bash
  .venv/bin/python -m pytest apps/server/tests/test_executions_pagination.py -q
  ```

## Known Risks / Incomplete Items

- **Server tests not yet executed** (permission gate above). The added tests
  follow the existing patterns in the same file (shared `db_session`/`exec_client`
  fixtures, `_seed_tasks`/`_seed_artifact_tasks`/`_run_artifact` helpers) and the
  validation mirrors the existing `task.invalid_page_size` path, but they remain
  unverified until the Python command is approved and run.
- No backend schedule, agent, Redis, executor, log-consumer, or auth behavior was
  changed; no DB migration. The web `Schedule.enabled` type is now required —
  call sites that construct a `Schedule` literal must set it (the one test fixture
  was updated).
