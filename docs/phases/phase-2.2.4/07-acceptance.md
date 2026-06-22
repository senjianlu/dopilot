# Phase 2.2.4 — Acceptance

## Accepted Behavior

- Server runtime generates a strong `DOPILOT_AGENT_TOKEN` when none is
  configured.
- Generated token is persisted at `<server.data_dir>/secrets/agent-token` and
  reused across restarts.
- Configured `DOPILOT_AGENT_TOKEN` wins and does not touch the generated-token
  file.
- `load_settings()` remains side-effect-free.
- Generated token is applied to the runtime settings before app startup.
- `create_app(settings)` makes `Depends(get_settings)` return the same settings
  object, so outbound server→agent auth and inbound heartbeat auth agree.
- `dopilot-server agent-token print [--quiet]` reads or generates the same token
  without DB/Redis/ASGI startup.
- All-in-one compose remains explicit with shared `DOPILOT_AGENT_TOKEN`.
- New server-only compose can omit `DOPILOT_AGENT_TOKEN` and use runtime
  generation.
- New agent-only compose requires `DOPILOT_AGENT_TOKEN` and never receives
  `DOPILOT_ADMIN_API_TOKEN`.

## Verification

- Targeted tests: 55 passed.
- Full pytest suite: 502 passed.
- Ruff: passed.
- Compose config:
  - all-in-one: passed;
  - server-only: passed;
  - agent-only with `REDIS_PASSWORD`: passed;
  - agent-only with full `DOPILOT_REDIS_URL`: passed.
- Required-failure compose checks:
  - missing Redis info: failed as expected;
  - missing `DOPILOT_AGENT_TOKEN`: failed as expected.
- CLI smoke: passed, including reuse and mode `600`.
- `git diff --check`: passed.

## Remaining Out Of Scope

- Token rotation/revocation.
- Multiple valid agent tokens.
- Expiring enrollment tokens.
- Database-backed token storage.
- Agent-side token generation.
- TLS/VPN/private-network implementation.
- Compatibility for old split token env vars.
