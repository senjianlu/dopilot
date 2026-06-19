# 05 · Phase 1.7 Packet 2 — implementation report

Scope delivered: Scrapy task templates, task creation from immutable template
snapshots, schedules referencing templates, schedule trigger-now, the
zero-healthy-node terminal `no_target` task path, the single-instance schedule
runner (APScheduler), and the Web pages/menu to manage templates & schedules.
Per `docs/phases/phase-1.7/00-brief.md` and the packet-2 prompt.

The packet-1 seams are preserved unchanged: the Redis/disk/agent wire still
carries `execution_id` = task id and `attempt_id` = atomic execution id; no
`apps/agent/**` file was touched. The new `/api/v1/templates` and
`/api/v1/schedules` surfaces were added; the existing `/api/v1/executions`
crawler/manual run/log/cancel flow is unchanged except that the no-healthy-node
case now creates a `no_target` task instead of returning 409 (the one
intentional, brief-mandated behavior change — its test was updated).

## 1. Changed files by area

### Domain model + migration
- `models/scheduling.py` — **new.** `TaskTemplate` (table `task_templates`) and
  `Schedule` (table `schedules`, FK → `task_templates.id`).
- `models/execution.py` — `Task` gains `source`, `template_id`, `schedule_id`,
  `template_snapshot` (provenance + immutable snapshot).
- `models/__init__.py` — exports `TaskTemplate`, `Schedule`.
- `migrations/versions/0005_templates_schedules.py` — **new.** Creates both
  tables (+ `ix_schedules_template_id`) and adds the four `tasks` columns.
  Down-rev `0004`; offline SQL to head verified valid PostgreSQL.

### State machine
- `services/states.py` — added the task-source constants
  (`TASK_SOURCE_MANUAL` / `TASK_SOURCE_TRIGGER_NOW` / `TASK_SOURCE_TIMER` +
  `TASK_SOURCES`). `TASK_NO_TARGET` (already terminal from packet 1) is now
  actually produced.

### Services
- `services/executions.py` — `TaskOrigin` dataclass; `create_task(request,
  origin)` writes provenance + snapshot; **`mark_no_target(task, …)`** sets the
  terminal zero-execution state with `status_reason`/`status_detail`. View
  builders emit `source`/`template_id`/`schedule_id`.
- `services/templates.py` — **new.** Template CRUD, validation (only `scrapy`;
  name+project+spider required), `template_snapshot`, `build_run_request`
  (template → `ExecutionRunRequest` + snapshot), `template_view`.
- `services/schedules.py` — **new.** Schedule CRUD, trigger validation
  (interval > 0 or 5-field cron), **`trigger_now`** (source
  `schedule_trigger_now`, never coalesced) and **`fire_timer`** (source
  `schedule_timer`, coalesced only on undispatched same-schedule backlog),
  `schedule_view`.
- `services/dispatch.py` — **new.** `dispatch_from_template(...)` — the single
  template→task→dispatch path shared by run-from-template, trigger-now, and
  timer firing (so there is no second, drifting dispatch implementation).
- `services/outbox.py` — replaced the dormant target-keyed
  `has_unterminated_for_target` with **`has_undispatched_backlog_for_schedule`**
  (schedule-keyed; queued task + unresolved outbox row only).

### Executor / node selection
- `nodes/service.py` — added non-raising **`resolve_target_nodes`** returning
  `(selected, healthy_count)`; `select_target_nodes` (still 409) now delegates
  to it and is retained for egg deploy.
- `executors/base.py` — `BaseExecutor.run` gains `origin: TaskOrigin | None`.
- `executors/scrapyd.py` — creates the task **first**, then selects nodes; zero
  nodes → `mark_no_target` + commit + return (no 409, no fake execution).
  Otherwise unchanged (one execution + one run-outbox + one log file per node).

### Scheduler runtime
- `scheduler/runner.py` — **new.** `ScheduleRunner` (single in-process
  `AsyncIOScheduler`; interval + `CronTrigger.from_crontab`) calling
  `fire_timer` per tick in a fresh session; `reload()` resyncs jobs from the DB;
  `build_schedule_runner` returns `None` unless `[scheduler].enabled`.
- `app.py` — lifespan builds/starts/stops the runner (gated) and exposes
  `app.state.schedule_runner`.

### API
- `api/v1/templates.py` — **new.** `POST/GET /templates`, `GET/PUT/DELETE
  /templates/{id}`, `POST /templates/{id}/run`.
- `api/v1/schedules.py` — **new.** `POST/GET /schedules`, `GET/PUT/DELETE
  /schedules/{id}`, `POST /schedules/{id}/trigger-now`; create/update/delete
  call `runner.reload()` when a runner is live.
- `api/v1/schemas.py` — `Template*` / `Schedule*` request/response models;
  `source`/`template_id`/`schedule_id` added to `ExecutionView` /
  `ExecutionSummary`.
- `api/v1/router.py` — mounts the two new routers.

### Web
- `api/types.ts` — `TaskTemplate`, `Schedule`, `TriggerType`, `TaskSource`,
  create-request types, plus provenance on the execution types.
- `api/templates.ts`, `api/schedules.ts` — **new** client modules.
- `pages/TemplatesPage.vue`, `pages/SchedulesPage.vue` — **new** list + create
  dialog + run-now / trigger-now / delete.
- `router/index.ts`, `layouts/MainLayout.vue` — `/templates` + `/schedules`
  routes and menu entries.
- `i18n/locales/{en,zh}.ts` — `nav.templates`/`nav.schedules` + `templates.*` /
  `schedules.*` sections.

### Tests
- `tests/test_templates.py` — **new** (7): CRUD, run-from-template snapshot,
  edit-after-run immutability, template run → `no_target`.
- `tests/test_schedules.py` — **new** (10): CRUD, interval/cron validation,
  trigger-now snapshot, repeated trigger-now not coalesced, `fire_timer`
  dispatch + backlog coalesce.
- `tests/test_outbox.py` — coalesce tests rewritten schedule-keyed.
- `tests/test_executions.py` — `no_healthy_nodes` test now asserts the
  `no_target` task.
- `web/src/pages/__tests__/TemplatesPage.spec.ts` — **new** (3): render, create
  with node strategy, run → navigate.

## 2. Migration strategy

Single additive revision `0005` (down-rev `0004`): two `CREATE TABLE` + one
index + four `ALTER TABLE tasks ADD COLUMN` (all with server defaults, so the
add is safe on a populated table). No rename, no data move, fully reversible
(`downgrade` drops the columns/index/tables). The SQLite test schema is built
from the ORM models (`conftest.create_all`); PostgreSQL remains the schema
authority. Offline SQL `alembic upgrade 0004:0005 --sql` generates valid
PostgreSQL.

## 3. API surfaces added

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/templates` | create template |
| GET | `/api/v1/templates` | list templates |
| GET | `/api/v1/templates/{id}` | get template |
| PUT | `/api/v1/templates/{id}` | update template |
| DELETE | `/api/v1/templates/{id}` | delete template |
| POST | `/api/v1/templates/{id}/run` | create + dispatch a task from snapshot (source=manual) |
| POST | `/api/v1/schedules` | create schedule |
| GET | `/api/v1/schedules` | list schedules |
| GET | `/api/v1/schedules/{id}` | get schedule |
| PUT | `/api/v1/schedules/{id}` | update schedule |
| DELETE | `/api/v1/schedules/{id}` | delete schedule |
| POST | `/api/v1/schedules/{id}/trigger-now` | create + dispatch immediately (source=schedule_trigger_now) |

Run / trigger-now return `ExecutionRunResponse{execution_id=task.id, status}`;
they surface 202 `dispatch_unknown` exactly like `/executions/run`, and 200 with
`status="no_target"` when no node is healthy.

## 4. Web pages / routes added

- `/templates` → `TemplatesPage.vue` — list, create (name/project/spider/
  version/node-strategy), **Run now**, delete.
- `/schedules` → `SchedulesPage.vue` — list, create (name/template/
  interval-or-cron), **Trigger now**, delete.
- Menu entries added in `MainLayout.vue` between Crawlers and Executions.

## 5. Zero-node `no_target` behavior

Task dispatch creates the `Task` **before** node selection and uses the
non-raising `resolve_target_nodes`. When the strategy yields zero healthy
candidate nodes, `mark_no_target` sets `status = no_target`,
`status_reason = "no_target"`, and `status_detail = {node_strategy, node_ids,
healthy_count}`, stamps `started_at`/`finished_at`, commits, and returns. There
are **no child executions** and roll-up is never invoked (an empty roll-up
returns `None`, which would otherwise hang the task in `queued`). `no_target` is
already in `TASK_TERMINAL` and has no out-edges, so reconcile/cancel leave it
alone. This applies uniformly to manual `/executions/run`, run-from-template,
trigger-now, and timer firing.

## 6. How repeated / concurrent runs avoid coalesce blocking

- Manual run, run-from-template, and trigger-now **never** consult coalesce —
  each call always creates a new task (acceptance: re-running while a prior task
  is active is allowed; verified by `test_repeated_trigger_now_not_coalesced`).
- Only `fire_timer` (the `schedule_timer` path) calls
  `has_undispatched_backlog_for_schedule(schedule_id)`, which returns true only
  when a task for that schedule is still `queued` **and** has an unresolved
  (pending/dispatching/failed_retryable) outbox row — i.e. genuine Redis-outage
  backlog. A `running` task or a `queued` task whose outbox is already `sent`
  does **not** suppress a new firing (verified by `test_coalesce_false_when_*`).
- Redis outbox invariant preserved: one `run` command row per atomic execution
  (the per-node loop in the executor is unchanged; `all`/`random`/`selected`
  counts verified in `test_executions.py`).

## 7. Tests added / updated

See §1 “Tests”. New server coverage: template snapshot immutability after edit,
node-strategy → execution count (retained), zero-node `no_target` (manual +
template), repeated trigger-now, schedule-keyed coalesce (suppress backlog,
allow running/dispatched), interval & cron validation. New web coverage:
templates page render + create-with-strategy + run-and-navigate.

## 8. Commands run — pass/fail

```
.venv/bin/pytest apps/server/tests packages/protocol/tests   → 184 passed
.venv/bin/ruff check apps packages                            → All checks passed!
corepack pnpm --filter web test                               → 6 files / 10 tests passed
corepack pnpm --filter web build                              → built OK (pre-existing
                                                                 vite chunk-size + @vueuse
                                                                 pure-comment warnings only)
cd deploy/docker && docker compose config                     → OK
alembic -c alembic.ini upgrade 0004:0005 --sql                → valid PostgreSQL SQL
```

`make compose-smoke` was **NOT run**: it requires a live Postgres + Redis +
agent stack (full end-to-end runtime) that is not available in this sandbox. No
operational end-to-end acceptance is claimed beyond the offline `docker compose
config` validation and the integration tests that exercise the run/trigger →
task/executions/outbox/log path against the in-memory SQLite + fake Redis.

## 9. Known risks / incomplete items

- **Live timer firing not exercised by tests.** The `ScheduleRunner`
  (APScheduler) is gated by `[scheduler].enabled` (default off) and not started
  in tests (ASGITransport runs no lifespan). The thing the timer *calls*
  (`fire_timer` + coalesce) is unit-tested directly; the APScheduler wiring
  itself (trigger construction, `reload`) is covered only by import/static
  review, not a running-timer test. First real-stack run should confirm a timer
  produces a `schedule_timer` task.
- **Cron is implemented** (stored + `CronTrigger.from_crontab`, validated as
  5-field) rather than deferred; only basic field-count validation happens at
  create time — a syntactically-5-field-but-semantically-bad cron would fail at
  APScheduler job-add (runner `reload`), surfaced in logs, not at the API.
- **Runner reload coupling.** The schedules API reloads the live runner via
  `app.state.schedule_runner`; if the runner is disabled this is a no-op, so new
  schedules take effect only on next start — acceptable since the runner is off
  by default this phase.
- **`no_target` response code.** Manual `/executions/run` now returns 200
  `no_target` instead of 409 `no_healthy_nodes`. Any external caller relying on
  the 409 would break; there are none (single-admin, in-repo web), and the web
  treats `no_target` as a terminal status already.
- **compose-smoke / browser smoke** not run (see §8).
