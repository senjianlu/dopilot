# Claude Feasibility Prompt: Phase 2 Python Wheel Script Support

You are Claude Code working in the dopilot repository. This is a feasibility
validation only. Do not implement phase 2 and do not edit application code.

## Task

Read the current mainline docs and current code, then validate Codex's phase-2
preflight conflict list and proposed direction. Write a concise report to:

```text
docs/phases/phase-2/00a-feasibility-review.md
```

You may also write/update:

```text
docs/phases/phase-2/claude-progress.md
```

Do not edit other files.

## Required Context

Read these files first:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/01-gap-executors.md`
- `docs/dopilot/03-gap-realtime-logs.md`
- `docs/refactor/00-redis-streams-agent-communication.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`

Then inspect the current code paths needed to confirm or correct the conflicts:

- `packages/protocol/dopilot_protocol/common.py`
- `packages/protocol/dopilot_protocol/streams.py`
- `packages/protocol/dopilot_protocol/execution.py`
- `apps/server/dopilot_server/services/states.py`
- `apps/server/dopilot_server/services/artifacts.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/dopilot_server/services/resolve.py`
- `apps/server/dopilot_server/executors/registry.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/nodes/service.py`
- `apps/agent/dopilot_agent/config/settings.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/runners/scrapyd.py`
- `apps/agent/dopilot_agent/redis/logs.py`
- `apps/agent/dopilot_agent/state/store.py`
- `apps/web/src/api/types.ts`
- `apps/web/src/pages/BuildArtifactsPage.vue`
- `apps/web/src/pages/TemplatesPage.vue`

Use `rg` to discover adjacent files if needed.

## Questions To Answer

1. Are the conflict points in `00-preflight-conflicts.md` accurate? For each,
   mark `confirmed`, `partially confirmed`, or `not confirmed`, with file/line
   references.
2. Is canonicalizing capabilities to `python_wheel` / `docker_runtime` the least
   risky direction, or should phase 2 keep `script` as the heartbeat capability
   and adjust server mapping instead? Explain the tradeoff and your
   recommendation.
3. What is the smallest safe implementation slice that can run a `.whl` on an
   agent and persist stdout/stderr through the existing Redis log stream without
   destabilizing Scrapy?
4. Which files/modules are the highest-risk change points?
5. Which tests should be mandatory before Codex writes the phase-2 brief?
6. List any missing product or architecture decisions that require user approval.

## Constraints

- Do not use or edit `reference/scrapydweb/` except as read-only behavior
  reference if absolutely necessary.
- Do not edit application code.
- Do not run broad test suites; this is a read/analysis task. You may run cheap
  read-only commands such as `rg`, `sed`, `nl`, `git status`, and `git diff`.
- If a command fails due to permissions or environment, record it in the report.
- Keep the report concise and decision-oriented; do not paste long code blocks.

## Expected Report Shape

Use these headings:

```text
# Phase 2 Feasibility Review

## Verdict
## Conflict Review
## Recommendation
## Minimal Safe Slice
## High-Risk Files
## Required Tests
## Open Decisions
## Commands Run
```

