# Test Plan: Task Runtime Context

## Coverage Goals

- Protocol serialization: runtime context fields, deterministic compact JSON,
  nullable field rendering, and carrier maps.
- Server dispatch: Scrapy and Python wheel outbox payloads include concrete
  runtime context after per-node execution creation.
- Agent Scrapy path: runtime context is injected as Scrapy settings and
  overrides user-supplied `-s DOPILOT_*` values.
- Agent Python wheel path: runtime context is injected into child env and
  overrides forged payload env values.
- Regression: existing protocol, server, and agent tests continue to pass.

## Commands

```bash
PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest packages/protocol/tests/test_schemas.py apps/server/tests/test_executions.py::test_run_dispatches_command_execution_queued apps/server/tests/test_python_wheel.py::test_wheel_run_dispatches_python_wheel_command apps/agent/tests/test_command_consumer.py::test_run_injects_runtime_context_as_scrapy_settings apps/agent/tests/test_python_wheel.py::test_wheel_run_injects_runtime_context_env_last
PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest packages/protocol/tests apps/server/tests apps/agent/tests
.venv/bin/ruff check apps packages
git diff --check
```

## Notes

The nominal `.venv/bin/pytest ...` command is currently not executable in this
checkout because the script has a stale shebang. Use `.venv/bin/python -m
pytest ...` with the explicit `PYTHONPATH` shown above until the local venv is
regenerated.
