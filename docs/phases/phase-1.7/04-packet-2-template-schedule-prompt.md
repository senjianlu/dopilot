# Claude Implementation Prompt · Phase 1.7 Packet 2

You are Claude Code working in the dopilot repository.

## Assignment

Implement the remaining user-visible Phase 1.7 template/schedule/task behavior:

- Scrapy task templates.
- Task creation from immutable template snapshots.
- Schedules referencing templates.
- Trigger-now for schedules.
- Zero-healthy-node tasks with terminal `no_target`.
- Web pages/menu entries so the user can see and use templates/schedules.

Active brief:

- `docs/phases/phase-1.7/00-brief.md`

Previous packet reports:

- `docs/phases/phase-1.7/00a-feasibility-review.md`
- `docs/phases/phase-1.7/02-packet-1-implementation-report.md`
- `docs/phases/phase-1.7/03-codex-review.md`

## Current Workspace State

Packet 1 changes are present in the worktree and are intentionally uncommitted.
Work with them; do not revert them. Important packet-1 decisions:

- Server domain uses `Task` (parent) and `Execution` (atomic per-node).
- Redis/disk/agent seam remains stable:
  - wire `execution_id` = task id;
  - wire `attempt_id` = atomic execution id.
- Public `/api/v1/executions` and Web execution/attempt vocabulary are still a
  compatibility seam from Packet 1. Packet 2 may introduce new `/api/v1/tasks`,
  `/api/v1/templates`, and `/api/v1/schedules` surfaces, but do not break the
  existing crawler/manual run flow unless the new tests are updated accordingly.
- `TASK_NO_TARGET`, `Task.status_reason`, and `Task.status_detail` already
  exist, but the zero-node creation path is not implemented yet.

## Required Context

Read before editing:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`
- `docs/phases/phase-1.7/00-brief.md`
- `docs/phases/phase-1.7/00a-feasibility-review.md`
- `docs/phases/phase-1.7/02-packet-1-implementation-report.md`
- `docs/phases/phase-1.7/03-codex-review.md`
- `apps/server/dopilot_server/models/execution.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/nodes/service.py`
- `apps/server/dopilot_server/services/outbox.py`
- `apps/server/dopilot_server/scheduler/__init__.py`
- `apps/server/dopilot_server/app.py`
- `apps/server/dopilot_server/api/v1/router.py`
- `apps/server/dopilot_server/api/v1/executions.py`
- `apps/web/src/router/index.ts`
- `apps/web/src/layouts/MainLayout.vue`
- `apps/web/src/pages/CrawlersPage.vue`
- `apps/web/src/pages/ExecutionsPage.vue`
- `apps/web/src/api/types.ts`
- `apps/web/src/locales/zh.ts`

## In Scope

Backend:

- Add schema/migration for Scrapy task templates.
  - Include name, description, `task_type`, artifact/project/version/spider,
    settings, args, node_strategy, selected node ids, and metadata timestamps.
  - `task_type` is forward-compatible but only `scrapy` is valid now.
- Add schema/migration for schedules.
  - A schedule references one template.
  - Support enough trigger fields for phase 1.7: interval seconds and a simple
    cron expression or cron field set. If both is too broad, implement interval
    first and document cron as not yet implemented in the report.
  - Pause/resume is out of scope; do not add a paused state.
- Add task snapshot fields if not already present:
  - source type: manual, schedule_trigger_now, schedule_timer;
  - template_id and optional schedule_id;
  - copied template payload snapshot.
- Implement services/API:
  - CRUD/list/get for templates sufficient for Web.
  - CRUD/list/get for schedules sufficient for Web.
  - `POST trigger-now` on a schedule creates a task from the template snapshot
    and dispatches it through the same task dispatch path as manual/template run.
  - Run-from-template endpoint creates a task from template snapshot.
  - Existing manual crawler run may remain as ad-hoc task creation.
- Implement zero-node behavior:
  - For template/manual/schedule task creation, create the task before node
    selection.
  - If no aggregate healthy target nodes match strategy, store a task with zero
    executions, terminal `no_target`, `status_reason="no_target"`, and useful
    `status_detail`.
  - Do not create fake executions.
- Preserve concurrent repeated runs:
  - Running a template/schedule trigger while a previous task is active must
    create a new task.
  - Any coalesce must only suppress undispatched same-schedule backlog, not
    active/running tasks and not manual/trigger-now.
- Keep Redis/disk/agent seam stable.

Frontend:

- Add navigation/menu entries for task templates and schedules.
- Add pages to list/create basic Scrapy templates and schedules.
- Add actions:
  - run a template now;
  - trigger a schedule now.
- Existing crawler page can keep ad-hoc run/upload behavior, but the user must
  have a visible place to manage templates/schedules.
- UI should be functional and restrained; no marketing page.

Docs/reports:

- Update or create implementation report:
  `docs/phases/phase-1.7/05-packet-2-implementation-report.md`

## Out Of Scope

- Python script executor.
- Docker long-lived executor.
- Schedule pause/resume.
- Multi-user/RBAC.
- Multi-server HA / distributed locks.
- Rewriting the agent protocol fields.
- Reintroducing server->agent HTTP run/status/tail.
- Copying/importing from `reference/scrapydweb/`.

## Required Progress Notes

Update:

`docs/phases/phase-1.7/claude-progress.md`

Within the first few minutes, append an estimate with rough duration class,
proposed update cadence, checkpoints, and likely long-running commands. Then
update at meaningful checkpoints and before/after long-running commands. The
cadence is a guideline, not a hard timer.

## Output Required

Create:

- `docs/phases/phase-1.7/05-packet-2-implementation-report.md`

The report must include:

- changed files grouped by area;
- migration strategy;
- API surfaces added;
- Web pages/routes added;
- how zero-node `no_target` behaves;
- how repeated/concurrent runs avoid coalesce blocking;
- tests added/updated;
- commands run with pass/fail output;
- known risks or incomplete items.

## Required Tests / Commands

Run focused tests first, then run all of these before finishing:

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

If Docker/browser smoke becomes practical during the packet, run one of:

```bash
cd deploy/docker && docker compose config
make compose-smoke
```

Do not claim full operational acceptance without reporting the exact command
result.

## Acceptance Criteria

- Templates are visible in Web and can be created/listed.
- A template can be run now and creates a task using a copied snapshot.
- Editing a template after a task exists does not mutate that task snapshot.
- Schedules are visible in Web and can be created/listed.
- Trigger-now on a schedule creates a task immediately from the referenced
  template snapshot.
- No healthy node creates a persisted zero-execution task with terminal
  `no_target`.
- `all`, `random`, and `selected` node strategies still produce the expected
  execution counts when healthy nodes exist.
- Repeated runs are allowed while earlier tasks are active.
- Redis outbox still has one run command per atomic execution.
- Existing manual crawler run/log/cancel behavior still works.
- Required tests/build pass or failures are documented with exact output.
