# 06 · Codex review（Phase 1.7 packet 2）

## Findings

No unresolved blocking findings remain.

Codex found and fixed two edge-case issues after Claude returned:

- Cron validation accepted any 5-field string, so a semantically invalid cron
  could be committed and then fail during scheduler reload. `services/schedules.py`
  now validates cron with `CronTrigger.from_crontab` and returns structured
  `400 schedule.invalid_cron`.
- Deleting a template referenced by a schedule would rely on the database FK and
  could surface as a 500. `services/templates.py` now returns structured
  `409 template.in_use`.

Tests were added for both cases:

- `test_create_cron_schedule_invalid_range_400`
- `test_delete_template_referenced_by_schedule_409`

## Review Notes

- Templates and schedules are now visible via Web routes `/templates` and
  `/schedules`.
- Run-from-template and schedule trigger-now both go through the shared
  template dispatch path.
- Zero healthy nodes now creates a persisted zero-execution task with terminal
  `no_target`, as required by the phase brief.
- Manual/template/trigger-now runs are not coalesced. Timer coalesce is scoped
  to undispatched same-schedule backlog.
- Redis/disk/agent seam remains unchanged (`execution_id=task_id`,
  `attempt_id=execution_id`).
- No `apps/agent/**` files were changed.

## Verification

Commands run by Codex:

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
cd deploy/docker && docker compose config
DOPILOT_DATABASE_URL='postgresql+psycopg://user:pass@localhost/dopilot' \
  ../../.venv/bin/alembic -c alembic.ini upgrade head --sql
git diff --check
```

Results:

- `pytest`: 186 passed.
- `ruff`: all checks passed.
- `web test`: 6 test files / 10 tests passed.
- `web build`: passed. Vite emitted existing chunk-size and Rollup pure-comment
  warnings from dependencies.
- `docker compose config`: valid.
- Alembic offline SQL to head: valid through `0005`.
- `git diff --check`: clean.

## Residual Risk

- `make compose-smoke` was not run in this review pass. The stack should be
  smoke-tested after rebuilding the compose image because Phase 1.7 now changes
  migrations, API routes, and Web assets.
- Live APScheduler timer firing was not exercised end-to-end; tests cover the
  `fire_timer` service path and coalesce policy, but not real wall-clock firing
  in a running container.
