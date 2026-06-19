# 00a · Phase 1.6 feasibility review

## Scope validated

Phase 1.6 covers Web verification polish and Scrapy artifact management after
the phase 1.5 Redis Streams migration:

- fix Redis blocking-read timeout noise and false healthy node state;
- expose aggregate node health via heartbeat details;
- improve dashboard status cards;
- replace direct egg deploy-on-upload with a server filesystem artifact store and
  agent cache-on-run;
- add a crawler page and move Scrapy run actions into that page;
- add a built-in demo Scrapy spider egg;
- remove placeholder navigation and default auth-enabled entry to login.

## Claude feasibility verdict

Feasible without changing the Redis Streams architecture, but it should be split
into two tracks:

- **P0 operational health**: Redis timeout handling + aggregate health is
  straightforward and should ship first.
- **Artifact store / crawler page**: feasible but larger than a UI-only change
  because it retires the current upload-immediately-deploy-to-agent behavior and
  adds a server artifact store plus an authenticated agent fetch/cache path.

## Findings

- Redis timeout root cause is the redis-py 8 default `socket_timeout=5` seconds
  colliding with `XREADGROUP BLOCK 5000`. Empty blocking reads can time out at
  the same boundary and are currently logged as drain failures.
- Agent and server consumer loops catch all exceptions generically, so an idle
  blocking read becomes a warning stack trace and adds unnecessary backoff.
- Agent heartbeat currently reports process/scrapyd details only. It does not
  report Redis transport, command consumer, event outbox, or log publisher
  health, so Web can show heartbeat-healthy while command consumption is
  degraded.
- Current artifact upload path forwards egg bytes directly to a selected agent
  via HTTP and records the deployed agent in `scrapy_artifacts`. This does not
  satisfy the new server-filesystem-source-of-truth model.
- Egg bytes should not travel over Redis Streams. Agent cache-on-run needs an
  authenticated HTTP fetch path from server to agent.

## Codex decisions

- Treat Redis timeout / false healthy as the first P0 implementation packet.
- Redis client construction must ensure blocking reads have `socket_timeout`
  greater than `block_ms`, or a dedicated blocking client with no read timeout.
  Timeout from an idle blocking read must be handled as an empty poll, not a
  warning-level failure.
- Extend heartbeat `detail` with a `redis` block. Server aggregates node status
  as heartbeat freshness plus Redis transport/consumer health. Missing `redis`
  detail from old agents renders degraded/unknown, not a crash.
- Artifact source of truth is filesystem, not database. Use sidecar manifests:
  `/server-data/artifacts/scrapy/<sha256>.egg` and `<sha256>.json`.
- `scrapy_artifacts` may remain as a non-authoritative cache/index only if useful,
  but the brief must not depend on DB as the artifact truth.
- Run command payload carries an `artifact` object with hash, project/version
  label for scrapyd, filename, size, and server fetch path. Agent ensures the
  artifact is cached and deployed before scheduling the spider.
- Agent cache uses tmp + lock + ready files:
  `<hash>.egg.tmp.<pid>.<attempt_id>`, `<hash>.egg.lock`,
  `<hash>.egg`, and `<hash>.egg.ready`.

## Open questions resolved without user escalation

- Same-name different-hash crawlers are allowed and shown as separate rows.
- Cleanup is explicitly deferred.
- The legacy direct deploy-on-upload path may be retired in phase 1.6 because the
  new model better matches the phase 1.5 Redis architecture and multi-agent
  behavior.

## Required tests

- Consumer idle `TimeoutError` does not log warning stack traces and does not
  back off as a drain failure.
- Redis socket timeout invariant is covered for agent and server clients.
- Fresh heartbeat with Redis degraded excludes a node from scheduling and shows
  degraded status in the nodes API.
- Old heartbeat without `detail.redis` is handled safely.
- Upload writes egg + manifest atomically and allows same filename with different
  hashes.
- Agent cache miss fetches under lock, validates sha256, deploys to scrapyd, and
  writes `.ready`.
- Concurrent same-hash runs on one agent do not corrupt or duplicate the cache.
- Run command with artifact hash deploys then schedules on an agent that did not
  previously have the egg.
