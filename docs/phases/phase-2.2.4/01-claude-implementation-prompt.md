# Phase 2.2.4 Claude Implementation Prompt

You are Claude Code implementing a bounded dopilot task. Follow the repository
governance model. Do not fetch, vendor, copy, or import upstream scrapydweb code.

## Active Brief

Read and implement:

- `docs/phases/phase-2.2.4/00-brief.md`

Also read:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2.2.4/00a-feasibility-review.md`
- `docs/phases/phase-2.2.3/00-brief.md`
- `docs/phases/phase-2.2.3/07-acceptance.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/08-docker-deployment.md`

## In Scope

- Implement generated server-side agent token persistence.
- Add `server.data_dir` and `DOPILOT_SERVER_DATA_DIR`.
- Add `dopilot-server agent-token print` and `--quiet`.
- Ensure generated token is used consistently by `AgentClient` and
  `Depends(get_settings)` auth dependencies.
- Add server-only and agent-only Docker Compose files.
- Update focused docs and tests.

## Out Of Scope

- Token rotation/revocation.
- Multi-token enrollment.
- DB-backed token persistence.
- TLS/VPN implementation.
- Any old split-token compatibility.
- Agent-side token generation.
- Untracked `tmux.sh`.

## Progress Notes

Maintain:

```text
docs/phases/phase-2.2.4/claude-progress.md
```

At minimum, write an initial estimate and update before/after long-running
verification commands.

## Required Report

Write:

```text
docs/phases/phase-2.2.4/01-claude-implementation-report.md
```

Include:

- changed files;
- behavior implemented;
- tests added/updated;
- exact commands run and outcomes;
- unresolved risks or skipped commands.

## Required Verification

Run as many as possible and report exact outcomes:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_agent_token.py apps/server/tests/test_heartbeat_api.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose -f docker-compose.yml config
cd deploy/docker && docker compose -f docker-compose.server.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

If your permission layer blocks a command, report the exact command and failure.
Do not silently substitute without saying so.
