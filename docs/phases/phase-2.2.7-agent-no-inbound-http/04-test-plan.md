# Phase 2.2.7 — Test Plan

## Required Verification

- Lint changed Python code:
  `ruff check apps packages`
- Protocol regression:
  `pytest packages/protocol/tests`
- Agent daemon and healthcheck regression:
  `pytest apps/agent/tests`
- Server regression:
  `pytest apps/server/tests`
- Deployment config:
  `docker compose -f deploy/docker/docker-compose.yml config`
  `docker compose -f deploy/docker/docker-compose.agent.yml config` with the
  required environment values supplied.
- Residue checks:
  - no active deploy/config `6800` reference;
  - no active `AgentClient`, `get_agent_client`, `deploy_egg`,
    `EggDeployResponse`, or `require_agent_token` reference;
  - no local `6800` listener.

## Coverage Expectations

- Agent daemon starts and stops without an HTTP listener.
- Redis workers are wired and stopped in reverse order.
- Healthcheck succeeds/fails based on local managed scrapyd readiness and config
  validity.
- Heartbeat sends no advertised endpoint, so server falls back to
  `agent://{agent_id}`.
- Server artifact upload/download APIs remain intact.
