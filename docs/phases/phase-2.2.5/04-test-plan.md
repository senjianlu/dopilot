# Phase 2.2.5 — Test Plan

## Focused Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_health.py apps/agent/tests/test_config.py
```

Expected coverage:

- `/health` shape and auth behavior remain correct;
- `create_app(settings)` injects the same settings object into `get_settings`;
- agent config loading remains unchanged.

## Agent Regression Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
```

Expected coverage:

- all agent API/auth/runner/Redis tests remain compatible with the new app
  factory dependency override.

## Static And Deploy Checks

```bash
.venv/bin/ruff check apps packages
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

Expected:

- lint passes;
- agent-only compose still renders;
- rendered agent-only compose contains no `DOPILOT_CONFIG`;
- no whitespace errors.
