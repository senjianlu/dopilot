# Claude Implementation Prompt: Task Runtime Context

You are Claude Code working in the dopilot repository.

## Task Name

`task-runtime-context`

## Active Brief

Implement from:

- `docs/phases/task-runtime-context/00-brief.md`
- `docs/phases/task-runtime-context/00a-feasibility-review.md`

## Required Context

Read these first:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-2b/00-brief.md`
- `packages/protocol/dopilot_protocol/execution.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/executors/python_wheel.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/services/resolve.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/runners/python_wheel.py`
- `apps/agent/dopilot_agent/scrapyd/client.py`
- relevant tests under `packages/protocol/tests`, `apps/server/tests`, and
  `apps/agent/tests`

## In Scope

- Add a shared `DopilotRuntimeContext` protocol model/helper and deterministic
  conversion to `DOPILOT_*` maps.
- Build runtime context on the server per concrete execution after
  `create_execution(...)`, because `execution_id` and `agent_id` are per target.
- Include the canonical context as `runtime_context` in Scrapy and Python wheel
  run payloads.
- Inject Scrapy runtime context as per-job Scrapy settings in the agent.
- Inject Python wheel runtime context as child process env in the agent.
- Ensure platform `DOPILOT_*` keys override user/task values at the final
  carrier merge point.
- Update focused protocol/server/agent tests.
- Update comments/docs touched by the behavior change.

## Out Of Scope

- User-defined/custom environment variable UI, API, DB storage, or profiles.
- Secret handling/masking.
- Docker runtime implementation.
- Replacing scrapyd with direct `scrapy crawl` subprocess execution.
- Broad executor or runner registry refactors.
- Upstream scrapydweb code fetch/copy/vendor/import.

## Expected Report

Write your implementation report to:

`docs/phases/task-runtime-context/01-claude-implementation-report.md`

Include:

- changed files;
- implementation summary;
- tests added/updated;
- exact commands run and outcomes;
- unresolved risks or TODOs.

Also create/update progress notes at:

`docs/phases/task-runtime-context/claude-progress.md`

Use your own reasonable cadence.

## Required Commands

Run at minimum:

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests
.venv/bin/ruff check apps packages
```

If you touch frontend files, also run:

```bash
corepack pnpm --filter web test
corepack pnpm --filter web build
```

If a command cannot run, record the exact command, failure, and reason in the
report.

## Notes

- Existing worktree changes may exist. Do not revert unrelated changes.
- Keep edits scoped to this task.
- Prefer small helpers over duplicating runtime-context serialization in server
  and agent code.
