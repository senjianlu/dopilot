# Phase 2.2.5 Feasibility Prompt — Agent Default Config Dependency Injection

You are Claude Code doing feasibility validation only. Do not implement.

## Context

Read:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `apps/agent/dopilot_agent/main.py`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/agent/dopilot_agent/api/health.py`
- `apps/agent/dopilot_agent/auth/dependencies.py`
- `apps/agent/tests/conftest.py`
- `apps/agent/tests/test_health.py`
- `deploy/docker/Dockerfile`
- `deploy/docker/docker-compose.agent.yml`
- `deploy/docker/docker-compose.yml`

## User-Observed Failure

In an agent-only deployment, `/health` returns 500 and logs:

```text
dopilot_agent.config.loader.ConfigError: no config path provided; set DOPILOT_CONFIG or pass path explicitly
```

The stack trace shows FastAPI dependency resolution calling
`dopilot_agent.config.loader.get_settings()`, which calls bare `load_settings()`
without `default_path`.

## Current Understanding

- `apps/agent/dopilot_agent/main.py::main()` loads settings with
  `load_settings(default_path=DEFAULT_CONFIG_PATH)`.
- The Docker image bakes `/app/configs/agent.toml`.
- Compose intentionally does not set `DOPILOT_CONFIG`.
- `main()` then calls `create_app(settings)`.
- `create_app(settings)` builds `app.state.runtime` from the injected settings,
  but it does not override the `get_settings` dependency.
- Request handlers such as `/health` and auth dependencies use
  `Depends(get_settings)`, so they call cached `get_settings()` and then bare
  `load_settings()`, losing the default path.
- Existing tests usually override `get_settings` manually in fixtures, which may
  hide this real entrypoint path.

This looks analogous to the phase 2.2.4 server-side fix where
`create_app(settings)` injects the provided settings into the `get_settings`
dependency path.

## Proposed Fix

- In `apps/agent/dopilot_agent/main.py::create_app(settings)`, when `settings` is
  not `None`, set:

  ```python
  app.dependency_overrides[get_settings] = lambda: settings
  ```

- Keep direct `create_app()` with no settings unchanged.
- Existing test fixtures that set their own override after `create_app(settings)`
  should still win.
- Update docstrings/comments to say agent entrypoint falls back to the baked
  default config path and request dependencies share the injected settings.
- Add or update tests so this exact path is covered:
  - build `settings` with `make_settings(...)`;
  - call `create_app(settings)` without manually overriding `get_settings`;
  - call `/health`;
  - assert 200 and expected `agent_id`;
  - optionally assert `app.dependency_overrides[get_settings]()` is the injected
    settings object.

## Questions For Feasibility

Return only:

- Feasibility verdict.
- Whether the root cause analysis is correct.
- Any blockers or risky assumptions.
- Whether the proposed fix is sufficient.
- Whether any other agent dependencies or startup paths also need adjustment.
- Suggested exact files to change.
- Suggested focused tests/commands.

Do not implement.
