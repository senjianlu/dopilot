# dopilot

dopilot is a private, single-admin scheduling platform (Scrapy → Python scripts →
Docker long-running crawlers), built greenfield as an `apps/` + `packages/`
monorepo. Goals, decisions and the phased roadmap live in **`docs/`** — start with
[`docs/dopilot/00-requirements.md`](docs/dopilot/00-requirements.md) and
[`CLAUDE.md`](CLAUDE.md). `reference/scrapydweb/` is a read-only behavioral
reference only (never imported, never built).

> **Status:** Phase 0 (platform skeleton) is implemented. It boots and is testable
> but does **not** yet run real Scrapy/script/docker work — see
> [`docs/phases/phase-0/00-brief.md`](docs/phases/phase-0/00-brief.md).

## Layout

```
apps/
  server/   dopilot-server  — FastAPI hub: /api/v1 JSON, auth, nodes, PostgreSQL + Alembic
  agent/    dopilot-agent   — worker HTTP service: /health, /logs/tail, /status, cleanup
  web/      Vue 3 + Element Plus + Vite + TS SPA (login, layout, dashboard, nodes, zh/en i18n)
packages/
  protocol/ dopilot-protocol — shared server↔agent Pydantic schemas (no app deps)
deploy/docker/  Dockerfile.server, Dockerfile.agent, docker-compose.yml (server + agent + db)
configs/        server.example.toml, agent.example.toml   (loaded via DOPILOT_CONFIG)
```

## Prerequisites

- Python **3.12** (with `python3-venv`/`ensurepip`; if your distro lacks it, see *Troubleshooting*)
- Node **22+** with `pnpm` (this repo uses Corepack: `corepack pnpm …`)
- Docker + Docker Compose (for PostgreSQL and the backend compose loop)

## Backend (server + agent + protocol)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e packages/protocol          # install protocol first (server/agent depend on it)
pip install -e "apps/server[dev]"
pip install -e "apps/agent[dev]"
```

Run a local PostgreSQL, apply migrations, then start both services:

```bash
cd deploy/docker && docker compose up -d db && cd ../..        # PostgreSQL on :5432
(cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot \
   alembic upgrade head)

DOPILOT_CONFIG=configs/server.example.toml dopilot-server      # http://localhost:5000/api/v1
DOPILOT_CONFIG=configs/agent.example.toml  dopilot-agent       # http://localhost:6800
```

Config is read from the TOML pointed to by `DOPILOT_CONFIG`; `DOPILOT_DATABASE_URL`
overrides `[database].url`, and `AGENT_ID` / `AGENT_WORKDIR` override the agent TOML.
Web auth is **config-present-or-off**: it is enabled only when `[auth]`
`admin_username` + `admin_password` + `token_secret` are all set (the example
`change-me` values are **not** production-safe). Agent auth is enabled only when
`[auth].shared_token` is set.

## Web SPA

```bash
corepack pnpm install            # approves esbuild/vue-demi build scripts (pnpm-workspace.yaml)
corepack pnpm --filter web dev   # http://localhost:5173, proxies /api -> http://localhost:5000
corepack pnpm --filter web build
```

## Tests / lint

```bash
pytest                                   # all suites (server 24, agent 15, protocol 9)
corepack pnpm --filter web test          # vitest
ruff check apps packages                 # lint (pip install ruff)
cd deploy/docker && docker compose config
```

A `Makefile` wraps the common flows: `make install web-install db-up migrate server agent web test compose-config lint`.

## Docker (backend loop)

`deploy/docker/docker-compose.yml` builds and runs `db` + a one-shot `migrate`
step (`alembic upgrade head`) + `agent` + `server` (images `rabbir/dopilot:latest`
/ `rabbir/dopilot-agent:latest`; build context is the repo root and `.dockerignore`
excludes `reference/`). The server mounts `configs/server.docker.toml`, which
reaches `db`/`agent` by compose **service name** (not `localhost`). The web SPA
runs separately via Vite. server is single-replica only (`uvicorn workers=1`).

```bash
cd deploy/docker && docker compose up -d --build     # db -> migrate -> agent -> server
```

The `agent` image bundles `scrapy` + `scrapyd`; the agent process spawns a local
`scrapyd` child (config `[scrapyd].start = true`) listening on container-internal
`127.0.0.1:6801`. Only the agent HTTP API (`6800`) is published — `6801` is never
exposed to the host. Both `agent` and `server` declare healthchecks, so
`server` only starts once `agent` is `service_healthy` (and the scrapyd
subprocess is up).

## Phase 1: Scrapy chain

Phase 1 runs the first real execution loop: upload a built Scrapy egg, run a
spider on an agent's in-process scrapyd, pull the job log back to the server, and
land it under `/server-data/logs` with the offset/status index in PostgreSQL.

Fixed names used below come from the demo fixture
(`tests/fixtures/scrapy_demo/`): Scrapy project `demo`, spider `phase1`,
committed egg `tests/fixtures/scrapy_demo/eggs/demo_phase1.egg`. The spider is
offline and deterministic — it logs `phase1 demo spider started` /
`phase1 demo spider done` and scrapes 2 items.

### Compose smoke (recommended)

One repeatable, clean-volume end-to-end check that builds the images and drives
the whole chain (clean volumes -> migrate -> agent+scrapyd -> upload egg -> run
spider -> assert log markers -> assert `complete` -> tear down):

```bash
make compose-smoke           # == scripts/smoke-phase1.sh
```

It tears the stack down (`docker compose down -v`) on exit. Set `KEEP_UP=1` to
leave a passing stack running for inspection. It needs `docker`, `curl` and
`python3` on the host (no venv). If the committed egg is absent it is rebuilt
inside the agent container via `python3 setup.py bdist_egg`.

### Local dev (host processes + db container)

Run the db in Docker and the server+agent on the host. The agent spawns its own
scrapyd child, so it needs `scrapy` + `scrapyd` importable in the same env:

```bash
# 0. install deps (server + agent need scrapy/scrapyd for the local agent run)
pip install -e packages/protocol -e "apps/server[dev]" -e "apps/agent[dev]"
pip install 'scrapy>=2.11,<3' 'scrapyd>=1.4,<2'

# 1. db + migrations
scripts/dev-db.sh up                                          # PostgreSQL on :5432
(cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot \
   alembic upgrade head)

# 2. run agent + server (separate terminals)
DOPILOT_CONFIG=configs/agent.example.toml  dopilot-agent      # :6800 (+ internal scrapyd :6801)
DOPILOT_CONFIG=configs/server.example.toml dopilot-server     # :5000

# 3. (re)build the demo egg only if you changed the fixture source
tests/fixtures/scrapy_demo/build_egg.sh                       # -> eggs/demo_phase1.egg

# 4. upload the egg, run the spider, watch the logs (web auth off in the
#    *.example.toml configs -> no token needed locally)
curl -fsS -X POST http://localhost:5000/api/v1/artifacts/scrapy/egg \
  -F project=demo -F version=$(date +%s) \
  -F file=@tests/fixtures/scrapy_demo/eggs/demo_phase1.egg

curl -fsS -X POST http://localhost:5000/api/v1/executions/run \
  -H 'Content-Type: application/json' \
  -d '{"task_type":"scrapy","target":"demo:phase1","node_strategy":"all","params":{"project":"demo","spider":"phase1"}}'
# -> {"execution_id": "..."}; then poll status / read logs:
curl -fsS http://localhost:5000/api/v1/executions/<id>
curl -fsS http://localhost:5000/api/v1/executions/<id>/logs
```

> The compose configs (`configs/server.docker.toml`) set `[auth]`, so web auth is
> **ON** there and API calls need a bearer token from `POST /api/v1/auth/login`
> (`admin` / `change-me`); the smoke script handles this. The local
> `*.example.toml` configs leave auth off, so the curl calls above need no token.

## Troubleshooting

- **`python3 -m venv` fails with "ensurepip is not available"** — install
  `python3.12-venv`, or bootstrap pip into a pip-less venv:
  `python3 -m venv --without-pip .venv && curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python`.
- **`pnpm install` reports `ERR_PNPM_IGNORED_BUILDS`** — `esbuild`/`vue-demi` are
  pre-approved in `pnpm-workspace.yaml` (`allowBuilds`); on older pnpm use
  `pnpm approve-builds`.
