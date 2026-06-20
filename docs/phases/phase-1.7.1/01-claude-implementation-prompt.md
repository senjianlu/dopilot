# Claude implementation prompt · Phase 1.7.1

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/phase-1.7.1/00-brief.md`

This is a broad frontend optimization with required backend support. Keep the
work scoped to Phase 1.7.1 only.

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-1.7/00-brief.md`
- `docs/phases/phase-1.7/09-acceptance.md`
- `docs/phases/phase-1.7.1/00a-feasibility-review.md`
- `docs/phases/phase-1.7.1/00-brief.md`

Then inspect the relevant code paths:

- server nodes model/API/service;
- server executions API/service;
- server templates/schedules services and APIs;
- server health API;
- web pages for dashboard, nodes, templates, schedules, executions;
- web API clients/types/i18n/tests.

## Implementation Order

1. Backend node scheduling-state and soft-delete migration/API/service changes.
2. Backend dispatch selection changes for offline/deleted nodes.
3. Backend execution pagination + spider filter + aggregate child counts.
4. Backend dashboard stats and schedule `next_run_at` metadata.
5. Frontend API/types/i18n updates.
6. Frontend page updates.
7. Tests and verification.

## Constraints

- Do not edit `reference/scrapydweb/`.
- Do not copy structure or code from `reference/scrapydweb/`.
- Do not reintroduce server-to-agent HTTP run/status/tail.
- Do not reintroduce `POST /nodes/refresh`.
- Do not silently mutate existing templates when selected nodes go offline or
  are deleted.
- Node delete is soft delete. Do not physically remove node rows.
- Offline is a scheduling state, not a health state. Heartbeat health must still
  be visible.
- Deleted nodes should not resurrect implicitly on heartbeat.
- Keep changes compatible with PostgreSQL and the SQLite test path.
- Keep chart implementation light; do not add a large chart dependency unless
  you document why native SVG/CSS is unsuitable.
- If you cannot complete the full brief in one pass, stop after the backend
  contract is coherent and report what remains.

## Output Required

Create or update:

- `docs/phases/phase-1.7.1/01-claude-implementation-report.md`
- `docs/phases/phase-1.7.1/claude-progress.md`

The implementation report must include:

- changed files grouped by server/web/docs/tests;
- implementation notes;
- tests added or updated;
- commands run with exact pass/fail outcomes;
- known risks, shortcuts, or incomplete items.

At the start, write `claude-progress.md` with rough duration, update cadence,
checkpoints, and likely long-running commands. Update it at meaningful
checkpoints.

## Codex Monitoring Constraint

This packet is expected to be long-running. Codex should do one early check to
confirm the subprocess did not immediately fail, then monitor roughly every
five minutes unless there is an explicit completion signal such as a final
report file, final command outcomes, or process exit. Prefer cheap checks:
process state, `claude-progress.md`, final report existence, and final JSON.

## Required Commands

Run these unless blocked, and report exact outcomes:

```bash
pytest apps/server/tests packages/protocol/tests
ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

If a command cannot run, record the exact failure and smallest next action.
