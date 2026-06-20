# Claude Feasibility Prompt: Phase 2a ID Naming Clean-Cut

You are Claude Code working in the dopilot repository. This is a focused
feasibility validation only. Do not implement changes and do not edit
application code.

## Task

Validate whether phase 2a can safely implement this clean-cut:

```text
old Redis/agent/log seam:
  execution_id = Task.id
  attempt_id   = Execution.id

new unified naming:
  task_id      = Task.id
  execution_id = Execution.id
```

Additional user decisions:

- No backwards compatibility for old Redis messages or old agent state files.
- Cutover requires no in-flight executions, Redis streams/pending commands
  cleared, and server/agent/protocol deployed lockstep.
- Legacy HTTP agent/log schemas that still carry old naming should be deleted if
  no live code path uses them, not renamed and kept.

Write the feasibility report to:

```text
docs/phases/phase-2a/00a-feasibility-review.md
```

You may update:

```text
docs/phases/phase-2a/claude-progress.md
```

Do not edit other files.

## Required Context

Read:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`
- `docs/phases/phase-2/00b-plan-review.md`
- `docs/dopilot/00-requirements.md`
- `docs/refactor/00-redis-streams-agent-communication.md`

Inspect code as needed, especially:

- `packages/protocol/dopilot_protocol/streams.py`
- `packages/protocol/dopilot_protocol/agent.py`
- `packages/protocol/dopilot_protocol/logs.py`
- `packages/protocol/dopilot_protocol/__init__.py`
- `apps/server/dopilot_server/models/execution.py`
- `apps/server/dopilot_server/models/command_outbox.py`
- `apps/server/dopilot_server/models/event_audit.py`
- `apps/server/dopilot_server/services/outbox.py`
- `apps/server/dopilot_server/services/events.py`
- `apps/server/dopilot_server/services/logs.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/redis/dispatcher.py`
- `apps/server/dopilot_server/redis/reconcile.py`
- `apps/server/dopilot_server/api/v1/tasks.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/redis/events.py`
- `apps/agent/dopilot_agent/redis/logs.py`
- `apps/agent/dopilot_agent/state/store.py`
- `apps/agent/dopilot_agent/runners/scrapyd.py`
- tests under `packages/protocol/tests`, `apps/server/tests`, `apps/agent/tests`

Use `rg` to discover references.

## Questions To Answer

1. Is deleting `dopilot_protocol.agent` / `dopilot_protocol.logs` legacy schemas
   feasible in phase 2a, or are they still imported by live code/tests?
2. If deletion is feasible, what public imports or `__init__.py` exports must be
   removed or updated?
3. Are there any hard blockers to the clean-cut rename under the accepted
   cutover assumptions?
4. What exact items must the implementation brief include to avoid accidental
   global-sed mistakes, especially where public API `execution_id` already means
   atomic `Execution.id`?
5. What verification commands should be mandatory for phase 2a?
6. What residual risks, if any, require user acceptance beyond the already
   accepted clean-cut cutover?

## Constraints

- Do not implement.
- Do not edit application code.
- Do not run broad tests. Read-only shell commands are allowed.
- Do not read or edit `reference/scrapydweb/`.
- Keep the report concise and decision-oriented with file references.

## Expected Report Shape

Use these headings:

```text
# Phase 2a Feasibility Review

## Verdict
## Legacy Schema Deletion
## Clean-Cut Rename Feasibility
## Brief Requirements
## Required Verification
## Residual Risks
## Commands Run
```

