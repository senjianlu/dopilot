# 06 · Phase 1 Acceptance

Date: 2026-06-18

Scope: Codex re-ran the Phase 1 verification suite after Claude's second review
response in `docs/phases/phase-1/05-review-response.md`.

## Acceptance Decision

**Phase 1 is accepted.**

The Scrapy execution chain is now verified end to end:

```text
web/server API
  -> server ScrapydExecutor
  -> dopilot-agent HTTP API
  -> agent-managed scrapyd
  -> scrapy job
  -> agent log tail
  -> server pull + /server-data/logs
  -> PostgreSQL execution/log indexes
  -> server/web log APIs
```

The two Codex review blockers were resolved:

- `scrapyd` unreachable no longer implies `finished` just because a log file
  exists; agent now reports `unknown` and lets server lost/timeout policy handle
  it.
- SSE log streaming no longer pins a request-scoped DB session for the lifetime
  of the stream; preflight DB reads use a short-lived session before
  `StreamingResponse` starts.

The second-round Docker build blocker was also resolved by pinning
`psycopg[binary]==3.3.4` and adding pip retry/timeout settings to the Docker
builds. A clean-volume compose smoke run now completes successfully.

## Verification Results

| Check | Command | Result |
|---|---|---|
| Docker availability | `command -v docker`; `docker version` | Docker CLI and daemon available |
| Docker Hub access | `docker pull python:3.12-slim` | passed |
| Python tests | `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests` | 179 passed |
| Python lint | `.venv/bin/ruff check apps packages` | passed |
| Web tests | `corepack pnpm --filter web test` | 7 passed |
| Web build | `corepack pnpm --filter web build` | passed |
| Compose config | `cd deploy/docker && docker compose config` | valid |
| Phase 1 smoke | `bash scripts/smoke-phase1.sh` | `SMOKE PASSED`, 14 passed / 0 failed |
| Compose cleanup | `cd deploy/docker && docker compose ps --all` | no remaining containers |

## Phase 1 Smoke Details

The smoke script verified the real compose-backed Scrapy path from clean
volumes:

- Built `rabbir/dopilot:latest` and `rabbir/dopilot-agent:latest`.
- Started PostgreSQL, migration, agent, and server services.
- Confirmed:
  - `db` healthy.
  - `migrate` completed `alembic upgrade head`.
  - `agent` healthy.
  - `server` healthy.
  - `agent /health` reports `detail.scrapyd.running == true`.
- Logged in with the example admin credentials and obtained a bearer token.
- Refreshed nodes and confirmed the compose agent is healthy with scrapyd
  running.
- Confirmed the committed demo egg exists:
  `tests/fixtures/scrapy_demo/eggs/demo_phase1.egg`.
- Uploaded the demo egg through the server artifact API.
- Created a Scrapy execution through `POST /api/v1/executions/run`.
- Polled execution detail until terminal status `complete`.
- Read logs through the server log API and confirmed both demo markers:
  - `phase1 demo spider started`
  - `phase1 demo spider done`
- Confirmed final execution status remains `complete`.
- The script ran teardown with `docker compose down -v`; no compose containers
  remained afterward.

## Accepted Behavior

Phase 1 now provides:

- Real agent-managed scrapyd subprocess startup in the Docker agent image.
- Real Scrapy egg deployment via agent `/artifacts/scrapy/egg`.
- Real Scrapy job scheduling through server `ScrapydExecutor` and agent `/run`.
- Persistent execution / attempt / log index models and Alembic migration.
- Server-side log pull into `/server-data/logs`.
- Offset-based log tailing and final drain.
- SSE log streaming with reconnect/backfill behavior.
- Node refresh and node selection for `all`, `random`, and `selected`.
- Explicit handling for lost/unknown attempts instead of indefinitely running
  tasks.
- Regression tests for the reviewed failure modes.

## Residual Non-Blocking Items

- `corepack pnpm --filter web test` still emits Vue warnings for unresolved
  `v-loading` in isolated page test setup. The assertions pass; this can be
  cleaned up by registering or stubbing the Element Plus loading directive in
  Vitest setup.
- `corepack pnpm --filter web build` still emits Vite chunk-size warnings. This
  is acceptable for Phase 1 and can be addressed later with route-level splitting
  or manual chunks.

## Handoff Notes

Phase 1 is ready to commit. The next phase can build on the accepted Scrapy
execution baseline without reopening the Phase 1 blockers.
