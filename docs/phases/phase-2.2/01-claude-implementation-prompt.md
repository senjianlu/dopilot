# Phase 2.2 Claude Implementation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/phase-2.2/00-brief.md`

## Required Context

Read these before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2/00-brief.md`
- `docs/phases/phase-2.2/00a-feasibility-review.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/08-docker-deployment.md`
- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/auth/dependencies.py`
- `apps/server/dopilot_server/models/scheduling.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/dopilot_server/services/schedules.py`
- `apps/server/dopilot_server/scheduler/runner.py`
- `apps/server/dopilot_server/api/v1/schedules.py`
- `apps/server/dopilot_server/api/v1/templates.py`
- `apps/server/dopilot_server/api/v1/schemas.py`
- `apps/server/migrations/versions/`
- relevant tests under `apps/server/tests/`

## Constraints

- Keep changes scoped to phase 2.2.
- Do not implement `dopilot.toml`, `scripts/dopilot_sync.py`, labels/source
  ownership fields, or any manifest reconciler.
- Do not fetch, vendor, copy, or import upstream scrapydweb code. There is no
  local snapshot; upstream is a behavior reference consulted externally only.
- Preserve existing task/execution, Redis, agent, artifact, and log behavior
  unless the brief explicitly changes it.
- Add or update tests for changed behavior.
- If permissions prevent a command from running, record the exact command and
  permission failure in the report.

## Output Required

Create or update:

- `docs/phases/phase-2.2/01-claude-implementation-report.md`
- `docs/phases/phase-2.2/claude-progress.md`

At the start, write an initial `claude-progress.md` note with size class,
expected update cadence, checkpoints, and likely long-running commands. Update
it at meaningful checkpoints and before/after long-running commands.

The implementation report must include:

- changed files grouped by area;
- implementation notes;
- migrations added;
- tests added or updated;
- commands run with exact pass/fail outcomes;
- known risks or incomplete items.

## Required Commands

Run at least:

```bash
pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py
ruff check apps packages
cd deploy/docker && docker compose config
```

Also run broader commands if your changes touch shared imports, generated
frontend-facing schemas, or behavior that the narrow commands do not cover:

```bash
pytest
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Do not mark the task complete if required tests did not run. Record the blocker
instead.
