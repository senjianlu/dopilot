# 03 · Phase 0 Acceptance

Date: 2026-06-18

Scope: Codex re-ran the phase 0 verification suite after Claude's fix commit
`379dfd3 feat: scaffold dopilot Phase 0 monorepo skeleton`.

## Verification Results

| Check | Command | Result |
|---|---|---|
| Python tests | `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests` | 48 passed |
| Python lint | `.venv/bin/ruff check apps packages` | passed |
| Web tests | `corepack pnpm --filter web test` | 3 passed |
| Web build | `corepack pnpm --filter web build` | passed |
| Compose config | `cd deploy/docker && docker compose config` | valid |
| Clean-volume compose smoke | `docker compose down -v`, then `docker compose up -d --build` | passed |

## Clean-Volume Compose Smoke

The compose backend loop was verified from a clean volume:

- `db` became healthy.
- `migrate` ran `alembic upgrade head` and exited with status `0`.
- The empty PostgreSQL database was initialized with:
  - `alembic_version`
  - `auth_tokens`
  - `nodes`
- `GET /api/v1/health` returned `status: ok` and `database: ok`.
- `POST /api/v1/auth/login` with the example admin credentials issued an opaque
  bearer token.
- `POST /api/v1/nodes/refresh` reached the agent over the compose network and
  returned a healthy node:
  - `endpoint: agent:6800`
  - `agent_id: scrapy-agent-1`
  - `capabilities: {scrapy: true, script: false, docker: false}`

After verification, `docker compose down -v` was run to remove containers,
network, and volumes.

## Notes

- `corepack pnpm --filter web test` still emits Vue warnings for unresolved
  `v-loading` in the isolated `NodesPage` test setup. This does not fail the
  suite and is non-blocking for phase 0.
- `corepack pnpm --filter web build` still emits Vite chunk-size warnings. This
  is non-blocking for phase 0.

## Acceptance Decision

Phase 0 is accepted. The platform skeleton is committed, testable, and the
backend compose loop now starts correctly from an empty database.
