<p align="center">
  <img src="apps/web/public/logo.svg" alt="dopilot logo" width="120" />
</p>

<h1 align="center">dopilot</h1>

<p align="center">
  A private, single-admin scheduling platform for running Scrapy spiders and
  Python scripts across worker nodes.
</p>

<p align="center">
  <b>English</b> · <a href="README.zh-CN.md">简体中文</a>
</p>

---

## What dopilot is

dopilot is a self-hosted platform that schedules and runs jobs on remote worker
nodes, streams their logs back in real time, and keeps a durable record of every
run. It is built greenfield as an `apps/` + `packages/` monorepo.

It is deliberately **single-admin**: there is no multi-user system or RBAC. The
upstream **scrapydweb** project (under `reference/scrapydweb/`) is kept only as a
read-only behavioral reference; it is never imported or built.

### What it can run today

| Job type | Status | How it runs |
| --- | --- | --- |
| **Scrapy spiders** | Available | Upload a built `.egg`; the agent runs the spider on its in-process scrapyd. |
| **Python scripts** | Available | Upload a `.whl`; the agent runs a shell command with the wheel on `PYTHONPATH`. |
| **Docker long-running crawlers** | Planned | A future phase. Not implemented yet. |

## How it works

dopilot has two Docker roles, both built from one unified image
(`rabbir/dopilot:latest`); the runtime role is selected by the container command:

- **server**: the FastAPI hub. Serves the `/api/v1/*` JSON/SSE API and the
  bundled web UI, owns scheduling (APScheduler), persists business data and log
  indexes in **PostgreSQL**, and writes log bodies to files under
  `/server-data/logs`.
- **agent**: a worker. Consumes commands, runs jobs, and pushes status events and
  log increments back.

The server and agents talk over **Redis Streams** plus an agent heartbeat. Redis
is a transient message bus, not a database, and never the source of business
truth. The agent never connects to PostgreSQL directly.

```
 server ──XADD command──►  Redis Streams  ──consume──►  agent ──run──► scrapyd / python
   ▲                                                       │
   └────── status events · log increments · heartbeat ─────┘
```

Core domain model (snapshot is frozen at task creation):

```
BuildArtifact → ExecutionTemplate → Schedule → Task → Execution
```

A **Task** is one trigger; it fans out to one **Execution** per selected node,
chosen by the node strategy (`selected`, `all`, or `random`, filtered by node
capability and health).

### Python script execution model

A Python script is packaged as a `.whl` build artifact. On the agent, each wheel
is installed once per `sha256` with:

```bash
pip install --no-deps --target <agent-cache>/python_wheel/<sha256>/site <wheel>
```

The shell command then runs with that directory injected on `PYTHONPATH`:

```bash
PYTHONPATH=<site-dir>:$PYTHONPATH /bin/sh -c "<command>"
```

There is **no virtualenv**, no dependency resolution (`--no-deps`), and no
console-script entry point. Run importable modules, e.g. `python -m main`.
Dependencies the script needs beyond the wheel must already be present in the
agent environment.

## Quick deploy (Docker Compose)

The compose stack builds from two local base images
(`rabbir/dopilot-py-base:local`, `rabbir/dopilot-web-base:local`). `make
compose-up` builds those base images first, then brings up the full stack
(PostgreSQL + Redis + one-shot migrate + agent + server):

```bash
make compose-up
```

The server is then reachable at **http://localhost:5000** (web UI and API). The
server runs single-replica only (in-process scheduler + in-memory SSE tables).

> Compose configs set `[auth]`, so web auth is **on** there. The default
> `change-me` credentials are not production-safe; change them before exposing
> the server.

## Local development

Prerequisites: Python **3.12**, Node **22+** with Corepack (`corepack pnpm …`),
and Docker (for PostgreSQL and Redis).

```bash
# 1. Python packages (protocol first; server/agent depend on it)
make install
source .venv/bin/activate

# 2. Backing services.
# Postgres can use the committed compose service; Redis needs a host port for
# host-run server/agent processes.
scripts/dev-db.sh up
docker run -d --rm --name dopilot-redis-dev -p 6379:6379 \
  redis:7 redis-server --appendonly yes

# 3. Apply migrations (server owns the schema)
make migrate

# 4. Run the services (separate terminals).
# For the agent, copy configs/agent.example.toml to a local file and set:
#   [agent].server_url = "http://localhost:5000"
#   [agent].advertise_endpoint = "localhost:6800"
#   [redis].url = "redis://localhost:6379/0"
make server
DOPILOT_CONFIG=configs/agent.local.toml dopilot-agent

# 5. Web UI in dev mode (Next.js)
NEXT_PUBLIC_API_BASE=http://localhost:5000/api/v1 corepack pnpm --filter web dev
```

Stop the local Redis container with `docker stop dopilot-redis-dev`.

`DOPILOT_CONFIG` points at a TOML config under `configs/`; `DOPILOT_DATABASE_URL`
and `DOPILOT_REDIS_URL` override the database and Redis URLs. Web auth and agent
auth are **config-present-or-off**: each is enabled only when its credentials are
set.

The web app is a **Next.js static export** (shadcn/ui + react-i18next) served by
`dopilot-server` from the same container; there is no separate web container and
no Node production runtime.

## Tests & lint

```bash
make test                          # pytest (server/agent/protocol) + web vitest
corepack pnpm --filter web build   # static export build
ruff check apps packages           # lint
cd deploy/docker && docker compose config
```

## Documentation

Goals, decisions, and the phased roadmap live under [`docs/`](docs/README.md):

- [`docs/dopilot/00-requirements.md`](docs/dopilot/00-requirements.md): the
  north-star: product goals, confirmed decisions, the phased roadmap.
- [`docs/dopilot/10-roadmap.md`](docs/dopilot/10-roadmap.md): the consolidated
  build/port roadmap.
- [`CLAUDE.md`](CLAUDE.md): architecture, hard constraints, current status.

## License

See the repository for license details.
