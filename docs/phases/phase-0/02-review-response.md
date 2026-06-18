# 02 · Phase 0 Review Response

Date: 2026-06-18

Scope: remediation of the two findings in [`01-review.md`](01-review.md). Both
findings were accepted as valid. P1 (blocking) and P2 (minor) are fixed; the
review's verification commands were re-run and still pass.

## P1 (blocking) — Docker backend loop could not initialize a fresh database

**Cause.** `deploy/docker/docker-compose.yml` started `server` after `db` was
healthy but ran no migrations, and the Alembic assets were not even present in
the server image: `apps/server/pyproject.toml` packages only `dopilot_server`,
while `alembic.ini` + `migrations/` are siblings of the package, and
`Dockerfile.server` installed only built wheels. So `compose up` from an empty
volume booted the server, but `nodes` / `auth_tokens` were never created and
DB-backed endpoints (login, nodes) would fail.

**Fix.**

1. `deploy/docker/Dockerfile.server` (runtime stage) now copies the Alembic
   assets into the image:

   ```dockerfile
   COPY apps/server/alembic.ini ./alembic.ini
   COPY apps/server/migrations ./migrations
   ```

2. `deploy/docker/docker-compose.yml` gains an explicit one-shot `migrate`
   service that reuses the server image (same build + tag, built once) and
   overrides its entrypoint:

   ```yaml
   migrate:
     build: { context: ../.., dockerfile: deploy/docker/Dockerfile.server }
     image: rabbir/dopilot:latest
     entrypoint: ["alembic", "upgrade", "head"]
     environment:
       DOPILOT_DATABASE_URL: postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
     depends_on:
       db: { condition: service_healthy }
     restart: "no"
   ```

   `server` now also waits on it:

   ```yaml
   depends_on:
     db:      { condition: service_healthy }
     migrate: { condition: service_completed_successfully }
     agent:   { condition: service_started }
   ```

**Design notes.** Migration stays an explicit, observable step rather than being
folded into app startup; the server process still never calls
`Base.metadata.create_all()` — Alembic remains the only schema authority.
`alembic upgrade head` is idempotent, so it is a no-op when already at head.
The `migrate` service needs only `DOPILOT_DATABASE_URL` because `migrations/env.py`
resolves the URL from that env var first (config TOML is the fallback).

### P1 follow-on — agent unreachable inside the compose network

Running the loop from a clean volume surfaced a second problem: the `server`
service mounted `configs/server.example.toml`, whose `[nodes].agents =
["localhost:6800"]` is correct for host/dev but wrong inside compose — there
`localhost` is the server's own container, so `/nodes/refresh` recorded the agent
as `unhealthy`. The agent must be reached by service name (`agent:6800`), exactly
as `docs/dopilot/08-docker-deployment.md` §2.5 prescribes.

Fix: added a committed compose config `configs/server.docker.toml`
(`[nodes].agents = ["agent:6800"]`, `[database].url` → `db:5432`) and mounted it
in the `server` service instead of the dev example. The example stays the
host/dev template; the docker file is the compose template.

## P2 (minor) — generated frontend artifacts in the source tree

**Cause.** `apps/web/tsconfig.node.json` is a composite/referenced project, so
`vue-tsc -b` emitted `vite.config.js` + `vite.config.d.ts` next to the source,
and build mode wrote `tsconfig*.tsbuildinfo`. `.gitignore` did not cover them.

**Fix (configure TypeScript so nothing lands in the source tree).** A referenced
composite project cannot set `noEmit` (`vue-tsc -b` → TS6310), so instead the
emit and build-info are redirected into the gitignored `node_modules/.tmp/`:

- `tsconfig.node.json`: keep `composite: true`, add
  `outDir: ./node_modules/.tmp/tsconfig-node` and
  `tsBuildInfoFile: ./node_modules/.tmp/tsconfig.node.tsbuildinfo`.
- `tsconfig.json`: add `incremental: true` +
  `tsBuildInfoFile: ./node_modules/.tmp/tsconfig.tsbuildinfo`.
- `.gitignore`: add `*.tsbuildinfo` as a safety net.

After a clean `vue-tsc -b --force && vite build`, the `apps/web` source tree has
**no** emitted `.js` / `.d.ts` / `.tsbuildinfo` files.

## Re-verification

Local suites after the fixes:

| Command | Result |
|---|---|
| `pytest` (server 24 / agent 15 / protocol 9) | 48 passed |
| `ruff check apps packages` | passed |
| `corepack pnpm --filter web test` | 3 passed |
| `vue-tsc -b --force && vite build` | passed, no source-tree artifacts |
| `docker compose config` | valid |

P1 end-to-end — `docker compose build` then `docker compose up -d` from a clean
volume (`down -v` first), verified:

- Orchestration order honored: `db` (healthy) → `migrate` runs
  `alembic upgrade head` and **`Exited (0)`** → `server` starts.
- `migrate` created the schema from empty: `psql \dt` shows `nodes`,
  `auth_tokens`, `alembic_version` (3 tables).
- `GET /api/v1/health` → `{"status":"ok","database":"ok"}`.
- `POST /api/v1/auth/login` (admin/change-me) → opaque token issued.
- `POST /api/v1/nodes/refresh` → server reached `agent:6800` over the compose
  network and upserted the node **`healthy`** with `agent_id: scrapy-agent-1`,
  `endpoint: agent:6800`, `capabilities {scrapy:true, script:false, docker:false}`.
- `docker compose down -v` cleaned up. Re-running from clean reproduces the above.

## Status

Both findings from `01-review.md` are fixed and verified, including the P1
follow-on (compose-network agent addressing). The backend compose loop now comes
up correctly from an empty database. No findings outstanding.
