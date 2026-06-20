# 01 · Phase 1.7.1 Claude implementation report

Date: 2026-06-20. Status: complete (full brief implemented in one pass).

## Summary

Implemented the Phase 1.7.1 frontend optimization plus the backend contracts it
needs:

- node reversible offline/online + soft delete, with selection/dashboard
  exclusion and a heartbeat-does-not-resurrect invariant;
- execution-list backend pagination + spider filter + aggregate (non-N+1)
  child counts;
- dashboard service-health table (Server/Agent/Redis/PostgreSQL breathing
  lights) + a native-SVG 30-day task/run bar chart backed by a new stats
  endpoint;
- template creation by artifact + spider selection (Project field removed) and
  an involved-nodes multi-select with badge precedence;
- schedule trigger-time display, `next_run_at` metadata, and a create-dialog
  next-run estimate (interval = estimate, cron via backend preview).

The Phase 1.5/1.7 architecture is unchanged: Redis-Streams dispatch, single
server instance, PostgreSQL as the source of truth, no server→agent HTTP, no
`POST /nodes/refresh`, no copying from `reference/scrapydweb/`.

## Changed files

### Server

- `apps/server/dopilot_server/models/node.py` — `scheduling_enabled`,
  `scheduling_disabled_at`, `deleted_at` columns.
- `apps/server/dopilot_server/models/execution.py` — indexed `Task.spider`
  column (copied from run params at creation).
- `apps/server/migrations/versions/0006_node_state_task_spider.py` — new
  migration for the node state/soft-delete columns + `tasks.spider` (+ index).
- `apps/server/dopilot_server/nodes/service.py` — render new node fields in
  `_node_to_dict` / unseen-endpoint shape; exclude offline+deleted from the
  candidate query (`_healthy_capable_nodes` feeds `resolve_target_nodes` /
  `select_target_nodes` / `pick_deploy_node`); new ops `get_node_or_404`,
  `offline_node`, `online_node`, `soft_delete_node`, and a single-node
  `node_view` helper.
- `apps/server/dopilot_server/api/v1/nodes.py` — `POST /nodes/{id}/offline`,
  `POST /nodes/{id}/online`, `DELETE /nodes/{id}` (soft delete).
- `apps/server/dopilot_server/services/executions.py` — `create_task` copies
  spider; `list_tasks_page` (page/page_size/total + spider filter),
  `child_execution_counts` (one aggregate query), `list_task_spiders`;
  `task_summary` exposes `spider`; `ALLOWED_PAGE_SIZES`.
- `apps/server/dopilot_server/api/v1/executions.py` — paginated `GET
  /executions?page=&page_size=&spider=` with page_size validation and aggregate
  child counts.
- `apps/server/dopilot_server/services/stats.py` (new) — `daily_task_counts`
  bucketed per local calendar day in the scheduler timezone.
- `apps/server/dopilot_server/api/v1/stats.py` (new) — `GET
  /stats/tasks/daily?days=30`.
- `apps/server/dopilot_server/services/schedules.py` — `compute_next_run_at`,
  `preview_next_run`; `schedule_view` now emits `next_run_at` (timezone-aware).
- `apps/server/dopilot_server/api/v1/schedules.py` — thread scheduler timezone
  into views; `POST /schedules/preview-next-run`.
- `apps/server/dopilot_server/api/v1/health.py` — schedulable-only agent health
  aggregate (`agent.status` green/yellow/red) for the dashboard.
- `apps/server/dopilot_server/api/v1/schemas.py` — new node fields on
  `NodeView`; pagination envelope + `spiders` + `spider` on the execution
  schemas; `ScheduleView.next_run_at`; `DailyTaskCount`/`DailyTaskStatsResponse`
  and next-run preview request/response.
- `apps/server/dopilot_server/api/v1/router.py` — mount the stats router.

### Web

- `apps/web/src/api/types.ts` — node scheduling fields + `NodeBadge`; execution
  pagination params/envelope + `EXECUTION_PAGE_SIZES`; `ExecutionSummary.spider`;
  `Schedule.next_run_at`; next-run preview + daily-stats types; `HealthInfo.agent`.
- `apps/web/src/api/nodes.ts` — `refreshNodes` is now `listNodes` (no
  `/nodes/refresh`); `offlineNode`/`onlineNode`/`deleteNode`.
- `apps/web/src/api/executions.ts` — `listExecutions(params)` returns the full
  paginated response.
- `apps/web/src/api/schedules.ts` — `previewNextRun`.
- `apps/web/src/api/stats.ts` (new) — `getDailyTaskStats`.
- `apps/web/src/utils/nodeBadge.ts` (new) — badge precedence + tag-type map +
  `isOperable` (shared by Nodes + Templates).
- `apps/web/src/pages/NodesPage.vue` — refresh via list, precedence badge +
  raw-health column, offline/online/delete ops column (hidden when `id == null`
  or deleted).
- `apps/web/src/pages/ExecutionsPage.vue` — spider filter (with "all"), backend
  pagination control (5/10/20/50/100, closest-to-height default), total.
- `apps/web/src/pages/TemplatesPage.vue` — artifact→spider selection (Project
  input + column removed), involved-nodes multi-select (locked for all/random,
  editable for selected; offline/deleted not selectable; badge chips).
- `apps/web/src/pages/SchedulesPage.vue` — trigger-time column, next-run column,
  read-only create-dialog estimate.
- `apps/web/src/pages/DashboardPage.vue` — service-health table with breathing
  lights + native-SVG 30-day bar chart.
- `apps/web/src/i18n/locales/en.ts`, `zh.ts` — new keys for node ops/badges,
  execution spider/total, template artifact/spider/nodes, schedule
  trigger-time/next-run, dashboard service table + chart.

### Docs

- `docs/phases/phase-1.7.1/claude-progress.md` (new).
- `docs/phases/phase-1.7.1/01-claude-implementation-report.md` (this file).

### Tests

- `apps/server/tests/test_node_ops.py` (new) — offline/online exclusion +
  reversibility, soft-delete exclusion + still-listed, heartbeat keeps
  delete/offline state, ops endpoints + 404.
- `apps/server/tests/test_executions_pagination.py` (new) — spider copy,
  pagination + total, spider filter, aggregate child counts, distinct spiders,
  HTTP envelope/validation, all-selected-unschedulable → `no_target`.
- `apps/server/tests/test_stats_nextrun.py` (new) — 30 daily buckets + endpoint;
  interval estimate + cron determinism; schedule views include `next_run_at`;
  preview endpoint.
- `apps/web/src/pages/__tests__/NodesPage.spec.ts` — rewritten: refresh-via-list,
  ops endpoints, operation visibility, badge precedence.
- `apps/web/src/pages/__tests__/ExecutionsPage.spec.ts` — rewritten: paginated
  envelope + spider/page/size params.
- `apps/web/src/pages/__tests__/TemplatesPage.spec.ts` — rewritten: derived
  artifact payload, node selector lock/unlock.
- `apps/web/src/pages/__tests__/SchedulesPage.spec.ts` — extended: trigger-time
  + next-run + interval/cron estimate.
- `apps/web/src/pages/__tests__/DashboardPage.spec.ts` (new) — health rows +
  daily chart.

## Implementation notes

- **Offline ≠ unhealthy.** `NodeView.status` stays the heartbeat-derived health;
  offline/deleted are separate fields. The web badge applies precedence
  (deleted > offline > healthy > warning) but the raw health is still shown.
- **No implicit resurrection.** `upsert_node_heartbeat` never touches
  `deleted_at`/`scheduling_enabled`, so a deleted/offline node keeps reporting
  health without re-entering scheduling. Selection exclusion is enforced in the
  single candidate query, so `resolve_target_nodes`, `select_target_nodes` and
  `pick_deploy_node` all inherit it.
- **Selected templates are not mutated.** Offline/deleted selected nodes are
  simply skipped at runtime (they fall out of the candidate set); when none
  remain the existing zero-execution `no_target` task is produced
  (`status_detail` carries strategy/node_ids/healthy_count).
- **Spider filter** uses an indexed `tasks.spider` column populated at task
  creation from parsed params — queryable under PostgreSQL and the SQLite test
  path; the list response also returns the distinct known spiders for the UI.
- **N+1 avoided** via one grouped `COUNT` over the page's task ids
  (`child_execution_counts`), asserted in `test_child_execution_counts_aggregate`.
- **next_run_at**: interval is an explicit estimate (`now + interval_seconds`);
  cron uses APScheduler `CronTrigger.from_crontab`. The create-dialog estimate
  computes interval locally (no round-trip) and resolves cron via
  `POST /schedules/preview-next-run`.
- **Chart**: native SVG `<rect>` bars (tasks overlaid on executions) — no chart
  dependency added, per the brief constraint.

## Commands run

- `.venv/bin/pytest apps/server/tests -q -p no:cacheprovider` → **192 passed**.
- `.venv/bin/pytest packages/protocol/tests -q -p no:cacheprovider` → **29 passed**.
- `.venv/bin/ruff check apps packages` → **All checks passed** (9 trailing-
  newline/import findings from the edit pass auto-fixed via `--fix`).
- `corepack pnpm --filter web test` → **8 files / 22 tests passed**.
- `corepack pnpm --filter web build` → **built successfully** (vue-tsc type-check
  + vite production build).

The combined `pytest apps/server/tests packages/protocol/tests` form is not in
the sandbox allowlist, so the two suites were run separately (identical
coverage). The compose smoke (`scripts/smoke-phase1.sh`) was not run: this packet
adds API/UI surface and additive migration columns but does not change the
Redis/disk/agent dispatch path, so the brief's "broaden only if shared runtime
paths change" threshold was not met.

## Known risks / shortcuts / incomplete items

- **Migration applied on PostgreSQL not exercised here.** Tests build the SQLite
  schema from the ORM models (per `conftest.py`); `0006` mirrors `0005`'s style
  (`sa.true()` server_default, standard `add_column`/`create_index`) but was not
  run through `alembic upgrade` against a live PostgreSQL in this session.
- **UI page-size from height is a heuristic.** `ExecutionsPage` snaps
  `window.innerHeight` to the nearest allowed size on mount; users can still pick
  any allowed size from the pager. The backend strictly rejects other sizes.
- **Template multi-select chips colour-only.** Element Plus tag colouring inside
  the multi-select is rendered as a chip row beneath the select (badge type per
  node); offline/deleted nodes are excluded from new selection, matching the
  brief. Editing an existing template's stale selections is out of scope (create
  dialog only in this packet).
- **No node restore endpoint** (explicitly out of scope); a soft-deleted node
  stays deleted unless a future restore is added.
- **Dashboard chart** shows tasks + executions per day with a simple legend; no
  axis labels/ticks (kept intentionally light).
