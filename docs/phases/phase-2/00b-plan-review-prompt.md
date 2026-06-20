# Claude Plan Review Prompt: Phase 2a/2b Split

You are Claude Code working in the dopilot repository. This is a read-only plan
review. Do not implement changes and do not edit application code.

## Task

Review the updated phase-2 preflight decisions and validate the proposed split:

- Phase 2a: breaking id-name clean-cut from `execution_id` / `attempt_id` seam
  to `task_id` / `execution_id`.
- Phase 2b: Python wheel shell-command runner with no venv, no dependency
  management, merged log stream, and process-group cancellation.

Write your report to:

```text
docs/phases/phase-2/00b-plan-review.md
```

You may update:

```text
docs/phases/phase-2/claude-progress.md
```

Do not edit other files.

## Required Context

Read:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`
- `docs/phases/phase-2/00a-feasibility-review.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`

Inspect current code with `rg` / `sed` / `nl` as needed, especially:

- `packages/protocol/dopilot_protocol/streams.py`
- `packages/protocol/dopilot_protocol/agent.py`
- `packages/protocol/dopilot_protocol/logs.py`
- `apps/server/dopilot_server/models/execution.py`
- `apps/server/dopilot_server/models/command_outbox.py`
- `apps/server/dopilot_server/models/event_audit.py`
- `apps/server/dopilot_server/services/outbox.py`
- `apps/server/dopilot_server/services/events.py`
- `apps/server/dopilot_server/services/logs.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/redis/dispatcher.py`
- `apps/server/dopilot_server/redis/reconcile.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/api/v1/tasks.py`
- `apps/server/dopilot_server/api/v1/schemas.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/redis/events.py`
- `apps/agent/dopilot_agent/redis/logs.py`
- `apps/agent/dopilot_agent/state/store.py`
- `apps/agent/dopilot_agent/runners/scrapyd.py`
- `apps/server/migrations/versions/0004_task_execution_rename.py`
- `apps/web/src/api/types.ts`
- `apps/web/src/api/tasks.ts`

## Questions To Answer

1. Is the 2a/2b split technically sound? If not, propose a safer split.
2. For phase 2a, list the exact rename surface:
   - protocol fields,
   - DB columns / migration,
   - server services,
   - agent state and Redis publishers/consumers,
   - log paths and file-index rows,
   - public API/query fields that should or should not change,
   - web types/client usage,
   - tests.
3. Identify any locations where `execution_id` already correctly means the
   public atomic `Execution.id` and should remain `execution_id`.
4. State whether phase 2a needs a backwards-compatibility layer for old Redis
   messages or old agent state files. Assume the user is willing to accept a
   clean-cut unless you see a hard blocker.
5. For phase 2b, validate the no-venv shell-command design:
   - wheel install into current environment with `--no-deps`,
   - dependencies manually managed by operator,
   - merged stdout/stderr to `log`,
   - process-group SIGTERM -> 10s -> SIGKILL cancellation,
   - per-run workspace/log/state keyed by `execution_id` (the atomic id after
     phase 2a).
6. List mandatory tests for phase 2a and phase 2b separately.
7. List remaining decisions that still need user approval.

## Constraints

- Do not edit application code.
- Do not run broad tests. Read-only shell commands are allowed.
- Do not use or edit `reference/scrapydweb/`.
- Keep the report concise and decision-oriented with file references.

## Expected Report Shape

Use these headings:

```text
# Phase 2 Plan Review

## Verdict
## Phase 2a Rename Surface
## Public API Notes
## Compatibility
## Phase 2b Runner Review
## Required Tests
## Remaining Decisions
## Commands Run
```

