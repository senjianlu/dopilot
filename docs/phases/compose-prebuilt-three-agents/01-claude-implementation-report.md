# Compose Prebuilt Image + Three Agents — Claude Implementation Report

Implements `docs/phases/compose-prebuilt-three-agents/00-brief.md` per the
applied decisions: the default deploy path pulls the CI-built image, the base
compose starts three symmetric agents, default configs are baked into the image,
and the Makefile flow is removed.

## Changes

### Compose

- **`deploy/docker/docker-compose.yml` (rewritten — default user path).**
  - No `build:` entries. All image-bearing services use
    `${DOPILOT_IMAGE:-rabbir/dopilot:latest}` (migrate, the three agents,
    server).
  - Three symmetric agents `scrapy-agent-1`, `scrapy-agent-2`, `scrapy-agent-3`
    via a shared `x-agent` YAML anchor; they differ only by `AGENT_ID` and a
    per-agent named volume (`dopilot-agent{1,2,3}-data`). The old single `agent`
    service and `dopilot-agent-data` volume are gone.
  - Published ports: server `5000` and **only** `scrapy-agent-1` `6800`
    (smoke/debug). scrapyd `6801` is never published. (`db` `5432` retained as
    before.)
  - No host config mounts — configs are baked into the image (below).
  - `server.depends_on` waits for db + redis + migrate + **all three** agents
    healthy. Single server replica preserved.

- **`deploy/docker/docker-compose.build.yml` (new — local source build).**
  Adds `build:` to `migrate`, `scrapy-agent-1`, `scrapy-agent-2`,
  `scrapy-agent-3`, and `server` via a shared `x-dopilot-build` anchor
  (`context: ../..`, `dockerfile: deploy/docker/Dockerfile`). Build args default
  to the **public CI base images** `rabbir/dopilot-py-base:latest` /
  `rabbir/dopilot-web-base:latest`, still overridable via
  `DOPILOT_PY_BASE_IMAGE` / `DOPILOT_WEB_BASE_IMAGE`. The base file's `image:`
  tag is reused as the built tag.

- **`deploy/docker/docker-compose.e2e.yml` removed.** The base compose now
  defines all three agents, so the two-extra-agent overlay is obsolete.

### Image

- **`deploy/docker/Dockerfile`.** Runtime stage now bakes default configs into
  the image:
  - `COPY configs/server.docker.toml ./configs/server.toml`
  - `COPY configs/agent.example.toml ./configs/agent.toml`

  (`WORKDIR /app`, so these land at `/app/configs/*.toml`, matching the existing
  `DOPILOT_CONFIG` env defaults.) `.dockerignore` does not exclude `configs/`,
  so they are in the build context. The prebuilt image now runs with no host
  config mounts; mounts remain available for overrides.

### Make flow removed

- **`Makefile` deleted.**
- **`scripts/build-docker-base.sh` deleted** (became unused: the Makefile is
  gone and the smoke scripts now use the build override, which pulls the public
  CI base images). **Kept** `deploy/docker/Dockerfile.base` and
  `scripts/docker-deps-hash.sh` — CI (`.github/workflows/docker.yml`) still uses
  them.

### Smoke scripts

- **`scripts/smoke-phase1.sh`, `scripts/smoke-phase1-ui.sh`.**
  - `dc()` now layers `docker-compose.yml` + `docker-compose.build.yml`
    (was `+ docker-compose.e2e.yml`).
  - Removed the `scripts/build-docker-base.sh` invocation from bring-up.
  - `SERVICE_OF` maps each agent id to its own compose service name
    (`scrapy-agent-1` is now its own service, no longer aliased to `agent`);
    the egg-build helper uses `dc ps -q scrapy-agent-1`.

### Docs (current-facing only; historical phase reports untouched)

- **`README.md`, `README.zh-CN.md`.** Quick-deploy section now shows
  `docker compose pull && docker compose up -d` (prebuilt, three agents) plus
  the build-override command; `DOPILOT_IMAGE` documented. `make
  install/migrate/server/test` replaced with direct `python -m venv` / `pip
  install -e` / `alembic upgrade head` / `dopilot-server` / `pytest` +
  `pnpm --filter web test` commands.
- **`CONTRIBUTING.md`.** Local-setup `make install`/`make migrate` replaced with
  direct commands; `make compose-smoke` replaced with `scripts/smoke-phase1.sh`.
- **`AGENTS.md`.** `make compose-smoke` → `scripts/smoke-phase1.sh`.
- **`docs/agent-governance/02-claude-invocation.md`.** `make compose-smoke` →
  `scripts/smoke-phase1.sh` in the allowlist guidance.
- **`docs/agent-governance/03-commit-convention.md`.** `repo` scope example no
  longer cites `Makefile`.
- **`docs/dopilot/08-docker-deployment.md`.** §2.5 compose example rewritten to
  the prebuilt-image + three-agent shape (baked configs, only `scrapy-agent-1`
  publishes 6800); §7.3 manual build/push rewritten around the pull-default and
  the `docker-compose.build.yml` override (public base images), dropping the
  `build-docker-base.sh` / `make compose-build|compose-up` steps; per-role
  env/volume table rows updated for the three agents, baked configs, and CI base
  note.

## Out of scope (unchanged)

Product facts beyond deployment/build flow and default agent count are
untouched. Docker long-running crawlers remain **planned / unimplemented**.

## Validation results

All commands run from the repo unless noted. Docker/pytest/pnpm full runs were
not executed (per instructions); only quick config validation was run.

- `git diff --check` → **clean** (no output, no whitespace errors).
- `cd deploy/docker && docker compose config -q` → **BASE_CONFIG_OK** (valid).
  `docker compose config --services` lists: `db`, `migrate`, `redis`,
  `scrapy-agent-1`, `scrapy-agent-2`, `scrapy-agent-3`, `server`.
- `cd deploy/docker && docker compose -f docker-compose.yml -f
  docker-compose.build.yml config -q` → **BUILD_CONFIG_OK** (valid). All five
  image-bearing services resolve `build.context: <repo root>`,
  `dockerfile: deploy/docker/Dockerfile`, and base-image args defaulting to
  `rabbir/dopilot-{py,web}-base:latest`.
- Reference sweep:
  `rg -n "make |Makefile|compose-smoke|build-docker-base|docker-compose\.e2e"
  README.md README.zh-CN.md CONTRIBUTING.md AGENTS.md docs/agent-governance
  docs/dopilot scripts deploy/docker .github`
  → only **one** match remains:
  `docs/agent-governance/02-claude-invocation.md:50` — the English phrase
  "do not **make** the allowlist so narrow…" (benign; not a Make reference).
- Extra sweep for stale identifiers (`dopilot-agent-data`, `docker-compose.e2e`,
  `compose-up`, `compose-build`, `COMPOSE_E2E`, `build-docker-base` across
  `*.sh/*.md/*.yml/*.yaml/*.py`, excluding `docs/phases/`) → **no matches**.
  Remaining `e2e` tokens in `smoke-phase1-ui.sh` refer to browser end-to-end
  testing, not the removed compose file.

Not run (per instructions / acceptable cost): full `pytest`, `ruff`,
`pnpm --filter web test|build`, and `scripts/smoke-phase1.sh` (Docker build +
run). The Dockerfile `COPY configs/...` lines were verified to be in-context
(`.dockerignore` does not exclude `configs/`) but the image build itself was not
executed.
