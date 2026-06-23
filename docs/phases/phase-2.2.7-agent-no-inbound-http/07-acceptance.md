# Phase 2.2.7 — Acceptance

## Accepted State

`dopilot-agent` is now an outbound-only daemon:

- no FastAPI/uvicorn agent runtime;
- no agent inbound API;
- no `/health` endpoint;
- no agent egg-deploy endpoint;
- no `6800` listener or published port;
- local container healthcheck uses `dopilot-agent-healthcheck`;
- server no longer has an `AgentClient` or server -> agent HTTP client wiring.

Scrapy eggs are stored on the server and fetched by the agent during Redis
command execution before local scrapyd scheduling.

## Verified

- `ruff check apps packages`
- `pytest packages/protocol/tests`
- `pytest apps/agent/tests`
- `pytest apps/server/tests`
- all-in-one compose config
- agent-only compose config with required env values
- no `6800` listener
- no active removed-symbol residue

## Residual Risk

A full live split-deployment smoke was not run. Recommended next release-gate
smoke: start server + Redis, join one remote/K3s agent, upload a Scrapy egg, run
a task, and confirm the node appears as `agent://{agent_id}`, heartbeats stay
fresh, artifact fetch succeeds, and no inbound agent port is open.
