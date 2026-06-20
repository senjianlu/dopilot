# 00 · Phase 1.8 brief（Build artifacts + execution templates clean-cut）

## Goal

Clean up the Phase 1 scheduling/execution domain before Phase 2.0 adds Python3
script execution with `subprocess` + `.whl` build artifacts.

Phase 1.8 should make the public product model explicit:

- `BuildArtifact`: executable artifact, not the build process.
- `ExecutionTemplate`: reusable run definition bound to one build artifact.
- `Schedule`: timer definition that references one execution template.
- `Task`: one parent run created by direct artifact run, template run, schedule
  trigger-now, or schedule timer.
- `Execution`: one atomic per-node execution under a task.

This is a hard clean-cut. Do not preserve public/web historical names where a
parent task was called an execution and an atomic execution was called an
attempt.

## Architecture Constraints

- Keep the Phase 1.5 Redis Streams architecture:
  - server dispatches commands through Redis command streams;
  - agents publish events/logs;
  - heartbeat remains agent-initiated;
  - no server-to-agent HTTP run/status/tail path.
- Keep Redis/disk/agent seam fields frozen:
  - seam `execution_id` still means parent `Task.id`;
  - seam `attempt_id` still means atomic `Execution.id`;
  - on-disk log paths keep `{execution_id}/{attempt_id}`.
- Add `task_type` to the frozen wire list:
  - keep `task_type` only in protocol/Redis command payloads where the current
    agent expects it;
  - core server domain should use a clearer discriminator, preferably
    `artifact_type`;
  - translate to wire `task_type` at boundary code.
- Do not implement Python wheel runtime or Docker image runtime in Phase 1.8.
  Reserve types only.
- Do not copy, import, restructure, or edit `reference/scrapydweb/`.
- PostgreSQL remains the business source of truth. Agent and Web do not connect
  to PostgreSQL.

## Product Decisions

- Build artifacts are real DB entities.
- Execution templates must bind exactly one build artifact.
- Direct build artifact run is allowed and creates a task from an ad-hoc
  execution-template snapshot without persisting a template.
- Schedule overrides are in scope:
  - schedules may override execution parameters, node strategy, and selected
    nodes;
  - schedules must not override the build artifact.
- Resolved snapshot precedence:

```text
schedule override > execution template default > build artifact default
```

- Product goal is that the standard agent eventually becomes all-capable, but
  the model and dispatch service must still filter by capability:

```text
healthy + schedulable + not deleted + supports resolved artifact type
```

## In Scope

### Build Artifacts

- Add canonical `BuildArtifact` model/table.
- Suggested minimum fields:
  - `id` opaque 32-char id;
  - `artifact_type`: `scrapy`, reserved `python_wheel`, reserved
    `docker_image`;
  - `package_format`: `egg` for Scrapy, reserved `wheel` / `image`;
  - `name` or `filename`;
  - `content_hash` for file artifacts, currently Scrapy egg sha256;
  - `size_bytes`;
  - `metadata` JSONB for type-specific data such as Scrapy `project`,
    `version`, `spiders`, and `fetch_path`;
  - timestamps.
- For Phase 1.8, only `artifact_type="scrapy"` and `package_format="egg"` are
  runnable.
- Use `(artifact_type, content_hash)` as the Scrapy dedup key when content hash
  exists.
- Do not rename the existing `scrapy_artifacts` table in place. Treat it as a
  legacy deployment/cache table unless implementation proves it can be safely
  removed. The canonical product entity is `build_artifacts`.
- Generalize artifact API and UI labels from Crawler/Scrapy Artifact to Build
  Artifact while preserving the Scrapy egg upload workflow.
- Scrapy upload should create or return the matching `BuildArtifact` row after
  the filesystem manifest is written.

### Execution Templates

- Rename `TaskTemplate` to `ExecutionTemplate` in model/service/API/Web.
- Rename table `task_templates` to `execution_templates` with data-preserving
  Alembic migration where practical.
- Execution templates must store `build_artifact_id` and validate that the
  artifact exists and is runnable in Phase 1.8.
- New or updated execution templates must require a build artifact. For legacy
  rows with unresolvable artifact JSON during migration, prefer nullable
  backfill plus application validation over destructive deletion; report any
  unresolved rows in migration comments/tests.
- Remove core-domain `task_type` from templates if possible. Derive the runnable
  discriminator from the bound build artifact.
- Keep Scrapy-specific defaults (`project`, `version`, `spider`, `settings`,
  `args`) in type-specific fields or payloads as appropriate, but do not expose
  "project" as an editable product field in the Web UI.
- Web must show the Scrapy command/entrypoint as disabled/read-only. Users may
  edit parameters only.

### Tasks And Executions

- Public API/Web clean-cut:
  - parent run schema names should be `TaskView`, `TaskSummary`,
    `TasksResponse`;
  - atomic per-node schema names should be `ExecutionView`;
  - public fields should use `task_id` for the parent and `execution_id` for
    the atomic execution where both are needed;
  - public arrays should use `executions`, not `attempts`.
- Route clean-cut:
  - prefer `/api/v1/tasks` for parent run list/detail/log views;
  - keep or add redirects only if they are extremely low-risk, but do not emit
    dual public response shapes.
- Task rows should carry the resolved artifact type or artifact snapshot needed
  for filtering and history. If the existing `params` and `template_snapshot`
  can hold the resolved snapshot cleanly, avoid adding redundant hot-table
  columns except for query-critical fields such as `spider`.
- Each task must have a resolved build artifact snapshot copied at creation
  time.
- Each atomic execution must be traceable to the resolved build artifact through
  its parent task snapshot. Do not add per-execution artifact snapshot columns
  unless implementation needs per-node variance.

### Direct Build Artifact Run

- Direct artifact run creates a `Task` through the same dispatch path as
  template/schedule runs.
- It must synthesize an ad-hoc execution-template snapshot without persisting an
  `ExecutionTemplate`.
- The resulting task source should clearly distinguish direct artifact runs
  from execution-template runs and schedule runs.

### Schedules

- Rename schedule FK from template vocabulary to execution-template vocabulary
  in model/API/Web.
- Add schedule override storage. A JSONB `overrides` payload is acceptable if it
  keeps the first implementation bounded; discrete columns are also acceptable
  if they match existing patterns better.
- Overrides may include:
  - execution settings/args/params;
  - `node_strategy`;
  - `node_ids`.
- Overrides may not include `build_artifact_id`.
- `trigger_now` and timer firing must use the same resolution path.
- The resolved snapshot frozen into the task must reflect schedule overrides.

### Node Capability Filtering

- Add or formalize artifact-type to node-capability mapping:
  - `scrapy` -> `scrapy`;
  - reserved `python_wheel` -> `python_wheel`;
  - reserved `docker_image` -> `docker_runtime`.
- Selection functions must receive/use the resolved artifact type instead of
  hardcoding `scrapy`.
- Phase 1.8 UI may keep capability display minimal, but no backend dispatch
  path should ignore capability.

### Web UI

- Rename pages/navigation/copy from crawlers/task templates/executions/attempts
  to build artifacts/execution templates/tasks/executions.
- Build artifact upload remains Scrapy egg upload in Phase 1.8, but the product
  surface should make the broader concept clear.
- Execution template creation selects a build artifact, then selects Scrapy
  spider from that artifact metadata.
- Scrapy command display is disabled/read-only; users configure args/settings.
- Schedules reference execution templates and expose override controls for
  params and node selection.

## Out Of Scope

- Python `.whl` upload, validation, venv creation, subprocess execution, or log
  capture.
- Docker image upload/pull/run or Docker/K3s lifecycle management.
- Multi-user/RBAC.
- Distributed scheduler locks or multi-server HA.
- Reintroducing server-to-agent HTTP run/status/tail.
- Hard deletion of historical task/execution/build artifact rows.
- Copying/importing/editing `reference/scrapydweb/`.

## Expected Files / Modules

- Server models and migrations:
  - `apps/server/dopilot_server/models/execution.py`
  - `apps/server/dopilot_server/models/scheduling.py`
  - `apps/server/dopilot_server/models/__init__.py`
  - new/updated Alembic migration under
    `apps/server/migrations/versions/`
- Server artifact/template/schedule/task APIs:
  - `apps/server/dopilot_server/api/v1/artifacts.py`
  - `apps/server/dopilot_server/api/v1/templates.py`
  - `apps/server/dopilot_server/api/v1/schedules.py`
  - `apps/server/dopilot_server/api/v1/executions.py` or new `tasks.py`
  - `apps/server/dopilot_server/api/v1/router.py`
  - `apps/server/dopilot_server/api/v1/schemas.py`
- Server services:
  - `apps/server/dopilot_server/artifacts/scrapy_store.py`
  - `apps/server/dopilot_server/services/templates.py`
  - `apps/server/dopilot_server/services/schedules.py`
  - `apps/server/dopilot_server/services/dispatch.py`
  - `apps/server/dopilot_server/services/executions.py`
  - `apps/server/dopilot_server/nodes/service.py`
  - `apps/server/dopilot_server/redis/dispatcher.py`
- Protocol package only where boundary translation requires it:
  - `packages/protocol/dopilot_protocol/*`
- Web:
  - `apps/web/src/api/types.ts`
  - `apps/web/src/api/*.ts`
  - `apps/web/src/router/*`
  - relevant pages currently named around crawlers/templates/schedules/
    executions
  - i18n locale files
- Tests:
  - focused server migration/service/API tests;
  - focused web tests for renamed pages and API payloads.

## Required Implementation Order

1. Add `BuildArtifact` entity and migration/backfill.
2. Wire Scrapy egg upload/listing to canonical build artifacts.
3. Rename task templates to execution templates and add mandatory
   `build_artifact_id` validation for new/updated rows.
4. Clean internal discriminator naming, keeping wire `task_type` translated at
   the Redis/protocol boundary.
5. Implement task creation from resolved artifact/template snapshot, including
   direct ad-hoc artifact runs.
6. Implement schedule override storage and resolution in both trigger-now and
   timer firing.
7. Replace public API schema/route vocabulary with Task/Execution names and
   remap log endpoint fields/params carefully.
8. Update Web API types, routes, pages, copy, and tests to the clean-cut public
   contract.
9. Add capability filtering by resolved artifact type across all dispatch paths.
10. Run focused backend tests first, then Web tests/build.

## Acceptance Criteria

- Uploading a Scrapy egg creates or reuses a `BuildArtifact` row with
  `artifact_type="scrapy"` and `package_format="egg"`.
- A build artifact can be listed and directly run, creating a task with an
  ad-hoc snapshot and one execution per selected healthy capable node.
- Execution templates cannot be created or updated without a valid build
  artifact.
- Running an execution template creates a task whose resolved snapshot contains
  the build artifact, params, node strategy, and selected nodes.
- A schedule references an execution template and cannot override its build
  artifact.
- Schedule trigger-now and timer firing both apply overrides with precedence:
  schedule override > execution template default > build artifact default.
- Public API/Web use Task for parent runs and Execution for per-node units; no
  public `attempts[]` array remains.
- Public log APIs use public `task_id`/`execution_id` semantics while
  Redis/disk/log-index internals still use seam `execution_id`/`attempt_id`.
- Core server domain does not keep misleading `task_type` as a domain concept;
  wire `task_type` remains only where needed for existing agent protocol.
- Dispatch target selection filters by resolved artifact capability.
- Existing Scrapy execution through Redis Streams still works.
- Python wheel and Docker image types are reserved but not executable.

## Required Tests

- Server unit/integration tests:
  - Scrapy upload creates/reuses build artifact by `(artifact_type,
    content_hash)`;
  - execution template create/update requires build artifact;
  - direct build artifact run creates an ad-hoc task snapshot;
  - execution-template run snapshots artifact and params immutably;
  - schedule overrides merge with the correct precedence for params/node
    strategy/node ids;
  - schedule cannot override build artifact;
  - capability filtering excludes healthy nodes that lack the resolved
    artifact capability;
  - public task detail returns `executions[]` with public `task_id` /
    `execution_id` semantics;
  - log endpoint remaps public IDs to seam IDs correctly;
  - Redis dispatcher still emits wire `task_type` for the existing agent.
- Migration tests or focused migration validation where practical:
  - backfill build artifacts from existing Scrapy artifact descriptors;
  - preserve existing tasks/executions/log rows.
- Web tests:
  - build artifact page lists/uploads Scrapy egg artifacts;
  - execution template page selects a build artifact and shows read-only Scrapy
    command;
  - schedules page references execution templates and submits overrides;
  - task list/detail renders parent tasks and child executions;
  - API client uses `/tasks` and clean-cut response types.

## Required Commands

```bash
pytest apps/server/tests packages/protocol/tests
ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Run compose smoke if the implementation touches runtime dispatch enough that
unit/integration tests are insufficient:

```bash
scripts/smoke-phase1.sh
```

## Risks To Watch

- The public `execution_id` meaning changes in this phase, but seam
  `execution_id` remains parent task id. Log APIs and serializers need explicit
  boundary mapping.
- `task_type` must not survive as a misleading core-domain field after the
  cleanup. If a temporary compatibility field is unavoidable, isolate and
  document it.
- Data backfill from legacy JSON artifact descriptors may find incomplete rows.
  Do not delete user data silently.
- C+D API/Web clean-cut must ship atomically because no public compatibility
  layer is required.
- This phase is larger than a pure rename; implementation should be split into
  bounded packets if needed, but final acceptance requires the whole public
  model to be coherent.
