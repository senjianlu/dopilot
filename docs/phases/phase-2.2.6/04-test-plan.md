# Phase 2.2.6 — Test Plan

## Focused Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_config.py apps/agent/tests/test_heartbeat_worker.py
```

Expected coverage:

- `DOPILOT_SERVER_URL` overrides TOML `[agent].server_url`.
- unset `DOPILOT_SERVER_URL` keeps TOML unchanged.
- heartbeat worker still builds heartbeat URLs from `settings.agent.server_url`.

## Agent Regression Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
```

Expected coverage:

- no regression across agent auth/API/Redis/runner/cache behavior.

## Static And Compose Checks

```bash
.venv/bin/ruff check apps packages
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 DOPILOT_SERVER_URL=http://server.example:5000 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

Expected:

- lint passes;
- first compose renders and includes `DOPILOT_SERVER_URL`;
- rendered agent-only compose has no `DOPILOT_CONFIG` and no
  `DOPILOT_ADMIN_API_TOKEN`;
- second compose fails because `DOPILOT_SERVER_URL` is required;
- no whitespace errors.
