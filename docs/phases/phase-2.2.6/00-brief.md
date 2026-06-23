# Phase 2.2.6 Brief — Agent Server URL Env Override

## Goal

Fix agent-only / K3s deployments where the baked agent config's
`server_url = "http://server:5000"` cannot resolve outside the all-in-one Docker
Compose network.

Agents must be able to receive the server HTTP base URL via environment variable
without mounting a custom TOML.

## In Scope

### Agent Config Loader

- Add env override:

  ```text
  DOPILOT_SERVER_URL -> [agent].server_url
  ```

- Env wins over TOML, following the existing loader pattern.
- Update loader docstring/comment listing env overrides.
- Do not rename the existing `[agent].server_url` field.
- Do not add validation beyond existing string parsing.

### Tests

- Add or update agent config tests:
  - `DOPILOT_SERVER_URL` overrides TOML `server_url`;
  - no env keeps TOML/default behavior unchanged.

### Agent-Only Compose

- Update `deploy/docker/docker-compose.agent.yml`:
  - document `DOPILOT_SERVER_URL` as required;
  - set `DOPILOT_SERVER_URL` in the agent environment with Compose `:?` required
    syntax;
  - keep `DOPILOT_AGENT_TOKEN` required;
  - keep Redis URL behavior unchanged;
  - do not set `DOPILOT_CONFIG`;
  - do not inject `DOPILOT_ADMIN_API_TOKEN`.

- Keep all-in-one `deploy/docker/docker-compose.yml` unchanged functionally:
  baked `http://server:5000` is correct inside that network.

### Docs

Update live deployment docs and README snippets as needed:

- `configs/agent.example.toml`
- `docs/dopilot/08-docker-deployment.md`
- `README.md`
- `README.zh-CN.md`

Docs must say:

- `DOPILOT_SERVER_URL` is an **agent-side** env var;
- it is the server HTTP base URL for heartbeat and artifact/wheel fetch;
- examples:

  ```text
  http://<server-ip-or-dns>:5000
  http://dopilot-server.dopilot.svc.cluster.local:5000
  https://dopilot.example.com
  ```

- token auth is not transport encryption; cross-host HTTP still needs
  private network/VPN/TLS/reverse proxy as appropriate.

## Out Of Scope

- K8s manifest generation.
- Server-side changes.
- Changing heartbeat protocol.
- Changing Redis URL behavior.
- Docker image rebuild/publish.
- Untracked `tmux.sh`.

## Required Verification

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_config.py apps/agent/tests/test_heartbeat_worker.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
.venv/bin/ruff check apps packages
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 DOPILOT_SERVER_URL=http://server.example:5000 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

Expected:

- Tests pass.
- First compose command renders and includes `DOPILOT_SERVER_URL`.
- Second compose command fails because `DOPILOT_SERVER_URL` is missing.
- Rendered agent-only compose contains no `DOPILOT_CONFIG` and no
  `DOPILOT_ADMIN_API_TOKEN`.

If Claude cannot run a command due its permission layer, it must report the
exact command and failure; Codex will run it.

## Acceptance Criteria

- Agent-side env `DOPILOT_SERVER_URL` can override `[agent].server_url`.
- Agent-only compose fails fast when `DOPILOT_SERVER_URL` is missing.
- Agent-only compose renders when `DOPILOT_SERVER_URL`, `DOPILOT_AGENT_TOKEN`,
  and Redis connection info are supplied.
- Docs explain the K3s/cross-host deployment requirement.
