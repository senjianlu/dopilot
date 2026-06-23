# Claude Feasibility Validation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of the proposed web UI follow-ups before Codex
finalizes the implementation brief. Do not implement code in this step.

## Proposed Direction

Use `docs/phases/task-web-ui-followups/00-brief.md` as the draft brief.

Key decisions to validate:

- schedules enabled UI uses the existing shadcn `Switch` and existing
  `PUT /api/v1/schedules/{id}` API;
- task status filtering is implemented as a backend query filter because task
  listing is backend-paginated;
- task-detail execution ordering is display-only and sorted by `agent_id`, then
  `id`;
- favicon reuses `apps/web/public/logo.svg`;
- no migration, Redis, agent, executor, or auth work is in scope.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/task-web-ui-followups/00-brief.md`
- `docs/phases/phase-2.2/00-brief.md`
- `docs/phases/task-execution-log-selection/00-brief.md`
- the code paths named in the brief.

## Output Required

Return a concise feasibility response with:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Keep the response concrete. Focus on implementation feasibility, not product
brainstorming.
