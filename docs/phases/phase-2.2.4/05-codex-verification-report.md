# Phase 2.2.4 — Codex Verification Report

## Commands Run

| Command | Result |
| --- | --- |
| `PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_agent_token.py apps/server/tests/test_heartbeat_api.py` | PASS — 55 passed |
| `.venv/bin/ruff check apps packages` | PASS — All checks passed |
| `cd deploy/docker && docker compose -f docker-compose.yml config` | PASS — rendered |
| `cd deploy/docker && docker compose -f docker-compose.server.yml config` | PASS — rendered |
| `cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config` | PASS — rendered |
| `cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 DOPILOT_REDIS_URL=redis://:pw@example-redis:6379/0 docker compose -f docker-compose.agent.yml config` | PASS — rendered |
| `PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest` | PASS — 502 passed |
| `git diff --check` | PASS — no whitespace errors |
| `cd deploy/docker && docker compose -f docker-compose.agent.yml config` | Expected failure — missing Redis info |
| `cd deploy/docker && REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config` | Expected failure — missing `DOPILOT_AGENT_TOKEN` |

## Rendered Compose Token Filter

Filtered over all rendered compose outputs:

```text
/tmp/dopilot-compose-agent-url.yml: DOPILOT_AGENT_TOKEN only
/tmp/dopilot-compose-agent.yml: DOPILOT_AGENT_TOKEN only
/tmp/dopilot-compose-all.yml: agent services get DOPILOT_AGENT_TOKEN
/tmp/dopilot-compose-all.yml: server gets DOPILOT_ADMIN_API_TOKEN and DOPILOT_AGENT_TOKEN
/tmp/dopilot-compose-server.yml: server gets DOPILOT_ADMIN_API_TOKEN and empty DOPILOT_AGENT_TOKEN
```

Interpretation:

- agent-only compose does not inject `DOPILOT_ADMIN_API_TOKEN`;
- server-only compose leaves `DOPILOT_AGENT_TOKEN` empty, so runtime generation
  applies;
- all-in-one compose remains explicit because server and agents start together.

## CLI Smoke

Codex ran a temp-config smoke with unreachable DB/Redis:

- first `agent-token print --quiet` generated a token;
- second `agent-token print --quiet` returned the same token;
- `<data_dir>/secrets/agent-token` existed and was non-empty;
- POSIX mode was `600`.

## Notes

The `.venv/bin/pytest` console script still has a stale shebang in this
environment, so tests were run with `.venv/bin/python -m pytest`.
