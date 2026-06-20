# 00 · Phase 1.7.1 brief（Frontend UI optimization）

## Goal

Improve the Phase 1.7 web UI and add the backend contracts needed to support
large execution history, node scheduling controls, better template creation,
schedule next-run visibility, and dashboard health/statistics.

This phase keeps the Phase 1.5/1.7 architecture:

- server dispatches through Redis Streams;
- agents publish heartbeat/events/logs;
- PostgreSQL remains the source of truth;
- the server remains single-instance;
- `reference/scrapydweb/` is read-only behavioral reference only.

## Confirmed Product Decisions

- Nodes support reversible offline/online state.
- Nodes support delete. Delete is implemented as soft delete so historical
  references can still render a deleted node.
- Node badges use these colors:
  - deleted: gray;
  - offline: red;
  - healthy online: green;
  - degraded/unhealthy/unknown online: yellow.
- Offline nodes still receive heartbeat and display real health details, but
  are not eligible for task dispatch or dashboard scheduling-health aggregates.
- Backend pagination is required for execution history because it can grow by
  tens of thousands of rows per day.
- Page sizes are `5`, `10`, `20`, `50`, and `100`; the frontend chooses the
  closest suitable size from table height and requests that page from the
  backend.

## In Scope

### Nodes

- Add node scheduling state and soft-delete fields, with Alembic migration.
  Suggested shape:
  - `scheduling_enabled` boolean default true;
  - `scheduling_disabled_at` nullable timestamp;
  - `deleted_at` nullable timestamp.
- Add node API endpoints:
  - `GET /api/v1/nodes`;
  - `POST /api/v1/nodes/{node_id}/offline`;
  - `POST /api/v1/nodes/{node_id}/online`;
  - `DELETE /api/v1/nodes/{node_id}` for soft delete.
- Keep heartbeat upsert behavior for offline nodes.
- Decide carefully how heartbeat behaves for soft-deleted nodes:
  - preferred: do not resurrect deleted nodes automatically;
  - if the same `agent_id` heartbeats again, keep `deleted_at` and update health
    fields unless a future explicit restore endpoint is added.
- Exclude offline/deleted nodes from:
  - `resolve_target_nodes`;
  - `select_target_nodes`;
  - `pick_deploy_node`;
  - dashboard schedulable-agent aggregate.
- Do not mutate existing templates when referenced nodes are offlined/deleted.
- Existing selected-template runs skip unschedulable referenced nodes. If none
  remain, create the existing zero-execution `no_target` task with useful
  `status_detail`.
- Fix the web refresh button by replacing the removed `POST /nodes/refresh`
  path with a fresh `GET /nodes`.
- Add Nodes page operations column:
  - offline when scheduling is enabled and node is not deleted;
  - online when scheduling is disabled and node is not deleted;
  - delete when not deleted.
- Disable or hide offline/delete actions for configured-but-unseen nodes with
  `id == null`.

### Backend Pagination And Execution Filtering

- Replace fixed execution list `limit=200` with server-side pagination.
- Add `GET /api/v1/executions?page=&page_size=&spider=`.
- Validate page inputs:
  - `page >= 1`;
  - `page_size` must be one of `5, 10, 20, 50, 100`.
- Return a paginated response with:
  - `executions`;
  - `page`;
  - `page_size`;
  - `total`.
- Avoid the current N+1 child-count pattern by querying child execution counts
  in aggregate for the current task page.
- Add spider filtering.
  - Prefer a task-level `spider` column populated at task creation from parsed
    Scrapy params/template snapshot, with migration and tests.
  - If a lower-risk equivalent is chosen, it must still work under PostgreSQL
    and the SQLite test path.
- Update frontend execution API/types and Executions page to use backend
  pagination and spider filter.
- The spider filter should include an "all" state and let users filter by known
  spider values.

### Dashboard

- Replace the current descriptions-only health view with a three-column service
  health table:
  - Service;
  - breathing status light;
  - Notes.
- Rows:
  - Server;
  - Agent;
  - Redis;
  - PostgreSQL.
- Agent health is based on schedulable, non-deleted nodes:
  - green when all schedulable seen nodes are healthy;
  - yellow when at least one schedulable node is degraded/unhealthy/unknown and
    at least one schedulable healthy node exists;
  - red when no schedulable healthy node exists.
- Add a backend stats endpoint for the last 30 days of parent task/run counts.
  Suggested route: `GET /api/v1/stats/tasks/daily?days=30`.
- The 30-day chart should be a compact bar chart. Avoid adding a heavyweight
  chart dependency unless implementation proves native SVG/CSS unsuitable.

### Templates

- Remove user-facing Project input and Project table column from templates.
- Template creation should select an uploaded Scrapy artifact, then select a
  spider from that artifact's `spiders`.
- Use artifact metadata to populate backend fields required by Scrapy dispatch
  (`project`, `version`, artifact payload).
- Add "involved nodes" under node strategy:
  - `all` and `random`: disabled multi-select showing current non-deleted,
    schedulable nodes;
  - `selected`: editable multi-select of current non-deleted, non-offline nodes,
    regardless of health.
- Multi-select selected items should show badge status:
  - healthy online: green;
  - degraded/unhealthy/unknown online: yellow;
  - offline: red;
  - deleted historical references: gray.
- Do not allow new selection of offline/deleted nodes.

### Schedules

- Display trigger information as "Trigger time":
  - interval: `every XX seconds`;
  - cron: raw cron expression.
- Add `next_run_at` to schedule API views.
- Add a "next run time" column before actions.
- In the create schedule dialog, display read-only estimated next run time below
  the interval/cron input.
- `next_run_at` may be computed from the submitted trigger and current time.
  For interval triggers, this is an estimate unless the live APScheduler job has
  an exact next fire time available.

## Out Of Scope

- Python script executor.
- Docker long-lived crawler executor.
- Distributed scheduler locks or multi-server HA.
- A new node restore endpoint after delete.
- Hard deletion of nodes.
- Pagination for every small list if it adds broad churn; executions are the
  required large-history path.
- Reintroducing server-to-agent HTTP run/status/tail.
- Copying or importing anything from `reference/scrapydweb/`.

## Expected Files / Modules

- Server:
  - `apps/server/dopilot_server/models/node.py`
  - `apps/server/dopilot_server/models/execution.py`
  - `apps/server/dopilot_server/api/v1/nodes.py`
  - `apps/server/dopilot_server/api/v1/executions.py`
  - `apps/server/dopilot_server/api/v1/health.py`
  - `apps/server/dopilot_server/api/v1/schedules.py`
  - `apps/server/dopilot_server/api/v1/schemas.py`
  - `apps/server/dopilot_server/nodes/service.py`
  - `apps/server/dopilot_server/services/executions.py`
  - `apps/server/dopilot_server/services/schedules.py`
  - new stats service/API if useful;
  - Alembic migration under `apps/server/dopilot_server/db/migrations/`.
- Web:
  - `apps/web/src/api/*.ts`
  - `apps/web/src/api/types.ts`
  - `apps/web/src/pages/DashboardPage.vue`
  - `apps/web/src/pages/NodesPage.vue`
  - `apps/web/src/pages/TemplatesPage.vue`
  - `apps/web/src/pages/SchedulesPage.vue`
  - `apps/web/src/pages/ExecutionsPage.vue`
  - i18n locale files.
- Tests:
  - focused server tests for node state/delete, selection filtering,
    pagination/filtering, stats, and next-run metadata;
  - focused web tests for the updated pages.

## Acceptance Criteria

- Nodes page refresh works without calling removed `POST /nodes/refresh`.
- A node can be offlined, remains visible with real health, and is excluded from
  dispatch target selection.
- An offlined node can be brought online again and becomes eligible when healthy
  and capable.
- A node can be soft-deleted and is excluded from normal scheduling choices.
- Existing selected templates are not silently changed when a selected node is
  offlined/deleted.
- Running a selected template whose selected nodes are all unschedulable creates
  a visible `no_target` task.
- Execution list requests backend pages and displays total/page controls.
- Execution list supports spider filtering.
- Execution list backend avoids per-row N+1 child-count queries for the current
  page.
- Dashboard shows Server/Agent/Redis/PostgreSQL health rows with breathing
  lights and notes.
- Dashboard shows a 30-day daily task/run count bar chart.
- Template creation no longer exposes Project, and spider selection is based on
  the chosen artifact.
- Template node selector follows the enabled/disabled and badge rules.
- Schedule list shows trigger time and next run time.
- Schedule create dialog shows read-only estimated next run time.

## Required Tests

- Server tests:
  - node offline excludes a healthy node from `resolve_target_nodes`;
  - node online restores eligibility;
  - soft-deleted nodes are excluded from selection and list/selector surfaces;
  - heartbeat does not clear soft-delete state;
  - selected templates skip offline/deleted selected nodes;
  - all-selected-unschedulable template run creates `no_target`;
  - `GET /executions` validates page/page_size and returns `total`;
  - `GET /executions` spider filter returns only matching tasks;
  - execution list aggregates child counts without N+1 behavior where practical
    to assert;
  - stats daily endpoint returns 30 day buckets;
  - schedule views include `next_run_at` for interval and cron.
- Web tests:
  - Nodes page refresh calls list endpoint and renders operation buttons;
  - node badge colors/states render for healthy/degraded/offline/deleted;
  - Templates page artifact/spider selection submits derived payload;
  - Templates page node selector locks for `all/random` and enables for
    `selected`;
  - Schedules page shows trigger time and next run estimate;
  - Executions page sends pagination and spider filter params;
  - Dashboard renders health rows and daily chart.

## Required Commands

```bash
pytest apps/server/tests packages/protocol/tests
ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Broaden to the compose smoke only if backend dispatch behavior or migrations
touch shared runtime paths enough to justify it:

```bash
scripts/smoke-phase1.sh
```

## Risks To Watch

- Do not let node soft-delete resurrect implicitly on heartbeat.
- Do not treat offline as unhealthy. Offline is a scheduling-control state;
  heartbeat health remains independently visible.
- Do not silently remove node ids from existing templates.
- Do not reintroduce the removed server-driven node refresh model.
- Keep pagination response changes synchronized between server schemas,
  TypeScript types, and page tests.
- Be explicit that interval `next_run_at` is an estimate unless using a live
  scheduler job's next fire time.
