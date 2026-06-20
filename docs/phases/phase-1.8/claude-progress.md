# Phase 1.8 — Claude progress notes

## Size class & cadence

- Size class: **90m+** (large architecture/domain clean-cut spanning models,
  migrations, services, protocol boundary, public API routes, and a full Web
  SPA vocabulary hard-cut + tests).
- Update cadence: after each bounded packet below.
- Likely long-running commands: `pytest apps/server/tests packages/protocol/tests`,
  `corepack pnpm --filter web test`, `corepack pnpm --filter web build`.

## Plan / packets

- **A. Build artifacts (backend):** `BuildArtifact` model + `build_artifacts`
  table, `services/artifacts.py` (upsert/list/reconcile), artifact API
  (`GET /artifacts`, upload creates row, `POST /artifacts/{id}/run`), migration
  0007 with template-descriptor backfill.
- **B. Discriminator + ExecutionTemplate rename:** `Task.task_type` →
  `artifact_type`; rename `TaskTemplate`→`ExecutionTemplate`, table
  `task_templates`→`execution_templates`, drop core `task_type`, add
  `build_artifact_id`; executor base/registry/scrapyd → `artifact_type` +
  capability map; protocol `ExecutionRunRequest.task_type`→`artifact_type`,
  `ExecutionRunResponse.execution_id`→`task_id`; resolver service.
- **C. Schedules overrides:** `Schedule.template_id`→`execution_template_id`,
  add `overrides` JSONB; trigger-now + timer apply overrides with precedence.
- **D. Public API/route clean-cut:** new `/tasks` routes, `TaskView`/
  `ExecutionView`/`TaskSummary`/`TasksResponse`; log endpoint task_id/
  execution_id remap (seam stays execution_id/attempt_id).
- **E. Web hard-cut:** types, api, router, pages, i18n, tests.
- **F. Tests + required commands.**

## Frozen seams (must NOT change)

- Redis/disk/agent: seam `execution_id` = parent Task.id, `attempt_id` =
  atomic Execution.id; on-disk `{execution_id}/{attempt_id}`.
- Wire `task_type` survives only in: `AgentCommand.task_type`, Redis run
  command `payload["task_type"]`. Sourced from outbox payload at the dispatcher.

## Log

- (start) Read brief, feasibility, governance, requirements, refactor/00, and
  inspected server domain (models/services/api/redis/protocol), migrations,
  test conftest, and the full web inventory. Starting packet A.
- (mid) Implemented packets A–D backend: `BuildArtifact` model + migration 0007
  with template-descriptor backfill; `services/artifacts.py`; `ExecutionTemplate`
  rename + mandatory `build_artifact_id`; `Task.artifact_type`/
  `execution_template_id` renames; protocol `artifact_type`/`task_id`; executor
  registry/capability map; `services/resolve.py` (precedence resolver);
  schedule `overrides`; new `/tasks` + `/artifacts/{id}/run` routes; public
  Task/Execution schemas; LogSnapshot seam remap.
- (web) Launched a background agent for the web SPA hard-cut (types/api/router/
  pages/i18n/tests). It completed: 23 web tests pass, build clean.
- (tests) Rewrote/repaired server + protocol tests; added `test_resolve.py` +
  capability-filter test. FINAL: 207 server + 29 protocol pass, ruff clean,
  web test (23) + build pass. Done.
