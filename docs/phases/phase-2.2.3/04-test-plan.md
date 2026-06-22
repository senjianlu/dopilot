# Phase 2.2.3 — Test Plan

## Purpose

Verify that dopilot has fully moved from split directional machine tokens to one
server-agent machine token while keeping the admin API token separate.

## Targeted Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_heartbeat_api.py apps/agent/tests/test_config.py apps/agent/tests/test_auth.py apps/agent/tests/test_heartbeat_worker.py
```

Coverage expected:

- server config maps `DOPILOT_AGENT_TOKEN` to `[agents].agent_token`;
- old split env vars have no effect;
- `DOPILOT_ADMIN_API_TOKEN` does not fill machine auth;
- short non-empty machine tokens fail config loading;
- heartbeat auth uses `agents.agent_token`;
- agent config maps `DOPILOT_AGENT_TOKEN` to `[agent].agent_token`;
- agent protected endpoints and heartbeat/artifact requests use
  `agent.agent_token`.

## Broader Regression Tests

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
```

Coverage expected:

- no shared server/agent/protocol regression from config model changes;
- no stale imports of removed settings models;
- lint catches unused imports and rename fallout.

## Deployment Configuration Checks

```bash
cd deploy/docker && docker compose config
cd deploy/docker && docker compose config | rg 'DOPILOT_CONFIG|DOPILOT_ADMIN_API_TOKEN|DOPILOT_AGENT_TOKEN|DOPILOT_AGENT_SHARED_TOKEN|DOPILOT_SERVER_SHARED_TOKEN'
git diff --check
```

Expected filtered compose output:

- 3 agent `DOPILOT_AGENT_TOKEN` entries;
- 1 server `DOPILOT_AGENT_TOKEN` entry;
- 1 server `DOPILOT_ADMIN_API_TOKEN` entry;
- no agent `DOPILOT_ADMIN_API_TOKEN`;
- no `DOPILOT_CONFIG`;
- no old split env vars.
