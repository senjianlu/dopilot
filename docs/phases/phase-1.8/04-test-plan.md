# 04 · Phase 1.8 Test Plan

## Scope

Phase 1.8 changed shared database schema, public API contracts, dispatch
resolution, Redis command payload construction, Web routes/pages, and product
terminology. The test plan must cover:

- build artifact creation/listing/dedup;
- execution template artifact binding;
- direct build artifact run;
- schedule overrides and precedence;
- public Task/Execution API shapes;
- log endpoint public-id to seam-id mapping;
- artifact-type capability filtering;
- Redis wire `task_type` preservation;
- Web page/API client clean-cut;
- Alembic migration on PostgreSQL.

## Required Backend Tests

- Scrapy egg upload creates/reuses a `BuildArtifact`.
- Reserved artifact types are not runnable.
- Execution template create/update requires a runnable build artifact.
- Direct artifact run creates a task with ad-hoc snapshot.
- Template run creates immutable resolved snapshot.
- Schedule trigger-now and timer firing apply overrides.
- Schedule override cannot change build artifact.
- Node capability filtering excludes healthy but incapable nodes.
- Public task detail returns `executions[]`, not `attempts[]`.
- Public log endpoint returns `task_id` + atomic `execution_id` while reading
  internal log index `(execution_id=task_id, attempt_id=execution_id)`.
- Redis command payload still carries wire `task_type="scrapy"` for the current
  agent.

## Required Web Tests

- Build artifacts page lists/uploads/runs Scrapy artifacts.
- Execution template page selects a build artifact and spider.
- Execution template page shows read-only Scrapy command.
- Schedules page references execution templates and submits overrides.
- Tasks page uses backend pagination and spider filter.
- Task detail renders child executions and log viewer.
- Web build/typecheck passes.

## Required Commands

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests -q -p no:cacheprovider
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

## Migration Smoke

Run a fresh PostgreSQL migration smoke:

```bash
cd apps/server
DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:<port>/dopilot ../../.venv/bin/alembic upgrade head
DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:<port>/dopilot ../../.venv/bin/alembic current
```

Expected: `0007 (head)`.

## Optional Smoke

Run compose smoke before deployment/tagging:

```bash
scripts/smoke-phase1.sh
```
