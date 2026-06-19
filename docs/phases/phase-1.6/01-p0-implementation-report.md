# 01 · P0 implementation report

## Scope

Implemented only the phase 1.6 P0 operational-health packet:

- Redis blocking-read timeout fix for server and agent clients.
- Agent Redis runtime health surfaced through heartbeat detail.
- Server aggregate node health and scheduling exclusion for degraded Redis
  transport.
- Backend tests for the new health behavior and Redis client invariant.

Crawler artifact store/cache/page, dashboard cards, auth entry routing, and
navigation cleanup remain in the later phase 1.6 packets.

## Governance note

Codex attempted two Claude implementation handoffs for this P0 packet. The first
was blocked by Claude tool-permission handling; the second ran without producing
usable file changes or a report. Because the user explicitly asked not to block
on further confirmation and the Redis false-healthy bug was P0, Codex performed
the bounded implementation directly and reviewed the resulting diff/tests.

## Changes

- `RedisStreams.from_url()` now passes `socket_timeout=None` on both server and
  agent, avoiding redis-py 8's default read timeout colliding with
  `XREADGROUP BLOCK 5000`.
- Agent has a shared `RedisRuntimeStatus` object updated by:
  - `CommandConsumer` for running/read/error state;
  - `EventPublisher` for Redis publish status and outbox pending count;
  - `LogPublisher` for running/publish/error state.
- `HeartbeatWorker` includes `detail.redis` when Redis is configured.
- Server node status is now computed from heartbeat freshness plus
  `detail.redis.connected == true` and `command_consumer.running == true`.
- Missing or disconnected Redis detail marks a fresh node `degraded`.
- `select_target_nodes()` and `pick_deploy_node()` exclude degraded nodes.
- Web API TypeScript node status type now includes `degraded`.

## Verification

Passed:

```bash
.venv/bin/python -m pytest -q apps/server/tests apps/agent/tests packages/protocol/tests
# 243 passed

.venv/bin/python -m ruff check apps packages
# All checks passed

corepack pnpm --filter web test
# 6 files / 7 tests passed

corepack pnpm --filter web build
# built successfully

cd deploy/docker && docker compose config
# valid compose config
```

## Residual work

- Web nodes page still needs explicit refresh UX verification and status label
  treatment for `degraded`.
- Dashboard/database/Redis status cards are not implemented in this P0 packet.
- Crawler artifact store, upload validation, agent cache, demo spider, and run
  relocation are not implemented yet.
