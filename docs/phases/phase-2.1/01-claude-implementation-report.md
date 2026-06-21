# Phase 2.1 — Claude Implementation Report

Frontend migration: **Vue 3 + Element Plus + Vite → Next.js (static export) +
shadcn/ui + Recharts + react-i18next**, preserving the FastAPI `/api/v1/*`
backend and the static-web deployment model.

## Summary

`apps/web` is now a Next.js 15 App-Router TypeScript app built with
`output: "export"` + `trailingSlash: true` (no `next start`, no Node production
runtime). shadcn/ui (radix base, **slate** theme, Tailwind v4) provides the
component layer; the `sidebar-07` and `login-01` blocks were installed and
adapted. Light/dark + language switches sit together top-right. The dashboard
chart uses Recharts (via shadcn `chart`). FastAPI static serving was rewritten
for per-route export files. All host checks pass; see
[Commands](#commands-run--exact-outcomes).

## Changed files by area

### Frontend app scaffold (`apps/web/`, new)

- `package.json` (rewritten: next/react/tailwind v4/shadcn deps), `next.config.mjs`
  (`output: export`, `trailingSlash`, `images.unoptimized`), `tsconfig.json`,
  `postcss.config.mjs`, `components.json` (shadcn: radix/new-york/slate),
  `.gitignore`, `vitest.config.ts`, `vitest.setup.ts`.
- `app/`: `layout.tsx` (providers), `globals.css` (slate tokens + Tailwind v4),
  `page.tsx` (redirect → `/login`), `not-found.tsx` (→ `404.html`),
  `login/page.tsx`, and the authenticated route group `app/(app)/`:
  `layout.tsx` (sidebar shell), `dashboard/`, `nodes/`, `artifacts/`,
  `templates/`, `schedules/`, `tasks/`, `tasks/detail/`, `maintenance/`.

### shadcn components

- `components/ui/*` — installed primitives (button, input, label, card, table,
  badge, alert, alert-dialog, dialog, select, dropdown-menu, separator,
  skeleton, sonner, tooltip, sheet, sidebar, breadcrumb, avatar, tabs,
  collapsible, scroll-area, switch, pagination, chart, empty, spinner, field,
  textarea).
- `components/layout/` — `app-sidebar.tsx` (adapted `sidebar-07`),
  `locale-switch.tsx`, `theme-toggle.tsx`, `top-controls.tsx`.
- `components/features/` — `login-form.tsx` (adapted `login-01`),
  `log-viewer.tsx` (SSE), `status-badge.tsx` (`ToneBadge`/`StatusLight`).
- `components/providers.tsx` — theme + i18n + toaster + 401 handler.
- `hooks/use-confirm.tsx` — imperative `useConfirm` over shadcn `AlertDialog`.

### Frontend library (`apps/web/lib/`)

- `api/*` — axios client, token store, types, and resource modules (auth,
  health, nodes, artifacts, templates, schedules, tasks, stats, maintenance)
  ported verbatim from the Vue app (framework-agnostic).
- `i18n/config.ts` + `i18n/locales/{zh,en}.ts` (react-i18next; `{var}` →
  `{{var}}`), `nodeBadge.ts`, `nodeSelection.ts`, `scrapyCommand.ts`,
  `templateCommand.ts`, `utils.ts` (`cn`), `test/render.tsx`.

### Backend (static serving only)

- `apps/server/dopilot_server/app.py` — static resolver rewritten for Next
  export: direct file → `<route>/index.html` → `<route>.html` → `404.html`;
  `/api/*` never rewritten; CORS origin updated to the Next dev port (`:3000`).
- `apps/server/tests/test_web_static.py` — rewritten for export semantics.

### Tests (frontend)

- `lib/__tests__/{scrapyCommand,nodeSelection,templateCommand}.test.ts`,
  `lib/api/__tests__/client.test.ts`,
  `components/features/__tests__/log-viewer.test.tsx`,
  `app/(app)/{nodes,artifacts,templates,schedules,tasks}/__tests__/*.test.tsx`.
- e2e: `e2e/helpers/ui.ts` + `e2e/specs/phase1-ui.spec.ts` updated.

### Build / docs / workspace

- `deploy/docker/Dockerfile` (copy `apps/web/out` → `/app/web`),
  `deploy/docker/Dockerfile.base` (web-deps comment), `.dockerignore`
  (`out/` + `.next/`), `pnpm-workspace.yaml` (`allowBuilds`), `pnpm-lock.yaml`.
- `docs/dopilot/00-requirements.md`, `10-roadmap.md`, `06-frontend-rewrite.md`.

### Removed

- The entire Vue tree under `apps/web/src/`, plus `index.html`,
  `vite.config.ts`, `tsconfig.node.json`, `env.d.ts`.

## Implementation notes

- **Routing / static export.** App Router with a `(app)` route group carrying
  the sidebar shell; `login` and the root redirect sit outside it. Task detail
  moved from `/tasks/:id` to **`/tasks/detail?id=<task_id>`** (static export has
  no dynamic route file); the component reads `?id` via `useSearchParams`, which
  is wrapped in `<Suspense>` (required for export prerender).
- **Auth.** Client-side only (no Next middleware). The axios 401 interceptor
  calls a handler registered in `Providers` that does `router.replace("/login")`
  — same behavior as the old SPA. `LogViewer` decides whether to fetch an SSE
  `stream_token` by checking `getToken()`.
- **Theme.** `next-themes` (`attribute="class"`, persisted) drives the shadcn
  slate tokens. Recharts series use `var(--color-*)` from the shadcn `ChartConfig`
  so chart colours follow the theme.
- **i18n.** Single `i18next` instance, default `zh`, persisted override applied
  after mount (avoids hydration mismatch). Message catalogs reuse the existing
  zh/en content with interpolation converted to `{{var}}`.
- **Confirmations.** The Element Plus `ElMessageBox` promise helper became an
  imperative `useConfirm()` backed by one shared `AlertDialog`; pages still call
  `await confirm({...})` and branch on the boolean (keeps them unit-testable).
- **Status colours.** Node/task traffic-light state renders via `ToneBadge` /
  `StatusLight` carrying a stable `data-tone` (`green|red|amber|gray`). e2e keys
  on `data-tone` instead of the removed `el-tag--*` classes.
- **testid contract preserved** where it mattered: `app-shell`, `nav-*`,
  `login-*`, `nodes-table`, `node-agent-*`, `node-badge-*`, `node-cap-*-*`,
  `node-offline/online/delete-*`, `artifacts-table`, `artifact-*`,
  `templates-table`, `template-*`, `schedules-table`, `schedule-*`,
  `tasks-table`, `task-view-*`, `task-detail`, `task-status`, `task-mark-lost`,
  `task-executions`, `execution-agent-*`, `maintenance-*`, `log-body`.

## shadcn commands run + adaptations

Project setup was deterministic (hand-written `components.json` + slate
`globals.css`) to avoid the interactive base-color prompt; everything else used
the CLI. `npx shadcn@latest info --json` confirmed: framework `next`,
`tailwindVersion v4`, `base radix`, `style new-york`, `iconLibrary lucide`,
alias `@`, `rsc true`.

Commands (all via the project package runner; a `pnpm` PATH shim → `corepack
pnpm` was needed because the CLI shells out to bare `pnpm`):

- `npx shadcn@latest add <primitive>` for each primitive listed above (run in a
  retry loop — see Risks: the `ui.shadcn.com` registry host returned intermittent
  TLS resets, so single-component adds were retried until each landed).
- `npx shadcn@latest add chart`
- `npx shadcn@latest add sidebar-07`
- `npx shadcn@latest add login-01`

Adaptations to the generated blocks (per the skill: adapt, don't keep demo
content):

- **`sidebar-07`** shipped `app-sidebar.tsx` + `nav-main/nav-projects/nav-user/
  team-switcher.tsx` (sample teams/projects/user) and a demo `app/dashboard/
  page.tsx`. All demo files were **removed**; `components/layout/app-sidebar.tsx`
  was written fresh: dopilot's flat 7-item nav (Link + `usePathname` active
  state + `nav-<key>` testids) and a dopilot brand header. The demo
  `app/dashboard/page.tsx` collided with the route-group page and was deleted.
- **`login-01`** shipped `components/login-form.tsx` (email / Google / forgot /
  signup) + `app/login/page.tsx`. The form was rewritten to
  `components/features/login-form.tsx`: single admin username/password using
  `FieldGroup`/`Field`, calling the real `login` API, preserving `login-username`
  / `login-password` / `login-submit` testids; the page imports it.
- Generated UI primitives were used as-is; semantic tokens + variants throughout
  (`Field`/`FieldGroup` for forms, `AlertDialog` for destructive confirms,
  `Empty`/`Skeleton`/`Spinner`/`Badge` rather than custom markup, `gap-*` not
  `space-*`).

## Tests added / updated

- **Pure logic (vitest):** `scrapyCommand` (9), `nodeSelection` + node-badge tone
  (5), `templateCommand` scrapy-vs-wheel (5), api client/token + `buildStreamUrl`
  (5).
- **Components (Testing Library + jsdom):** `LogViewer` EventSource incl. stream
  token (2); pages — nodes (badge/cap tones + offline confirm/cancel),
  artifacts (rows + egg upload + wheel details), templates (render + default
  command + run-navigates + delete-confirm), schedules (render + trigger-nav +
  delete-confirm), task-detail (status/executions + cancel + mark-lost + terminal
  hides actions).
- **Server:** `test_web_static.py` rewritten for export route resolution + API
  non-rewrite + exported 404.
- **e2e:** helpers (`confirm-accept`, radix Select, login Input) and the spec
  (`data-tone` badges, `/tasks/detail?id=` route) updated; Scrapy + Python-wheel
  paths preserved.

## Commands run — exact outcomes

| Command | Result |
| --- | --- |
| `.venv/bin/pytest apps/server/tests/test_web_static.py` | **4 passed** |
| `corepack pnpm --filter web test` | **43 passed** (10 files) |
| `corepack pnpm --filter web build` | **success** — 13 routes exported to `out/` |
| `.venv/bin/ruff check apps packages` | **All checks passed** |
| `cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config` | **OK** |
| `.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests` | **429 passed** |
| FastAPI serving the real `out/` (ASGITransport sanity) | `/`, `/dashboard/`, `/tasks/detail/?id=`, `/login/` = 200; `/nope/`, `/api/*` = 404 |
| `corepack pnpm install --filter web --frozen-lockfile` | **Already up to date** (Docker-parity) |

## Docker / browser smoke

<!-- SMOKE_RESULT -->
_Pending — `scripts/smoke-phase1-ui.sh` is running (clean-volume Docker stack +
Playwright). Result appended below on completion._

## Known risks / shortcuts / incomplete items

- **shadcn registry flakiness.** `ui.shadcn.com` returned intermittent TLS
  resets; component installs used a retry loop. All required components/blocks
  landed. No offline fallback was needed.
- **Node multi-select.** The "selected" node picker is a wrap of toggle
  `ToneBadge`s (not a Popover+Command combobox) — simpler, shadcn-native, and the
  branch logic lives in the unit-tested `nodeSelection`/pure helpers. radix
  `Select`-driven paths (artifact/strategy/template pickers) are exercised by the
  Playwright smoke rather than jsdom (radix Select is unreliable under jsdom).
- **Dev proxy removed.** The Vite `/api` proxy is gone; production is same-origin
  (FastAPI hosts the export). Devs running `next dev` point at a server via
  `NEXT_PUBLIC_API_BASE`; CORS now allows `:3000`.
- **`pnpm` PATH shim.** The shadcn CLI shells out to bare `pnpm`; this box only
  has `corepack pnpm`, so a shim was added to `~/.local/bin` for the install
  session. Not required at runtime or for `corepack pnpm --filter web …`.
- Auth remains client-side only for web routes (unchanged from the old SPA;
  backend API auth stays authoritative).
