# Phase 2.2.7 — Codex Review

**Reviewer:** Codex  
**Date:** 2026-06-23

## Findings

No blocking code findings after review.

One documentation consistency issue was found during review: several active docs
and config comments still described `DOPILOT_AGENT_TOKEN` as authenticating both
directions, including the removed server -> agent egg-deploy path. Codex fixed
those comments directly in:

- `CLAUDE.md`
- `README.md`
- `configs/server.example.toml`
- `configs/server.docker.toml`
- `docs/dopilot/03-gap-realtime-logs.md`
- `docs/dopilot/06-frontend-rewrite.md`
- `docs/dopilot/08-docker-deployment.md`
- `docs/refactor/00-redis-streams-agent-communication.md`

The remaining `6800` matches in current docs are explicit "removed" statements
or phase-1 historical/superseded references. The active deploy/config surface no
longer publishes or checks `6800`.

## Review Notes

- `dopilot-agent` no longer imports or starts FastAPI/uvicorn. `run_agent()`
  owns the daemon lifecycle and preserves the former lifespan ordering.
- Agent inbound API/auth modules were deleted. Server `AgentClient` wiring was
  deleted. `EggDeployResponse` was removed from protocol exports.
- The existing agent-pull artifact path remains intact:
  `ScrapyArtifactCache.ensure()` fetches server artifacts and deploys them to
  local scrapyd before scheduling.
- `dopilot-agent-healthcheck` is a local exec check. It loads config and checks
  local managed scrapyd `daemonstatus.json`; real cluster liveness remains
  heartbeat-based.

## Residual Risk

No full live server + Redis + agent smoke was run in this Codex review. Unit
tests cover the daemon wiring and the command consumer path, and compose config
validates the deployment shape. A live split-deployment smoke is still useful
before tagging a release image.
