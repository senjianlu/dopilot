# 00 · Phase 1.7 brief（Task templates, tasks, schedules）

> Phase 1.7 starts after phase 1.6 health/artifact work. Keep the phase 1.5
> Redis Streams architecture: server dispatches commands through Redis, agents
> publish events/logs, and target selection uses aggregate healthy nodes only.

## Goal

Introduce the canonical scheduling domain model:

- `execution`: the most atomic agent execution, bound to one target node/agent.
- `task`: one run instance copied from a template; it may have many executions
  or zero executions when no healthy agent is available.
- `schedule`: a timer/trigger definition that references a template and creates
  tasks.
- `template`: a reusable run definition copied into each task snapshot.

This replaces the current ambiguous model where `executions` represents a
logical multi-node run and `execution_attempts` represents the per-node atomic
unit.

## Compatibility Decision

Keep the Redis/disk/agent seam stable:

- Wire, disk paths, agent state files, Redis commands/events/logs keep the
  existing fields `(execution_id, attempt_id)`.
- At that seam, `execution_id` continues to mean the parent logical run, now
  called `task` in the server domain.
- At that seam, `attempt_id` continues to mean the atomic per-agent unit, now
  called `execution` in the server domain.
- New server DB/service/API/Web vocabulary should use `(task_id, execution_id)`.
- Boundary code must translate and document this explicitly. Do not rename agent
  state, Redis stream payload fields, or on-disk log path components in this
  phase.

## Context

Relevant files and decisions:

- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/refactor/00-redis-streams-agent-communication.md`
- `docs/phases/phase-1.6/00-brief.md`
- `apps/server/dopilot_server/models/execution.py`
- `apps/server/dopilot_server/executors/scrapyd.py`
- `apps/server/dopilot_server/services/executions.py`
- `apps/server/dopilot_server/nodes/service.py`
- `packages/protocol/dopilot_protocol/execution.py`
- `apps/web/src/pages/CrawlersPage.vue`
- `apps/web/src/pages/ExecutionsPage.vue`

User-confirmed decisions on 2026-06-19:

1. Manually selecting all nodes creates one atomic execution per node. Two
   nodes means two executions under one task.
2. Concurrent repeated runs are allowed; do not coalesce or reject because a
   previous task/template run is still active.
3. Record failure events only for executions that actually exist. If no
   execution was created, the task has no executions.
4. A task copies a template snapshot at creation time. It does not read mutable
   template fields at run time.
5. Use the proposed domain split: template -> task -> execution, schedule
   references template.
6. Schedules support immediate trigger for testing. Pause is out of scope.
7. Scheduling and manual execution choose only aggregate healthy nodes.

## In Scope

- Add persistent task templates for Scrapy run definitions:
  - name/description;
  - task type, currently `scrapy`;
  - artifact hash/project/version/spider defaults;
  - settings/args defaults;
  - node strategy and selected node ids;
  - enabled/metadata fields only if needed for listing, not schedule pause.
- Add persistent tasks as immutable template snapshots:
  - source type: manual, immediate schedule trigger, timer trigger;
  - optional `template_id`;
  - copied task type, artifact, spider, settings, args, node strategy, selected
    node ids;
  - status rollup over executions: queued/running/complete/failed/canceled/lost/no_target.
- Rename the current logical `Execution` concept into `Task`.
- Rename current `ExecutionAttempt` as the atomic `Execution`.
- Prefer a clean phase-1.7 physical schema rename over a permanent logical wrap:
  the target DB vocabulary is `tasks` and `executions`, not `executions` and
  `execution_attempts`.
- Public `/api/v1` and Web may clean-cut to task/execution naming in this
  greenfield phase. Do not maintain dual public vocabularies unless a test or
  migration blocker proves it necessary.
- Preserve compatibility only at the Redis/disk/agent seam described above.
- Add schedule persistence that references templates:
  - interval and/or cron trigger fields sufficient for phase 1.7;
  - create a task from template snapshot when triggered;
  - support an immediate trigger endpoint that runs now using the same snapshot
    path as timer firing.
- Manual crawler runs should either:
  - run from an existing template; or
  - create an ad-hoc task snapshot from the submitted form without persisting a
    template, if the UI still needs direct run.
- Target selection for a task uses only aggregate healthy nodes.
- If no healthy node is available, create a task with zero executions and
  terminal status `no_target`, plus `status_reason` and `status_detail` on the
  task row. Do not create a fake execution or a new task-events table for this
  phase.
- For `all`, create one execution per healthy selected node.
- For `random`, create exactly one execution chosen from healthy candidates.
- For `selected`, create executions only for selected healthy nodes.
- Keep concurrent repeated runs allowed. Scheduler coalesce may only suppress an
  undispatched same-schedule backlog caused by Redis/dispatcher outage. It must
  never suppress manual runs, trigger-now runs, or a new timer run merely because
  an older task from the same template/schedule is already running.
- Update Web pages and labels so the list page shows tasks and task detail shows
  child executions.

## Out Of Scope

- Python script executor.
- Docker long-lived crawler executor.
- Schedule pause/resume.
- Multi-user ownership/RBAC.
- Distributed scheduler locks or multi-server HA.
- Storing artifact bytes in PostgreSQL.
- Reintroducing server->agent HTTP run/status/tail.
- Copying or importing anything from `reference/scrapydweb/`.

## Required Implementation Order

1. Add a clean rename migration and ORM/service rename:
   `executions` -> `tasks`, `execution_attempts` -> `executions`, parent
   references `execution_id` -> `task_id`, and atomic references `attempt_id` ->
   `execution_id` where they are server-domain columns.
2. Keep Redis/disk/agent identifiers stable and add explicit boundary
   translation. Agent code should remain out of scope.
3. Add task status `no_target`, `status_reason`, and `status_detail`; make
   `no_target` terminal and ensure empty child execution sets do not roll up to
   queued forever.
4. Move Scrapy dispatch to create a task first, select healthy nodes, then create
   one atomic execution and one command outbox row per chosen node. Zero healthy
   nodes short-circuits into the `no_target` task path.
5. Add templates and immutable task snapshot copying.
6. Add schedule creation/list/trigger-now endpoints, scheduler runner, and
   schedule-keyed undispatched-backlog coalesce.
7. Update Web API types and pages for templates, schedules, tasks, and task
   execution detail.
8. Add tests before broad UI polish; keep labels and compatibility explicit.

## Acceptance Criteria

- A Scrapy template can be created and used for manual run.
- Manual run with `node_strategy=all` against two healthy nodes creates one task
  and two atomic executions.
- Manual run with `random` creates one task and one atomic execution.
- Manual run with selected nodes creates executions only for selected healthy
  nodes.
- Re-running the same template while a previous task is active creates another
  task; it is not blocked by coalesce.
- If there are no healthy nodes, the task is stored with zero executions and a
  visible terminal `no_target` status with `status_reason/status_detail`.
- A schedule references a template and creates tasks from copied template
  snapshots.
- Editing a template after a task is created does not mutate the historical task
  snapshot.
- Trigger-now on a schedule creates a task immediately through the same path as
  timer firing.
- Node selection excludes degraded/unhealthy/unknown nodes.
- Redis command outbox has one run command per atomic execution.
- Redis/disk/agent payloads still use `(execution_id=task_id,
  attempt_id=execution_id)` at the boundary; server/API/Web expose
  `(task_id, execution_id)`.
- Existing log/event/cancel behavior still converges per atomic execution.
- Web shows task-level rows and child executions clearly.

## Required Tests

- Unit tests:
  - template snapshot copy is immutable after template edits;
  - node strategy all/random/selected maps to the expected execution count;
  - no healthy nodes creates a zero-execution no-target task;
  - repeated runs do not coalesce;
  - scheduler coalesce suppresses only undispatched same-schedule backlog;
  - status rollup from executions to task.
- Integration tests:
  - manual Scrapy template run writes task/executions/outbox/log rows correctly;
  - schedule trigger-now creates a task from the template snapshot;
  - Redis event/log consumers update the atomic execution and parent task status.
- Frontend tests:
  - task list renders task rows;
  - task detail renders child executions;
  - crawler/template run form submits node strategy and selected nodes.
- Smoke/manual checks:
  - compose stack can run the demo crawler from a template;
  - trigger-now creates a visible task and logs stream normally.

## Required Commands

```bash
pytest apps/server/tests packages/protocol/tests
ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

## Risks To Watch

- The current DB names invert the new model. Avoid a half-renamed state where
  `execution_id` sometimes means parent task and sometimes means atomic
  execution.
- Redis/disk/agent payload compatibility matters. The wire field
  `execution_id` remains the parent task id, and `attempt_id` remains the atomic
  execution id. Server boundary code must translate consistently.
- Existing log paths include `execution_id/attempt_id`; do not rename those path
  components in this phase.
- Scheduler coalesce in `services/outbox.py` was designed for duplicate
  suppression. Phase 1.7 explicitly allows repeated concurrent template runs, so
  any remaining coalesce must not suppress user-confirmed behavior.
- Zero-execution tasks need their own status/event model because there is no
  child execution to carry failure state.
