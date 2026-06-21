# Claude Feasibility Validation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of the open-source MIT readiness scope before Codex
finalizes implementation.

Do not implement code in this step. Do not delete files in this step.

The user explicitly said `CLAUDE.md` is stale and needs to be synchronized to the
current version. Treat that as an important review target.

## Proposed Direction

Use the active brief:

- `docs/phases/open-source-mit-readiness/00-brief.md`

Short version:

- add a root MIT `LICENSE`;
- add concise `SECURITY.md` and `CONTRIBUTING.md`;
- remove the local `reference/scrapydweb/` snapshot from the current tree;
- update current-facing docs so they no longer claim the local reference snapshot
  exists;
- preserve completed phase reports and architecture notes as historical material
  where changing them would rewrite facts;
- update `CLAUDE.md` to reflect the current repo state through Python wheel
  script support and no local reference snapshot;
- no runtime behavior change and no git history rewrite in this task.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `README.md`
- `README.zh-CN.md`
- `docs/phases/open-source-mit-readiness/00-brief.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/05-dev-setup-and-known-issues.md`
- `docs/agent-governance/templates/claude-implementation-prompt.md`

Use `rg` to locate current-facing stale references to `reference/scrapydweb/` or
`reference/`. Do not inspect the contents of `reference/scrapydweb/`; it is being
removed for public MIT readiness.

## Output Required

Create:

- `docs/phases/open-source-mit-readiness/00a-feasibility-review.md`

Use these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Keep the response short and concrete. Focus on implementation feasibility and
stale-doc risk, not product brainstorming. If there are no blockers, say so
clearly.
