# Claude Implementation Prompt

You are Claude Code working in the dopilot repository.

## Task

Implement phase 2.2.3 from:

- `docs/phases/phase-2.2.3/00-brief.md`

Use the feasibility decision in:

- `docs/phases/phase-2.2.3/00a-feasibility-review.md`

## Required Context

Read:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2.3/00-brief.md`
- `docs/phases/phase-2.2.3/00a-feasibility-review.md`

Then inspect only the code/tests/docs needed to implement the brief.

## In Scope

- Server config/auth code and tests.
- Agent config/auth code and tests.
- Docker Compose, config examples, README, and live architecture/deploy docs.
- Phase implementation report.

## Out Of Scope

- Do not implement server-generated token persistence or enrollment CLI.
- Do not add TLS/VPN/transport encryption.
- Do not keep compatibility for `DOPILOT_AGENT_SHARED_TOKEN` or
  `DOPILOT_SERVER_SHARED_TOKEN`.
- Do not make agents receive or derive from `DOPILOT_ADMIN_API_TOKEN`.
- Do not change `DOPILOT_CONFIG` Docker Compose behavior.
- Do not rewrite historical phase records under `docs/phases/phase-2.2/`,
  `docs/phases/phase-2.2.1/`, or `docs/phases/phase-2.2.2/`.
- Do not touch untracked `tmux.sh`.

## Progress Notes

Maintain:

- `docs/phases/phase-2.2.3/claude-progress.md`

Write an initial note early with estimated size/duration and update it at
meaningful checkpoints.

## Required Report

Write:

- `docs/phases/phase-2.2.3/01-claude-implementation-report.md`

The report must include:

- changed files;
- behavior implemented;
- tests added/updated;
- exact commands run and pass/fail outcomes;
- unresolved risks or shortcuts.

## Required Commands

Run if possible:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_heartbeat_api.py apps/agent/tests/test_config.py apps/agent/tests/test_auth.py apps/agent/tests/test_heartbeat_worker.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
cd deploy/docker && docker compose config | rg 'DOPILOT_CONFIG|DOPILOT_ADMIN_API_TOKEN|DOPILOT_AGENT_TOKEN|DOPILOT_AGENT_SHARED_TOKEN|DOPILOT_SERVER_SHARED_TOKEN'
git diff --check
```

If a command is blocked by permissions or local environment, record the exact
command and error in the report.

## Acceptance Reminders

- `DOPILOT_ADMIN_API_TOKEN` is admin-only and should not appear in agent service
  environments.
- `DOPILOT_AGENT_TOKEN` is the only machine token.
- Old split envs have no effect and should be absent from active config/docs.
- Token auth is not transport encryption; docs should say TLS/VPN/private
  network is still required for encrypted cross-host transport.
