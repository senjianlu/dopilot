# Phase 2.2.7 Brief — Remove Agent Inbound HTTP / Port 6800

## Goal

Make `dopilot-agent` an outbound-only worker daemon. In the supported deployment
model, agents may run on separate hosts or in K3s where only agent-initiated
traffic to the server/Redis is available. The agent must not expose or listen on
an HTTP API, and port `6800` must disappear from the active runtime and deploy
surface.

## Confirmed Direction

- `dopilot-agent` no longer starts uvicorn/FastAPI and no longer listens on
  `6800`.
- Server -> agent HTTP egg deployment is removed. Scrapy eggs are stored and
  served by the server; agents fetch them from the server during Redis command
  execution via the existing `ScrapyArtifactCache.ensure()` path.
- Agent health is represented by agent -> server heartbeat and server-side
  `nodes.last_seen_at`. Container healthchecks are only local restart hints.
- Heartbeats should not advertise a network endpoint. Existing fallback
  `agent://{agent_id}` is the node identity; no DB migration is needed.
- `DOPILOT_AGENT_TOKEN` remains the machine token for agent -> server heartbeat
  and artifact/wheel fetches. Documentation must stop saying it authenticates a
  server -> agent direction.

## In Scope

### Agent runtime

- Replace the FastAPI/uvicorn entrypoint with a plain asyncio daemon.
- Preserve current runtime start/stop order:
  1. build settings/runtime;
  2. start managed scrapyd when configured;
  3. create Redis client and start command consumer/log publisher when Redis is
     configured;
  4. start heartbeat when server URL is configured;
  5. block until SIGTERM/SIGINT;
  6. stop log publisher, command consumer, Redis client, heartbeat, and scrapyd
     cleanly.
- Remove agent inbound API modules/endpoints:
  - `/health`;
  - `/artifacts/scrapy/egg`;
  - inbound bearer auth used only by that endpoint.
- Remove agent CLI `-b/--bind` and `-p/--port` flags.
- Remove no-longer-meaningful agent config fields:
  - `[agent].host`;
  - `[agent].port`;
  - `[agent].advertise_endpoint`.
- Add or update a local healthcheck command/module for containers. It should:
  - load the baked/default agent config with env overrides;
  - if `[scrapyd].start=true`, verify local scrapyd answers on its configured
    container-internal host/port;
  - exit non-zero on config load or managed scrapyd failure;
  - not open or require any agent HTTP listener.

### Server/runtime cleanup

- Delete the server `AgentClient` and lifespan `agent_client` construction.
- Ensure no server route or service expects to call an agent HTTP endpoint.
- Keep server artifact upload/download endpoints intact:
  - `POST /api/v1/artifacts/scrapy/egg`;
  - `GET /api/v1/artifacts/scrapy/{sha256}/egg`;
  - `POST/GET` wheel artifact paths.

### Protocol cleanup

- Remove `EggDeployResponse` if it becomes unused.
- Keep `HealthResponse`; the server health API still uses it.
- Keep heartbeat `endpoint` protocol field only if current server behavior needs
  it for compatibility; active agents should send `None`.

### Deploy/config/docs

- Update Dockerfile to expose only server HTTP (`5000`), not agent `6800`.
- Update all-in-one and agent-only compose files:
  - command becomes `dopilot-agent`;
  - remove `6800:6800`;
  - replace HTTP healthcheck with the local healthcheck command.
- Update config examples and docs so agent is described as outbound-only:
  - Redis command consumer;
  - agent -> Redis events/logs;
  - agent -> server heartbeat and artifact/wheel fetches;
  - no server -> agent HTTP exception.
- Update test fixtures/docs that use `http://a1:6800` as live examples. Pure UI
  sample strings may stay only if clearly not representing an active endpoint;
  prefer `agent://a1` where practical.

## Out Of Scope

- No DB migration.
- No new network identity mechanism beyond existing `agent://{agent_id}`.
- No changes to server artifact storage/download semantics.
- No token rotation, mTLS, Redis topology, or multi-replica server work.
- No Docker/K3s executor work.
- Do not fetch, vendor, copy, or import upstream scrapydweb code.

## Acceptance Criteria

- Running `dopilot-agent` starts the worker daemon and does not bind `6800` or
  any other agent HTTP port.
- Scrapy runs still fetch the egg from server by artifact `fetch_path`, deploy it
  to local scrapyd, then schedule the spider.
- Agent heartbeat still reaches server when `DOPILOT_SERVER_URL` is configured,
  and registered nodes use `agent://{agent_id}` when no endpoint is sent.
- Docker compose agent services do not publish or check `6800`.
- No production code references `AgentClient`, `get_agent_client`,
  `deploy_egg`, `EggDeployResponse`, `require_agent_token`, or agent
  `/artifacts/scrapy/egg`.
- Docs no longer describe `6800` or server -> agent HTTP as an active path.

## Required Tests And Verification

Run the narrowest passing set that covers the change, then broaden if needed:

```bash
ruff check apps packages
pytest apps/agent
pytest apps/server
pytest packages/protocol
cd deploy/docker && docker compose config
cd deploy/docker && docker compose -f docker-compose.agent.yml config
```

Also run targeted reference checks and record the output in the implementation
report:

```bash
rg -n "AgentClient|get_agent_client|deploy_egg|EggDeployResponse|require_agent_token|/artifacts/scrapy/egg" apps packages
rg -n "6800" apps/agent deploy configs docs/dopilot docs/refactor README.md
```

If a full compose smoke is too expensive in this pass, record that explicitly
and provide the manual command to prove no listener opens:

```bash
ss -ltnp | grep 6800 || echo "OK: no agent 6800 listener"
```
