# Phase 2.1 — Claude Implementation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/phase-2.1/00-brief.md`

This is a broad frontend migration. Keep changes scoped to the brief and avoid
backend behavior changes except the required static-export hosting update.

## Required Context

Read these before editing:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2.1/00-brief.md`
- `docs/phases/phase-2.1/00a-feasibility-review.md`
- `.agents/skills/shadcn/SKILL.md`
- `.agents/skills/shadcn/cli.md`
- `.agents/skills/shadcn/rules/composition.md`
- `.agents/skills/shadcn/rules/forms.md`
- `.agents/skills/shadcn/rules/icons.md`
- `.agents/skills/shadcn/rules/styling.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/06-frontend-rewrite.md`
- `apps/web/`
- `apps/server/dopilot_server/app.py`
- `apps/server/tests/test_web_static.py`
- `deploy/docker/Dockerfile`
- `deploy/docker/Dockerfile.base`
- `scripts/smoke-phase1-ui.sh`

## In Scope

- Replace `apps/web` with a Next.js TypeScript static-export app.
- Initialize and use shadcn/ui inside `apps/web`.
- Install the shadcn blocks requested by the user:
  - `npx shadcn@latest add sidebar-07`
  - `npx shadcn@latest add login-01`
- Use slate colors.
- Keep shadcn components local to `apps/web`; do not add `packages/ui`.
- Add light/dark mode and language switching in the top-right.
- Use Recharts for dashboard charts.
- Preserve workflows and key `data-testid` values where practical.
- Change task detail URL to `/tasks/detail?id=<task_id>`.
- Update FastAPI static serving for Next static export.
- Update tests, Docker build files, lockfile, and frontend docs.

## Out Of Scope

- Do not edit `reference/scrapydweb/`.
- Do not copy code or structure from `reference/scrapydweb/`.
- Do not redesign backend APIs.
- Do not introduce a Next production server, SSR-only features, server actions,
  route handlers, or Next middleware auth.
- Do not add `packages/ui`.
- Do not change Redis, scheduler, agent, or executor behavior.

## shadcn Requirements

- Use the installed shadcn skill instructions.
- Run shadcn commands from `apps/web`.
- After initialization, run and inspect:

```bash
npx shadcn@latest info --json
```

- Use `npx shadcn@latest docs <component>` before major component use.
- Use shadcn CLI for registry components; do not manually fetch registry files.
- Read and review files added by `sidebar-07` and `login-01`; adapt them to
  dopilot rather than keeping demo content.
- Use semantic tokens, component variants, and shadcn composition rules.

## Progress Notes

Create/update:

- `docs/phases/phase-2.1/claude-progress.md`

At the start, write a short estimate with size class (`45-90m` or `90m+` is
acceptable), checkpoint plan, likely long-running commands, and blockers. Update
the progress file at meaningful checkpoints and before/after long-running
commands.

## Output Required

Create:

- `docs/phases/phase-2.1/01-claude-implementation-report.md`

The report must include:

- changed files grouped by area;
- implementation notes;
- shadcn commands run and any adaptations made to generated blocks;
- tests added or updated;
- commands run with exact pass/fail outcomes;
- Docker/browser smoke outcome or exact blocker;
- known risks, shortcuts, or incomplete items.

## Required Commands

Run during/final verification as appropriate and report exact outcomes:

```bash
.venv/bin/pytest apps/server/tests/test_web_static.py
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config
```

Run this final browser smoke if feasible:

```bash
scripts/smoke-phase1-ui.sh
```

If the static-serving change or test setup suggests broader risk, also run:

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests
```

If a required command fails, either fix it or record the exact blocker. Do not
mark the task complete with an unexplained failing command. Leave no Docker
containers running.

## Acceptance Notes

The phase is not accepted until Codex reviews the diff and test output. Your
report should make review cheap: list exact commands, exact results, and any
remaining risks.
