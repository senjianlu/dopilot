# Claude Feasibility Validation Prompt Template

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of this proposed solution before Codex finalizes the
implementation brief.

Do not implement code in this step.

## Proposed Direction

`<paste concise Codex proposal or link to draft plan>`

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `<relevant docs>`
- `<specific code paths if known>`

## Output Required

Return a concise feasibility response with these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Keep the response short and concrete. Focus on implementation feasibility, not
product brainstorming. If there are no blockers, say so clearly.

For a long-running feasibility check, write `<phase-or-task>/claude-progress.md`
early with rough duration, proposed update cadence, current context, files being
inspected, and blockers. Update it again at meaningful checkpoints. This is a
coordination note, not a hard-timer requirement.
