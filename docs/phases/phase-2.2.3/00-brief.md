# Phase 2.2.3 Brief — Single Agent Machine Token

## Goal

Simplify server-agent machine authentication to one token:

- `DOPILOT_ADMIN_API_TOKEN`: admin API only, server-side only.
- `DOPILOT_AGENT_TOKEN`: server-agent machine auth only, shared by server and
  every agent.

The project should no longer expose or support two directional machine-token
environment variables.

## Confirmed Product Decisions

- Abandon split machine tokens entirely:
  - no `DOPILOT_AGENT_SHARED_TOKEN`;
  - no `DOPILOT_SERVER_SHARED_TOKEN`;
  - no docs/comments encouraging split-token setup;
  - no fallback from admin token to machine token.
- Agents must never receive or derive from `DOPILOT_ADMIN_API_TOKEN`.
- `DOPILOT_AGENT_TOKEN` authenticates both directions:
  - server -> agent surviving egg-deploy HTTP path;
  - agent -> server heartbeat and artifact fetches.
- Non-empty `agent_token` shorter than 16 characters fails config loading.
- Docker Compose should keep default machine auth on with the dev-only default
  `${DOPILOT_AGENT_TOKEN:-change-me-agent-token}`.
- This phase does not implement generated enrollment tokens or `docker exec`
  helper commands. That is a later phase.

## In Scope

### Server Config And Auth

- Remove active `AgentAuthSettings` / `[agent_auth].shared_token`.
- Replace `[agents].server_shared_token` with `[agents].agent_token`.
- Add env override:
  - `DOPILOT_AGENT_TOKEN -> [agents].agent_token`.
- Remove env overrides:
  - `DOPILOT_AGENT_SHARED_TOKEN`;
  - `DOPILOT_SERVER_SHARED_TOKEN`.
- Delete machine-token fallback from `auth.admin_api_token`.
- Add loader validation:
  - empty/missing `agent_token` is allowed and keeps machine auth off;
  - non-empty `agent_token.strip()` length `< 16` raises `ConfigError`.
- Use `settings.agents.agent_token` in:
  - `apps/server/dopilot_server/app.py` when constructing `AgentClient`;
  - `apps/server/dopilot_server/auth/agent_dependencies.py` for heartbeat auth.

### Agent Config And Auth

- Replace `[agent].server_shared_token` and `[auth].shared_token` with one
  `[agent].agent_token`.
- Remove active agent `AuthSettings` if it becomes empty.
- Add env override:
  - `DOPILOT_AGENT_TOKEN -> [agent].agent_token`.
- Remove env handling for:
  - `DOPILOT_AGENT_SHARED_TOKEN`;
  - `DOPILOT_SERVER_SHARED_TOKEN`;
  - machine-token fallback from `DOPILOT_ADMIN_API_TOKEN`.
- Use `settings.agent.agent_token` in:
  - protected agent endpoint auth dependency;
  - heartbeat worker;
  - Scrapy/Python artifact cache clients.

### Config, Deploy, Docs

- Update:
  - `CLAUDE.md`;
  - `docs/dopilot/00-requirements.md`;
  - `docs/dopilot/03-gap-realtime-logs.md`;
  - `docs/dopilot/06-frontend-rewrite.md`;
  - `docs/dopilot/08-docker-deployment.md`;
  - `docs/refactor/00-redis-streams-agent-communication.md`;
  - `README.md`;
  - `README.zh-CN.md`;
  - `configs/server.example.toml`;
  - `configs/server.docker.toml`;
  - `configs/agent.example.toml`;
  - `deploy/docker/docker-compose.yml`.
- Docker Compose env:
  - server gets `DOPILOT_ADMIN_API_TOKEN` and `DOPILOT_AGENT_TOKEN`;
  - agents get `DOPILOT_AGENT_TOKEN` only, never `DOPILOT_ADMIN_API_TOKEN`.
- Compose must still not set `DOPILOT_CONFIG`.
- Live docs should clearly state token auth is not transport encryption; cross
  host encryption still requires TLS/VPN/private networks.

## Out Of Scope

- Server-generated token persistence.
- Agent enrollment CLI / `docker exec ... agent-token print`.
- Token rotation.
- TLS/VPN setup.
- Compatibility for old split envs.
- Historical phase record rewrites under `docs/phases/phase-2.2*`.
- Untracked `tmux.sh`.

## Expected Tests

### Server

- `apps/server/tests/test_config.py`
  - `DOPILOT_AGENT_TOKEN` populates `settings.agents.agent_token`.
  - old split envs are ignored.
  - `DOPILOT_ADMIN_API_TOKEN` no longer fills any machine token.
  - short non-empty `agent_token` raises `ConfigError`.
  - empty/missing `agent_token` leaves machine auth off.
- `apps/server/tests/test_heartbeat_api.py`
  - heartbeat auth uses `agents.agent_token`.
  - no token configured keeps machine auth off.
- Other tests updated away from `agent_auth.shared_token` /
  `agents.server_shared_token`.

### Agent

- `apps/agent/tests/test_config.py`
  - `DOPILOT_AGENT_TOKEN` populates `settings.agent.agent_token`.
  - old split envs and admin token are ignored for machine auth.
  - short non-empty `agent_token` raises `ConfigError`.
- `apps/agent/tests/test_auth.py`
  - protected agent endpoints use `agent.agent_token`.
- `apps/agent/tests/test_heartbeat_worker.py`
  - heartbeat/artifact auth headers use `agent.agent_token`.
- Test helpers updated to stop constructing removed config models/fields.

## Required Verification

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_heartbeat_api.py apps/agent/tests/test_config.py apps/agent/tests/test_auth.py apps/agent/tests/test_heartbeat_worker.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
cd deploy/docker && docker compose config | rg 'DOPILOT_CONFIG|DOPILOT_ADMIN_API_TOKEN|DOPILOT_AGENT_TOKEN|DOPILOT_AGENT_SHARED_TOKEN|DOPILOT_SERVER_SHARED_TOKEN'
git diff --check
```

If Claude cannot run a command due its permission layer, it must report the
exact command and failure; Codex will run it.

## Acceptance Criteria

- Admin token and agent token are separated:
  - server has both;
  - agents have only `DOPILOT_AGENT_TOKEN`.
- Old split envs have no effect.
- No active code path derives machine auth from `admin_api_token`.
- No active code path references removed split settings.
- Default compose renders with `DOPILOT_AGENT_TOKEN` and without
  `DOPILOT_CONFIG`.
- Tests and docs reflect the simplified two-token model.
