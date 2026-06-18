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

## Troubleshooting

- **`python3 -m venv` fails with "ensurepip is not available"** — install
  `python3.12-venv`, or bootstrap pip into a pip-less venv:
  `python3 -m venv --without-pip .venv && curl -sSL https://bootstrap.pypa.io/get-pip.py | .venv/bin/python`.
- **`pnpm install` reports `ERR_PNPM_IGNORED_BUILDS`** — `esbuild`/`vue-demi` are
  pre-approved in `pnpm-workspace.yaml` (`allowBuilds`); on older pnpm use
  `pnpm approve-builds`.
