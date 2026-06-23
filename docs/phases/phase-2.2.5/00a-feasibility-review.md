# Phase 2.2.5 — Feasibility Review

## Claude Verdict

Feasible. Root cause analysis is correct, and the proposed fix is sufficient.

## Confirmed Root Cause

The agent entrypoint does this correctly at startup:

```python
settings = load_settings(default_path=DEFAULT_CONFIG_PATH)
uvicorn.run(create_app(settings), ...)
```

That lets the container intentionally run without `DOPILOT_CONFIG`, because the
image bakes `/app/configs/agent.toml`.

However, `create_app(settings)` currently only uses the injected settings to
build `app.state.runtime`. It does not inject the same settings into FastAPI's
`get_settings` dependency path.

Request handlers such as `/health` and agent auth dependencies call:

```python
Depends(get_settings)
```

`get_settings()` calls bare `load_settings()` with no explicit path and no
`default_path`. In a container that does not set `DOPILOT_CONFIG`, this raises:

```text
ConfigError: no config path provided; set DOPILOT_CONFIG or pass path explicitly
```

So the agent process can start, but `/health` fails with 500.

## Confirmed Fix

In `apps/agent/dopilot_agent/main.py::create_app(settings)`, when `settings` is
not `None`, wire the same settings object into FastAPI dependency overrides:

```python
app.dependency_overrides[get_settings] = lambda: settings
```

This mirrors the server-side phase 2.2.4 fix and makes runtime settings and
request dependency settings consistent.

Keep the no-argument `create_app()` fallback unchanged.

## Test Requirement

Add a regression test that does **not** use the existing conftest helper which
manually overrides `get_settings`.

The test should:

- build a `Settings` object directly;
- call `create_app(settings)`;
- assert `app.dependency_overrides[get_settings]()` is that same object;
- call `/health` through `ASGITransport`;
- assert HTTP 200 and expected `agent_id`.

## Codex Decision

No user escalation is required for product/architecture. This is a bug fix for
the accepted deployment model: agent containers should run without
`DOPILOT_CONFIG` by using the baked default config path.

Proceed with a small implementation brief and bounded fix.
