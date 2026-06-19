# 02 · Codex review（阶段 1.5）

## Scope reviewed

- Active brief: `docs/phases/phase-1.5/00-brief.md`
- Claude result source: `/tmp/dopilot-phase-1.5-results.md`
- Implementation report: `docs/phases/phase-1.5/01-implementation-report.md`
- Authority: `docs/refactor/00-redis-streams-agent-communication.md`
- Diff scope: current staged phase-1.5 Redis Streams implementation plus the small `CLAUDE.md` doc correction made during this review.

Reviewed high-risk paths:

- server command outbox / dispatcher / run dispatch / cancel;
- agent command consumer / two-phase attempt state / event outbox / log publisher;
- server event consumer / log consumer / heartbeat and event-stall reconcile;
- heartbeat API and node selection;
- Alembic `0003_redis_streams`;
- compose Redis service and server/agent config;
- removal or legacy isolation of server->agent HTTP run/status/tail.

## Findings

### P0 / Blocking

- None.

### P1 / Must fix

- None.

### P2 / Fixed during review

- `CLAUDE.md` still carried stale project status and image publishing guidance. It said there was no dopilot application code yet and described separate `rabbir/dopilot-agent:latest` publishing, while the current source of truth uses the application code in `apps/` + `packages/` and one unified `rabbir/dopilot:latest` image. Codex updated `CLAUDE.md` to match `docs/dopilot/00-requirements.md` and `deploy/docker/docker-compose.yml`.

## Review notes

- The old server->agent HTTP run/status/tail/log-cleanup paths are removed or reduced to legacy documentation/types. The surviving HTTP exception is egg deploy via agent `/addversion.json`; agent `/health` remains for container healthcheck.
- Redis command dispatch follows the producer-outbox model: business rows and outbox commit before XADD; dispatcher XADD is at-least-once and agent idempotency is keyed by `attempt_id`.
- Manual Redis dispatch failure returns explicit 503 and marks execution/attempt failed; XADD-success plus sent-mark commit loss returns 202 `dispatch_unknown`.
- Agent command processing implements `reserved -> started -> done`, pending claim recovery, duplicate command republish, `spawn_aborted`, cancel/reclaim split, and cleanup command handling.
- Status event handling prevents terminal regression, allows server-lost soft terminal override by agent hard terminal, records dedupe/audit, and drives execution rollup.
- Log handling preserves the design distinction between agent logical offset (`last_pulled_offset`) and server physical file size (`final_offset`/`size_bytes`), with sticky `partial` on gaps.
- Reconcile no longer calls agent HTTP status/health. It uses heartbeat recency and event-stall clocks, emits server-lost, and enqueues reclaim stop only when appropriate.

## Residual risks

- The dispatcher/cancel race is handled by `stop(intent=cancel)` convergence, not by a strict guarantee that a command racing with cancel can never enter Redis after a prior status read. This matches the accepted `dispatch_unknown` style risk model and is covered by idempotent agent cancel semantics, but it remains a concurrency edge to watch in higher-load integration.
- `reserved-orphan` remains an accepted TOCTOU limitation: a crash between scrapyd scheduling and local `started` persistence can leave an uncorrelated scrapyd orphan job while the attempt reports `spawn_aborted`.
- Pure `heartbeat_timeout` server-lost attempts are not cleaned until the agent recovers and reports enough state to reclaim or finalize safely. This avoids deleting logs/state for a still-running process, but leaves stale local agent files when an agent never returns.
- Full `docker compose up --build` end-to-end Scrapy smoke was not run in this Codex review pass. Unit/integration tests, compose config, and real PostgreSQL migrations were verified; full container smoke remains the final operational check.

## Required Claude follow-up

None. No blocking code findings remain.
