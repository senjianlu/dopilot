# 01 · Phase 1.8 — Claude implementation report

Build artifacts + execution-template/task/schedule clean-cut. A hard clean-cut:
no public/web backward-compat shapes are preserved. Redis/disk/agent seam fields
(`execution_id` = task id, `attempt_id` = execution id, wire `task_type`) are
frozen and translated at the boundary.

## Result summary

| Command | Outcome |
| --- | --- |
| `pytest apps/server/tests` | **207 passed** |
| `pytest packages/protocol/tests` | **29 passed** |
| `ruff check apps packages` | **All checks passed** |
| `corepack pnpm --filter web test` | **23 passed (8 files)** |
| `corepack pnpm --filter web build` | **built OK** (vue-tsc clean) |

(Exact commands run with `-p no:cacheprovider`; see "Commands run" below.)

## Changed files by area

### Server — models & migration
- `models/execution.py` — new `BuildArtifact` (`build_artifacts`, unique
  `(artifact_type, content_hash)`, `artifact_metadata` JSONB); `Task.task_type`
  → `artifact_type`, `Task.template_id` → `execution_template_id`; `ScrapyArtifact`
  kept as legacy registry (not renamed in place).
- `models/scheduling.py` — `TaskTemplate` → `ExecutionTemplate`
  (`execution_templates`), drops core `task_type`, adds `build_artifact_id` FK
  (nullable for legacy readability); `Schedule.template_id` →
  `execution_template_id`, adds `overrides` JSONB.
- `models/__init__.py` — export `BuildArtifact`, `ExecutionTemplate`.
- `migrations/versions/0007_build_artifacts_clean_cut.py` — **new**.
  Creates `build_artifacts`; backfills it (data-preserving) from distinct
  `task_templates.artifact` descriptors deduped on `(scrapy, sha256)`; renames
  `task_templates` → `execution_templates`, adds + backfills `build_artifact_id`
  by matching descriptor sha256 → `content_hash`, drops the superseded
  `task_type`/`artifact` columns; renames `tasks.task_type`/`template_id` and
  `schedules.template_id`; adds `schedules.overrides`. No historical task/
  execution/log/template rows are deleted; unresolved legacy templates keep a
  NULL `build_artifact_id` and stay readable.

### Server — services
- `services/states.py` — artifact-type constants, `RUNNABLE_ARTIFACT_TYPES`,
  `ARTIFACT_PACKAGE_FORMAT`, `ARTIFACT_CAPABILITY` map, new task sources
  (`direct_artifact`, `template`; legacy `manual` kept).
- `services/artifacts.py` — **new**: Scrapy egg → `BuildArtifact` upsert (dedup
  on `(scrapy, sha256)`), runtime reconcile of the on-disk store, runnable
  lookup, snapshot/view builders.
- `services/resolve.py` — **new**: single run resolver with precedence
  `override > template default > build artifact default`; `sanitize_overrides`
  rejects any `build_artifact_id` override.
- `services/templates.py` — `ExecutionTemplate` CRUD; create/update REQUIRE a
  runnable build artifact; `project`/`version` derived from the artifact;
  `build_run_request` resolves via `resolve_run`.
- `services/dispatch.py` — `dispatch_resolved` + `run_direct_artifact` +
  `run_execution_template`; one executor path for all run sources.
- `services/schedules.py` — `execution_template_id`, stores/round-trips
  `overrides`; trigger-now + timer apply overrides through the resolver.
- `services/executions.py` — `TaskOrigin.execution_template_id`;
  `create_task` writes `artifact_type`; public view builders emit
  `TaskView`/`ExecutionView` (`task_id` back-ref, `executions[]`,
  `build_artifact`); error codes → `task.not_found` /
  `task.execution_not_found`.
- `executors/base.py`,`registry.py`,`scrapyd.py` — `artifact_type` discriminator;
  capability-aware node selection via `ARTIFACT_CAPABILITY`;
  `DispatchUnknownError.task_id`.

### Server — API
- `api/v1/tasks.py` — **new** (replaces `executions.py`): `/tasks` list/detail/
  cancel + `/tasks/{id}/logs` snapshot/stream/stream-token; public
  `task_id`/`execution_id`, internal seam mapping. No generic `/executions/run`.
- `api/v1/artifacts.py` — `GET /artifacts` (DB + reconcile), upload creates/
  reuses the build artifact, `POST /artifacts/{id}/run` (direct ad-hoc run).
- `api/v1/templates.py`,`schedules.py`,`router.py`,`schemas.py` — new
  vocabulary/shapes (`BuildArtifactView`, `TaskView`/`ExecutionView`/
  `TaskSummary`/`TasksResponse`, `ExecutionTemplate*`, `RunOverrides`
  (`extra="forbid"` → 422 on `build_artifact_id`), `ArtifactRunRequest`,
  `TaskRunResponse`, `LogSnapshot{task_id,execution_id}`).

### Protocol
- `dopilot_protocol/execution.py` — `ExecutionRunRequest.task_type` →
  `artifact_type`; `ExecutionRunResponse.execution_id` → `task_id`. Wire
  `task_type` still set in the Redis command payload (`scrapyd` executor) and
  carried on `AgentCommand`/`dispatcher._build_command` — unchanged.

### Web (background agent, verified locally)
- `api/types.ts`, `api/artifacts.ts`, `api/tasks.ts` (new, replaces
  `executions.ts`), `api/templates.ts`, `api/schedules.ts`.
- `router/index.ts`, `layouts/MainLayout.vue`.
- New pages `BuildArtifactsPage.vue` / `TasksPage.vue` / `TaskDetailPage.vue`
  (replace Crawlers/Executions/ExecutionDetail); `TemplatesPage.vue`
  (build-artifact + spider select, read-only Scrapy command), `SchedulesPage.vue`
  (execution-template + override controls); `components/LogViewer.vue`.
- `i18n/locales/en.ts`,`zh.ts` (artifacts/tasks/task namespaces, attempts→
  executions, new error keys).

### Tests
- New: `apps/server/tests/test_resolve.py` (precedence, override-forbid,
  capability map). Rewrote `test_executions.py` (now `/tasks` + artifact run,
  `executions[]`, capability-filter no_target, seam→public id remap),
  `test_executions_pagination.py`, `test_templates.py`, `test_schedules.py`
  (+overrides + cannot-override-artifact), `test_artifacts.py` (build-artifact
  upload/dedup), `test_sse.py` (URL rename). Constructor renames in
  `test_outbox/dispatcher/event_consumer/reconcile_redis/log_consumer/
  stats_nextrun/scheduler_runner.py`; `conftest.py` (`Seeder.build_artifact`,
  import from `api.v1.tasks`). Protocol `test_schemas.py` updated for renamed
  fields. Web specs rewritten by the web agent.

## Implementation notes

- **Discriminator**: core domain uses `artifact_type` everywhere; the only
  surviving wire `task_type` is in the Redis run-command payload
  (`scrapyd` executor sets `payload["task_type"]="scrapy"`) and on `AgentCommand`
  (dispatcher reads it from the outbox payload) — the agent protocol is
  untouched. Verified by `test_run_dispatches_command_execution_queued`.
- **Resolved snapshot** lives in `Task.template_snapshot` (`build_artifact`,
  resolved params, node strategy/ids, applied `overrides`); `Task.artifact_type`
  is the queryable resolved type; `Task.spider` remains the only query-critical
  hot column. No per-execution artifact snapshot column added.
- **Direct artifact run** = resolver with empty template defaults +
  `source=direct_artifact`; no `ExecutionTemplate` is persisted.
- **Capability filter**: `resolve_target_nodes(capability=ARTIFACT_CAPABILITY[
  artifact_type])`; a healthy node lacking the resolved capability is excluded
  (→ `no_target`). Verified by
  `test_run_excludes_node_without_resolved_capability`.
- **Schedule overrides** can’t touch the build artifact: `RunOverrides`
  (`extra="forbid"`) yields 422 at the API, and `sanitize_overrides` raises
  `schedule.artifact_override_forbidden` at the service layer.
- **Reserved types** (`python_wheel`/`docker_image`) are valid type values but
  not runnable — `get_runnable_artifact_or_404` → 400 `artifact.not_runnable`,
  and they’re unregistered in the executor registry.

## Commands run (exact)

```
.venv/bin/pytest apps/server/tests -q -p no:cacheprovider          # 207 passed
.venv/bin/pytest packages/protocol/tests -q -p no:cacheprovider    # 29 passed
.venv/bin/ruff check apps packages                                 # All checks passed
corepack pnpm --filter web test                                    # 23 passed (8 files)
corepack pnpm --filter web build                                   # built OK
```

## Known risks / shortcuts / not done

- **Migration not executed against PostgreSQL** in this run (the test DB is
  SQLite built from the ORM via `create_all`, per the repo convention). The
  0007 migration is syntactically lint-clean and mirrors 0005/0006 patterns, but
  its SQL backfill/rename path has NOT been run on a live Postgres here. Suggest
  a Codex/CI `alembic upgrade head` + downgrade smoke before acceptance.
- **`scripts/smoke-phase1.sh` (compose smoke) not run** — requires Docker, not
  available in this environment. Dispatch mechanics are covered by the
  integration tests over fakeredis (run command emitted, wire `task_type`
  preserved, capability filter, cancel/stop, no_target, 503/202 paths).
- **Legacy `manual` task source** is kept in `TASK_SOURCES` for pre-1.8 rows;
  new code only emits `direct_artifact` / `template` / `schedule_*`.
- **Runtime reconcile-on-list** for build artifacts writes missing rows on `GET
  /artifacts` (so on-disk eggs predating the table surface). Bounded and
  idempotent, but it is a write on a GET; acceptable for single-admin.
- **`docs/dopilot` not edited** — the product-model docs (`00-requirements.md`,
  roadmap) still describe the pre-1.8 vocabulary; updating them is a Codex
  decision. Flagging per the governance "write decisions back to docs" rule.
- Web build emits the pre-existing >500 kB chunk-size advisory (unrelated to
  this change).
