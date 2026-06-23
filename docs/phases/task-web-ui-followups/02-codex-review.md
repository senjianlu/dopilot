# Codex Review

## Findings

- None blocking.

## Review Notes

- Schedule enable/disable stays on the existing partial `PUT
  /api/v1/schedules/{id}` path and sends only `{ enabled: next }` from the table
  quick-toggle.
- New schedule creation still defaults disabled unless the modal switch is
  turned on, matching phase 2.2 backend semantics.
- Task status filtering is implemented in SQL before pagination and total
  counting; it composes with build-artifact and legacy spider filters.
- Task-detail execution ordering is display-only and sorts a copy by
  `agent_id`, then `id`, with null/empty agent ids last.
- Sidebar and favicon changes are scoped to their requested files.
- No agent, Redis, executor, auth, migration, or schedule backend behavior was
  changed.

## Residual Risks

- The task status dropdown displays backend status ids (`queued`, `running`,
  etc.) directly, consistent with the existing task status badges. Localized
  per-status labels remain a possible later UI polish item.

## Decision

- Accepted for verification.
