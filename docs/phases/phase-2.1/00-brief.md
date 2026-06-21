# Phase 2.1 Brief — Frontend Migration To Next.js + shadcn/ui

## Goal

Replace the current Vue 3 + Element Plus + Vite frontend with a static
TypeScript + Next.js frontend using shadcn/ui, slate colors, light/dark mode,
and Recharts, while preserving the existing FastAPI `/api/v1/*` backend and the
static-web deployment model.

The final deployed UI must still be static HTML/CSS/JS served by
`dopilot-server`; phase 2.1 must not introduce `next start`, a Node production
runtime, WebSocket, or a separate frontend container.

## Context

Relevant files and decisions:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/06-frontend-rewrite.md`
- `docs/phases/phase-2.1/00a-feasibility-review.md`
- `.agents/skills/shadcn/SKILL.md`
- `apps/web/`
- `apps/server/dopilot_server/app.py`
- `apps/server/tests/test_web_static.py`
- `deploy/docker/Dockerfile`
- `deploy/docker/Dockerfile.base`
- `scripts/smoke-phase1-ui.sh`

External docs checked by Codex:

- Next static exports:
  `https://nextjs.org/docs/pages/guides/static-exports`
- shadcn skills:
  `https://ui.shadcn.com/docs/skills`
- shadcn v3 colors:
  `https://v3.shadcn.com/colors`
- shadcn sidebar docs:
  `https://v3.shadcn.com/docs/components/sidebar`
- shadcn monorepo docs:
  `https://v3.shadcn.com/docs/monorepo`

## User Decisions

- Treat this as phase 2.1.
- Use TypeScript + Next.js + shadcn/ui + Recharts.
- Keep the final output static.
- Use the slate palette from `https://v3.shadcn.com/colors`.
- Use `npx shadcn@latest add sidebar-07` for the sidebar baseline.
- Use `npx shadcn@latest add login-01` for the login baseline.
- Put theme switching in the top-right with the language switch.
- Use the shadcn AI skill.
- Rework the web build base image as needed.
- Keep shadcn components inside `apps/web`; do not add `packages/ui`.

## In Scope

- Replace `apps/web` Vue/Vite app with a Next.js TypeScript app.
- Configure Next static export:
  - `output: "export"`.
  - `trailingSlash: true`.
  - no production `next start`.
- Initialize shadcn in `apps/web`.
  - Components live in `apps/web/components/ui`.
  - App/business components live under `apps/web/components`, grouped by role
    (`layout`, `features`, etc.) rather than mixed into `components/ui`.
  - Use slate as the base color.
  - Use the installed project-level shadcn skill and run shadcn CLI commands
    from `apps/web`.
- Add required shadcn blocks and components:
  - `sidebar-07`.
  - `login-01`.
  - shadcn primitives needed for forms, dialogs, tables, badges, alerts,
    pagination, selects, uploads, skeletons/spinners, tooltips, and charts.
- Preserve current user-facing workflows:
  - login/logout and auth-off tolerance;
  - dashboard health and stats;
  - nodes list, capabilities, offline/online/delete;
  - build artifact list/upload/details for Scrapy egg and Python wheel;
  - execution templates create/run/delete, including Python wheel shell command;
  - schedules create/delete/trigger-now with overrides;
  - tasks list and task detail;
  - realtime log viewer over EventSource/SSE.
- Route changes required by static export:
  - replace current `/tasks/:id` client route with
    `/tasks/detail?id=<task_id>`.
  - update all navigation, tests, and Playwright expectations accordingly.
- FastAPI static hosting changes:
  - keep `/api` paths API-only and never rewrite them to web assets.
  - resolve exported static route files before falling back.
  - support `path/index.html` for `trailingSlash: true`.
  - optionally support `path.html` for robustness.
  - serve exported `404.html` for unknown non-API static routes.
- i18n:
  - replace `vue-i18n` with a React-side static-export-safe solution.
  - default choice: `react-i18next`.
  - reuse existing zh/en message content where practical.
  - default language remains Chinese.
- Theme:
  - add light/dark mode using CSS variables and class-based theme switching.
  - persist theme in browser storage.
  - put the theme switch next to the language switch in the top-right.
  - ensure Recharts colors follow theme tokens.
- Docker/build:
  - update `apps/web/package.json`, lockfile, and web build scripts.
  - update `deploy/docker/Dockerfile.base` web dependency target for Next,
    React, Tailwind, shadcn, Recharts, and related dependencies.
  - update `deploy/docker/Dockerfile` to copy Next static export output into
    `/app/web`.
  - keep the Python base/runtime unchanged unless a concrete build failure
    proves otherwise.
- Tests:
  - replace Vue unit tests with React/Next-compatible tests.
  - preserve key `data-testid` names where possible to keep Playwright flow
    stable.
  - update Playwright helpers that were coupled to Element Plus DOM/classes.
  - keep browser smoke coverage for both Scrapy and Python wheel flows.
- Docs:
  - update `docs/dopilot/00-requirements.md`,
    `docs/dopilot/10-roadmap.md`, and
    `docs/dopilot/06-frontend-rewrite.md` frontend technology references.
  - add implementation/test reports under `docs/phases/phase-2.1/`.

## Out Of Scope

- No backend API contract redesign.
- No database, Redis, scheduler, executor, or agent behavior changes.
- No Next production server, no `next start`, no SSR-only features, no server
  actions, no route handlers, no Next middleware auth guard.
- No `packages/ui` workspace in phase 2.1.
- No new multi-user/RBAC behavior.
- No visual marketing/landing-page redesign; this is an operational admin UI.
- No change to server-to-web SSE protocol and no WebSocket.

## Required Implementation Order

1. Read the shadcn skill and run project-aware shadcn commands only after
   initializing `components.json` inside `apps/web`.
2. Replace the web scaffold with Next static export and Tailwind/shadcn setup.
3. Implement or adapt FastAPI static-file resolution for Next static export and
   update `apps/server/tests/test_web_static.py`.
4. Port shared frontend infrastructure:
   - API client and token handling;
   - auth store/hook;
   - i18n;
   - theme provider/switch;
   - layout/sidebar/top-right controls.
5. Add shadcn `sidebar-07` and adapt it to dopilot navigation.
6. Add shadcn `login-01` and adapt it to dopilot username/password login.
7. Port pages and components feature by feature, preserving testids:
   dashboard, nodes, artifacts, templates, schedules, tasks, task detail,
   maintenance, log viewer.
8. Replace or update unit/component tests.
9. Update Playwright e2e helpers/specs for shadcn DOM and the new
   `/tasks/detail?id=...` route.
10. Update Docker build files and frontend docs.
11. Run required host checks and, if feasible in the current run, the Docker
    browser smoke.

## Acceptance Criteria

- `apps/web` is a Next.js TypeScript app with static export enabled.
- `corepack pnpm --filter web build` produces static output suitable for
  FastAPI hosting.
- FastAPI serves exported route HTML correctly:
  - `/dashboard/` returns the dashboard HTML asset.
  - `/tasks/detail/?id=<id>` or equivalent trailing-slash form returns the task
    detail HTML asset.
  - `/api/...` is not rewritten to HTML.
  - unknown non-API paths use `404.html`.
- The visible UI uses shadcn components with slate theme tokens and supports
  light/dark switching.
- The sidebar is based on `sidebar-07`.
- Login is based on `login-01`.
- Language and theme controls are together in the top-right.
- Dashboard charting uses Recharts.
- Existing operational workflows still work through the browser smoke:
  Scrapy egg upload/run/logs, Python wheel listing/run/logs, tasks, schedules,
  nodes actions.
- No production Node runtime is introduced.
- No `packages/ui` workspace is introduced.
- Documentation no longer states Vue/Element Plus/Vite as the active frontend
  technology stack.

## Required Tests

Unit / component coverage:

- React/API client/auth/token behavior.
- Log viewer EventSource behavior including stream token handling.
- Pages with high branch complexity:
  - build artifacts upload/details;
  - templates create/run/delete, including Python wheel free-form command;
  - schedules create/delete/trigger-now/overrides;
  - nodes actions and capability rendering;
  - task detail cancel/mark-lost/log viewer.

Integration / server coverage:

- `apps/server/tests/test_web_static.py` for Next static export route
  resolution and API non-rewrite behavior.

Frontend e2e coverage:

- Update `apps/web/e2e/specs/phase1-ui.spec.ts` and helpers to pass on the
  shadcn/Next UI.
- Preserve coverage for both Scrapy and Python wheel paths.

Smoke / manual coverage:

- `scripts/smoke-phase1-ui.sh` should pass against the bundled production static
  Next UI.
- If Docker smoke cannot run, record the exact blocker and leave no containers
  running.

## Required Commands

Claude should run the narrowest commands during iteration, and the final report
must include exact outcomes for:

```bash
.venv/bin/pytest apps/server/tests/test_web_static.py
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config
```

For final page-level verification, run if feasible:

```bash
scripts/smoke-phase1-ui.sh
```

If implementation touches shared backend static-serving behavior beyond
`test_web_static.py`, broaden pytest to:

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests
```

## shadcn Rules

- Use the installed skill at `.agents/skills/shadcn/SKILL.md`.
- After shadcn initialization, run:

```bash
npx shadcn@latest info --json
```

- Before using major shadcn components, run `npx shadcn@latest docs <component>`
  and consult the returned docs.
- Use `npx shadcn@latest add ... --dry-run` before adding or updating
  components when practical.
- Use semantic tokens and component variants rather than raw Tailwind colors.
- Use `gap-*`, not `space-x-*` / `space-y-*`.
- Use `FieldGroup` / `Field` patterns for forms where the installed shadcn
  version provides them.
- Use `AlertDialog` for destructive confirmations.
- Do not create duplicate UI primitives outside `components/ui`.

## Risks To Watch

- Static export route handling is the main architecture risk; do not leave SPA
  fallback behavior that always serves root `index.html`.
- Next App Router client components need `"use client"` wherever browser APIs,
  hooks, EventSource, localStorage, or event handlers are used.
- shadcn blocks may import assets, routes, icons, or file paths that need cleanup
  for this repo.
- Tailwind/shadcn dependency installation changes the lockfile and web base
  image cache; Docker build must be verified.
- Existing Playwright selectors rely on Element Plus classes and teleported DOM;
  update helpers instead of weakening e2e assertions.
- Auth is still client-side only for web routes; this is acceptable because it
  matches current static SPA behavior and backend API auth remains authoritative.
