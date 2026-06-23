# Phase 2.2.6 Claude Implementation Prompt

You are Claude Code implementing a bounded deployment config fix. Follow the
repository governance model. Do not fetch, vendor, copy, or import upstream
scrapydweb code.

## Active Brief

Read and implement:

- `docs/phases/phase-2.2.6/00-brief.md`

Also read:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2.2.6/00a-feasibility-review.md`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/agent/tests/test_config.py`
- `deploy/docker/docker-compose.agent.yml`
- `configs/agent.example.toml`
- `docs/dopilot/08-docker-deployment.md`

## In Scope

- Add `DOPILOT_SERVER_URL -> [agent].server_url`.
- Add/update focused tests.
- Update agent-only compose to require `DOPILOT_SERVER_URL`.
- Update docs/README snippets that describe agent-only deployment.
- Write implementation report.

## Out Of Scope

- Server-side code.
- K8s manifest generation.
- Redis behavior changes.
- Docker image rebuild/publish.
- Untracked `tmux.sh`.

## Required Report

Write:

```text
docs/phases/phase-2.2.6/01-claude-implementation-report.md
```

Include changed files, behavior implemented, tests added/updated, exact commands
run and outcomes, and unresolved risks/skipped commands.

## Required Verification

Run as many as possible and report exact outcomes:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_config.py apps/agent/tests/test_heartbeat_worker.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
.venv/bin/ruff check apps packages
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 DOPILOT_SERVER_URL=http://server.example:5000 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

The second compose command is expected to fail because `DOPILOT_SERVER_URL` is
missing. Report that as expected failure.

If your permission layer blocks a command, report the exact command and failure.
