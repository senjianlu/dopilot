# Phase 1.7 Packet 1 — Claude progress heartbeat

## 2026-06-19 — context read + scope locked

- Read brief, feasibility review, all server/protocol/web surface files.
- Scope decision: full internal server-domain rename (Task/Execution); keep two
  stable seams — (1) Redis/disk/agent wire, (2) public HTTP/web contract.

## 2026-06-19 — implementation complete (code), tests blocked on exec approval

- **Done (code)**:
  - `services/states.py`: inverted to TASK_*/EXEC_*; added `TASK_NO_TARGET`
    terminal; renamed `rollup_task_status`, `is_valid_task_transition`,
    `is_valid_execution_transition`, `AGENT_TO_EXEC`.
  - `models/execution.py`: `Execution`→`Task` (table `tasks`, +`status_reason`,
    +`status_detail`), `ExecutionAttempt`→`Execution` (table `executions`, FK
    `task_id`); `ExecutionLogFile`/seam columns unchanged. `models/__init__.py`
    exports updated.
  - `migrations/versions/0004_task_execution_rename.py`: rename tables/col + add
    columns; data-preserving; seam columns untouched.
  - Propagated through `services/{executions,outbox,events,cancel}.py`,
    `executors/scrapyd.py`, `redis/{dispatcher,reconcile}.py`,
    `api/v1/{executions,schemas}.py`. `services/logs.py` needed no change (pure
    seam). Routes/JSON/error-codes kept stable (web seam).
  - `protocol/streams.py`: added the wire-seam doc note. `web/src/api/types.ts`:
    additive `no_target` + optional `status_reason`/`status_detail`.
  - Updated tests: `test_states`, `test_outbox`, `test_dispatcher`,
    `test_event_consumer`, `test_log_consumer`, `test_reconcile_redis`,
    `test_executions`, `test_sse`, `conftest.py` Seeder (`running_task`).

---

# Phase 1.7 Packet 2 — Claude progress heartbeat

## 2026-06-19 — context read + estimate

- Read brief, feasibility, packet-1 report, codex review, packet-2 prompt, and
  every in-scope server/web file. APScheduler 3.11.2 confirmed available.
- **Duration class:** large (models + migration + zero-node path + template &
  schedule services/API + scheduler runner + web pages/routes + tests + report).
- **Update cadence:** at each checkpoint and before/after long commands.
- **Checkpoints:** (1) models+migration; (2) zero-node `no_target`;
  (3) templates service+API+run; (4) schedules service+API+trigger-now+runner+
  coalesce; (5) web; (6) tests + 4 required commands; (7) report.
- **Likely long commands:** `.venv/bin/pytest apps/server/tests
  packages/protocol/tests`, `.venv/bin/ruff check apps packages`,
  `corepack pnpm --filter web test`, `corepack pnpm --filter web build`.

## 2026-06-19 — backend complete, tests green (focused)

- Done: models (`scheduling.py`: TaskTemplate, Schedule) + Task origin/snapshot
  cols; migration `0005`; `states.py` source consts; `executions.py` TaskOrigin
  + `mark_no_target` + provenance views; `nodes/service.py` `resolve_target_nodes`
  (non-raising); scrapyd executor zero-node `no_target` + origin; schedule-keyed
  coalesce (`outbox.has_undispatched_backlog_for_schedule`); `services/templates.py`,
  `services/dispatch.py`, `services/schedules.py`; `scheduler/runner.py`
  (APScheduler, gated by `[scheduler].enabled`) wired into app lifespan; API
  routers `templates.py` + `schedules.py` registered.
- Tests: rewrote outbox coalesce tests (schedule-keyed), updated 409→no_target
  test; added `test_templates.py` (7) + `test_schedules.py` (10). Focused runs
  green. Next: full server suite + ruff, then frontend.

## 2026-06-19 — frontend + all commands green; report written

- Web: types (TaskTemplate/Schedule/+provenance), api `templates.ts` /
  `schedules.ts`, pages `TemplatesPage.vue` / `SchedulesPage.vue`, routes + menu
  entries, en/zh i18n, `TemplatesPage.spec.ts` (3 tests).
- **All required commands pass:**
  - `pytest apps/server/tests packages/protocol/tests` → 184 passed.
  - `ruff check apps packages` → all checks passed.
  - `pnpm --filter web test` → 6 files / 10 tests passed.
  - `pnpm --filter web build` → built OK (pre-existing dep warnings only).
  - Extra: `docker compose config` OK; alembic offline SQL `0004:0005` valid.
  - NOT run: `make compose-smoke` (needs a live Postgres/Redis/agent stack).
- Report: `docs/phases/phase-1.7/05-packet-2-implementation-report.md`. Done.
- **Static verification (passed)**: every `svc.*` call resolves to a defined
  function; every `states.*` constant is defined; no stale
  `ExecutionAttempt`/`ATTEMPT_`/old-svc-name references in source or tests; all
  remaining `.execution_id`/`.attempt_id` are legitimate seam usages.
- **Blocker**: the sandbox auto-allows read-only commands (find/grep/ls) but
  gates execution of `.venv/bin/pytest` / `python` / `ruff` behind interactive
  approval that did not clear this session. `pytest`/`ruff`/`pnpm` therefore
  NOT executed by me — exact commands are in the implementation report; awaiting
  approval to run.
- **Next**: run the three required commands once approved; report written.

---

# Phase 1.7 Final Acceptance — Claude progress heartbeat

## 2026-06-19 — context read + estimate (validation packet)

- Read brief, both packet reports + codex reviews, smoke script, runner,
  test_schedules/test_templates, nodes/templates/schedules API.
- **Findings to act on:**
  - `scripts/smoke-phase1.sh` step 5 uses the removed `POST /api/v1/nodes/refresh`
    → must move to the Redis heartbeat model (`GET /api/v1/nodes`, agent already
    heartbeats); also the run path is legacy `/executions/run` only → must add a
    template/schedule Phase 1.7 path.
  - Residual risk flagged by both reviews: live `ScheduleRunner` (APScheduler
    wiring: trigger build + reload + `_fire`) has no running-timer test → add
    direct coverage that registers/reloads jobs and exercises the timer path.
  - `make compose-smoke` target needs to be confirmed/updated for the heartbeat
    model + a template path.
- **Plan (this packet):** (1) baseline-run the required Python/web commands to
  confirm current green; (2) add `ScheduleRunner` test; (3) verify schedules
  web/API coverage, add if missing; (4) rewrite smoke script for heartbeat +
  template path; (5) compose config + alembic SQL; (6) docker compose smoke;
  (7) final validation report.
- **Env confirmed:** `.venv` py3.12, docker 29.5.3, compose v5.1.4 present.
- **Update cadence:** before/after each long command, esp. docker/compose.

## 2026-06-19 — tests + smoke edits done; baseline all green

- **Baseline (pre-edit) all green:** pytest 186, ruff clean, web 6/10, web build
  OK, `docker compose config` OK, alembic offline SQL to head valid through 0005
  (`0003->0004` rename incl. `RENAME COLUMN execution_id TO task_id`;
  `0004->0005` creates `task_templates`+`schedules`+4 task cols).
- **Added `apps/server/tests/test_scheduler_runner.py` (8 tests):** runner gating
  (enabled/disabled), interval+cron trigger build, start registers one job per
  schedule, reload syncs add/remove, reload-before-start no-op, and the timer
  callback `_fire` creates a real `schedule_timer` task + one run command on the
  agent Redis stream, plus unknown-schedule no-op. Closes both reviews' "live
  APScheduler not exercised" residual risk.
- **Added `apps/web/src/pages/__tests__/SchedulesPage.spec.ts` (4 tests):**
  render, interval create, cron create (cron set / interval null), trigger-now
  navigates. SchedulesPage previously had zero coverage.
- **Rewrote `scripts/smoke-phase1.sh` for phase 1.7 + heartbeat model:**
  - step 5 now polls `GET /api/v1/nodes` until heartbeat-healthy (removed the
    gone `POST /nodes/refresh`); added step 5b `GET /api/v1/health` DB/Redis/
    nodes-ok assertions.
  - step 8 now creates a Scrapy **template** then `POST /templates/{id}/run`
    (template -> task -> execution), replacing legacy `/executions/run`.
  - step 12 added: `POST /schedules` + `/trigger-now` creates a new task with
    `source=schedule_trigger_now`.
- **Re-ran after edits:** pytest **194 passed**, ruff clean, web **7 files / 14
  tests**, `bash -n` smoke OK.
- **Next (long):** `make compose-smoke` (builds images + brings up
  db/migrate/agent/server on fresh volumes; runs the template + schedule paths).
