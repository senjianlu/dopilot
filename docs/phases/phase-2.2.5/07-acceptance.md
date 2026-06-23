# Phase 2.2.5 — Acceptance

## Accepted Behavior

- Agent containers can rely on the baked `/app/configs/agent.toml` without
  setting `DOPILOT_CONFIG`.
- `main()` loads settings with the baked default path.
- `create_app(settings)` now makes request-time `Depends(get_settings)` use the
  same injected settings object.
- `/health` no longer falls back to bare `load_settings()` in that deployment
  path.
- Existing app factory fixtures remain compatible.

## Verification

- Focused health/config tests: 22 passed.
- Full agent tests: 119 passed.
- Ruff: passed.
- Agent-only compose config: passed.
- Rendered agent-only compose contains no `DOPILOT_CONFIG`.
- `git diff --check`: passed.

## Remaining Out Of Scope

- Docker image rebuild/publish.
- Config loader semantic changes.
- Server changes.
- Compose changes.
