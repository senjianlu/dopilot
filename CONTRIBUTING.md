# Contributing to dopilot

Thanks for your interest in dopilot. It is an MIT-licensed, self-hosted,
single-admin scheduling platform built as an `apps/` + `packages/` monorepo.

## Before you start

- Read [`CLAUDE.md`](CLAUDE.md) for the architecture, hard constraints, and
  current implementation state.
- Read [`docs/dopilot/00-requirements.md`](docs/dopilot/00-requirements.md) (the
  north-star: goals, confirmed decisions, phased roadmap) before proposing any
  behavior change.
- Honor the locked decisions: single-admin (no multi-user/RBAC), single-replica
  server (`uvicorn workers=1`, one in-process scheduler), PostgreSQL as the only
  database, Redis as a transient message bus, and the strict job-type order
  (Scrapy → Python script → Docker, in that order).

dopilot draws **behavioral** inspiration from the upstream
[scrapydweb](https://github.com/my8100/scrapydweb) project (Scrapy `1.6.0`,
commit `1341cf9`). That is a *behavior reference only*: do **not** fetch, vendor,
copy, restructure from, or import upstream scrapydweb code into this MIT tree.
Consult it externally if you need to understand a behavior; never paste it in.

## Local setup

Prerequisites: Python **3.12**, Node **22+** with Corepack (`corepack pnpm …`),
and Docker (for PostgreSQL and Redis).

```bash
# Python packages (protocol first; server/agent depend on it)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e ./packages/protocol
pip install -e "./apps/server[dev]"
pip install -e "./apps/agent[dev]"

scripts/dev-db.sh up    # PostgreSQL
docker run -d --rm --name dopilot-redis-dev -p 6379:6379 \
  redis:7 redis-server --appendonly yes

# apply migrations (server owns the schema)
(cd apps/server && DOPILOT_CONFIG=../../configs/server.example.toml alembic upgrade head)
```

See [`README.md`](README.md) (Local development) for running the server, agent,
and web dev server.

## Verification commands

Run the narrowest commands that cover your change, then broaden when shared
contracts or cross-app behavior changed:

```bash
pytest                              # server / agent / protocol tests
ruff check apps packages            # Python lint
corepack pnpm --filter web test     # web unit tests (vitest)
corepack pnpm --filter web build    # web static export build
cd deploy/docker && docker compose config
```

For Scrapy end-to-end behavior (builds the image from local source via the
compose build override; no `make` required):

```bash
scripts/smoke-phase1.sh
```

Do not mark work complete if the tests that cover it did not run — record the
blocker instead.

## Commits & pull requests

- This repo follows **Conventional Commits 1.0.0**, adapted to dopilot, enforced
  by a local `commit-msg` hook. See
  [`docs/agent-governance/03-commit-convention.md`](docs/agent-governance/03-commit-convention.md).
- Keep PRs scoped; update the relevant `docs/` when a decision or behavior
  changes.
- New or changed behavior needs tests under `apps/server/tests/`,
  `apps/agent/tests/`, `packages/protocol/tests/`, or `apps/web`.

## Security

Do not file security issues in public. Follow [`SECURITY.md`](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the MIT
License (see [`LICENSE`](LICENSE)).
