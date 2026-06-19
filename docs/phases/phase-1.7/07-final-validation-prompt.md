# Claude Test/Validation Prompt · Phase 1.7 Final Acceptance

You are Claude Code working in the dopilot repository.

## Assignment

Close Phase 1.7 by adding any missing acceptance/smoke tests and running the
full verification suite with broad enough permissions.

Phase 1.7 is not accepted until this packet produces a final test report and no
blocking findings remain.

## Required Context

Read before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-1.7/00-brief.md`
- `docs/phases/phase-1.7/02-packet-1-implementation-report.md`
- `docs/phases/phase-1.7/03-codex-review.md`
- `docs/phases/phase-1.7/05-packet-2-implementation-report.md`
- `docs/phases/phase-1.7/06-packet-2-codex-review.md`
- `scripts/smoke-phase1.sh`
- `deploy/docker/docker-compose.yml`
- `apps/server/dopilot_server/api/v1/nodes.py`
- `apps/server/dopilot_server/api/v1/templates.py`
- `apps/server/dopilot_server/api/v1/schedules.py`
- `apps/server/dopilot_server/scheduler/runner.py`
- `apps/server/tests/test_schedules.py`
- `apps/server/tests/test_templates.py`
- `apps/web/src/pages/TemplatesPage.vue`
- `apps/web/src/pages/SchedulesPage.vue`

## In Scope

- Add or update tests needed to remove Phase 1.7 residual risk:
  - live-ish `ScheduleRunner` coverage: start/reload a runner with a short
    interval or directly verify it registers/reloads jobs and can call the timer
    path without waiting on real minutes;
  - Web/API coverage for schedules if missing;
  - smoke script coverage for templates and schedules.
- Update `scripts/smoke-phase1.sh` if needed for the current Redis heartbeat
  model. The old `POST /api/v1/nodes/refresh` path is gone; use the current
  nodes API/heartbeat behavior.
- Extend or add a Phase 1.7 smoke path that verifies in Docker compose:
  - migration reaches Alembic head including `0005`;
  - server health reports DB/Redis/nodes ok;
  - a Scrapy template can be created;
  - template run or schedule trigger-now creates a task;
  - no healthy-node behavior is not required in compose smoke if the agent is
    healthy, but it must be covered by automated tests.
- Run all required commands and capture exact output.
- Fix issues found by tests, keeping edits scoped to Phase 1.7 validation.

## Out Of Scope

- New product features beyond Phase 1.7.
- Python script executor.
- Docker long-lived executor.
- Multi-server HA/distributed locks.
- Renaming Redis/agent wire fields.
- Editing `reference/scrapydweb/`.

## Required Progress Notes

Append to:

`docs/phases/phase-1.7/claude-progress.md`

Write an initial estimate and then update before/after long commands, especially
Docker/compose commands.

## Output Required

Create:

- `docs/phases/phase-1.7/08-final-validation-report.md`

The report must include:

- tests added/updated;
- smoke script changes;
- exact commands run and pass/fail output;
- Docker compose/smoke result;
- any remaining risks;
- explicit recommendation: accept Phase 1.7 or do not accept.

## Required Commands

Run these at minimum:

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
DOPILOT_DATABASE_URL='postgresql+psycopg://user:pass@localhost/dopilot' \
  ../../.venv/bin/alembic -c alembic.ini upgrade head --sql
```

Then run Docker smoke. Prefer a clean, repeatable smoke that tears down after
success:

```bash
make compose-smoke
```

If `make compose-smoke` is obsolete for Phase 1.7, update it or add a dedicated
Phase 1.7 smoke script and run that. Do not leave containers running unless a
failure requires inspection; if so, report exact container state and logs.

## Acceptance Criteria

- Full Python/protocol tests pass.
- Ruffle/lint passes.
- Web tests and build pass.
- Compose config passes.
- Alembic SQL to head passes through `0005`.
- Docker smoke passes with the current Redis heartbeat model.
- Smoke covers at least one template/schedule Phase 1.7 path, not only legacy
  manual `/executions/run`.
- Final report recommends accepting Phase 1.7.
