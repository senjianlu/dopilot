You are Claude Code acting as the implementation and test agent for dopilot.

Follow repository constraints from `AGENTS.md`, `CLAUDE.md`, and the task brief.
Do not consult, fetch, vendor, copy, or import upstream scrapydweb code.

Task brief:
- `docs/phases/task-web-archive-indicators-search-breadcrumb/00-brief.md`

Feasibility review:
- `docs/phases/task-web-archive-indicators-search-breadcrumb/00a-feasibility-review.md`

Implement the task end to end.

Required scope:

1. Backend template API archive metadata
   - Extend `ExecutionTemplateView` with required live artifact fields:
     - `build_artifact_archived: bool`
     - `build_artifact_archived_at: str | None`
   - Populate these fields in create/get/list/update template responses.
   - Preserve runtime behavior: archived bound artifacts must still allow
     existing template runs and schedule dispatch.
   - Avoid an N+1 on template list. Extend or replace the existing batched
     artifact metadata helper so it returns artifact type and archive state per
     template.
   - Missing/dangling artifact bindings should serialize as
     `build_artifact_archived=false`, `build_artifact_archived_at=null`.

2. Shared web UI
   - Add a reusable archived build warning indicator component.
   - Use existing shadcn Tooltip composition and lucide icon.
   - Tooltip text must be localized, with Chinese text exactly:
     `该构建已经归档`
   - Make the trigger keyboard/focus accessible.
   - Include `TooltipProvider` in the shared component so tests render without
     relying on the app shell provider.

3. Templates page
   - Add a search input in the table/card header area near the title/action
     controls.
   - Filter displayed templates by `template.name` prefix.
   - Search semantics: trim input, case-insensitive, `startsWith`, empty shows
     all, no debounce required.
   - Render the amber archived indicator immediately after the displayed version
     value when `template.build_artifact_archived` is true, including when the
     displayed version is `-`.
   - Preserve existing create/edit/run/delete behavior and existing archived
     artifact picker behavior.

4. Schedules page
   - Add the same search behavior, filtering by `schedule.name` prefix.
   - Reuse the templates list already loaded by the page to determine whether
     a schedule's execution template references an archived build artifact.
   - Render the amber archived indicator immediately after the execution
     template name when the resolved template is archived.
   - Do not add archive fields to `ScheduleView` unless absolutely necessary.

5. App shell
   - Fix collapsed sidebar logo clipping when `collapsible="icon"` is active.
   - Add a breadcrumb to the right of the vertical separator beside the sidebar
     trigger, keeping top controls on the far right.
   - Use existing shadcn Breadcrumb components.
   - Breadcrumb content is app root plus current top-level nav page. Nested
     routes should map to their parent top-level nav item, e.g. `/tasks/detail`
     still shows the Tasks crumb only.
   - Breadcrumb should truncate cleanly and not collide with top controls.

6. Tests
   - Add/update backend tests for the new template response fields, including
     archived and unarchived artifacts.
   - Add/update web tests for:
     - Templates archived indicator rendering.
     - Schedules archived indicator rendering via loaded templates.
     - Prefix search semantics on Templates and Schedules.
   - Update all TypeScript fixtures because the new `ExecutionTemplate` archive
     fields are required.

Verification commands to run and report:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol .venv/bin/python -m pytest apps/server/tests/
.venv/bin/python -m ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
git diff --check
```

Output required:
- Summary of files changed.
- Test command results.
- Any residual risk or manual visual checks that still need human review,
  especially for collapsed sidebar logo and breadcrumb layout.
