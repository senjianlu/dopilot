# Phase 2.1 — Claude Progress

## Estimate

- **Size class:** `90m+` (full Vue 3 → Next.js static-export rewrite: 10 pages, API
  client, auth, i18n, theme, sidebar/login blocks, log viewer SSE, FastAPI static
  serving change, unit + e2e tests, Docker, docs).

## Checkpoint plan

1. Toolchain + network sanity (done).
2. Read existing Vue source: API contracts, workflows, testids.
3. Scaffold Next.js static-export app + Tailwind + shadcn init (slate).
4. `shadcn add sidebar-07 login-01` + needed primitives; `info --json`.
5. FastAPI static resolver + `test_web_static.py`.
6. Port shared infra: api client/token, auth, i18n, theme, layout/top-right.
7. Port pages feature-by-feature preserving testids; `/tasks/detail?id=`.
8. Unit/component tests; e2e helpers/specs.
9. Docker base/runtime; docs.
10. Required commands; smoke if feasible.

## Likely long-running commands

- `corepack pnpm install` (network), `npx shadcn@latest add ...` (flaky network to
  ui.shadcn.com), `corepack pnpm --filter web build`, `docker compose ... config`,
  `scripts/smoke-phase1-ui.sh` (Docker build + browser).

## Blockers / risks

- **Network to `ui.shadcn.com` is intermittent** (observed 200 then SSL_ERROR_SYSCALL
  on consecutive curls). shadcn `add` may need retries; if a block can't be fetched
  it is recorded as a blocker.

## Log

- Started: read brief, feasibility, AGENTS, shadcn skill/cli, app.py, test_web_static.
- Verified node v22.22.3, corepack pnpm 11.7.0, npx 10.9.8, ruff 0.15.17.
- Scaffolded Next 15 static-export app (output:export, trailingSlash). Tailwind v4.
- shadcn init (manual components.json + slate globals.css). `info --json` OK.
- pnpm shim created (~/.local/bin/pnpm -> corepack pnpm) so shadcn `add` deps work.
- Added all primitives + blocks sidebar-07, login-01, chart (retry loop vs flaky TLS).
- Ported lib/api/* (verbatim), i18n (zh/en, {{var}}), theme/i18n providers, confirm
  hook (AlertDialog), LogViewer (SSE), status badges, app shell, all 8 pages +
  login + 404. Task detail route is /tasks/detail?id=.
- Built static export OK (13 routes, out/ with route/index.html + 404.html).
- FastAPI static resolver rewritten (route/index.html, .html, 404.html; /api never
  rewritten). test_web_static.py rewritten → 4 passed. Broader pytest → 429 passed.
- Frontend tests: 43 passed / 10 files (scrapyCommand, nodeSelection, templateCommand,
  api client/token, log-viewer SSE, nodes/artifacts/templates/schedules/task-detail).
- e2e helpers + spec updated: confirm-accept, radix Select, data-tone badges,
  /tasks/detail?id= route.
- Docker: Dockerfile.base (Next web-deps), Dockerfile (out/ copy), .dockerignore
  (out/.next). Frozen-lockfile install verified. `docker compose config` OK.
- ruff OK. Docs (00-requirements, 10-roadmap, 06-frontend-rewrite) updated to
  Next.js + shadcn + react-i18next.
- Verified FastAPI serving the REAL export end-to-end (ASGITransport): /, /dashboard/,
  /tasks/detail/?id=, /login/ = 200; /nope/ + /api/* = 404. OK.
- Implementation report written.
- Docker smoke attempt 1: image built OK, stack healthy, but Playwright found 0 tests
  — `import.meta` in the spec failed because the new package.json dropped
  `"type": "module"` (old Vue one had it). FIXED: re-added `"type": "module"`.
  Verified: playwright --list shows 9 tests; build + 43 vitest + frozen install
  still pass. Re-running smoke.
