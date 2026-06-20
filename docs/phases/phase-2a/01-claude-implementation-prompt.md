# Claude Implementation Prompt: Phase 2a ID Naming Clean-Cut

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/phase-2a/00-brief.md`

Phase 2a is the id naming clean-cut only:

```text
task_id      = Task.id
execution_id = Execution.id
```

Do not implement Python wheel execution or phase 2b behavior.

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/phases/phase-2a/00-brief.md`
- `docs/phases/phase-2a/00a-feasibility-review.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`
- `docs/phases/phase-2/00b-plan-review.md`
- `docs/dopilot/00-requirements.md`
- `docs/refactor/00-redis-streams-agent-communication.md`

## Constraints

- Keep changes scoped to phase 2a.
- Do not edit `reference/scrapydweb/`.
- Do not copy structure or code from `reference/scrapydweb/`.
- Preserve public HTTP API and web JSON behavior unless the brief explicitly
  says otherwise.
- Do not do broad global text replacement. `execution_id` is a collision token:
  public/domain uses already mean `Execution.id` and must stay as-is.
- Add or update tests for changed behavior.
- Add Alembic migration `0009`; do not edit old migration files.
- Delete only schemas/methods that a fresh reference scan confirms have no live
  caller.

## Output Required

Create or update:

- `docs/phases/phase-2a/01-claude-implementation-report.md`
- `docs/phases/phase-2a/claude-progress.md`

The implementation report must include:

- changed files grouped by area;
- implementation notes;
- deleted legacy schemas/methods and reference-scan evidence;
- tests added or updated;
- commands run with pass/fail output;
- exact blockers for any required command that could not run;
- known risks or incomplete items.

At the start, spend up to five minutes estimating the rough duration and write
an initial `docs/phases/phase-2a/claude-progress.md` note with size class
(`<15m`, `15-45m`, `45-90m`, or `90m+`), proposed update cadence, checkpoints,
and likely long-running commands. Then update that file at meaningful
checkpoints and before/after long-running commands.

Do not mark the task complete if required tests did not run. Record the blocker
instead.
