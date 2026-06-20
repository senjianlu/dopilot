# Phase 2a Brief: ID Naming Clean-Cut

## Goal

Unify internal task/execution identifiers across the Redis wire, server DB
columns, agent state files, and log paths:

```text
old seam:
  execution_id = Task.id
  attempt_id   = Execution.id

new seam:
  task_id      = Task.id
  execution_id = Execution.id
```

This is a deliberate clean-cut change before phase 2b Python wheel execution.
Existing Scrapy behavior must keep working after the rename.

## Context

Read before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`
- `docs/phases/phase-2/00b-plan-review.md`
- `docs/phases/phase-2a/00a-feasibility-review.md`

Accepted decisions:

- No backwards compatibility for old Redis messages, pending commands, or old
  agent state/log paths.
- Cutover requires no in-flight executions, cleared Redis streams/pending
  commands, and lockstep deploy of protocol, server, and agent.
- Legacy HTTP schemas carrying old seam naming should be deleted when no live
  code path uses them.
- The rename is a name-collision swap. `execution_id` already means
  `Execution.id` in public/domain surfaces, so broad global replacement is not
  allowed.

## In Scope

- Protocol Redis stream schema rename:
  - `AgentCommand.execution_id` -> `task_id`
  - `AgentCommand.attempt_id` -> `execution_id`
  - `AgentEvent.execution_id` -> `task_id`
  - `AgentEvent.attempt_id` -> `execution_id`
  - `AgentLogEvent.execution_id` -> `task_id`
  - `AgentLogEvent.attempt_id` -> `execution_id`
- Protocol legacy schema cleanup:
  - Delete `AgentStopRequest`, `CleanupResponse`, `TailRequest`,
    `TailResponse`, their exports, and tests.
  - Keep and rename live schemas with seam fields: `AgentRunRequest`,
    `AgentStopResponse`, `AgentStatusResponse`.
  - Delete `AgentRunResponse` and `ScrapydRunner.run()` if a fresh reference
    scan confirms the method has no live caller. If a live caller exists, keep
    them and rename seam fields instead.
  - Leave `AttemptStatus`, `EggDeployResponse`, and `LogStream` unchanged unless
    imports need mechanical cleanup.
- Server model and migration updates:
  - Add Alembic migration `0009` with `down_revision = "0008"`.
  - Rename `execution_log_files.execution_id` -> `task_id`.
  - Rename `execution_log_files.attempt_id` -> `execution_id`.
  - Rename `command_outbox.execution_id` -> `task_id`.
  - Rename `command_outbox.attempt_id` -> `execution_id`.
  - Rename `event_audit.attempt_id` -> `execution_id`.
  - Rename affected indexes/constraints in the migration.
- Server internal service updates for outbox, dispatcher, reconcile, events,
  logs, maintenance, cancellation, executors, and log file paths.
- Agent internal state and Redis updates:
  - Rename command/event/log handling to consume/publish `task_id` and
    `execution_id`.
  - Rename on-disk state files from `{attempt_id}.json` to
    `{execution_id}.json`.
  - Rename log cursor files from `{attempt_id}.logpos` to
    `{execution_id}.logpos`.
  - Rename log body layout from `{root}/YYYY/MM/{execution_id}/{attempt_id}.log`
    to `{root}/YYYY/MM/{task_id}/{execution_id}.log`.
- Test updates covering protocol, server, and agent behavior after the rename.
- Remove obsolete comments/docstrings that describe the old seam translation.

## Out Of Scope

- Python wheel artifacts or runner support.
- venv, dependency, shell-command, or subprocess behavior.
- Backwards compatibility shims for old Redis payloads, old DB column names, old
  state files, or old log paths.
- Public HTTP API, web TypeScript types, or browser-facing JSON changes.
- Docker/K3s support.
- Any edit under `reference/scrapydweb/`.

## Required Implementation Order

1. Re-run focused `rg` checks for the legacy schemas and
   `ScrapydRunner.run()` before deletion.
2. Update protocol stream schemas and live legacy protocol schemas. Delete only
   confirmed dead schemas/methods.
3. Update server models and add migration `0009`; do not edit old migrations.
4. Update server services, Redis dispatch/reconcile, executor code, and log path
   helpers at the internal seam only.
5. Update agent state, command consumer, event/log publishers, runner code, and
   on-disk path/cursor naming.
6. Update tests in lockstep, deleting tests only for deleted dead schemas.
7. Run required formatting/lint/test commands and record output in the
   implementation report.

## Do Not Rename

These surfaces already use `execution_id` to mean atomic `Execution.id` and
should not be changed for phase 2a:

- `apps/server/dopilot_server/api/v1/tasks.py` query parameter
  `execution_id` for log snapshot/SSE.
- `apps/server/dopilot_server/api/v1/schemas.py` public response fields.
- `apps/server/dopilot_server/services/executions.py` public/domain helpers
  such as `get_execution(execution_id)` and
  `resolve_execution(task_id, execution_id)`.
- `apps/server/dopilot_server/logs/sse.py` and
  `apps/server/dopilot_server/logs/stream_token.py` public log streaming
  contracts.
- `apps/web/**` types and API calls, unless a test proves a comment-only or
  internal correction is required.

Phase 2a must have zero intentional public API or web JSON drift.

## Acceptance Criteria

- Redis command/event/log payloads use `task_id` for `Task.id` and
  `execution_id` for `Execution.id`.
- Server DB models use `task_id` / `execution_id` columns for command outbox,
  event audit, and execution log files.
- Alembic migration `0009` applies and rolls back with data-preserving column
  renames.
- Agent state, log cursor, and log file paths are keyed by the new names.
- Existing Scrapy schedule, dispatch, stop/cancel, event, log, reconciliation,
  and cleanup behavior still passes tests.
- Dead legacy schemas and their exports/tests are removed; live schemas are
  renamed, not lost.
- Public HTTP/web behavior is unchanged.
- No old seam `attempt_id` token remains in `apps/` or `packages/` except where
  there is a justified non-seam use documented in the implementation report.

## Required Tests

- Protocol:
  - `pytest packages/protocol/tests`
- Server:
  - `pytest apps/server/tests`
  - Include unchanged public API/SSE coverage, especially
    `apps/server/tests/test_sse.py` and `apps/server/tests/test_executions.py`.
- Agent:
  - `pytest apps/agent/tests`
- Migration:
  - From `apps/server`: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
- Static checks:
  - `ruff check apps packages`
- Config smoke:
  - From `deploy/docker`: `docker compose config`
- Residual token check:
  - `rg -n 'attempt_id' apps packages`

If an environment-specific command cannot run, record the exact blocker and run
the closest narrower command.

## Required Commands

```bash
ruff check apps packages
pytest packages/protocol/tests
pytest apps/server/tests
pytest apps/agent/tests
cd apps/server && alembic upgrade head && alembic downgrade -1 && alembic upgrade head
rg -n 'attempt_id' apps packages
cd deploy/docker && docker compose config
```

## Risks To Watch

- Mixed old/new protocol deployments silently mis-map ids. This is accepted only
  under the lockstep deploy gate.
- In-flight old state/log files become orphaned after cutover. This is accepted
  only under the quiesce and Redis-flush gate.
- `execution_id` is a collision token. Every change must be based on local
  meaning, not token replacement.
- Migration/index naming differs between SQLite tests and PostgreSQL Alembic
  history; verify against migration files and model metadata.
