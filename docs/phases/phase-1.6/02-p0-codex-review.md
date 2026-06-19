# 02 · P0 Codex review

## Findings

No blocking findings after review.

## Review notes

- The original compose error was consistent with redis-py 8's default read
  timeout colliding with the existing 5000 ms blocking reads. Setting
  `socket_timeout=None` keeps blocking stream consumers from timing out when
  Redis is reachable but idle.
- The agent no longer reports healthy solely because it can POST an HTTP
  heartbeat. Heartbeat details now include Redis transport state, and server
  selection requires that state to be healthy.
- Fresh heartbeats without `detail.redis` are intentionally degraded. This makes
  older or partially started agents visible but not schedulable.
- Runtime status is intentionally in memory. It describes current transport
  health and is not business state.

## Test review

The P0 backend coverage verifies:

- server and agent Redis clients disable socket read timeout;
- heartbeat payload includes Redis status;
- heartbeat without Redis detail marks node degraded;
- nodes API renders missing Redis detail as degraded;
- scheduler/deploy node selection excludes missing or disconnected Redis detail;
- existing phase 1.5 server/agent/protocol behavior remains green.

Commands:

```bash
.venv/bin/python -m pytest -q apps/server/tests apps/agent/tests packages/protocol/tests
.venv/bin/python -m ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
```
