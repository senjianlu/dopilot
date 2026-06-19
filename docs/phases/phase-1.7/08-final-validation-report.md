# Phase 1.7 Final Validation Report

Date: 2026-06-19

## Scope

Final acceptance validation for Phase 1.7:

- task/execution domain split;
- templates and schedules;
- no-target behavior;
- scheduler runner coverage;
- Docker smoke coverage for the current Redis heartbeat model and Phase 1.7 template/schedule paths.

## Tests Added Or Updated

- Added `apps/server/tests/test_scheduler_runner.py` with 8 tests covering:
  - scheduler enabled/disabled gating;
  - interval and cron trigger construction;
  - start registers schedule jobs;
  - reload adds/removes jobs;
  - reload before start is a no-op;
  - `_fire()` creates a real `schedule_timer` task and dispatches one run command;
  - unknown schedule id is a no-op.
- Added `apps/web/src/pages/__tests__/SchedulesPage.spec.ts` with 4 tests covering:
  - schedule list rendering;
  - interval schedule creation;
  - cron schedule creation;
  - trigger-now navigation to the created task.
- Existing Phase 1.7 API tests now cover templates, schedules, cron validation, no-target tasks, template delete-in-use conflict, and run/trigger provenance.

## Smoke Script Changes

Updated `scripts/smoke-phase1.sh`:

- Replaced removed `POST /api/v1/nodes/refresh` with polling `GET /api/v1/nodes` until a heartbeat-healthy agent appears.
- Added `/api/v1/health` DB/Redis/nodes assertions.
- Replaced legacy direct `/api/v1/executions/run` smoke path with:
  - upload committed Scrapy egg;
  - create a Scrapy task template;
  - run the template via `POST /api/v1/templates/{id}/run`;
  - poll the resulting task to `complete`;
  - assert landed Scrapy log markers.
- Added schedule path:
  - create schedule for the template;
  - `POST /api/v1/schedules/{id}/trigger-now`;
  - assert new task source is `schedule_trigger_now` and `schedule_id` links back.
- Fixed the template smoke payload to include the uploaded artifact. Without this, the server only stored the egg and the agent did not fetch/deploy it for the template run.
- Ensured early smoke failures print `SMOKE FAILED`, so external polling does not wait forever on a failed script.

## Commands Run

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests
```

Result: pass, `194 passed in 6.39s`.

```bash
.venv/bin/ruff check apps packages
```

Result: pass, `All checks passed!`.

```bash
corepack pnpm --filter web test
```

Result: pass, 7 files / 14 tests. Vue test warnings about unresolved `v-loading` stubs are pre-existing test-environment warnings and did not fail the run.

```bash
corepack pnpm --filter web build
```

Result: pass. Vite emitted existing Rollup/chunk-size warnings only.

```bash
docker compose -f deploy/docker/docker-compose.yml config
```

Result: pass.

```bash
cd apps/server
DOPILOT_DATABASE_URL='postgresql+psycopg://user:pass@localhost/dopilot' \
  ../../.venv/bin/alembic -c alembic.ini upgrade head --sql
```

Result: pass. Offline SQL generated migrations from `0001` through `0005`, including:

- `0003 -> 0004`: rename `executions` to `tasks`, `execution_attempts` to `executions`, add no-target reason/detail.
- `0004 -> 0005`: create `task_templates`, `schedules`, and task provenance/snapshot columns.

```bash
git diff --check
```

Result: pass.

## Docker Smoke

`make compose-smoke` could not be used in this shell because `make` is not installed:

```text
/bin/bash: line 1: make: command not found
```

Ran the equivalent smoke script directly:

```bash
scripts/smoke-phase1.sh
```

Result: pass.

Key smoke assertions:

- DB healthy.
- Alembic migrate service completed from empty database to head.
- Agent healthy and local Scrapyd running.
- Server healthy.
- `GET /api/v1/nodes` reported a heartbeat-healthy agent.
- `/api/v1/health` reported PostgreSQL ok, Redis ok, and at least one healthy node.
- Scrapy egg uploaded.
- Template created.
- Template run created a task with one child execution.
- Task completed.
- Scrapy log markers were present:
  - `phase1 demo spider started`
  - `phase1 demo spider done`
- Schedule created.
- Trigger-now created a new task with `source == schedule_trigger_now`.
- Trigger-now task linked back to the schedule.
- Smoke summary: `passed: 23 failed: 0`, `SMOKE PASSED`.
- Compose teardown completed; no Docker containers were left running.

## Remaining Risks

- `make compose-smoke` itself was not executable in the current environment because `make` is absent. The underlying smoke script passed directly.
- The running Claude final-validation process did not return its JSON report after the first failed smoke and remained idle. Codex completed the fix and validation directly rather than terminating the Claude process.

No blocking Phase 1.7 product or test risk remains.

## Recommendation

Accept Phase 1.7.
