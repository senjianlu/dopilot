# Phase 2.2.1 Claude Implementation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/phase-2.2.1/00-brief.md`

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2.1/00-brief.md`
- `docs/phases/phase-2.2.1/00a-feasibility-review.md`
- `docs/phases/phase-2.2/07-acceptance.md`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/app.py`
- `apps/agent/dopilot_agent/config/loader.py`
- agent CLI entrypoint
- `configs/server.example.toml`
- `configs/server.docker.toml`
- `configs/agent.example.toml`
- `deploy/docker/Dockerfile`
- `deploy/docker/docker-compose.yml`
- relevant server/agent config tests

## Constraints

- Keep changes scoped to phase 2.2.1.
- Do not implement `.env.example`, `dopilot.toml`, `scripts/dopilot_sync.py`,
  labels/source fields, or any reconciler.
- Do not add a backwards-compatible `DOPILOT_TOKEN_SECRET` alias.
- Do not rename the TOML field `[auth].token_secret`.
- Keep Redis password auth enabled by default.
- Do not fetch, vendor, copy, or import upstream scrapydweb code.

## Output Required

Create or update:

- `docs/phases/phase-2.2.1/01-claude-implementation-report.md`
- `docs/phases/phase-2.2.1/claude-progress.md`

The report must include changed files, implementation notes, tests added/updated,
commands run with exact outcomes, and known risks.

## Required Commands

Run at least:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
```

If `.venv/bin/pytest` fails because of stale shebangs, use
`.venv/bin/python -m pytest` as shown. Do not mark complete if required tests
did not run; record blockers exactly.
