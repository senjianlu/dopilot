# 资源硬上限——全仓库审计清单(2026-07-24)

> 迁自旧治理流程草稿 docs/phases/task-resource-hard-limits/00-proposal.md(该文件将随实现删除);
> Phase D(运维页面量化监控)章节保留于此,供下一个任务复用。

## Audit: current unbounded-growth inventory

Full-repo audit (server, agent, deploy, docs), 2026-07-24. Verdicts:
**U** = unbounded, **P** = partially bounded, **B** = bounded (OK).

### Deployment layer (direct cause of the observed VM freeze)

| # | Surface | Evidence | Verdict |
|---|---------|----------|---------|
| D1 | Container stdout logs: **no `logging:` block on any service** in `deploy/docker/docker-compose.yml`, `docker-compose.server.yml`, `docker-compose.agent.yml` — Docker default `json-file` driver grows without limit | grep over `deploy/` finds zero `max-size`/`max-file`/`logging:` | **U** |
| D2 | Redis: `redis-server --appendonly yes --requirepass …` with **no `maxmemory` / `maxmemory-policy`** (`docker-compose.yml:113-118`, `server.yml:79-84`); no `redis.conf` in repo | Redis RAM + AOF on `dopilot-redis:/data` can grow until host OOM | **U** |
| D3 | No `mem_limit` / `deploy.resources` on any service | — | **U** (out of scope by default; see Open Questions) |

### Server (`apps/server`)

| # | Surface | Evidence | Verdict |
|---|---------|----------|---------|
| S1 | `/server-data/logs` bodies: append-only via `logs/files.py:163-187` ← `services/logs.py:88-93`; **no per-file cap, no directory cap** | `docs/dopilot/03-gap-realtime-logs.md:366` already *specifies* a 100 MB per-file cap — never implemented | **U** |
| S2 | Retention config is **inert**: `[logs].retention_days` (`config/settings.py:150`, env `DOPILOT_LOG_RETENTION_DAYS`) and column `execution_log_files.retained_until` (`models/execution.py:225`) have **no consumer**. The only cleanup is the manual operator API `POST /maintenance/terminal-cleanup` → `services/maintenance.py:86` (`cleanup_terminal_data`, phase 1.8.2, explicitly "manual, not automatic") | no scheduled sweep exists | **U** |
| S3 | `event_audit` table: one row per consumed agent status event (`services/events.py:156`); **no delete path anywhere** — not even in `cleanup_terminal_data`. Fastest-growing table | — | **U** |
| S4 | `tasks` / `executions` / `execution_log_files` / `command_outbox` rows: pruned only by the manual cleanup API | `services/maintenance.py:145-166` | **P** |
| S5 | Artifact uploads: both endpoints do unbounded `await file.read()` into RAM (`api/v1/artifacts.py:115`, `:158`); **no size cap**, no max-body middleware | validators check extension/zip only | **U** |
| S6 | SSE per-subscriber queue: `asyncio.Queue()` with no `maxsize`, `put_nowait` on publish (`logs/sse.py:27,46-49`); a stalled subscriber grows RAM. Registry itself self-cleans; 30-min connection cap exists (`api/v1/tasks.py:82`) | — | **P** |
| S7 | Redis stream producers pass `maxlen=…, approximate=True` (`redis/commands.py:24-30`); caps in `[redis] stream_maxlen_*` (`settings.py:83-85`). But `[redis].log_retention_seconds` (`settings.py:86`) is **inert** (no XTRIM MINID anywhere) | MAXLEN bound works | **B** (with inert time-bound knob) |
| S8 | Default mismatch: code `retention_days = 14` (`settings.py:150`) vs `configs/server.docker.toml:101` = 30 vs docs promising 30 | — | consistency bug |

### Agent (`apps/agent`)

| # | Surface | Evidence | Verdict |
|---|---------|----------|---------|
| A1 | Artifact + wheel caches `{workdir}/artifacts/**`: every egg sha and every wheel sha **plus its unpacked `site/` tree** kept forever; `.ready` marker makes reuse permanent; no eviction/LRU/TTL (`artifacts/cache.py`, `artifacts/wheel_cache.py:65-83,176-178`). Likely the largest agent disk sink | — | **U** |
| A2 | Wheel job `job.log`: `{workdir}/python_wheel/workspaces/{execution_id}/job.log`, append, **no size cap** (`runners/python_wheel.py:95-96,160-169`); workspace deleted **only** on server-driven `cleanup_logs` command (`redis/commands.py:660-672`); no startup sweep, orphan recovery does not delete dirs (`commands.py:171-204`) | docs `03-gap-realtime-logs.md:366` specify agent TTL fallback (completed 3 d / orphan 7 d) — **not implemented** | **U** |
| A3 | `.logpos` cursor files `{workdir}/state/logpos/*.logpos`: `_handle_cleanup` deletes log/workspace/state file but **never the cursor file** — one leaked file per execution forever (`redis/logs.py:62-63` vs `commands.py:660-672`) | — | **U** (small-file leak) |
| A4 | Event outbox `{event_outbox_dir}/*.json`: durable by design; during a long Redis outage file count grows without cap (`redis/events.py:91-129`; only counted in heartbeat, `:81-84`) | — | **P** |
| A5 | Generated `scrapyd.conf` sets only dirs/ports — **no `jobs_to_keep` / `finished_to_keep`** (`scrapyd/process.py:100-114`); relies on scrapyd built-in defaults (5 finished jobs' logs+items per spider), not tunable; single running job's log still uncapped in size | — | **P** |
| A6 | In-memory per-execution structures never pruned mid-run: `CommandConsumer._locks` (`commands.py:107`), `_inproc_wheel` (`:117`), `LogPublisher._eof_sent` (`redis/logs.py:56`), `PythonWheelRunner._procs/_pgids/_logs/_exits/_reapers/_canceled` (`runners/python_wheel.py:84-89`) | slow RAM leak over process lifetime | **U** (memory) |
| A7 | Agent stream `maxlen` defaults (1 M logs / 100 K events) are constructor defaults, **not surfaced in TOML** (`redis/logs.py:44`, `redis/events.py:69`; `main.py:69-96` never passes them). Agent settings schema has **zero** limit/retention fields (`config/settings.py`) | XADD itself is trim-capped (B) | config gap |

### Already bounded (no action)

Heartbeats (single-row upsert, `nodes/service.py:144-166`); server/agent XADD MAXLEN trims;
`_claim_pending` iteration cap (`commands.py:245`); app processes log to stdout only
(no in-app log files); Postgres/named volumes are backup-managed business truth.

## Goal

Every growth surface above gets a **configurable hard cap with a safe default**,
and expiry is enforced **automatically** (scheduled), not only via the manual
maintenance API. Invariants preserved (`docs/refactor/00-redis-streams-agent-communication.md`):
log RPO ≠ 0 is accepted; log gaps/truncation are **visible audit facts**
(`log_integrity`) and must **never block execution status convergence**;
PostgreSQL keeps only index/offset/status; Redis stays a transient bus;
server stays single-replica/single-worker.

## Proposed scope — four sub-tasks, strict order

Codex may split these into separate briefs; A is compose/docs-only and
independently shippable, and directly addresses the incident that motivated this
task. D (operator-requested) replaces the maintenance page with a live
resource-metrics view quantifying every surface in the audit table.

### Sub-task A — deployment-layer hard caps (compose only, no app code) [P0]

1. **Container log rotation** (fixes D1): add a shared YAML anchor, applied to
   *every* service (server, agents, redis, db, migrate) in all three compose files:
   ```yaml
   x-logging: &default-logging
     driver: json-file
     options: { max-size: "10m", max-file: "3" }
   ```
2. **Redis memory ceiling** (fixes D2): extend the redis command with
   `--maxmemory ${DOPILOT_REDIS_MAXMEMORY:-512mb} --maxmemory-policy noeviction`.
   `noeviction` is deliberate: XADD fails loudly instead of silently evicting
   stream data; both sides already tolerate XADD failure (agent log cursor does
   not advance → retried from `job.log`; events sit in the durable outbox;
   server dispatch retries). Stream MAXLEN remains the primary bound; maxmemory
   is the backstop against host OOM.
3. **Docs**: update `docs/dopilot/08-docker-deployment.md` (ops section: what is
   capped where, and that hosts using journald/other drivers need their own cap).

### Sub-task B — server-side caps + automatic retention [P0]

1. **Per-execution log file cap** (S1): new `[logs].max_file_bytes`
   (default `104857600` = 100 MB, per `03-gap-realtime-logs.md:366`). Enforced in
   the log-consumer apply path (`services/logs.py` / `logs/files.py`): once the
   file reaches the cap, stop appending bytes but **keep consuming + ACKing** the
   stream (never stall the consumer), append one visible truncation marker line,
   and mark the row. Marking: add sticky value **`truncated`** to the
   `log_integrity` enum (`models/execution.py:209`) — flagged as an open question
   below (alt: reuse `partial` + gap fields).
2. **Automatic retention sweep** (S2, S4): a new lightweight periodic asyncio
   loop registered in the app lifespan next to the existing dispatcher/reconcile
   loops (`app.py:155-158`) — *not* APScheduler, which is gated by
   `[scheduler].enabled`. Interval `[maintenance].sweep_interval_seconds`
   (default 3600). Each tick calls the **existing**
   `cleanup_terminal_data(session, cutoff=now - retention_days, dry_run=False)`
   (`services/maintenance.py:86`) — this finally wires the inert
   `[logs].retention_days`. Manual API stays. Also populate `retained_until` when
   a log finalizes, so the UI can show expiry.
3. **`event_audit` retention** (S3): the sweep additionally deletes `event_audit`
   rows older than `[maintenance].event_audit_retention_days` (default 30),
   batched deletes (e.g. 5000/loop) to avoid long locks.
4. **Artifact upload size cap** (S5): new `[artifacts].max_upload_bytes`
   (default `209715200` = 200 MB). Replace `await file.read()` with chunked reads
   that abort with HTTP 413 once the cap is exceeded (bounds both RAM and disk
   per upload). No artifact auto-deletion (see Out of Scope).
5. **SSE queue bound** (S6): construct subscriber queues with
   `asyncio.Queue(maxsize=1000)`; on `QueueFull`, disconnect that subscriber
   (client reconnects and re-tails from offset — existing recovery path).
6. **Config consistency** (S7, S8): unify `retention_days` default to **30**
   (code default ↔ `configs/server.docker.toml` ↔ docs); either implement
   `log_retention_seconds` as a periodic `XTRIM MINID` in the reconcile loop or
   delete the knob — recommend implementing it (cheap, one call per tick).

### Sub-task C — agent-side janitor + caps [P0/P1]

1. **Agent janitor loop** (A2, A3): a periodic task (default every 600 s)
   implementing the documented TTL fallback (`03-gap-realtime-logs.md:366`):
   delete workspaces/logs/state of **terminal** executions older than
   `completed_log_ttl_days` (default 3) and **orphans** older than
   `orphan_log_ttl_days` (default 7); also runs once at startup. Fix
   `_handle_cleanup` (`redis/commands.py:660-672`) to delete the `.logpos`
   cursor file, and have the janitor sweep stale `state/logpos/` entries.
2. **`job.log` size cap** (A2): new `[agent].max_job_log_bytes` (default 100 MB)
   in `PythonWheelRunner` — on reaching the cap, write a truncation marker and
   stop writing (job keeps running; execution status unaffected). Scrapy-side:
   the agent cannot cap scrapyd's own open file; mitigated by (3) + janitor TTL —
   residual risk flagged below.
3. **Explicit scrapyd retention** (A5): generated `scrapyd.conf` gains
   `jobs_to_keep` / `finished_to_keep` surfaced as `[scrapyd]` settings
   (defaults = current scrapyd defaults 5 / 100, now explicit and tunable).
4. **Artifact/wheel cache eviction** (A1): `[agent].artifact_cache_max_bytes`
   (default 2 GiB, 0 = unlimited). Janitor evicts least-recently-used sha dirs
   (touch `.ready` mtime on cache hit) above the cap, never evicting artifacts
   referenced by a currently running execution.
5. **Event outbox cap** (A4): `[redis].event_outbox_max_files` (default 100 000).
   Above the cap, drop the **oldest** outbox files with an ERROR log and a
   heartbeat-visible counter — flagged as an open question (events are business
   truth; alternative is block-new-work).
6. **In-memory pruning** (A6) [P1]: remove per-execution entries from
   `_locks` / `_inproc_wheel` / `_eof_sent` / runner dicts once the execution is
   terminal and its EOF is published.
7. **Config surface** (A7): wire `maxlen_logs` / `maxlen_events` into
   `[redis]` agent TOML; add all new knobs to `configs/agent.example.toml` and
   env mappings, mirroring the server loader pattern.

### Sub-task D — quantify growth surfaces on the maintenance page [P0, operator-requested]

Replace the current 运维清理 (`/maintenance`) page content — the manual
terminal-cleanup form (`apps/web/app/(app)/maintenance/page.tsx`) — with a
**live resource-metrics view** that quantifies every audited surface. The manual
cleanup **API** (`POST /maintenance/terminal-cleanup`) stays server-side for
curl/ops use; its UI form is removed per operator decision.

**D1. Agent-side metrics via heartbeat (zero migration).**
The agent collects local disk metrics on a timer (piggyback on the Sub-task C
janitor loop; cache the sample, do **not** walk the FS on every heartbeat) and
attaches them under the existing free-form field
`AgentHeartbeatRequest.detail["disk"]` (`packages/protocol/dopilot_protocol/agent.py:251`).
The server already persists `detail` verbatim into `nodes.health` (JSONB,
`nodes/service.py:168`) and exposes it via `GET /nodes` (`nodes/service.py:109`)
— no protocol, DB, or server-handler change. Reported per agent:
- workspaces: count + total bytes (`{workdir}/python_wheel/workspaces`)
- artifact/wheel cache bytes (`{workdir}/artifacts/**`) vs configured cap
- scrapyd dirs bytes (`logs/`, `items/`, `eggs/`, `dbs/`)
- event outbox pending file count (already reported today via
  `detail["redis"].event_outbox.pending`, `redis/status.py:42-43`) + bytes
- `state/logpos` file count; `state/executions` file count
- agent-data volume `shutil.disk_usage` (total/used/free)

**D2. Server sampling loop + snapshot.**
New `ResourceStatsLoop` cloned from the `RedisReconcileLoop` pattern
(`redis/reconcile.py:256-303`), wired into the lifespan start/stop blocks
(`app.py:153-178`), interval `[maintenance].stats_interval_seconds`
(default 60). Each tick assembles a snapshot (stored on `app.state`,
served from memory — expensive walks never run per-request):
- **Server disk**: `/server-data/logs` bytes (fast path: `SUM(size_bytes)` over
  `execution_log_files`; plus a real dir walk offloaded via `asyncio.to_thread`,
  following the `logs/files.py:190-229` idiom), artifacts dir bytes
  (`settings.artifacts.root_dir` walk), `shutil.disk_usage` of
  `settings.server.data_dir`.
- **PostgreSQL**: row count + `pg_total_relation_size` for `tasks`, `executions`,
  `execution_log_files`, `command_outbox`, `event_audit`, plus
  `pg_database_size`. Raw `text()` SQL gated on
  `session.bind.dialect.name == "postgresql"` (idiom: `services/stats.py:77`);
  on SQLite (tests) fall back to plain `COUNT(*)` with null sizes.
- **Redis**: `used_memory` / `maxmemory` via `INFO memory`, AOF size via
  `INFO persistence`; `XLEN` of `EVENT_STREAM`, `LOG_STREAM`
  (`packages/protocol/dopilot_protocol/streams.py:52-54`) and each live agent's
  `command_stream(agent_id)`. Requires extending `RedisStreams` with
  `info()` (xlen is already wrapped, `redis/client.py:123-124`).
- **Per-agent**: fold in each node's `health["disk"]` + `last_seen_at` from the
  `nodes` table.

**D3. API.** New admin endpoint `GET /maintenance/resource-stats`
(same auth/registration pattern as `api/v1/maintenance.py:54-74`; register in
`api/v1/router.py`). Response: `sampled_at` + a flat list of metric entries
`{key, scope: server|postgres|redis|agent:<id>, value_bytes|value_count, limit,
level: ok|warn|critical}`. `limit` is read from the *same config knobs
introduced by sub-tasks A–C* (`max_file_bytes`, `retention_days`,
`stream_maxlen_*`, redis `maxmemory`, `artifact_cache_max_bytes`, outbox cap…);
`limit = null` where no cap applies (then `level` derives from free-disk
percentage only). Server computes `level` (warn ≥ 70 % of limit,
critical ≥ 90 % — single source of truth; the web only renders it).

**D4. Web page rewrite.** `apps/web/app/(app)/maintenance/page.tsx` becomes the
resource dashboard ("real-time" = poll `resource-stats` every 10 s via
`setInterval` in `useEffect` — no SSE; the snapshot itself refreshes at most
every `stats_interval_seconds`). Reuse existing patterns: `Card` sections per
scope (Server disk / PostgreSQL / Redis / per-Agent), shadcn `Table` rows with
`ToneBadge` (`components/features/status-badge.tsx`) colored by `level`, byte
formatting in `lib/format.ts`, `Skeleton` loading, and a usage bar (add the
missing shadcn `Progress` component to `components/ui/`). New
`lib/api/maintenance.ts` function + `types.ts` shapes; i18n keys replace the old
`maintenance.*` block in `lib/i18n/locales/{zh,en}.ts`; nav entry/label
(`nav.maintenance`, `components/layout/nav.ts:28`) stays. The old cleanup-form
JSX, its i18n keys, and its testids are deleted.

**Not measurable in-app** (documented on the page as a note, not a metric):
Docker json-file container-log sizes (daemon-owned; bounded by Sub-task A) and
Postgres/Redis container internals beyond what `INFO`/`pg_*` expose.

## Out of scope

- **Artifact body auto-deletion** — product decision: archived artifacts stay
  visible and runnable (`services/artifacts.py:242`). Only the upload size cap
  is in scope.
- Postgres server tuning, disk quotas, host-level logrotate/journald config
  (documented as operator guidance only).
- Multi-replica / HA anything (hard constraint stays: single replica, `workers=1`).
- Docker long-running crawler type (future phase).
- WebSocket / changes to the SSE fan-out model.

## Open questions for Codex

1. **Truncation marking** (B1): add `truncated` to the `log_integrity` enum
   (needs Alembic migration of nothing — column is String — but web UI must learn
   the value), or reuse `partial`? Recommendation: new value `truncated`
   (semantically distinct: cap hit vs transport gap).
2. **Retention sweep default-on?** Recommendation: on by default
   (`[maintenance].enabled = true`) — the whole point is limits that hold without
   operator action; opt-out stays possible.
3. **Outbox overflow policy** (C5): drop-oldest (keeps agent alive, loses oldest
   status events — server reconcile marks affected executions `lost`) vs
   refuse-new-executions. Recommendation: drop-oldest at a high cap.
4. **D3 `mem_limit`**: enforce container memory limits by default, or ship as
   commented examples? Recommendation: commented examples only (host sizes vary).
5. Split into separate briefs (A / B / C / D) or fewer? Recommendation: four, in
   order A → B → C → D; A is compose-only and immediately deployable. D reads
   its `limit` values from knobs introduced by B/C, so it lands last (or earlier
   with `limit = null` placeholders).
6. **Removing the manual-cleanup UI** (D4): operator has decided the current
   page content goes away. Confirm the server endpoint
   `POST /maintenance/terminal-cleanup` stays API-only (recommendation: yes —
   it remains the manual override alongside the automatic sweep), or whether a
   minimal "clean now" button should reappear on the new metrics page later.
7. **Metric staleness contract** (D2/D4): snapshot age is bounded by
   `stats_interval_seconds` (60 s) while the page polls every 10 s. Acceptable
   for "real-time"? Recommendation: yes; show `sampled_at` age on the page
   instead of pretending sub-second freshness.

## Acceptance criteria (across sub-tasks)

- Every service in all three compose files has a bounded log driver; redis runs
  with `maxmemory` + `noeviction`; `docker compose config` validates.
- A log stream exceeding `max_file_bytes` results in: file size ≤ cap (+ marker),
  stream fully consumed/ACKed, `log_integrity = truncated`, execution status
  still converges to its true terminal state.
- With `retention_days = N`, terminal task data and log files older than N days
  disappear within one sweep interval without operator action; `event_audit`
  rows older than the window are pruned; manual maintenance API still works.
- Upload of a file larger than `max_upload_bytes` returns 413 and leaves no
  partial file; RAM stays bounded during the attempt.
- Agent janitor removes expired workspaces / logpos / cache entries per TTL and
  LRU caps on a live agent, including after an unclean agent restart; a running
  execution's files are never removed.
- All new knobs load from TOML + env, appear in `configs/*.example.toml`, and
  are documented in `08-docker-deployment.md`.
- `GET /maintenance/resource-stats` (admin-auth) returns a snapshot no older
  than `stats_interval_seconds` covering: server log/artifact/data-dir bytes +
  volume free space, the five audited PG tables (rows + bytes) + DB size, Redis
  memory vs `maxmemory` + AOF size + XLEN of all three stream kinds, and one
  disk section per live agent; each entry carries `limit` (nullable) and a
  server-computed `level`.
- `/maintenance` page renders the metrics grouped by scope with level-colored
  badges and usage bars, auto-refreshes (~10 s), shows `sampled_at` age, and no
  longer contains the manual-cleanup form; agents report `detail["disk"]` in
  heartbeats and it appears both in `nodes.health` and on the page.
- Sampling never blocks the event loop (dir walks via `asyncio.to_thread`) and
  never runs per-request; a Redis/PG outage degrades the affected section to an
  "unavailable" state without failing the whole endpoint.

## Required tests

- Unit: log-cap enforcement path (cap hit mid-increment, marker written, ACK
  continues); chunked upload cap (413 at boundary); retention sweep cutoff math +
  `event_audit` batch delete; janitor TTL/orphan/LRU selection logic; outbox cap
  drop-oldest; scrapyd.conf rendering with new keys; settings/env loader for all
  new fields (server + agent).
- Integration (existing pytest patterns in `apps/server/tests`, `apps/agent/tests`):
  consumer keeps ACKing past a capped file; sweep deletes files + rows end-to-end;
  janitor on a fake workdir tree.
- Frontend (vitest): render `log_integrity = truncated` indicator (if B1 adds
  it); new maintenance-page test (none exists today — follow the
  `app/(app)/nodes/__tests__/nodes.test.tsx` mock pattern): renders all scopes
  from a mocked `resource-stats` payload, level→badge mapping, null-limit rows,
  stale-`sampled_at` display, and absence of the old cleanup-form testids.
- Server unit/integration: `resource_stats` service — PG-dialect gating (SQLite
  fallback), snapshot assembly with Redis down (degraded section), level
  computation at the 70 %/90 % boundaries, heartbeat `detail["disk"]`
  passthrough into `nodes.health` and into the endpoint response.
- Agent unit: disk-metrics collector (fake workdir tree → expected counts/bytes;
  cached between heartbeats).
- Smoke/manual: all-in-one compose up; `docker inspect` shows log opts; force a
  large log; observe truncation + retention.

## Required commands

```bash
pytest apps/server/tests apps/agent/tests packages/protocol/tests
ruff check apps packages
corepack pnpm --filter web test
docker compose -f deploy/docker/docker-compose.yml config -q
```

## Risks to watch

- Redis `noeviction` at `maxmemory` makes XADD fail → log gaps / delayed events.
  Accepted (RPO ≠ 0) but must be observable: keep ERROR logs + heartbeat outbox
  counter; verify server dispatch retry behavior under XADD failure.
- Retention sweep deleting data an operator still wanted → defaults must be
  conservative (30 d), knob documented, manual dry-run API unchanged.
- Scrapy running-job log size remains uncapped (scrapyd owns the file) — residual
  risk; janitor TTL bounds it in time, not size. Revisit if it bites.
- Janitor vs in-flight execution races: never delete anything whose execution is
  non-terminal or whose EOF is unpublished; janitor must re-check state under the
  same per-execution lock used by `_handle_cleanup`.
- Container log rotation truncates old stdout history — acceptable; operators
  needing history should ship logs elsewhere.
- Dir walks over huge trees (many small workspace/cache files) can be slow even
  off-loop — the sampler must time-box walks and reuse the DB-side
  `SUM(size_bytes)` fast path where an index exists; a slow tick must skip, not
  queue.
- Heartbeat payload growth: `detail["disk"]` must stay a small fixed-shape
  summary (counts/bytes only, no per-file lists) — it is persisted verbatim
  into `nodes.health` on every heartbeat.
