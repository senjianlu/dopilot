# Feasibility Review

## Proposed Direction

- Summary: implement five focused web UI follow-ups plus one narrow task-list
  status query filter, as described in `00-brief.md`.
- Source discussion or draft: user request on 2026-06-23 and
  `docs/phases/task-web-ui-followups/00-brief.md`.

## Claude Feedback

### Verdict

- Feasible.

### Blockers

- None.

### Risky Assumptions

- Quick schedule toggle through `updateSchedule(id, { enabled: next })` is safe
  because the backend update schema is partial and the route uses
  `exclude_unset`.
- No all-status constant currently exists; the implementation should derive
  valid task statuses from `TASK_ACTIVE | TASK_TERMINAL` or add a shared
  `TASK_STATUSES` constant.
- `agent_id` is nullable; the sort needs a pinned null ordering.
- Adding the schedules enabled column requires updating empty-row `colSpan`.

### Questions

- Favicon mechanism: choose metadata `icons` or App Router `icon.svg`.
- Quick-toggle UX: optimistic update or reload-on-success only.

### Suggested Scope Or Sequencing Changes

- Keep the five UI items in one packet; they are independent and small.
- Keep task-detail sort display-only and do not touch backend log/SSE resolution.
- Keep the invalid-status endpoint test in the focused task-list API test area.

## Codex Decision

- Accepted with brief updates.
- Task statuses must be validated against `TASK_ACTIVE | TASK_TERMINAL`, or a
  derived `TASK_STATUSES` constant added in `states.py`.
- Null/empty `agent_id` sorts last, then by execution `id`.
- Favicon uses `metadata.icons` pointing to `/logo.svg`.
- Schedule quick toggles reload on success only; no optimistic UI is required.

## User Escalations

- None.

## Resulting Brief Changes

- Clarified task status validation source.
- Clarified null `agent_id` sorting.
- Clarified favicon implementation.
- Clarified server test expectations for invalid status.
