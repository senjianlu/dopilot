# Claude Implementation Prompt · Phase 1.7 Packet 1

You are Claude Code working in the dopilot repository.

## Assignment

Implement phase 1.7 packet 1: canonical task/execution domain naming with a
stable Redis/disk/agent seam.

Active brief:

- `docs/phases/phase-1.7/00-brief.md`

Feasibility review:

- `docs/phases/phase-1.7/00a-feasibility-review.md`

## Required Context

Read before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`
- `docs/phases/phase-1.6/00-brief.md`
- `docs/phases/phase-1.7/00-brief.md`
- `docs/phases/phase-1.7/00a-feasibility-review.md`
- `docs/agent-governance/02-claude-invocation.md`
- `apps/server/dopilot_server/models/execution.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/services/states.py`
- `apps/server/dopilot_server/services/outbox.py`
- `apps/server/dopilot_server/services/events.py`
- `apps/server/dopilot_server/services/logs.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/redis/consumers.py`
- `apps/server/dopilot_server/redis/reconcile.py`
- `apps/server/dopilot_server/nodes/service.py`
- `packages/protocol/dopilot_protocol/streams.py`
- `packages/protocol/dopilot_protocol/execution.py`
- `apps/web/src/api/types.ts`

## In Scope

- Rename the server domain so the parent logical run is `Task` and the per-node
  atomic unit is `Execution`.
- Add/adjust Alembic migration for the clean server-domain schema target:
  `tasks`, `executions`, and server-domain references using `task_id` /
  `execution_id`.
- Keep Redis/disk/agent seam stable:
  - Redis/disk/agent `execution_id` means parent task id.
  - Redis/disk/agent `attempt_id` means atomic execution id.
  - Do not edit agent state/log path semantics.
  - Boundary code may translate between server-domain names and wire names.
- Add task terminal status `no_target`, plus task `status_reason` and
  `status_detail`.
- Update server services/routes/view builders/tests for the new domain names.
- Update package protocol and Web types only as needed for packet 1 naming.
- Keep existing behavior otherwise: manual Scrapy run still dispatches one
  atomic execution per selected healthy node, Redis command outbox still has one
  run command per atomic execution, log/event/cancel paths still converge.

## Out Of Scope

- Templates.
- Schedules and trigger-now.
- Scheduler runner/coalesce changes beyond preserving existing behavior.
- Python script executor.
- Docker long-lived executor.
- Agent code rename.
- Reintroducing server->agent HTTP run/status/tail.
- Copying or importing anything from `reference/scrapydweb/`.

## Required Progress Notes

This task may run for a while. Update:

`docs/phases/phase-1.7/claude-progress.md`

Within the first few minutes, write an initial estimate with rough duration
class (`<15m`, `15-45m`, `45-90m`, or `90m+`), proposed update cadence,
checkpoints, and likely long-running commands. Then update the file at
meaningful checkpoints and before/after long-running commands. The cadence is a
guideline, not a hard timer; for this packet, one update per major edit/test
phase is acceptable. Each entry should include timestamp, current step,
files/subsystems being edited or inspected, last command status, and blockers.

## Output Required

Create:

- `docs/phases/phase-1.7/02-packet-1-implementation-report.md`

The report must include:

- changed files grouped by area;
- migration strategy and whether dev data preservation is supported;
- explicit statement that Redis/disk/agent seam is unchanged;
- tests added or updated;
- commands run with pass/fail output;
- known risks or incomplete items.

## Required Tests / Commands

Run the narrowest relevant tests first, then these before finishing if feasible:

```bash
pytest apps/server/tests packages/protocol/tests
ruff check apps packages
corepack pnpm --filter web test
```

If a command fails because of an unrelated pre-existing issue, record exact
failure output in the report and keep the code changes scoped.

## Acceptance Criteria

- Server-domain code and API/view names clearly distinguish task from atomic
  execution.
- Redis stream payloads still carry existing field names and meanings at the
  seam: `execution_id=task_id`, `attempt_id=execution_id`.
- Existing manual Scrapy run tests pass or are updated to the new names without
  changing dispatch behavior.
- `no_target`, `status_reason`, and `status_detail` exist in the task model and
  status helpers, even if zero-node behavior is completed in a later packet.
- No agent code is renamed.
- Report and progress heartbeat are written.
