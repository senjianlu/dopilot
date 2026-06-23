# Phase 2.2.5 Claude Implementation Prompt

You are Claude Code implementing a bounded bug fix. Follow the repository
governance model. Do not fetch, vendor, copy, or import upstream scrapydweb code.

## Active Brief

Read and implement:

- `docs/phases/phase-2.2.5/00-brief.md`

Also read:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2.2.5/00a-feasibility-review.md`
- `apps/agent/dopilot_agent/main.py`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/agent/dopilot_agent/api/health.py`
- `apps/agent/tests/test_health.py`
- `apps/agent/tests/conftest.py`

## In Scope

- Fix `create_app(settings)` so request dependencies using `get_settings` share
  the injected settings object.
- Add the focused `/health` regression test described in the brief.
- Update concise docstrings/comments if needed.
- Write an implementation report.

## Out Of Scope

- Server changes.
- Config loader semantic changes.
- Compose changes unless tests reveal a directly related issue.
- Docker image rebuild/publish.
- Untracked `tmux.sh`.

## Required Report

Write:

```text
docs/phases/phase-2.2.5/01-claude-implementation-report.md
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
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests/test_health.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/agent/tests
.venv/bin/ruff check apps packages
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

If your permission layer blocks a command, report the exact command and failure.
Do not silently substitute without saying so.
