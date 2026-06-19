# 03 · Phase 1.6 implementation and review

## Implemented

### Operational health

- Fixed Redis blocking-read timeout noise by constructing server/agent Redis
  clients with no socket read timeout.
- Agent heartbeats now include Redis transport detail:
  command consumer, event outbox, and log publisher state.
- Server node status is aggregated from heartbeat freshness plus Redis transport
  health. Fresh nodes without Redis detail are `degraded`, not schedulable.
- Node selection for run/deploy excludes degraded Redis nodes.

### Dashboard and navigation

- `/api/v1/health` now returns server, PostgreSQL, Redis, and node-count status
  while retaining the legacy top-level fields.
- Dashboard shows server status, online node count, PostgreSQL status/version,
  and Redis status/version. App version is no longer shown.
- Default root route redirects to login.
- Placeholder navigation/page and standalone Scrapy run route/page were removed.

### Crawler artifacts

- Scrapy egg uploads now validate and store artifacts on the server filesystem:
  `/server-data/artifacts/scrapy/<sha256>.egg` and `<sha256>.json`.
- The manifest is the artifact source of truth and supports same filename with
  different hashes.
- Upload validation checks zip integrity and statically discovers spider names
  without executing crawler code in the server process.
- `GET /api/v1/artifacts/scrapy` lists manifests.
- `GET /api/v1/artifacts/scrapy/{sha256}/egg` lets authenticated agents fetch
  egg bytes.

### Agent cache and run

- Scrapy run payloads can carry an `artifact` object with hash/project/version
  and server fetch path.
- The agent cache uses `<hash>.egg`, `<hash>.egg.lock`,
  `<hash>.egg.tmp.<pid>.<attempt_id>`, and `<hash>.egg.ready`.
- `.ready` is written only after fetch, sha256 verification, and local scrapyd
  `addversion` succeed.
- Cache/deploy failures emit a clean failed attempt event and do not schedule
  the spider.
- The agent command consumer now also reconciles started local scrapyd attempts
  and emits terminal events when scrapyd reports finished/failed/canceled. This
  keeps execution records from staying `running` after the crawler process exits.

### Web crawler page

- Added a crawler page with upload, artifact table, hash/upload-time columns,
  spider list, validity state, and row-level run action.
- The old manual project/version Scrapy run form is removed from navigation and
  deleted.

### Built-in crawler

- Added `examples/scrapy_clock`, a Scrapy project with spider `clock` that runs
  for about 60 seconds and logs the current UTC time once per second.
- Dockerfile builds this project into an egg and writes the egg + manifest into
  `/server-data/artifacts/scrapy`.

## Codex review

No blocking findings remain.

Reviewed areas:

- Redis timeout fix addresses the observed redis-py 8 `socket_timeout` /
  `XREADGROUP BLOCK 5000` collision.
- Aggregate node health prevents the Web/API from treating HTTP heartbeat alone
  as schedulable health.
- Artifact upload no longer deploys to one arbitrary node, matching the
  server-source-of-truth model.
- Egg bytes are fetched over HTTP by the agent and not sent through Redis
  Streams.
- Same filename / different hash artifacts are represented as separate
  manifests.
- Live validation caught a missing agent-side completion watcher: scrapyd had
  logged `Process finished`, but the attempt remained `running` because the
  agent had only emitted `accepted/running`. The watcher fix was added and the
  existing live execution reconciled to `complete` after agent restart.

Residual risk accepted for this packet:

- If an agent process is killed while holding `<hash>.egg.lock`, later same-hash
  runs wait until timeout and fail cleanly. Automatic stale-lock cleanup is left
  for the later artifact cleanup work.

## Verification

Passed:

```bash
.venv/bin/python -m pytest -q apps/server/tests apps/agent/tests packages/protocol/tests
# 247 passed

.venv/bin/python -m ruff check apps packages
# All checks passed

corepack pnpm --filter web test
# 5 files / 6 tests passed

corepack pnpm --filter web build
# built successfully

cd deploy/docker && docker compose config
# valid compose config
```

Additional validation:

```bash
cd examples/scrapy_clock && ../../.venv/bin/python setup.py bdist_egg
# built dist/dopilot_clock-1.0.0-py3.12.egg successfully
```

Docker build note:

```bash
docker build -f deploy/docker/Dockerfile -t dopilot:phase-1.6-check .
```

did not reach the Dockerfile execution steps because the configured registry
returned EOF while resolving `node:22-slim` metadata. This is an external image
registry failure; the local egg build command above validates the new Scrapy
project packaging step.
