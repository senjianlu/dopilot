# Phase 2.2.3 — Acceptance

## Accepted Behavior

- `DOPILOT_ADMIN_API_TOKEN` is admin API only and server-side only.
- `DOPILOT_AGENT_TOKEN` is the only server-agent machine token.
- Server config uses `[agents].agent_token`.
- Agent config uses `[agent].agent_token`.
- Old split env vars and config fields have no active effect.
- No active code path derives machine auth from the admin API token.
- Docker Compose injects:
  - server: `DOPILOT_ADMIN_API_TOKEN` and `DOPILOT_AGENT_TOKEN`;
  - agents: `DOPILOT_AGENT_TOKEN` only.
- Docker Compose still does not set `DOPILOT_CONFIG`.
- Non-empty admin and agent tokens must be at least 16 characters.
- Docs explain that token auth is not transport encryption; cross-host
  encryption still requires TLS, VPN, or a private network.

## Verification

- Targeted tests: 65 passed.
- Full pytest suite: 485 passed.
- Ruff: passed.
- Docker Compose config: passed.
- Compose token filter: passed.
- `git diff --check`: passed.

## Remaining Out Of Scope

- Generated enrollment tokens.
- `docker exec` helper for printing/joining agent tokens.
- Token rotation.
- TLS/VPN implementation.
- Backward compatibility for old split env vars.
