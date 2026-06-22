# Phase 2.2.4 — Test Plan

## Targeted Server Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_agent_token.py apps/server/tests/test_heartbeat_api.py
```

Coverage expected:

- `server.data_dir` default, TOML, and `DOPILOT_SERVER_DATA_DIR` env override.
- `load_settings()` creates no generated token file.
- missing configured token generates and persists a token under
  `<data_dir>/secrets/agent-token`.
- generated token is long enough and persisted with owner-only permissions on
  POSIX.
- repeated resolution reuses the same persisted token.
- configured token wins and does not touch the generated file.
- runtime application flips machine auth on.
- `create_app(settings)` exposes the same generated-token settings through
  `get_settings`, so heartbeat auth enforces it.
- CLI default output includes `DOPILOT_AGENT_TOKEN=...`.
- CLI `--quiet` prints only the token.
- CLI does not require DB/Redis.

## Regression Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
git diff --check
```

Coverage expected:

- server/agent/protocol regression coverage after settings model changes;
- no stale imports or lint fallout;
- no whitespace errors.

## Compose Checks

```bash
cd deploy/docker && docker compose -f docker-compose.yml config
cd deploy/docker && docker compose -f docker-compose.server.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 DOPILOT_REDIS_URL=redis://:pw@example-redis:6379/0 docker compose -f docker-compose.agent.yml config
```

Expected:

- all-in-one renders with server and agents sharing `DOPILOT_AGENT_TOKEN`;
- server-only renders with empty `DOPILOT_AGENT_TOKEN`, allowing runtime
  generation;
- agent-only renders when required env is supplied;
- agent-only does not require `REDIS_PASSWORD` when `DOPILOT_REDIS_URL` is
  supplied;
- rendered agent-only contains no `DOPILOT_ADMIN_API_TOKEN`.

## Required-Failure Checks

```bash
cd deploy/docker && docker compose -f docker-compose.agent.yml config
cd deploy/docker && REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
```

Expected:

- no env fails because Redis info is missing;
- Redis password without `DOPILOT_AGENT_TOKEN` fails because agent token is
  required and has no dev fallback.

## CLI Smoke

Use a temp config with unreachable DB/Redis and `auth.disabled=true`; run:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client DOPILOT_CONFIG=<tmp>/server.toml .venv/bin/python -m dopilot_server.app agent-token print --quiet
```

Expected:

- exits 0 without DB/Redis;
- persists `<data_dir>/secrets/agent-token`;
- second run returns the same token;
- POSIX file mode is `600`.
