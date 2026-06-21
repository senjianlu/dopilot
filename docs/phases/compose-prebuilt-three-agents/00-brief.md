# Compose Prebuilt Image + Three Agents Brief

## User Request

- Remove Makefile-based user and contributor flows.
- Make the default deployment path Docker Compose using the CI-built
  `rabbir/dopilot` image, not a local build.
- Make the default Compose stack start three agents.
- Keep dopilot open-source friendly and simple to run.

## Current State

- `README.md` and `README.zh-CN.md` still present `make compose-up`,
  `make install`, `make migrate`, `make server`, and `make test`.
- `Makefile` exists and wraps local setup, Docker base-image build, Compose, and
  tests.
- `deploy/docker/docker-compose.yml` builds `rabbir/dopilot:latest` locally and
  currently starts one agent.
- `deploy/docker/docker-compose.e2e.yml` overlays two extra agents for smoke
  tests.
- The app image currently expects Compose config files to be mounted from the
  repo (`configs/server.docker.toml`, `configs/agent.example.toml`).
- CI already builds/pushes `rabbir/dopilot`.

## Proposed Shape

1. Default deployment:
   - `deploy/docker/docker-compose.yml` uses
     `${DOPILOT_IMAGE:-rabbir/dopilot:latest}` with no `build:` entries.
   - Quick deploy is:
     ```bash
     cd deploy/docker
     docker compose pull
     docker compose up -d
     ```
   - The stack runs PostgreSQL, Redis, one-shot migration, three agents, and one
     server.

2. Default three agents:
   - Add three agent services with unique `AGENT_ID` values:
     `scrapy-agent-1`, `scrapy-agent-2`, `scrapy-agent-3`.
   - Give each agent its own `/agent-data` named volume.
   - Keep the server single-replica and make it wait for all three agents to be
     healthy.
   - Publish only the server UI/API on `5000`; optionally keep the first agent's
     `6800` port for local debug if existing smoke scripts still need it.

3. Image-bundled default configs:
   - Copy `configs/server.docker.toml` and `configs/agent.example.toml` into the
     Docker image so the prebuilt image can run without host config mounts.
   - Compose may still allow custom config mounts through user overrides, but the
     default path should not require them.

4. Local source build / tests:
   - Add an optional Compose override such as
     `deploy/docker/docker-compose.build.yml` for local source builds and smoke
     tests.
   - Smoke scripts should use the build override when validating current source,
     but the user quick-deploy path should stay prebuilt-image only.

5. Remove Make flow:
   - Delete `Makefile`.
   - Replace current-facing documentation and governance commands with direct
     shell commands.
   - Replace `make compose-smoke` references with `scripts/smoke-phase1.sh`.
   - Do not rewrite historical phase reports except where a current instruction
     would mislead contributors.

## Acceptance Criteria

- A user can deploy from the repo with:
  ```bash
  cd deploy/docker
  docker compose pull
  docker compose up -d
  ```
- `docker compose config` from `deploy/docker` resolves a valid stack with three
  agents and no local build requirement.
- Smoke scripts no longer call Make or require locally built base images.
- Current-facing docs no longer instruct users to run `make`.
- Local development and verification docs still provide direct commands.
- The default stack still respects locked constraints:
  - one server replica;
  - PostgreSQL as business state;
  - Redis as transient server-agent message bus;
  - agent does not connect to PostgreSQL;
  - Docker long-running crawlers remain planned, not implemented.

## Validation Commands

```bash
git diff --check
cd deploy/docker && docker compose config
cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.build.yml config
.venv/bin/ruff check apps packages
.venv/bin/python -m pytest -q
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Run `scripts/smoke-phase1.sh` only if Docker runtime cost is acceptable for the
current pass.
