# Task: Web Archive Indicators, Prefix Search, Breadcrumb, Sidebar Logo

## Goal

Improve the templates/schedules UI around archived build artifacts and table
navigation:

- show a warning when a template/schedule references an archived build artifact;
- add prefix name search to Templates and Schedules pages;
- fix the collapsed sidebar logo clipping;
- add a breadcrumb to the app shell header beside the sidebar trigger.

This task builds on `docs/phases/task-artifact-archive/`, where build artifacts
gained `archived` / `archived_at`.

## Confirmed Decisions

- Search is client-side for this task.
- Search matches the row name from the start (`startsWith`), not contains.
- Search is case-insensitive and trims leading/trailing whitespace.
- Empty search shows all rows.
- Use a plain controlled search input. No debounce or clear button is required.
- Archived warning tooltip text is exactly Chinese:
  `该构建已经归档`
- Use a yellow/amber warning mark, not a full text badge, in Templates and
  Schedules tables.
- The warning mark appears:
  - on Templates page after the version value;
  - on Schedules page after the execution template name.
- Schedules page can derive archive state from the templates list it already
  loads. Do not add artifact state directly to `ScheduleView` unless feasibility
  proves it is needed.
- Add the breadcrumb on the right side of the vertical separator next to the
  sidebar trigger. Keep top controls on the far right.
- Breadcrumb content is app root plus current top-level navigation page.
  Nested routes map to their parent top-level nav item, so `/tasks/detail` shows
  the Tasks page crumb and does not require a separate Detail label.
- The new TypeScript `ExecutionTemplate` archive fields should be required to
  mirror the backend contract. Update fixtures instead of making the fields
  optional.

## Required Behavior

### Backend/API

- Extend `ExecutionTemplateView` with enough live artifact state for the web to
  know whether the template's bound artifact is archived:
  - `build_artifact_archived: boolean`
  - `build_artifact_archived_at: string | null`
- This is a live property from the bound `BuildArtifact`, not a frozen task
  snapshot.
- Existing create/update/get/list template APIs should populate the field.
- Template list population must avoid an N+1 artifact lookup. Extend the
  existing batch artifact metadata helper, or replace it with an equivalent
  batched helper that returns artifact type plus archive state per template.
- Missing/dangling artifact bindings should fall back to
  `build_artifact_archived: false` and `build_artifact_archived_at: null`.
- Existing runtime behavior remains unchanged: archive state must not block
  already-bound template runs or schedule dispatch.

### Shared Web UI

- Add or reuse a small component/helper for the archive warning indicator so the
  Templates and Schedules pages behave consistently.
- Use existing shadcn/ui Tooltip composition:
  `Tooltip` + `TooltipTrigger` + `TooltipContent`.
- Tooltip content text must be localized and Chinese default should be
  `该构建已经归档`.
- Use an icon from `lucide-react` for the warning mark.
- The indicator must be keyboard/focus accessible, not hover-only.
- The shared indicator should be self-contained for tests by including a
  `TooltipProvider` internally, because the app runtime already has one but the
  page test harness does not.
- A shared prefix-match helper may be added so Templates and Schedules use the
  same trim/case-insensitive/startsWith semantics.

### Templates Page

- Add a search input in the table/card header area near the title/action group.
- Filter displayed templates by `template.name` prefix.
- When `template.build_artifact_archived === true`, render an amber warning mark
  immediately after the version text in the Version column.
- Render the warning mark even when the displayed version value is `-`.
- Tooltip text: `该构建已经归档`.
- Existing create/edit/run/delete behavior must remain unchanged.
- The template edit picker behavior from task-artifact-archive remains unchanged:
  archived artifacts are not selectable as new bindings, but the current archived
  binding remains visible.

### Schedules Page

- Add a search input in the table/card header area near the title/action group.
- Filter displayed schedules by `schedule.name` prefix.
- For each schedule row, resolve the referenced template as today. If that
  template has `build_artifact_archived === true`, render the same amber warning
  mark immediately after the template name in the Template column.
- Existing schedule create/edit/trigger/delete/enable behavior must remain
  unchanged.

### App Shell

- Fix the collapsed sidebar logo so the logo mark is fully visible and not
  clipped when `collapsible="icon"` is active.
- Add a breadcrumb in the header after the separator to the right of the sidebar
  trigger.
- Breadcrumb should use the existing shadcn/ui Breadcrumb components.
- Breadcrumb content can be route-level:
  - current app name/root plus current nav page, or just the current nav page if
    that better fits the existing header.
- Breadcrumb should not collide with top controls, should truncate cleanly, and
  should be stable on nested routes such as `/tasks/detail`.

## Out Of Scope

- Server-side search/pagination.
- Changing schedule API runtime semantics.
- Blocking schedule/template runs for archived artifacts.
- Adding archive state to frozen task snapshots or task-list artifact filters.
- Adding new dependencies.
- Upstream scrapydweb consultation or code reuse.

## Expected Code Areas

- `apps/server/dopilot_server/api/v1/schemas.py`
- `apps/server/dopilot_server/api/v1/templates.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/tests/`
- `apps/web/lib/api/types.ts`
- `apps/web/app/(app)/templates/page.tsx`
- `apps/web/app/(app)/schedules/page.tsx`
- `apps/web/app/(app)/layout.tsx`
- `apps/web/components/layout/app-sidebar.tsx`
- `apps/web/components/layout/` or `apps/web/components/features/`
- `apps/web/lib/i18n/locales/`
- relevant web tests under `apps/web/app/(app)/**/__tests__/`

## Acceptance Criteria

- Templates and schedules tables have working prefix search by name.
- Archived-bound templates show an amber warning icon after version with a
  tooltip.
- Schedules referencing archived-bound templates show the same warning icon
  after the template name with a tooltip.
- Sidebar collapsed logo is fully visible.
- Header shows a breadcrumb after the sidebar trigger separator.
- Existing archive behavior and tests from `task-artifact-archive` still pass.
- Backend/web tests cover the new fields, indicators, and search behavior.

## Verification Commands

Use the local environment command variants if needed:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol .venv/bin/python -m pytest apps/server/tests/
.venv/bin/python -m ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
git diff --check
```
