# Claude Implementation Report: Task Runtime Context

## Changed Files

- `packages/protocol/dopilot_protocol/execution.py`
- `packages/protocol/dopilot_protocol/__init__.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/executors/python_wheel.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/runners/python_wheel.py`
- `packages/protocol/tests/test_schemas.py`
- `apps/server/tests/test_executions.py`
- `apps/server/tests/test_python_wheel.py`
- `apps/agent/tests/test_command_consumer.py`
- `apps/agent/tests/test_python_wheel.py`
- `docs/phases/task-runtime-context/00-brief.md`
- `docs/phases/task-runtime-context/claude-progress.md`
- `docs/phases/task-runtime-context/01-claude-implementation-report.md`

## Implementation Summary

- Added shared `DopilotRuntimeContext` protocol model with stable fields,
  deterministic compact JSON serialization, and explicit `to_env_map()` /
  `to_scrapy_settings()` carrier methods.
- Added optional `runtime_context` to Scrapy and Python wheel run payloads.
- Built runtime context on the server after each concrete `create_execution(...)`
  call, inside the per-node loop, so `task_id`, `execution_id`, and `agent_id`
  are execution-specific.
- Injected Scrapy runtime context into per-job Scrapy settings after parsed user
  command settings, so user `-s DOPILOT_*` values cannot override platform
  values.
- Injected Python wheel runtime context into the child process environment at the
  runner's final env merge point, after task payload env, so forged
  `DOPILOT_*` payload values cannot override platform values.
- Documented the future Docker executor contract: inject the same runtime
  context map as container environment variables with platform keys winning at
  the final container-env merge point.

## Tests Added/Updated

- Protocol tests for runtime-context JSON determinism, nullable carrier values,
  Scrapy settings/env map conversion, and payload round trips.
- Server Scrapy dispatch test now asserts outbox payload runtime context matches
  the concrete task, execution, agent, artifact type, task type, source, and
  template/schedule IDs.
- Server Python wheel dispatch test now asserts the same concrete runtime
  context values.
- Agent Scrapy command-consumer test proves runtime context reaches
  `scrapyd.schedule(... settings=...)` and overrides a forged
  `DOPILOT_TASK_ID` command setting.
- Agent Python wheel test proves runtime context reaches the child env and
  overrides a forged payload env value.

## Commands Run And Outcomes

- `.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests`
  - Outcome: failed before pytest startup.
  - Exact failure: `/bin/bash: line 1: .venv/bin/pytest: cannot execute: required file not found`
  - Reason: `.venv/bin/pytest` has a stale shebang pointing at
    `/home/rabbir/dopilot/.venv/bin/python`; this checkout is
    `/home/rabbir/Projects/dopilot`.
- `.venv/bin/ruff check apps packages`
  - Outcome: passed.
  - Output: `All checks passed!`
- `PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest packages/protocol/tests apps/server/tests apps/agent/tests`
  - Outcome: passed.
  - Output summary: `513 passed in 13.95s`
- `PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest packages/protocol/tests/test_schemas.py apps/server/tests/test_executions.py::test_run_dispatches_command_execution_queued apps/server/tests/test_python_wheel.py::test_wheel_run_dispatches_python_wheel_command apps/agent/tests/test_command_consumer.py::test_run_injects_runtime_context_as_scrapy_settings apps/agent/tests/test_python_wheel.py::test_wheel_run_injects_runtime_context_env_last`
  - Outcome: passed.
  - Output summary: `15 passed in 0.53s`
- `.venv/bin/ruff check --fix packages/protocol/dopilot_protocol/execution.py`
  - Outcome: fixed one import-order issue.
- `.venv/bin/ruff check packages/protocol/dopilot_protocol/execution.py apps/server/dopilot_server/services/executions.py apps/server/dopilot_server/executors/scrapyd.py apps/server/dopilot_server/executors/python_wheel.py apps/agent/dopilot_agent/redis/commands.py apps/agent/dopilot_agent/runners/python_wheel.py packages/protocol/tests/test_schemas.py apps/server/tests/test_executions.py apps/server/tests/test_python_wheel.py apps/agent/tests/test_command_consumer.py apps/agent/tests/test_python_wheel.py`
  - Outcome: passed.
  - Output: `All checks passed!`
- `git diff --check`
  - Outcome: passed with no output.

## Unresolved Risks Or TODOs

- No code-level TODOs remain for this task.
- The local `.venv/bin/pytest` entrypoint should be regenerated outside this
  task scope if future runs must use the exact script path instead of
  `.venv/bin/python -m pytest`.
