# Phase 2.1 Frontend Migration — Feasibility Review

## Proposed Direction

- Replace the current Vue 3 + Element Plus + Vite frontend in `apps/web` with
  TypeScript + Next.js + shadcn/ui + Recharts.
- Keep the deployed UI static: Next.js `output: "export"`, no `next start`, no
  Node runtime in production.
- Keep FastAPI as the only runtime server: it serves static web assets from
  `DOPILOT_WEB_DIST=/app/web` and continues to serve `/api/v1/*`.
- Use shadcn slate colors, `sidebar-07`, `login-01`, right-top theme/language
  controls, and light/dark mode.
- Keep `/api/v1` contracts and server-to-web SSE unchanged.
- Update frontend docs and Docker web dependency/build stages.

## Claude Feedback

### Verdict

Feasible with changes.

### Blockers

None.

### Must-Fix Design Correction

The existing FastAPI static handler cannot remain exactly as-is. Vue/Vite emits
a single SPA `index.html`, so the current handler falls back to `index.html` for
any non-API route. Next static export emits one HTML file per route, so the
server must resolve route paths to exported files such as:

- `dashboard/index.html` when using `trailingSlash: true`, or
- `dashboard.html` when using flat `.html` output.

`apps/server/tests/test_web_static.py` must be updated accordingly.

### Risky Assumptions

- i18n copy can be reused, but `vue-i18n` must be replaced by a React-side
  library. `react-i18next` is the simplest static-export-safe choice.
- Dev proxy behavior changes because Vite proxy is going away. Production stays
  same-origin because FastAPI serves the exported web assets.
- Auth guarding remains client-side only. This matches the current SPA behavior;
  no Next middleware or server runtime is introduced.
- shadcn blocks require Tailwind and a shadcn project configuration.

### Questions

1. Static routing shape: use `trailingSlash: true` plus `path/index.html`, or
   flat `.html` route files.
2. i18n library: `react-i18next` versus `next-intl` no-routing mode.
3. Preserve existing `data-testid` values to keep Playwright smoke stable.
4. 404 behavior: switch from SPA always-200 fallback to exported `404.html`.
5. Whether to keep shadcn in `apps/web` only rather than introducing
   `packages/ui`.

### Suggested Scope Or Sequencing Changes

- Freeze the `data-testid` contract as a migration invariant.
- Keep shadcn components local to `apps/web`; do not add a shared `packages/ui`
  workspace.
- Update FastAPI static serving and its tests as part of the first
  implementation packet.
- Rebuild only the web dependency base image target; Python base image does not
  need dependency changes.

## Codex Decision

Accepted with Codex defaults below, pending user confirmation:

- Use `trailingSlash: true` and make FastAPI resolve both `path/index.html` and
  `path.html` for robustness.
- Use static route `/tasks/detail?id=<task_id>` instead of unknown dynamic
  `/tasks/:id`.
- Use `react-i18next`.
- Preserve meaningful `data-testid` values and update only selectors coupled to
  Element Plus implementation details.
- Use exported `404.html` for unknown non-API paths.
- Keep shadcn files inside `apps/web`; do not introduce `packages/ui`.
- Keep dark mode and Recharts in phase 2.1 scope because the user explicitly
  requested them.

## User Escalations

Need user approval only if any Codex default above is unacceptable.

## Resulting Brief Changes

The phase brief must explicitly include:

- shadcn skill usage and project setup.
- FastAPI static route resolver changes for Next static export.
- Next route shape change for task detail.
- Docker web base-image rebuild requirement.
- Full frontend test and browser smoke rewrite/update requirements.

## Skill Setup

Codex installed the project-level shadcn AI skill:

```bash
npx skills add shadcn/ui
```

Installed files:

- `.agents/skills/shadcn/`
- `skills-lock.json`

The shadcn skill requires `components.json` to activate project-aware context.
During implementation, Claude must initialize shadcn in the new Next app before
using `npx shadcn@latest info --json`, `docs`, `search`, or `add`.
