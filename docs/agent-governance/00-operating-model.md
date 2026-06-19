# AI Agent Governance Operating Model

This repository uses a two-agent governance model.

## Roles

Codex is the product and engineering governance agent.

- Clarifies product intent and architecture with the user.
- Converts accepted direction into implementation briefs.
- Gives Claude bounded development and testing assignments.
- Reviews Claude's code, tests, and test output.
- Decides whether another Claude iteration is needed.
- Prepares final acceptance material for the user.

Claude Code is the implementation and verification agent.

- Validates detailed feasibility against the codebase.
- Implements the bounded brief.
- Adds or updates tests requested by Codex.
- Runs the requested verification commands.
- Reports exact changed files, commands, results, and unresolved issues.

The user is intentionally kept out of the middle loop except for strategy,
scope changes, credentials, destructive operations, and final acceptance.

## Default Flow

```text
User goal
  -> Codex clarifies scope and constraints
  -> Codex proposes a solution and confirms direction with the user
  -> Codex asks Claude for focused feasibility validation
  -> Claude validates feasibility and asks implementation-level questions
  -> Codex reviews Claude feedback and iterates only on concrete issues
  -> Codex writes or updates phase/task brief
  -> Claude implements from the brief
  -> Claude reports changed files and tests
  -> Codex reviews the diff
  -> Claude responds to Codex review when findings need implementation context
  -> Codex writes missing test requirements
  -> Claude adds/runs tests
  -> Codex reviews test results
  -> Claude responds to test-result concerns when failures or gaps need context
  -> Codex submits acceptance summary to user
```

## Artifact Locations

- Durable Codex instructions: `AGENTS.md`
- Durable Claude instructions: `CLAUDE.md`
- Governance protocol: `docs/agent-governance/`
- New Codex chat startup prompt:
  `docs/agent-governance/new-chat-prompt.md`
- Claude CLI invocation protocol:
  `docs/agent-governance/02-claude-invocation.md`
- Phase/task packets: `docs/phases/<phase-or-task>/`
- Cross-phase architecture decisions: `docs/dopilot/` or `docs/refactor/`

## Phase File Convention

Use the existing phase numbering style.

```text
00-brief.md
00a-feasibility-review.md
01-claude-implementation-report.md
02-codex-review.md
03-claude-review-response.md
04-test-plan.md
05-claude-test-report.md
06-codex-test-review.md
07-acceptance.md
```

Short phases may combine implementation and test reporting, but do not skip
feasibility validation, Codex review, or test-result review before acceptance.

## Communication Record Policy

Do not store full Codex-Claude chat transcripts in the repository by default.
They are noisy and hard to review. Store concise, decision-relevant artifacts
instead:

- feasibility validation: `docs/phases/<phase>/00a-feasibility-review.md`;
- implementation handoff/results: `01-claude-implementation-report.md`;
- Codex code review: `02-codex-review.md`;
- Claude response to review: `03-claude-review-response.md`;
- test plan and results: `04-test-plan.md` and `05-claude-test-report.md`;
- Codex test review: `06-codex-test-review.md`;
- final accepted state: `07-acceptance.md`.

Raw Claude subprocess output may be kept temporarily under `/tmp/`, for example
`/tmp/dopilot-claude-runs/<task-id>/`, when Codex needs to inspect it. Only
summaries, decisions, commands, results, blockers, and unresolved risks should
be promoted into `docs/phases/`.

## Handoff Rules

- Every Claude assignment must include context files, in-scope changes,
  out-of-scope changes, acceptance criteria, and required commands.
- Feasibility validation prompts must be narrow and short. Claude should answer
  only with blockers, risky assumptions, missing decisions, and implementation
  questions.
- Codex decides whether Claude feedback requires user input. Routine
  implementation details are resolved by Codex and Claude without escalating.
- Claude must not use `reference/scrapydweb/` as code to copy from.
- Codex must not accept "tests pass" without command names and outcomes.
- If Claude cannot complete a step, Claude reports the blocker and the smallest
  next action. Codex decides whether to iterate or escalate.
- Any architecture decision discovered during implementation must be written
  back to the relevant docs before acceptance.

## Completion Criteria

A task is done only when:

- the implementation matches the active brief;
- Claude feasibility feedback has been resolved or explicitly rejected by Codex;
- tests cover the changed behavior at the right level;
- Claude has had a chance to respond to blocking code-review and test-review
  findings before final acceptance;
- relevant commands have run or their absence is documented;
- Codex review has no unresolved blocking findings;
- docs and config examples are updated when behavior or deployment changed;
- the final acceptance note lists residual risks clearly.
