# Claude Implementation Prompt: Phase 2.2.7 Agent No Inbound HTTP

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/phase-2.2.7-agent-no-inbound-http/00-brief.md`

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2.7-agent-no-inbound-http/00-brief.md`
- `docs/phases/phase-2.2.7-agent-no-inbound-http/00a-feasibility-review.md`
- `docs/dopilot/00-requirements.md` decisions #11/#12/#13
- `docs/dopilot/10-roadmap.md` phase 1.5 communication notes
- `docs/refactor/00-redis-streams-agent-communication.md`
- Existing agent runtime code:
  - `apps/agent/dopilot_agent/main.py`
  - `apps/agent/dopilot_agent/deps.py`
  - `apps/agent/dopilot_agent/redis/commands.py`
  - `apps/agent/dopilot_agent/artifacts/cache.py`
- Existing server artifact and agent-client code:
  - `apps/server/dopilot_server/api/v1/artifacts.py`
  - `apps/server/dopilot_server/services/resolve.py`
  - `apps/server/dopilot_server/clients/agent.py`
  - `apps/server/dopilot_server/app.py`
- Deploy files:
  - `deploy/docker/Dockerfile`
  - `deploy/docker/docker-compose.yml`
  - `deploy/docker/docker-compose.agent.yml`

## Constraints

- Keep changes scoped to the brief.
- Do not fetch, vendor, copy, or import upstream scrapydweb code.
- Preserve server artifact upload/download APIs.
- Preserve Redis command/event/log behavior and heartbeat behavior.
- Preserve graceful shutdown semantics from the current FastAPI lifespan.
- Do not modify unrelated untracked files such as `tmux.sh`.
- Add or update tests for changed behavior.

## Output Required

Create or update:

- `docs/phases/phase-2.2.7-agent-no-inbound-http/01-claude-implementation-report.md`
- `docs/phases/phase-2.2.7-agent-no-inbound-http/claude-progress.md`

The implementation report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- commands run with exact pass/fail outcomes;
- known risks or incomplete items.

At the start, write a short progress note with rough size class, checkpoints,
and likely long-running commands. Update it at meaningful checkpoints and before
or after long-running commands.

## Required Verification

Run and report:

```bash
ruff check apps packages
pytest apps/agent
pytest apps/server
pytest packages/protocol
cd deploy/docker && docker compose config
cd deploy/docker && docker compose -f docker-compose.agent.yml config
rg -n "AgentClient|get_agent_client|deploy_egg|EggDeployResponse|require_agent_token|/artifacts/scrapy/egg" apps packages
rg -n "6800" apps/agent deploy configs docs/dopilot docs/refactor README.md
```

If any command cannot run, record the exact blocker and continue with the next
non-dependent command.

Do not mark the task complete if required tests did not run; report the blocker.
