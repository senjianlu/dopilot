# 00 · Phase 1.6 brief（Web health + crawler artifacts）

> Phase 1.6 starts after phase 1.5 acceptance commit
> `d3b0b24 Complete phase 1.5 Redis Streams migration`.
>
> Keep the phase 1.5 Redis Streams architecture. Do not reintroduce server->agent
> HTTP run/status/tail. HTTP remains acceptable for Web/API, heartbeat, and
> authenticated artifact byte download.

## 1. Goals

Phase 1.6 makes the running system verifiable from the Web UI and introduces a
content-addressed Scrapy crawler artifact workflow.

Primary goals:

1. Fix the Redis blocking-read timeout bug and false healthy node display.
2. Make the dashboard show real server/PostgreSQL/Redis/node status.
3. Make node health an aggregate of heartbeat freshness and agent Redis
   transport/consumer health.
4. Add a crawler page that stores validated Scrapy eggs on the server filesystem,
   lists available crawler artifacts, and runs a selected artifact.
5. Add an agent artifact cache with concurrency-safe lock/tmp/ready semantics.
6. Add a built-in demo Scrapy spider egg for Web validation.
7. Remove unfinished placeholder navigation and make auth-enabled entry start at
   the login page.

## 2. P0: Redis timeout and aggregate health

### Problem

In compose, both agent and server repeatedly log `redis.exceptions.TimeoutError`
from idle `XREADGROUP BLOCK` calls. Redis is reachable and healthy; Redis
`CLIENT LIST` shows blocking `xreadgroup` clients.

Root cause: redis-py 8 defaults `socket_timeout` to roughly 5 seconds while
consumer `block_ms` is 5000 ms. Empty blocking reads can hit client read timeout
at the same boundary.

Separately, Web shows the agent as healthy because heartbeat only proves the
agent process can POST to the server. It does not prove Redis command
consumption, event publishing, or log publishing are healthy.

### Requirements

- Server and agent Redis client builders must set a read timeout safely above
  the longest blocking read, or use a dedicated blocking connection with no
  read timeout.
- `CommandConsumer`, `EventConsumer`, and `LogConsumer` must treat an idle
  blocking-read timeout as an empty poll or recoverable transport status, not as
  warning-level drain failure noise.
- Agent heartbeat `detail` must include Redis health, at minimum:

```json
{
  "redis": {
    "connected": true,
    "last_ok_at": "2026-06-19T00:00:00+00:00",
    "last_error": null,
    "command_consumer": {
      "running": true,
      "last_read_at": "2026-06-19T00:00:00+00:00"
    },
    "event_outbox": {
      "pending": 0
    },
    "log_publisher": {
      "running": true,
      "last_publish_at": "2026-06-19T00:00:00+00:00"
    }
  }
}
```

- Server node status must become aggregate:
  - heartbeat fresh within `[agents].heartbeat_timeout_seconds`;
  - `detail.redis.connected == true`;
  - command consumer running;
  - missing Redis detail is `degraded`/`unknown`, not a crash.
- Scheduling and artifact deploy/run target selection must not choose a node
  whose aggregate health is degraded.
- The nodes page refresh button must be fixed to reload current server-side node
  state. It must not pretend to update `last_seen_at`; only heartbeat updates
  `last_seen_at`.

## 3. Dashboard

Dashboard should show:

- server API status;
- online/healthy node count;
- PostgreSQL status and version;
- Redis status and version;
- no application version display for now.

Backend may extend `/api/v1/health` or add a dedicated dashboard status endpoint.
Prefer a concise API shape that the Web can render directly and tests can assert.

## 4. Crawler artifact store

### Server source of truth

Scrapy egg artifacts live on the server filesystem:

```text
/server-data/artifacts/scrapy/<sha256>.egg
/server-data/artifacts/scrapy/<sha256>.json
```

The JSON manifest is the source-of-truth metadata sidecar:

```json
{
  "sha256": "...",
  "filename": "demo.egg",
  "project": "demo",
  "version": "sha256-<short>",
  "spiders": ["clock"],
  "size_bytes": 12345,
  "uploaded_at": "2026-06-19T00:00:00+00:00",
  "valid": true
}
```

Rules:

- Same filename/name with different sha256 is allowed and appears as separate
  rows.
- Upload writes temp files first, validates, then atomically renames egg and
  manifest into place.
- Cleanup is out of scope.
- Existing `scrapy_artifacts` DB rows may be left for backward compatibility or
  used as a rebuildable cache, but DB is not artifact truth.

### Validation

The server must validate an uploaded egg before marking it usable. Validation
must at least prove the egg is a structurally valid Python zip/egg and determine
the available spider names. If full spider discovery requires executing code,
prefer a conservative validation path and document the boundary; do not execute
untrusted crawler code in the server process.

## 5. Agent artifact cache

Agent cache directory:

```text
/agent-data/artifacts/scrapy/<sha256>.egg
/agent-data/artifacts/scrapy/<sha256>.egg.lock
/agent-data/artifacts/scrapy/<sha256>.egg.ready
```

Rules:

- `.ready` is the only signal that the cache is complete and deployed locally.
- If `.ready` is absent, acquire the lock before downloading or deploying.
- Download to `<sha256>.egg.tmp.<pid>.<attempt_id>`.
- Verify sha256 before renaming to `<sha256>.egg`.
- Deploy to local scrapyd with `addversion`.
- Write `.ready` only after successful local deployment.
- Concurrent attempts for the same hash must not corrupt files or perform
  duplicate deployment work.
- If integrity check or deployment fails, do not write `.ready`; report a clean
  failed attempt event.

## 6. Run command contract

Scrapy run command payload should keep existing fields and add an artifact
object:

```json
{
  "task_type": "scrapy",
  "project": "demo",
  "spider": "clock",
  "version": "sha256-<short>",
  "settings": {},
  "args": {},
  "artifact": {
    "hash": "<sha256>",
    "filename": "demo.egg",
    "project": "demo",
    "version": "sha256-<short>",
    "size_bytes": 12345,
    "fetch_path": "/api/v1/artifacts/scrapy/<sha256>.egg"
  }
}
```

Agent behavior:

1. Ensure artifact cache and local scrapyd deployment.
2. Schedule spider using the artifact project/version/spider.
3. Emit existing accepted/running/terminal events.

Egg bytes must not be sent over Redis Streams.

## 7. Web changes

- Remove placeholder route/menu entries.
- Default auth-enabled entry should be login. After login, navigate to dashboard.
- Keep auth-off development behavior simple; redirecting directly to dashboard is
  acceptable when `/auth/me` reports auth off.
- Add crawler page under nodes in navigation.
- Move Scrapy run controls into crawler page.
- Crawler page is a table showing filename/name, spiders, hash, upload time,
  size, valid/degraded status, and action buttons.
- Run action opens a minimal run form for spider/settings/args/node strategy, or
  runs with sensible defaults if no extra input is needed.
- Remove the manual project field from UI.
- Replace version column with hash and upload time.

## 8. Built-in demo spider

Add a demo Scrapy project in the repository. It should include a spider that:

- runs for about 60 seconds;
- logs the current time once per second;
- exits successfully.

Dockerfile must build this demo spider into an egg and place it in the server
artifact directory or seed location so a clean compose stack can show a runnable
crawler without user upload.

Do not import or copy code from `reference/scrapydweb/`.

## 9. Out of scope

- Python script executor.
- Docker long-lived crawler executor.
- Artifact cleanup/retention UI.
- Multi-server HA or distributed locks.
- WebSocket.
- Storing egg bodies in PostgreSQL.
- Running untrusted crawler code in the server process for validation.

## 10. Required tests

Backend:

- Redis client timeout invariant for blocking consumers.
- Idle `XREADGROUP` timeout does not log warning stack traces or back off as a
  drain failure.
- Heartbeat with Redis degraded updates node state but excludes it from target
  selection.
- Old heartbeat without Redis detail is handled safely.
- Dashboard health reports PostgreSQL and Redis version/status.
- Upload valid egg writes `<hash>.egg` and `<hash>.json`.
- Invalid egg does not become runnable.
- Same filename with different contents creates separate hash entries.
- Artifact download endpoint returns bytes with auth.
- Run command includes artifact payload.
- Agent cache miss fetches, verifies, deploys, and writes `.ready`.
- Concurrent same-hash cache requests serialize on lock.
- Hash mismatch fails cleanly and does not write `.ready`.

Frontend:

- Dashboard renders server/PostgreSQL/Redis/node status and no version field.
- Nodes page refresh reloads nodes and displays aggregate/degraded status.
- Placeholder menu is gone.
- Auth-enabled default entry lands on login.
- Crawler page lists artifacts and can trigger run for selected hash.

Verification:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
```

Recommended smoke:

```bash
cd deploy/docker && docker compose up --build
```

Then verify that the demo crawler is visible in Web, can run, logs current time
once per second, and no idle Redis timeout stack traces appear in server/agent
logs.
