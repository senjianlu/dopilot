# Task Runtime Context Brief

## Goal

Expose Dopilot runtime context to user workloads so Scrapy spiders, Python
script tasks, and future Docker tasks can identify the Dopilot run they belong
to.

The immediate user need is for Scrapy spiders to receive per-run identifiers
such as `task_id` even though every run has a different value. The broader
product expectation is a stable, cross-executor "Dopilot Runtime Context"
contract that scripts, spiders, and containers can consume with the same field
names.

## Context

Relevant files and decisions:

- `CLAUDE.md`
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

Current state:

- Python wheel payloads already carry `env`, and the agent merges that map into
  the child process environment.
- Scrapy payloads currently carry only `command` and `artifact`. The agent parses
  the command into Scrapy spider args/settings and calls scrapyd
  `/schedule.json`.
- scrapyd scheduling supports spider args and Scrapy settings per job, but not a
  first-class per-job OS environment map. Therefore Scrapy must receive runtime
  context through Scrapy settings, not by mutating process-level environment.

## Runtime Context Contract

Define a canonical Dopilot runtime context with stable string fields. First
version fields:

- `task_id`
- `execution_id`
- `agent_id`
- `artifact_type`
- `task_type`
- `source`
- `execution_template_id`
- `schedule_id`

Expose these as individual keys:

- `DOPILOT_TASK_ID`
- `DOPILOT_EXECUTION_ID`
- `DOPILOT_AGENT_ID`
- `DOPILOT_ARTIFACT_TYPE`
- `DOPILOT_TASK_TYPE`
- `DOPILOT_TASK_SOURCE`
- `DOPILOT_EXECUTION_TEMPLATE_ID`
- `DOPILOT_SCHEDULE_ID`

Also expose one JSON value:

- `DOPILOT_RUNTIME_CONTEXT`

For nullable fields, use an empty string in the individual `DOPILOT_*` key and
preserve `null` in `DOPILOT_RUNTIME_CONTEXT`.

`artifact_type` is the Dopilot domain/build-artifact discriminator, for example
`scrapy` or `python_wheel`. `task_type` is the Redis runner discriminator used
by the agent command path, currently `scrapy` or `python_wheel` and reserved for
the future Docker runner value.

The shared helper should provide explicit carrier methods even if they return
the same string map in the first version:

- `to_env_map()`
- `to_scrapy_settings()`

`DOPILOT_RUNTIME_CONTEXT` must be serialized deterministically with stable field
names, sorted keys, and compact separators so tests and user workloads see
predictable values.

Future Docker executor contract: when `docker_image` support lands, the agent
must inject this same `to_env_map()` output as container environment variables,
with Dopilot-owned `DOPILOT_*` keys overriding any user/container env values at
the final container-env merge point.

## In Scope

- Add a shared protocol helper/model for Dopilot runtime context and conversion
  to `DOPILOT_*` string maps.
- Build runtime context on the server per target execution, after
  `create_execution(...)`, because the context needs the concrete `execution_id`
  and `agent_id`.
- Include that canonical runtime context in Redis `run` command payloads for
  Scrapy and Python wheel executions as `runtime_context`.
- For Scrapy runs, agent must inject the runtime context into per-job Scrapy
  settings before calling scrapyd schedule. User-provided command `-s` settings
  must not be allowed to override `DOPILOT_*` runtime context keys.
- For Python wheel runs, server/agent must expose the runtime context as process
  environment variables. Runtime context must win over any task payload env for
  reserved `DOPILOT_*` keys, enforced at the last merge point before spawning
  the child process.
- Update tests so a Scrapy run receives the expected settings and a Python wheel
  run receives the expected environment variables.
- Document the future Docker executor contract: inject the same keys as
  container environment variables when Docker support lands.

## Out Of Scope

- User-defined/custom environment variables from the Web UI. Reserve
  `DOPILOT_*` now, but do not add custom env UI or storage.
- Secret storage, masking, encryption, or env profile management.
- Changing Scrapy command grammar beyond internal platform context injection.
- Replacing scrapyd with direct `scrapy crawl` subprocess execution.
- Implementing Docker runtime behavior before the Docker executor phase.
- Adding a user-facing helper SDK unless it is a very small local utility needed
  by tests; the primary deliverable is transmission of runtime context.

## Required Implementation Order

1. Add protocol/runtime-context model and tests.
2. Move run-payload construction inside each executor's per-node/per-execution
   loop and add runtime context to server-created Scrapy and Python wheel outbox
   payloads.
3. Inject Scrapy runtime context as per-job Scrapy settings in the agent.
4. Inject Python wheel runtime context as child process env in the agent.
5. Update docs/comments and add focused tests.

## Acceptance Criteria

- Scrapy executions receive `DOPILOT_TASK_ID` and `DOPILOT_EXECUTION_ID` as
  Scrapy settings with the actual Dopilot task/execution IDs for that run.
- Python wheel executions receive the same keys as environment variables.
- `DOPILOT_RUNTIME_CONTEXT` contains the same canonical context JSON in both
  execution paths.
- A user-supplied Scrapy `-s DOPILOT_TASK_ID=...` cannot override the platform
  value.
- A Python wheel payload env value such as `DOPILOT_TASK_ID=forged` cannot
  override the platform value.
- Existing Scrapy command behavior and Python wheel command behavior remain
  compatible.
- No database migration is introduced unless Claude identifies a concrete need
  during feasibility review.

## Required Tests

- Protocol unit tests for runtime-context serialization and string-map
  conversion.
- Server tests proving Scrapy and Python wheel outbox payloads include runtime
  context with the concrete `task_id`, `execution_id`, and `agent_id`.
- Agent Scrapy command-consumer test proving runtime context reaches
  `scrapyd.schedule(... settings=...)`.
- Agent Python wheel runner/consumer test proving runtime context reaches child
  env and reserved `DOPILOT_*` keys are not overridden by payload env.
- Existing Scrapy and Python wheel tests must continue to pass.

## Required Commands

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests
.venv/bin/ruff check apps packages
```

If frontend files are touched, also run:

```bash
corepack pnpm --filter web test
corepack pnpm --filter web build
```

## Risks To Watch

- Scrapy per-job context must not be implemented by mutating agent or scrapyd
  process environment; that would be unsafe with concurrent jobs.
- The field names must be stable because user workloads will depend on them.
- Future custom env support must reserve `DOPILOT_*` so users cannot forge
  platform runtime context.
- `DOPILOT_RUNTIME_CONTEXT` JSON ordering should be deterministic in tests.
