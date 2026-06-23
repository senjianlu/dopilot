# Claude Implementation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/task-web-ui-followups/00-brief.md`

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/task-web-ui-followups/00-brief.md`
- `docs/phases/task-web-ui-followups/00a-feasibility-review.md`
- `docs/phases/phase-2.2/00-brief.md`
- `docs/phases/task-execution-log-selection/00-brief.md`

## Constraints

- Keep changes scoped to the brief.
- Do not fetch, vendor, copy, or import upstream scrapydweb code. There is no
  local snapshot; upstream is a behavior reference consulted externally only.
- Do not copy structure or code from upstream scrapydweb.
- Do not touch unrelated untracked files such as `tmux.sh`.
- Preserve existing public behavior unless the brief explicitly changes it.
- Add/update tests for changed behavior.
- Use the existing shadcn `Switch` component; do not reinstall or overwrite UI
  components.
- For schedule table quick-toggle, send only `{ enabled: next }`, keep a pending
  row id, and reload on success. Do not implement optimistic UI.
- For task-detail execution ordering, sort a copy for display/default selection;
  do not mutate the API response.

## Expected Report Files

Create or update:

- `docs/phases/task-web-ui-followups/01-claude-implementation-report.md`
- `docs/phases/task-web-ui-followups/claude-progress.md`

At the start, write a short progress note with estimated size class and planned
checkpoints. Update it at meaningful checkpoints and before/after long-running
commands.

## Required Commands

Run and report exact outcomes:

```bash
.venv/bin/python -m pytest apps/server/tests/test_executions_pagination.py -q
corepack pnpm --filter web test
corepack pnpm --filter web build
```

If a required command cannot run, record the exact failure and blocker in the
implementation report.

## Output Required

The implementation report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- commands run with pass/fail output;
- known risks or incomplete items.
