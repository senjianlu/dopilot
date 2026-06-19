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
- Do not edit `reference/scrapydweb/`.
- Do not copy structure or code from `reference/scrapydweb/`.
- Preserve existing public behavior unless the brief explicitly changes it.
- Add or update tests for changed behavior.

## Output Required

Create or update:

- `<phase-or-task>/01-claude-implementation-report.md`

The report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- commands run with pass/fail output;
- known risks or incomplete items.

Do not mark the task complete if required tests did not run. Record the blocker
instead.
