# Claude Implementation Prompt Template

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `<phase-or-task>/00-brief.md`

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `<active phase brief>`
- `<specific architecture docs>`

## Constraints

- Keep changes scoped to the brief.
- Do not fetch, vendor, copy, or import upstream scrapydweb code. There is no
  local snapshot; upstream is a behavior reference consulted externally only.
- Do not copy structure or code from upstream scrapydweb.
- Preserve existing public behavior unless the brief explicitly changes it.
- Add or update tests for changed behavior.

## Output Required

Create or update:

- `<phase-or-task>/01-claude-implementation-report.md`
- `<phase-or-task>/claude-progress.md` for long-running work

The report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- commands run with pass/fail output;
- known risks or incomplete items.

At the start of a long-running task, spend up to five minutes estimating the
rough duration and write an initial `<phase-or-task>/claude-progress.md` note
with size class (`<15m`, `15-45m`, `45-90m`, or `90m+`), proposed update cadence,
checkpoints, and likely long-running commands. Then update the file at
meaningful checkpoints and before/after long-running commands. The cadence is a
guideline, not a hard timer; for large tasks, 10-20 minutes or one update per
major edit/test phase is acceptable. Keep entries short. This file is durable
progress coordination; the implementation report remains the authoritative final
output.

Do not mark the task complete if required tests did not run. Record the blocker
instead.
