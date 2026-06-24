# Claude Feasibility Validation Prompt: Task Runtime Context

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of the proposed `task-runtime-context` brief before
Codex finalizes the implementation packet.

Do not implement code in this step.

## Proposed Direction

Read `docs/phases/task-runtime-context/00-brief.md`.

The user expectation is:

- Dopilot should expose its runtime context to user workloads.
- Scrapy spiders, Python scripts, and future Docker workloads should get the
  same canonical Dopilot fields, especially per-run `task_id` and
  `execution_id`.
- This task is only runtime context transmission. User-defined/custom
  environment variables will be handled later after this is accepted.
- For Scrapy under scrapyd, do not force per-job OS environment variables if
  scrapyd cannot support that safely. Use Scrapy settings if that is the
  practical per-job carrier.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-2b/00-brief.md`
- `packages/protocol/dopilot_protocol/execution.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/executors/python_wheel.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/services/resolve.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/runners/python_wheel.py`
- `apps/agent/dopilot_agent/scrapyd/client.py`
- relevant tests under `packages/protocol/tests`, `apps/server/tests`, and
  `apps/agent/tests`

## Output Required

Return a concise feasibility response with these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Focus on implementation feasibility and any better approach you recommend. If
you have a materially better idea for the runtime context contract or carriers,
say so clearly so Codex can bring it back to the user before implementation.

Write the final feasibility summary to:

`docs/phases/task-runtime-context/00a-feasibility-review.md`

Keep it short and concrete. Do not implement code.
