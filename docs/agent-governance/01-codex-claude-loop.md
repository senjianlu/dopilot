# Codex-Claude Loop

Use this loop for substantial implementation work.

## 1. Codex Confirms The Solution Direction

Codex discusses the user's goal, proposes a solution, and confirms the intended
direction with the user before writing the implementation brief.

The confirmed direction can be lightweight, but it must include:

- target behavior;
- main implementation approach;
- explicit non-goals;
- open assumptions.

## 2. Codex Requests Claude Feasibility Validation

Before finalizing the brief, Codex sends Claude a short validation prompt based
on `templates/claude-feasibility-prompt.md`.

Claude should not implement during this step. Claude should return only:

- feasibility verdict;
- blockers;
- risky assumptions;
- missing product or architecture decisions;
- concrete implementation questions;
- recommended scope cuts if needed.

Codex reviews Claude's feedback and resolves routine implementation details
without involving the user. Escalate only when the feedback changes product
behavior, architecture direction, risk acceptance, credentials, or destructive
operations.

Codex and Claude may repeat this validation loop, but each round must be narrow:
one issue, one decision, one short answer. Do not let feasibility validation turn
into implementation.

Record the final feasibility exchange as
`docs/phases/<phase-or-task>/00a-feasibility-review.md` using
`templates/feasibility-review.md`. Store the conclusion, blockers, questions,
and Codex decision, not the full transcript.

## 3. Codex Creates The Work Packet

Codex writes a brief under `docs/phases/<phase-or-task>/00-brief.md` or updates
the active brief. The brief must answer:

- What behavior changes?
- Which files or modules are expected to change?
- Which architecture decisions constrain the work?
- What is explicitly out of scope?
- What tests and verification commands define done?

## 4. Codex Calls Claude

Codex gives Claude a bounded prompt based on
`templates/claude-implementation-prompt.md`.
The invocation must follow `02-claude-invocation.md`, including explicit
`--effort` selection and permission mode.

Claude's expected output:

- implementation changes;
- tests added or updated;
- commands run and exact outcomes;
- changed-file summary;
- risks, shortcuts, or TODOs.

## 5. Codex Reviews The Diff

Codex reviews with the same discipline as a code review. Findings lead the
response and are ordered by severity. Codex checks:

- active brief compliance;
- repo architecture and `CLAUDE.md` constraints;
- state transitions, idempotency, and recovery behavior;
- migrations and deployment config;
- test adequacy;
- accidental broad refactors.

If findings are blocking, Codex writes `02-codex-review.md` and sends Claude a
targeted fix or response prompt. Claude should be allowed to explain or contest
a finding when implementation context matters, but Codex makes the final review
decision.

## 6. Codex Owns The Test Strategy

Codex writes or updates `04-test-plan.md` when:

- the behavior is new;
- the phase touches shared protocol, database, Redis, logs, scheduling, auth, or
  deployment;
- Claude's tests are too narrow;
- a review finding needs regression coverage.

Claude implements/runs tests from that plan and records results in
`05-claude-test-report.md`.

## 7. Codex Reviews Test Results

Codex verifies that test output corresponds to the requested commands, not just
to a generic "passed" claim. If a command cannot run, Codex records why and
decides whether the residual risk needs user acceptance.

When test failures or coverage gaps are ambiguous, Codex gives Claude one
focused chance to explain, reproduce, or fix before final acceptance.

## 8. Codex Submits Acceptance

Codex writes `07-acceptance.md` and summarizes for the user:

- what changed;
- what was verified;
- what remains risky or deferred;
- whether final human acceptance is recommended.

## Escalation Triggers

Escalate to the user when:

- a product or architecture decision is ambiguous;
- the implementation requires credentials or external services unavailable to
  the agents;
- a destructive migration or data-loss tradeoff is proposed;
- tests cannot be run and the residual risk is material;
- Claude and Codex disagree after two focused iterations.
