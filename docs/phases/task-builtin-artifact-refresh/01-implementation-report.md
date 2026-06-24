# Implementation Report: Built-In Artifact Refresh

## Changed Files

- `apps/server/dopilot_server/services/builtin_artifacts.py`
- `apps/server/dopilot_server/app.py`
- `apps/server/tests/test_builtin_artifacts.py`
- `deploy/docker/Dockerfile`
- `examples/scrapy_clock/dopilot_clock/spiders/clock.py`
- `tests/fixtures/python_wheel_demo/main.py`
- `tests/fixtures/python_wheel_demo/dopilot_demo-0.1.0-py3-none-any.whl`
- `docs/phases/task-builtin-artifact-refresh/*`

## Summary

- Added a startup import helper for built-in artifacts under
  `/app/builtin-artifacts` (or `DOPILOT_BUILTIN_ARTIFACTS_DIR`).
- Wired server startup to import built-ins before Redis workers start.
- Made import content-hash based and truly idempotent:
  - complete same-hash store + DB state is a no-op;
  - missing store files are repaired;
  - same-hash existing DB metadata is preserved;
  - changed bytes create new artifact rows;
  - corrupt built-ins fail startup.
- Updated Docker build to copy the built-in Scrapy egg and default demo wheel to
  `/app/builtin-artifacts`.
- Updated `dopilot_clock` to default to 45 seconds and log `DOPILOT_*` env and
  Scrapy settings at run start.
- Updated and rebuilt `dopilot-demo` wheel so it logs all `DOPILOT_*` env vars
  at run start.

## Commands Run

- `PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest apps/server/tests/test_builtin_artifacts.py apps/server/tests/test_artifacts.py`
  - `10 passed`
- `PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest apps/server/tests/test_builtin_artifacts.py`
  - `7 passed`
- `PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest apps/server/tests/test_builtin_artifacts.py apps/server/tests/test_artifacts.py apps/server/tests/test_python_wheel.py apps/server/tests/test_executions.py apps/agent/tests/test_python_wheel.py::test_wheel_run_injects_runtime_context_env_last apps/agent/tests/test_command_consumer.py::test_run_injects_runtime_context_as_scrapy_settings packages/protocol/tests/test_schemas.py::test_runtime_context_serialization_and_carriers`
  - `42 passed`
- `PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest packages/protocol/tests apps/server/tests apps/agent/tests`
  - `520 passed`
- `.venv/bin/ruff check apps packages`
  - passed
- `git diff --check`
  - passed
- `cd deploy/docker && docker compose config`
  - passed

## Notes

- `.venv/bin/pytest` remains unusable in this checkout due to the stale shebang
  noted in the previous task, so verification used `.venv/bin/python -m pytest`.
