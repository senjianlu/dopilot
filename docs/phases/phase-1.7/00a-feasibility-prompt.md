# Claude Feasibility Validation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of the proposed phase 1.7 solution before Codex
finalizes the implementation brief.

Do not implement code in this step.

## Proposed Direction

Use `docs/phases/phase-1.7/00-brief.md` as the draft direction.

Codex is especially concerned about:

- migrating or wrapping the current inverted naming where `executions` is the
  parent logical run and `execution_attempts` is the per-node atomic execution;
- whether Redis stream fields can safely keep `execution_id` while changing it
  to mean the atomic execution id;
- log path/index migration from `execution_id/attempt_id` to task/execution
  semantics;
- allowing repeated concurrent runs while older outbox/scheduler coalesce code
  exists;
- zero-execution tasks when no healthy node is available.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`
- `docs/phases/phase-1.6/00-brief.md`
- `docs/phases/phase-1.7/00-brief.md`
- `apps/server/dopilot_server/models/execution.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/services/outbox.py`
- `apps/server/dopilot_server/services/events.py`
- `apps/server/dopilot_server/services/logs.py`
- `apps/server/dopilot_server/redis/consumers.py`
- `apps/server/dopilot_server/redis/reconcile.py`
- `apps/server/dopilot_server/nodes/service.py`
- `packages/protocol/dopilot_protocol/streams.py`
- `packages/protocol/dopilot_protocol/execution.py`
- `apps/web/src/api/types.ts`

## Output Required

Write the feasibility response to:

`docs/phases/phase-1.7/00a-feasibility-review.md`

If this check runs long, update:

`docs/phases/phase-1.7/claude-progress.md`

Write an early note with rough duration, proposed update cadence, current step,
files being inspected, last command status if relevant, and blockers. Update it
again at meaningful checkpoints. This is a coordination note, not a hard timer.

Use these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Keep the response concrete. Focus on implementation feasibility, not product
brainstorming. If there are no blockers, say so clearly.
