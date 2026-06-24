You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/task-artifact-archive/00-brief.md`

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md` if present
- `docs/phases/task-artifact-archive/00-brief.md`
- `docs/phases/task-artifact-archive/00a-feasibility-review.md`
- Relevant server/web files as needed

## Constraints

- Keep changes scoped to the brief.
- Do not fetch, vendor, copy, or import upstream scrapydweb code. There is no
  local snapshot; upstream is a behavior reference only.
- Preserve existing public behavior unless the brief explicitly changes it.
- Add/update backend and web tests for changed behavior.
- Use existing shadcn/ui components and local page patterns; do not add new
  dependencies unless absolutely required.
- Critical backend invariant: do not block existing template run/schedule
  dispatch for archived artifacts. Create/update binding validation must be
  separate from runnable-only runtime resolution.
- Critical web invariant: editing a template bound to an archived artifact must
  show its current binding clearly and must not offer archived artifacts as
  fresh selectable options.

## Output Required

Create or update:

- `docs/phases/task-artifact-archive/claude-progress.md`
- `docs/phases/task-artifact-archive/01-claude-implementation-report.md`

The implementation report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- commands run with pass/fail output;
- known risks or incomplete items.

## Verification Commands

Attempt these commands:

```bash
pytest apps/server/tests/
ruff check apps packages
corepack pnpm --filter web test
cd apps/server && alembic upgrade head
```

If a command cannot run, report the exact blocker. Do not mark the task
complete if required tests did not run; record the blocker instead.
