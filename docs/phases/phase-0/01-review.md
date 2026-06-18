# 01 · Phase 0 Implementation Review

Date: 2026-06-18

Scope: review Claude's phase 0 implementation after development. Phase 0 is a
platform skeleton only: real Scrapy/script/docker execution is intentionally out
of scope and 501 stubs are acceptable where documented.

## Findings

### P1: Docker backend loop cannot initialize a fresh database

`deploy/docker/docker-compose.yml` starts `server` after `db` is healthy, but no
service or entrypoint runs Alembic migrations.

`deploy/docker/Dockerfile.server` installs only built wheels into the runtime
image. `apps/server/pyproject.toml` packages only `dopilot_server`, so
`apps/server/migrations/` and `apps/server/alembic.ini` are not available inside
the server image.

Impact: `docker compose up server agent db` from an empty volume can start the
server process, but DB-backed endpoints such as login and nodes will fail because
the `auth_tokens` and `nodes` tables were never created.

Expected fix:

- Add an explicit migration path for Docker/release startup.
- Ensure Alembic assets are available in the server image, either by packaging
  them or copying them into the runtime image.
- Keep the rule that the app itself does not call `Base.metadata.create_all()` in
  production.

### P2: Generated frontend artifacts are in the untracked app tree

`rg --files apps/web` shows generated files:

- `apps/web/tsconfig.tsbuildinfo`
- `apps/web/tsconfig.node.tsbuildinfo`
- `apps/web/vite.config.js`
- `apps/web/vite.config.d.ts`

These are outputs from the TypeScript/Vite build path. `.gitignore` currently
ignores `apps/web/dist/` and `apps/web/node_modules/`, but not these files.

Expected fix:

- Add ignore rules for generated TS build info and emitted Vite config files, or
  configure TypeScript output so these files are not emitted into the source tree.
- Do not commit generated build artifacts.

## Verification Run

Commands run during review:

```bash
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check .
cd deploy/docker && docker compose config
```

Results:

- Python tests: 48 passed.
- Web tests: 3 passed.
- Web production build: passed, with Vite chunk-size warning.
- Ruff: passed.
- Docker compose config: passed.

Notes:

- `corepack pnpm --filter web test` emitted Vue warnings for unresolved
  `v-loading` in the isolated `NodesPage` test. This did not fail the suite, but
  the test setup can register Element Plus directives if the warning becomes
  noisy.
- The Vite production build warned that the main JS chunk is larger than 500 kB.
  This is acceptable for phase 0, but should be revisited when the web app grows.

## Review Conclusion

The phase 0 skeleton is mostly self-consistent and matches the intended boundary:
server, agent, web, protocol, config, auth, node health, stubs, and tests are in
place. The Docker + Alembic migration gap is the only blocking issue for claiming
the backend compose loop works from a clean database.
