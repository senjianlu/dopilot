# Docs README Sync Brief

## Goal

Sync the public project README and top-level docs navigation with the current
dopilot state through the Python script phase, while preserving historical phase
records and established architecture facts.

The root README must become the default English entry point, with a Simplified
Chinese counterpart. Both should be concise, explain how dopilot works, include
quick deploy / quick start commands, introduce basic product concepts, and use
the committed logo.

## Context

Relevant files and decisions:

- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `docs/README.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/06-frontend-rewrite.md`
- `docs/dopilot/04-gap-i18n.md`
- `docs/phases/phase-2a/03-acceptance-report.md`
- `docs/phases/phase-2b/00-brief.md`
- `docs/phases/phase-2b/04d-codex-agent-fix-review.md`
- `docs/phases/phase-2b/05c-codex-page-e2e-review.md`
- `deploy/docker/docker-compose.yml`
- `deploy/docker/Dockerfile`
- `apps/web/app/layout.tsx`
- `apps/web/components/layout/app-sidebar.tsx`
- `logo.svg`

Current facts to respect:

- Current implemented scope is Scrapy plus Python wheel script execution.
- Docker long-running crawlers remain a future phase and must not be described
  as available.
- The web app is Next.js static export + shadcn/ui + react-i18next, served by
  `dopilot-server`; there is no Node production runtime or separate web
  container.
- Deployment uses one unified image, `rabbir/dopilot:latest`; server, agent, and
  migrate select roles by command.
- Server/agent runtime communication uses Redis Streams plus agent heartbeat.
  Redis is a transient message bus, not business truth.
- PostgreSQL is the authoritative database for business data and log indexes.
  Log bodies live under `/server-data/logs`.
- Python wheel scripts use `pip install --no-deps --target` plus `PYTHONPATH`.
  There is no venv, no dependency resolution, and no console-script entry point
  promise in this phase.
- `reference/scrapydweb/` is read-only behavioral reference only.

## In Scope

- Rewrite `README.md` in English as the default, concise public entry point.
- Add `README.zh-CN.md` in Simplified Chinese and cross-link both README files.
- Move the submitted `logo.svg` into the canonical web asset location
  `apps/web/public/logo.svg`, use it from README, and replace the sidebar brand
  icon with it without changing app workflows.
- Update `docs/README.md` quick facts/navigation where it still presents old
  Vue/Vite/vue-i18n or phase-0 assumptions as current.
- Update only the main planning docs that still state the superseded Python
  script venv plan as current:
  `docs/dopilot/00-requirements.md` and `docs/dopilot/10-roadmap.md`.
- Keep changes simple and avoid broad documentation rewrites.

## Out Of Scope

- Do not edit `docs/phases/**` historical briefs, implementation reports,
  reviews, test reports, or acceptance reports.
- Do not edit `docs/architecture/**`.
- Do not edit `docs/refactor/00-redis-streams-agent-communication.md`.
- Do not edit `reference/scrapydweb/**`.
- Do not claim Docker/K3s long-running crawlers are implemented.
- Do not introduce new product behavior beyond logo usage.
- Do not add a separate web container, nginx, Node production runtime, or
  alternate image names in documentation.

## Required Implementation Order

1. Place the logo at `apps/web/public/logo.svg` and update the sidebar brand
   icon to render that asset.
2. Rewrite `README.md` and add `README.zh-CN.md`.
3. Update the narrow stale spots in `docs/README.md`,
   `docs/dopilot/00-requirements.md`, and `docs/dopilot/10-roadmap.md`.
4. Run focused frontend and docs sanity checks.
5. Write the implementation report.

## Acceptance Criteria

- `README.md` is English, simple, default, and links to `README.zh-CN.md`.
- `README.zh-CN.md` mirrors the English README at a useful level and links back
  to `README.md`.
- Both README files display or reference `apps/web/public/logo.svg`.
- README quick deploy includes the base-image requirement, preferably via
  `make compose-up`, and mentions `http://localhost:5000`.
- README local development mentions both PostgreSQL and Redis, and does not
  describe Vite or port 5173.
- README accurately states current support: Scrapy and Python wheel scripts
  available; Docker long-running crawlers planned.
- README describes the Python wheel execution model without venv wording.
- `docs/README.md` no longer states Vue/Vite/vue-i18n as the current frontend.
- `docs/dopilot/00-requirements.md` and `docs/dopilot/10-roadmap.md` no longer
  state the script phase uses venv as the current plan.
- Historical phase files are untouched.

## Required Tests

- Frontend tests:

```bash
corepack pnpm --filter web test
corepack pnpm --filter web build
```

- Sanity checks:

```bash
git diff --check
rg -n "Vue 3 \\+ Element Plus|Vite|vue-i18n|venv" README.md README.zh-CN.md docs/README.md docs/dopilot/00-requirements.md docs/dopilot/10-roadmap.md
```

If frontend commands cannot run, record the exact blocker in the report.

## Risks To Watch

- The existing logo uses `fill="currentColor"`. It is fine inside the app, but
  can be low contrast in README dark mode if rendered as an external image.
- The root README is heavily stale and should be replaced, not patched.
- Do not modify phase history to make old reports appear current.
- Do not accidentally document `rabbir/dopilot-agent` or `senjianlu` as an image
  namespace.
