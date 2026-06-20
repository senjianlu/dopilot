# 04 · Phase 1.7.1 test plan

## Scope

Phase 1.7.1 changes backend schema/API/service behavior and multiple web pages.
The test plan therefore covers:

- node offline/online/soft-delete state;
- dispatch target filtering for offline/deleted nodes;
- execution pagination and spider filtering;
- dashboard daily stats aggregation;
- schedule next-run metadata and preview;
- template artifact/spider and involved-node UI behavior;
- nodes, dashboard, schedules, and executions page rendering.

## Server Tests

Run:

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests
```

Required focused coverage:

- offline nodes are excluded from target selection;
- online restores target eligibility;
- soft-deleted nodes are excluded from selection but remain listable;
- heartbeat does not clear offline/delete state;
- selected templates with all unschedulable selected nodes create `no_target`;
- execution list validates page/page_size and returns total/page metadata;
- execution list filters by spider and exposes known spider values;
- child execution counts are aggregated for the current page;
- daily stats returns zero-filled 30-day buckets;
- daily stats uses database-side `GROUP BY`;
- schedule responses include `next_run_at`;
- schedule preview endpoint returns next-run estimates.

## Web Tests

Run:

```bash
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Required focused coverage:

- Nodes page refresh re-lists nodes instead of calling `/nodes/refresh`;
- node offline/online/delete actions call the right API functions;
- node badge precedence renders healthy/offline/deleted states;
- Templates page removes the Project column/input;
- Templates page submits artifact-derived project/version/spider payload;
- Templates page involved-node selector excludes offline/deleted/unseen nodes;
- Schedules page renders trigger time and next-run metadata;
- Schedules page computes/shows create-dialog next-run estimate;
- Executions page sends backend pagination and spider filter params;
- Dashboard renders service-health rows and the daily bar chart.

## Static / Migration Checks

Run:

```bash
.venv/bin/ruff check apps packages
git diff --check
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot ../../.venv/bin/alembic -c alembic.ini upgrade head --sql
```

The offline Alembic SQL must include the `0006` migration and the PostgreSQL
`tasks.spider` backfill before creating `ix_tasks_spider`.

## Out Of Scope Verification

`scripts/smoke-phase1.sh` is not required unless review finds changes to the
Redis/agent dispatch path. Phase 1.7.1 adds API/UI/schema support and leaves the
Redis command/event/log seam unchanged.
