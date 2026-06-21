# Phase 2.1 Frontend Migration — Claude Feasibility Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of the proposed phase-2.1 frontend migration before
Codex finalizes the implementation brief.

Do **not** implement code in this step.

## Proposed Direction

Phase 2.1 migrates the existing `apps/web` frontend from Vue 3 + Element Plus +
Vite to:

- TypeScript + Next.js.
- Static export only: configure Next with `output: "export"` and keep the final
  deployed web UI as static HTML/CSS/JS served by the existing FastAPI server
  from `DOPILOT_WEB_DIST=/app/web`.
- shadcn/ui using the slate palette from `https://v3.shadcn.com/colors`.
- Use the shadcn block `sidebar-07` via `npx shadcn@latest add sidebar-07` as
  the layout baseline.
- Use the shadcn block `login-01` via `npx shadcn@latest add login-01` as the
  login baseline, adapted to dopilot's single-admin username/password auth.
- Use Recharts for dashboard charts.
- Add light/dark theme switching on the top-right, next to the language switch.
- Keep i18n with existing zh/en copy, defaulting to Chinese.
- Keep browser `EventSource` SSE for logs. No WebSocket.
- Keep `/api/v1/*` API contracts unchanged.
- Update frontend documentation that currently names Vue/Element Plus/Vite.
- Update Docker web dependency base image and unified Dockerfile because the
  build moves from Vite `dist/` to Next static `out/`.

Default static-export routing decision for validation:

- Avoid unknown dynamic Next routes.
- Replace the current task detail route `/tasks/:id` with a static route using
  a query string, e.g. `/tasks/detail?id=<task_id>`.
- Update Web code and Playwright smoke selectors/links accordingly.
- Do not introduce a Next Node runtime or `next start`.

## Required Context

Read only what is needed:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/06-frontend-rewrite.md`
- `apps/web/package.json`
- `apps/web/src/`
- `apps/web/e2e/`
- `deploy/docker/Dockerfile`
- `deploy/docker/Dockerfile.base`
- `apps/server/dopilot_server/app.py`
- `apps/server/tests/test_web_static.py`

External documentation Codex checked:

- Next static export docs: `https://nextjs.org/docs/pages/guides/static-exports`
- shadcn v3 colors: `https://v3.shadcn.com/colors`
- shadcn sidebar docs: `https://v3.shadcn.com/docs/components/sidebar`
- shadcn monorepo docs: `https://v3.shadcn.com/docs/monorepo`

## Output Required

Return a concise feasibility response with these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing product or architecture decisions for Codex.
5. Suggested scope cuts or sequencing changes.

Focus on implementation feasibility against the current repository. In
particular, validate:

- Whether Next static export can preserve the current FastAPI static hosting
  model.
- Whether the `/tasks/detail?id=...` route decision is enough to avoid dynamic
  route export problems.
- Whether shadcn `sidebar-07` and `login-01` are plausible in this monorepo
  without adding a separate `packages/ui` workspace.
- Which tests and smoke checks must be rewritten.
- Whether the Docker base image truly needs to be rebuilt.

Keep the response short and concrete. If there are no blockers, say so clearly.
