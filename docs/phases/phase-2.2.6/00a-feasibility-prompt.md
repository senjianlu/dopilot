# Phase 2.2.6 Feasibility Prompt — Agent Server URL Env Override

You are Claude Code doing feasibility validation only. Do not implement.

## Context

Read:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/agent/dopilot_agent/config/settings.py`
- `apps/agent/dopilot_agent/redis/heartbeat.py`
- `apps/agent/tests/test_config.py`
- `deploy/docker/docker-compose.agent.yml`
- `configs/agent.example.toml`
- `docs/dopilot/08-docker-deployment.md`

## User-Observed Failure

The user runs the server on one VM and an agent in a K3s cluster. Agent `/health`
now returns 200 after phase 2.2.5, but heartbeat logs:

```text
heartbeat send failed
httpx.ConnectError: [Errno -2] Name or service not known
```

The heartbeat worker sends to:

```python
self._settings.agent.server_url.rstrip("/") + "/api/v1/agents/{agent_id}/heartbeat"
```

The baked agent config has:

```toml
[agent]
server_url = "http://server:5000"
```

That hostname is valid in all-in-one Docker Compose, but not in an agent-only
deployment on another VM/K3s cluster.

## Proposed Direction

Add an environment override:

```text
DOPILOT_SERVER_URL -> [agent].server_url
```

Use it in agent-only deployment docs/compose/K8s guidance so the operator can
point agents at the real server HTTP endpoint, e.g.

```text
http://<server-ip-or-dns>:5000
http://dopilot-server.dopilot.svc.cluster.local:5000
https://dopilot.example.com
```

Update `deploy/docker/docker-compose.agent.yml` so agent-only deployment requires
or clearly supports `DOPILOT_SERVER_URL`. Keep all-in-one compose unchanged:
inside that network, baked `http://server:5000` remains valid.

## Feasibility Questions

Return only:

- Feasibility verdict.
- Whether the root cause analysis is correct.
- Any blockers or risky assumptions.
- Whether `DOPILOT_SERVER_URL -> [agent].server_url` is sufficient.
- Whether agent-only compose should make `DOPILOT_SERVER_URL` required or
  optional with a default.
- Suggested exact files to change.
- Suggested focused tests/commands.

Do not implement.
