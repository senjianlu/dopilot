# Phase 2.2.5 — Claude Implementation Report

## Summary

Fixed agent-only deployments that intentionally omit `DOPILOT_CONFIG` and rely
on the baked `/app/configs/agent.toml`. `main()` already loaded the correct
baked default at startup, but `create_app(settings)` did not wire that same
settings object into FastAPI's `get_settings` dependency path. Request-time
dependencies (`/health`, agent auth) therefore fell back to bare
`load_settings()`, which raised `ConfigError: no config path provided` when no
`DOPILOT_CONFIG` was set. The fix injects the explicit settings object into
`app.dependency_overrides[get_settings]`, mirroring the server-side phase 2.2.4
behavior.

## Changed Files

- `apps/agent/dopilot_agent/main.py`
  - In `create_app(settings)`, after building `app.state.runtime`, add:
    `if settings is not None: app.dependency_overrides[get_settings] = lambda: settings`.
  - The no-argument `create_app()` path is unchanged (no override is set; it
    still resolves via the cached `get_settings` dependency).
  - Updated the `create_app` docstring and the module/`main()` docstrings to
    describe the baked default config and the dependency injection.
- `apps/agent/tests/test_health.py`
  - Added regression test `test_create_app_injects_settings_into_get_settings`.

## Behavior Implemented

- When `create_app(settings)` is called with an explicit `Settings` object (as
  `main()` does with the baked default config), the same object is used both to
  build `app.state.runtime` and to satisfy `Depends(get_settings)` request
  dependencies. Runtime settings and request-dependency settings are now the
  same object.
- An agent container with no `DOPILOT_CONFIG` can serve `/health` (and other
  request paths) without falling back to a bare `load_settings()` that would
  raise `ConfigError`.
- `create_app()` with no settings is unchanged, preserving the cached-singleton
  resolution path.

## Tests Added/Updated

- Added `test_create_app_injects_settings_into_get_settings` in
  `apps/agent/tests/test_health.py`. It deliberately does **not** use the
  conftest app builder (`_build_app` / `build_client`), which masks the bug by
  manually overriding `get_settings` after `create_app()`. The test:
  - builds a `Settings` via `make_settings`;
  - calls `create_app(settings)`;
  - asserts `app.dependency_overrides[get_settings]() is settings`;
  - drives `/health` through `httpx` `ASGITransport`;
  - asserts HTTP 200 and `agent_id == "agent-test-1"`.

## Commands Run and Outcomes

| Command | Outcome |
| --- | --- |
| `.venv/bin/ruff check apps packages` | **Passed** — `All checks passed!` |
| `git diff --check` | **Passed** — no output (no whitespace errors) |

## Skipped / Blocked Commands

The following required commands were blocked by the local permission layer
(returned `This command requires approval`); they were not run. Reported
verbatim for Codex to execute:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_health.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
```

Notes on the blocks:

- All `pytest` invocations were blocked (both with and without the `PYTHONPATH`
  prefix, and a plain `.venv/bin/python -c` import check was blocked too).
- The `docker compose ... config` command was blocked at the
  `DOPILOT_AGENT_TOKEN=... REDIS_PASSWORD=... docker compose ...` operation.

No command was silently substituted. `ruff` and `git diff --check` were run as
specified and passed.

## Unresolved Risks

- The agent test suite (`test_health.py`, `test_config.py`, full `apps/agent/tests`)
  was not executed locally due to the permission block, so the new regression
  test's green status and the absence of fixture regressions are unverified on
  this machine. The change is minimal and additive (override only set when
  `settings is not None`), and existing fixtures set their own
  `get_settings` override after `create_app()`, which still takes precedence
  (last assignment wins, and the conftest assigns after `create_app`). Codex
  should run the blocked pytest commands to confirm.
- `docker compose config` for the agent-only file was not validated locally;
  no compose changes were made (out of scope), so the agent-only compose
  remains free of `DOPILOT_CONFIG`.
