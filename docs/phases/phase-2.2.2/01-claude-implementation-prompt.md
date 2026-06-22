# Claude Implementation Prompt

You are Claude Code working in the dopilot repository.

## Task

Implement phase 2.2.2 from:

- `docs/phases/phase-2.2.2/00-brief.md`

Use the feasibility decision in:

- `docs/phases/phase-2.2.2/00a-feasibility-review.md`

## Required Context

Read:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2.2/00-brief.md`
- `docs/phases/phase-2.2.2/00a-feasibility-review.md`
- `docs/phases/phase-2.2.2/admin-api-token-design.md`

Then inspect only the code/tests/docs needed to implement the brief.

## In Scope

- Server auth/config implementation and tests.
- Agent config fallback implementation and tests.
- Config examples, Docker Compose, README, and live deployment docs updates.
- Phase implementation report.

## Out Of Scope

- Do not add compatibility for `DOPILOT_ADMIN_API_SECRET`.
- Do not add a new env override for `auth.token_secret`.
- Do not modify historical `docs/phases/phase-2.2/` or
  `docs/phases/phase-2.2.1/` records.
- Do not add CI sync scripts or deployment workflows.
- Do not change unrelated product behavior.
- Do not touch untracked `tmux.sh`.

## Progress Notes

Maintain:

- `docs/phases/phase-2.2.2/claude-progress.md`

Write an initial note early with estimated size/duration and update it at
meaningful checkpoints.

## Required Report

Write:

- `docs/phases/phase-2.2.2/01-claude-implementation-report.md`

The report must include:

- changed files;
- behavior implemented;
- tests added/updated;
- exact commands run and pass/fail outcomes;
- unresolved risks or shortcuts.

## Required Commands

Run if possible:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
git diff --check
```

If a command is blocked by permissions or local environment, record the exact
command and error in the report.

## Acceptance Reminders

- `DOPILOT_ADMIN_API_TOKEN` is the externally supplied static admin API token.
- `DOPILOT_ADMIN_API_SECRET` must have no effect.
- `token_secret` is TOML-only and remains the login/stream signing key.
- Static token auth must use constant-time comparison with non-empty guards.
- Compose must not set `DOPILOT_CONFIG`.
