# Phase 2.2.5 Brief — Agent Default Config Dependency Injection

## Goal

Fix agent-only deployments where the container intentionally omits
`DOPILOT_CONFIG` and relies on the baked `/app/configs/agent.toml`.

The agent process currently starts because `main()` loads settings with
`load_settings(default_path=DEFAULT_CONFIG_PATH)`, but request-time dependencies
such as `/health` call `Depends(get_settings)`, which calls bare
`load_settings()` with no default path and raises:

```text
ConfigError: no config path provided; set DOPILOT_CONFIG or pass path explicitly
```

## Confirmed Root Cause

Claude feasibility confirmed:

- `main()` loads the correct baked default config path.
- `create_app(settings)` builds `app.state.runtime` from the injected settings.
- `create_app(settings)` does not inject that settings object into FastAPI's
  `get_settings` dependency path.
- `/health` and agent auth dependencies both use `Depends(get_settings)`.
- Existing tests usually hide this because fixtures manually override
  `get_settings` after `create_app(settings)`.

## In Scope

- In `apps/agent/dopilot_agent/main.py::create_app(settings)`, when `settings` is
  not `None`, set:

  ```python
  app.dependency_overrides[get_settings] = lambda: settings
  ```

- Keep `create_app()` with no settings unchanged.
- Update the `create_app` / entrypoint docstring comments so they accurately
  describe the baked default config and dependency injection.
- Add a regression test that does not use the existing conftest app builder's
  manual dependency override:
  - build a `Settings` object directly or via `make_settings`;
  - call `create_app(settings)`;
  - assert `app.dependency_overrides[get_settings]()` is that settings object;
  - call `/health` through `ASGITransport`;
  - assert HTTP 200 and expected `agent_id`.

## Out Of Scope

- Changing agent config loading semantics.
- Reintroducing `DOPILOT_CONFIG` in compose.
- Server-side code.
- Docker image rebuild/publish.
- Old split token compatibility.
- Untracked `tmux.sh`.

## Required Verification

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_health.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
.venv/bin/ruff check apps packages
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

If Claude cannot run a command due its permission layer, it must report the
exact command and failure; Codex will run it.

## Acceptance Criteria

- Agent containers can run without `DOPILOT_CONFIG` and still serve `/health`.
- Runtime settings and `Depends(get_settings)` request dependencies share the
  same injected settings object when `create_app(settings)` is used.
- Existing test fixtures remain compatible.
- Agent-only compose remains free of `DOPILOT_CONFIG`.
