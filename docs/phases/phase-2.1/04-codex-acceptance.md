# Phase 2.1 — Codex Acceptance Review

## Status

Accepted for user review.

Phase 2.1 now migrates `apps/web` from Vue 3 + Element Plus + Vite to
Next.js static export + shadcn/ui + Recharts + react-i18next + TypeScript,
while keeping production as static assets served by `dopilot-server`.

## What landed

- Next.js App Router static export (`output: "export"`, `trailingSlash: true`);
  no `next start` or Node production runtime.
- shadcn/ui components inside `apps/web` only, using slate tokens, `sidebar-07`
  and `login-01` as adapted source material.
- Light/dark toggle and language switch in the top-right app controls.
- Dashboard chart via Recharts/shadcn chart.
- Static export route serving in FastAPI:
  direct file -> route `index.html` -> route `.html` -> `404.html`, with `/api/*`
  excluded from frontend fallback.
- Task detail route changed to static-export-safe `/tasks/detail?id=<task_id>`.
- E2E and unit tests migrated to React Testing Library/Vitest and Playwright.
- Docker web base/runtime flow rebuilt around `apps/web/out`.
- shadcn project skill installed under `.agents/skills/shadcn` with
  `skills-lock.json`.
- `.claude/` added to `.gitignore` as local tool state.

## Review loop

Claude implemented the main migration from
`01-claude-implementation-prompt.md`.

Codex review found four follow-ups:

- `next lint` was interactive/failing under Next 15.
- Radix/shadcn wrappers emitted React 18 ref warnings.
- LogViewer tests emitted missing `act(...)` warnings.
- Several current docs still pointed developers at Vue/Vite/Element Plus.

Claude completed the bounded follow-up in `03-claude-fix-report.md`.
Codex then made one small cleanup: removed stale `unrs-resolver` / `eslint-config-next`
allowBuilds wording after confirming the final ESLint setup does not use it.

## Codex verification

All commands below were run by Codex after the follow-up fixes:

| Command | Result |
| --- | --- |
| `corepack pnpm install --filter web --frozen-lockfile` | passed |
| `corepack pnpm --filter web lint` | passed, non-interactive `eslint .` |
| `corepack pnpm --filter web test` | 43 passed, no React ref/`act(...)` warnings |
| `corepack pnpm --filter web typecheck` | passed |
| `corepack pnpm --filter web build` | passed, 13 static routes exported |
| `.venv/bin/pytest apps/server/tests/test_web_static.py` | 4 passed |
| `.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests` | 429 passed |
| `.venv/bin/ruff check apps packages` | passed |
| `cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config` | passed |
| `scripts/smoke-phase1-ui.sh` | passed, 9 Playwright browser tests |
| `git diff --check` | passed |
| `docker ps --format '{{.Names}}\t{{.Status}}'` | empty after smoke teardown |

The browser smoke covered login/navigation, nodes, artifact upload, Scrapy
template execution/logs, built-in wheel listing, Python wheel template execution
and logs, task detail, schedules trigger-now, and node offline/online/delete.

## Remaining risks

- ESLint is intentionally lean: core JS, TypeScript, and React Hooks rules. It
  does not yet enforce Next core-web-vitals or JSX accessibility rules.
- Some docs retain old Vue/Vite references as historical context. The updated
  banners point future work at phase 2.1's Next.js implementation.
- shadcn registry output is React-19-style plain function components. Because
  this repo currently runs React 18, local Radix wrappers use `forwardRef`; a
  future `shadcn add --overwrite` can reintroduce the warnings unless the change
  is reapplied or React is upgraded.
