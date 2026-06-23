# Claude Feasibility Validation: Remove Agent Inbound HTTP / Port 6800

You are Claude Code working in the dopilot repository.

## Assignment

Validate feasibility only. Do not implement code in this step.

Codex and the user confirmed a deployment constraint: some real deployments run
the server on one VM and agents in a K3s cluster or another host, with only
agent-initiated connectivity to the server. The agent must not expose an HTTP
API for server-initiated calls, and the user chose the strict version: the agent
should stop starting an HTTP server entirely; port `6800` should be removed from
the active agent runtime/deploy surface.

## Current Investigation Summary

Codex found three classes of current `6800` / agent HTTP usage:

1. Real server -> agent HTTP residue:
   - `apps/server/dopilot_server/clients/agent.py` creates `AgentClient` for
     `POST /artifacts/scrapy/egg`.
   - `apps/server/dopilot_server/app.py` still creates this client in lifespan.
   - `apps/agent/dopilot_agent/api/artifacts.py` exposes
     `POST /artifacts/scrapy/egg` and forwards to local scrapyd
     `/addversion.json`.
   - `packages/protocol/dopilot_protocol/agent.py` still documents and exports
     `EggDeployResponse` for that endpoint.

2. Local agent healthcheck:
   - `apps/agent/dopilot_agent/api/health.py` exposes unauthenticated
     `GET /health`.
   - `apps/agent/dopilot_agent/main.py` creates a FastAPI app and the CLI starts
     uvicorn on `-p 6800`.
   - `deploy/docker/docker-compose.yml` and
     `deploy/docker/docker-compose.agent.yml` run `dopilot-agent -b 0.0.0.0 -p
     6800` and healthcheck `http://localhost:6800/health`.
   - `deploy/docker/Dockerfile` still `EXPOSE 5000 6800`.

3. Docs/tests/examples:
   - Tests and web fixtures use `http://a1:6800` mostly as sample node endpoint
     data.
   - Docs still say egg deploy is the HTTP exception and `/health` is container
     local.

Codex also found the replacement path already exists:

- Server stores and serves Scrapy eggs:
  `apps/server/dopilot_server/api/v1/artifacts.py`
  `GET /api/v1/artifacts/scrapy/{sha256}/egg`
- Server snapshots `fetch_path` into the run payload:
  `apps/server/dopilot_server/services/artifacts.py`
  `apps/server/dopilot_server/services/resolve.py`
- Agent consumes Redis run commands, then uses `ScrapyArtifactCache.ensure()` to
  fetch the egg from server and deploy it to local scrapyd before scheduling:
  `apps/agent/dopilot_agent/artifacts/cache.py`
  `apps/agent/dopilot_agent/redis/commands.py`

This suggests server -> agent egg push can be deleted rather than replaced with
a new mechanism.

## Proposed Direction

Remove the agent inbound HTTP runtime entirely:

- `dopilot-agent` should no longer start uvicorn/FastAPI or listen on port
  `6800`.
- Remove the active agent API router/endpoints for `/health` and
  `/artifacts/scrapy/egg`, unless a module remains only as dead legacy code with
  tests removed. Prefer deleting unused runtime code if feasible.
- Remove server `AgentClient` creation and the server -> agent egg deploy client.
- Keep Scrapy egg upload as server-side artifact storage only; runtime deploy to
  local scrapyd happens when an agent consumes a Redis run command and fetches
  the artifact from the server.
- Stop advertising agent HTTP endpoints in heartbeat; `endpoint` should be
  absent or become a non-network identity such as `agent://{agent_id}` if needed
  for node display/uniqueness.
- Change Docker/compose agent healthchecks away from HTTP `localhost:6800`.
  Prefer an exec/process-based check that proves the agent process is alive and,
  if practical, that local scrapyd is running when `[scrapyd].start=true`.
- Remove published `6800:6800` and `EXPOSE 6800` from deploy artifacts.
- Update docs/config examples/tests to describe agent as outbound-only:
  Redis command consumer + agent -> server heartbeat/artifact fetch + agent ->
  Redis events/logs.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md` decisions #11/#12/#13
- `docs/dopilot/10-roadmap.md` phase 1.5 communication notes
- `docs/refactor/00-redis-streams-agent-communication.md`
- Code paths listed above.

## Output Required

Write `docs/phases/phase-2.2.7-agent-no-inbound-http/00a-feasibility-review.md`
with:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing product or architecture decisions for Codex.
5. Suggested scope cuts or sequencing changes.
6. A concrete list of files/modules likely affected.
7. Recommended verification commands.

Keep the response concise and concrete. Focus on implementation feasibility and
hidden risks. If there are no blockers, say so clearly.
