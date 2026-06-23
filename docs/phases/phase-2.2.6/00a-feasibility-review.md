# Phase 2.2.6 — Feasibility Review

## Claude Verdict

Feasible and low-risk.

## Confirmed Root Cause

The user deploys server on one VM and agent in a K3s cluster. The agent image
uses the baked `/app/configs/agent.toml`, whose default is:

```toml
[agent]
server_url = "http://server:5000"
```

That hostname only resolves inside the all-in-one Docker Compose network. It
does not resolve from an agent-only deployment on another VM/K3s cluster, so the
heartbeat worker logs:

```text
httpx.ConnectError: [Errno -2] Name or service not known
```

The loader currently supports env overrides for `AGENT_ID`, `AGENT_WORKDIR`,
`DOPILOT_REDIS_URL`, and `DOPILOT_AGENT_TOKEN`, but not for `server_url`.

## Important Scope Note

`[agent].server_url` is not only for heartbeat. It is also the base HTTP endpoint
used by the agent artifact caches for Scrapy egg and Python wheel fetches. So
the fix should be described as the agent's server HTTP base URL for:

- heartbeat;
- artifact fetch;
- wheel fetch.

## Codex Decisions

- Add env override:

  ```text
  DOPILOT_SERVER_URL -> [agent].server_url
  ```

- This env is agent-side. Docs must make that clear.
- Keep all-in-one compose unchanged; baked `http://server:5000` is valid there.
- Make `DOPILOT_SERVER_URL` required in `deploy/docker/docker-compose.agent.yml`
  with Compose's `:?` syntax. Agent-only deployment should fail fast instead of
  silently using the invalid baked `http://server:5000`.
- Update docs to mention K3s/service examples, e.g.:

  ```text
  http://<server-ip-or-dns>:5000
  http://dopilot-server.dopilot.svc.cluster.local:5000
  https://dopilot.example.com
  ```

## No User Escalation Required

The user confirmed the real deployment shape and asked to fix it. The
implementation does not change product behavior; it adds a missing deployment
override for an already-existing config field.

## Suggested Verification

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_config.py apps/agent/tests/test_heartbeat_worker.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
.venv/bin/ruff check apps packages
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 DOPILOT_SERVER_URL=http://server.example:5000 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

The second compose command should fail because `DOPILOT_SERVER_URL` is required.
