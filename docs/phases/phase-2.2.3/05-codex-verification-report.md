# Phase 2.2.3 — Codex Verification Report

## Commands Run

| Command | Result |
| --- | --- |
| `PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_heartbeat_api.py apps/agent/tests/test_config.py apps/agent/tests/test_auth.py apps/agent/tests/test_heartbeat_worker.py` | PASS — 65 passed |
| `.venv/bin/ruff check apps packages` | PASS — All checks passed |
| `cd deploy/docker && docker compose config` | PASS — rendered successfully |
| `PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest` | PASS — 485 passed |
| `cd deploy/docker && docker compose config \| rg 'DOPILOT_CONFIG\|DOPILOT_ADMIN_API_TOKEN\|DOPILOT_AGENT_TOKEN\|DOPILOT_AGENT_SHARED_TOKEN\|DOPILOT_SERVER_SHARED_TOKEN'` | PASS — expected token-only output |
| `git diff --check` | PASS — no whitespace errors |

## Compose Filter Output

```text
DOPILOT_AGENT_TOKEN: change-me-agent-token
DOPILOT_AGENT_TOKEN: change-me-agent-token
DOPILOT_AGENT_TOKEN: change-me-agent-token
DOPILOT_ADMIN_API_TOKEN: change-me-admin-api-token
DOPILOT_AGENT_TOKEN: change-me-agent-token
```

Interpretation:

- every agent receives only `DOPILOT_AGENT_TOKEN`;
- server receives `DOPILOT_ADMIN_API_TOKEN` and `DOPILOT_AGENT_TOKEN`;
- no `DOPILOT_CONFIG`;
- no `DOPILOT_AGENT_SHARED_TOKEN`;
- no `DOPILOT_SERVER_SHARED_TOKEN`.

## Notes

`.venv/bin/pytest` has a stale shebang in this environment, so tests were run
with `.venv/bin/python -m pytest`.
