# Phase 2a Implementation Report: ID Naming Clean-Cut

> Claude implementation of the id-naming clean-cut per `00-brief.md`. Renames the
> Redis-wire / on-disk / DB seam from `execution_id`/`attempt_id` to
> `task_id`/`execution_id` so the wire, disk paths, DB index tables, and agent
> state all use the same names as the server domain (`Task.id` / `Execution.id`).
> The public HTTP/web surface is unchanged. This was a name-collision **swap**
> done per-file by local meaning — no tree-wide substitution.

## Result

```text
new seam:
  task_id      = Task.id
  execution_id = Execution.id   (was attempt_id)
```

All required commands pass (see Commands Run). No Scrapy behavior changed; the
seam-translation boundary in the server collapsed (mapping comments removed).

## Changed Files By Area

### Protocol (`packages/protocol/dopilot_protocol/`)

- `streams.py` — `AgentCommand`, `AgentEvent`, `AgentLogEvent`:
  `execution_id`->`task_id`, `attempt_id`->`execution_id`. Rewrote the obsolete
  "seam deliberately NOT renamed" module/class docstrings.
- `agent.py` — renamed seam fields on the **kept** schemas `AgentRunRequest`,
  `AgentRunResponse`, `AgentStopResponse`, `AgentStatusResponse`. **Deleted**
  dead `AgentStopRequest` and `CleanupResponse`. Updated module docstring.
- `logs.py` — **deleted** dead `TailRequest` / `TailResponse`; kept `LogStream`.
- `__init__.py` — dropped deleted symbols from imports + `__all__`.

### Server models + migration (`apps/server/`)

- `models/execution.py` — `ExecutionLogFile` columns
  `execution_id`->`task_id`, `attempt_id`->`execution_id`; PK is now
  `(task_id, execution_id, stream)`. Rewrote module + `Execution` +
  `ExecutionLogFile` seam docstrings.
- `models/command_outbox.py` — columns `execution_id`->`task_id`,
  `attempt_id`->`execution_id`; updated docstring.
- `models/event_audit.py` — column `attempt_id`->`execution_id`.
- `migrations/versions/0009_id_naming_clean_cut.py` — **new** (down_revision
  `0008`). Data-preserving `RENAME COLUMN` + index renames on
  `execution_log_files`, `command_outbox`, `event_audit`, mirroring 0004's style.
  Each two-column swap renames old `execution_id`->`task_id` first, then old
  `attempt_id`->`execution_id`, to avoid a name collision. Old migrations
  `0002`/`0003`/`0004` were **not** edited.

### Server services / redis / executors / logs (`apps/server/dopilot_server/`)

- `services/executions.py` — `create_log_file` writes `task_id`/`execution_id`;
  `get_log_file(session, task_id, execution_id, stream)` (positional callers
  already passed task then exec id, so unchanged at call sites). Rewrote module
  docstring, `resolve_execution` docstring, and the view-builder seam comment.
  **Left untouched** the public/domain `get_execution(execution_id)` and
  `resolve_execution(task_id, execution_id)` (already `Execution.id`).
- `services/outbox.py` — `create_run_outbox` / `create_stop_outbox` /
  `create_cleanup_outbox` params `task_id`/`execution_id`;
  `cancel_unsent_outbox(session, task_id)`;
  `has_undispatched_backlog_for_schedule` joins on `CommandOutbox.task_id`.
- `services/cancel.py` — `create_stop_outbox(task_id=..., execution_id=...)`.
- `services/events.py` — `apply_event` reads `event.execution_id`;
  `EventAudit(execution_id=...)`; `_has_unresolved_reclaim(execution_id)`;
  `_request_reclaim` builds stop with `task_id`/`execution_id`. Rewrote module
  docstring.
- `services/logs.py` — `get_log_file(session, event.task_id, event.execution_id,
  ...)`; SSE `manager.publish(event.task_id, ...)` (subscribers key on `task_id`).
- `services/maintenance.py` — log-index / command-outbox cleanup filters on
  `task_id`; rewrote module docstring + comments.
- `services/states.py` — rewrote the obsolete `attempt_id` seam note in the
  module docstring.
- `redis/dispatcher.py` — `_build_command` emits `task_id`/`execution_id`; run
  short-circuit uses `row.task_id`; dispatch-timeout uses
  `get_execution(row.execution_id)` + `get_task(row.task_id)`.
- `redis/reconcile.py` — log lookup / cleanup / reclaim use `task_id`/
  `execution_id`; `_reclaim_issued(execution_id)`; `finalize_drained_logs` joins
  `Execution.id == ExecutionLogFile.execution_id`; renamed internal
  `ReconcileReport.lost_attempt_ids` -> `lost_execution_ids`.
- `executors/scrapyd.py` — `create_run_outbox(task_id=..., execution_id=...)`;
  rewrote docstring + comment.
- `logs/files.py` — `log_path(root_dir, when, task_id, execution_id, stream)`;
  on-disk layout `{root}/YYYY/MM/{task_id}/{execution_id}.log`; updated
  docstrings.
- `api/v1/tasks.py`, `api/v1/schemas.py` — removed obsolete seam-mapping
  comments/docstrings only. **No public field, query param, or JSON change.**

### Agent (`apps/agent/dopilot_agent/`)

- `state/store.py` — `AttemptState` fields `execution_id`->`task_id`,
  `attempt_id`->`execution_id`; every method keyed by the atomic id now takes
  `execution_id`; `create_reserved(task_id=, execution_id=)`;
  `list_attempt_ids` -> `list_execution_ids`; state file is `{execution_id}.json`.
  (Class name `AttemptState` kept — see Decisions.)
- `state/__init__.py` — updated docstring (state file `{execution_id}.json`).
- `runners/scrapyd.py` — `run`/`stop`/`status` use `task_id`/`execution_id`;
  `stop(execution_id, task_id)` / `status(execution_id, task_id)` (positional
  order = atomic, task — preserved so callers are positionally compatible).
- `redis/commands.py` — consume `cmd.task_id`/`cmd.execution_id`; per-execution
  lock; all store/event/runner calls rekeyed; updated docstring/comments.
- `redis/events.py` — `emit_accepted`/`emit_running`/`emit_terminal`/
  `republish_current`/`_event` use `(task_id, execution_id)`.
- `redis/logs.py` — cursor file `{execution_id}.logpos`; `AgentLogEvent` uses
  `task_id`/`execution_id`; `publish_attempt(execution_id)`;
  `list_execution_ids`.
- `redis/heartbeat.py` — `list_execution_ids`.
- `artifacts/cache.py` — `ensure(execution_id=...)`, `_tmp_path(sha256,
  execution_id)`, `_fetch_verify_deploy(execution_id=...)` (tmp-suffix only).

### Tests

- Protocol: `test_stream_schemas.py`, `test_agent_schemas.py` (removed deleted-
  schema cases), `test_schemas.py` (removed `TailRequest`/`TailResponse` cases).
- Agent: `conftest.py`, `test_state_store.py`, `test_state_cas.py`,
  `test_command_consumer.py`, `test_runner.py`, `test_event_outbox.py`,
  `test_log_publisher.py`, `test_heartbeat_worker.py`.
- Server: `test_outbox.py`, `test_dispatcher.py`, `test_log_consumer.py`,
  `test_event_consumer.py`, `test_reconcile_redis.py`, `test_redis_fake.py`,
  `test_executions.py` (only the seam `AgentEvent`; public assertions intact),
  `test_maintenance.py`, `test_schedules.py`, `test_scheduler_runner.py`.
- `test_sse.py` was **not** edited (public log-streaming contract) — it passes
  unchanged, proving zero public drift.
- Renamed test names that embedded the `attempt_id` substring:
  `test_list_attempt_ids`->`test_list_execution_ids`,
  `test_duplicate_attempt_id_does_not_restart`->`..._execution_id...`,
  `test_stop_unknown_attempt_idempotent`->`..._execution_idempotent`.

## Implementation Notes

- **Collision discipline.** `execution_id` already meant `Execution.id` in the
  public/domain layer. Every edit was made by local meaning, never by token
  substitution. Per-file replace-all was used only where every occurrence in
  that file was confirmed seam.
- **Positional-call compatibility.** Where a helper's parameter *order* already
  matched the new naming (e.g. `get_log_file` called as `(session, task_id,
  exec_id)`; runner `stop`/`status` called positionally as `(atomic, task)`),
  only the signature names were updated so call sites needed no change.
- **SSE key.** `logs/sse.py` is keyed by the parent (`task_id`); the log
  consumer now publishes with `event.task_id`. `sse.py` / `stream_token.py` were
  left untouched per the brief (public contracts).
- **Migration shape.** 0009 uses `op.execute("ALTER TABLE ... RENAME COLUMN")`
  plus `drop_index`/`create_index` (same portable pattern as 0004). The PK on
  `execution_log_files` tracks the renamed columns automatically (verified in PG).

## Deleted Legacy Schemas/Methods + Reference-Scan Evidence

Fresh `rg` over `apps/`+`packages/` (excluding `reference/`) before deletion:

- `AgentStopRequest` — referenced only by its own def, `agent.py` docstring,
  `__init__.py`, and `tests/test_agent_schemas.py`. **Deleted.**
- `CleanupResponse` — referenced only by its own def, docstring, `__init__.py`,
  and `tests/test_agent_schemas.py`. (`TerminalCleanupResponse` in
  `api/v1/schemas.py` is unrelated and untouched.) **Deleted.**
- `TailRequest` / `TailResponse` — referenced only by `logs.py`, `__init__.py`,
  and `tests/test_schemas.py`. **Deleted.**

**Kept (live), renamed seam fields only:** `AgentRunRequest`,
`AgentRunResponse`, `AgentStopResponse`, `AgentStatusResponse`. The brief allowed
deleting `AgentRunResponse` + `ScrapydRunner.run()` *only if* no live caller
exists. `ScrapydRunner.run()` has no non-test caller (the run path uses
`schedule()` in `redis/commands.py`), but it **is** exercised by
`apps/agent/tests/test_runner.py` (10 calls). Per the feasibility review's
recommended option (a), I kept-and-renamed both to keep 2a a pure rename and
preserve the regression coverage; dead-method pruning is deferred to 2b.

**Left untouched (live, no seam fields):** `AttemptStatus`, `EggDeployResponse`,
`LogStream`.

## Tests Added / Updated

No net-new test files. All protocol/server/agent suites were updated in lockstep
to the new names; deleted-schema test cases were removed. The kept schemas keep
their round-trip tests (renamed fields). `test_sse.py` deliberately unchanged.

## Commands Run (pass/fail)

| Command | Result |
|---|---|
| `ruff check apps packages` | **pass** — "All checks passed!" |
| `pytest packages/protocol/tests` (`-q -p no:cacheprovider`) | **pass** — 65 passed |
| `pytest apps/agent/tests` (`-q -p no:cacheprovider`) | **pass** — 83 passed |
| `pytest apps/server/tests` (`-q -p no:cacheprovider`) | **pass** — 231 passed |
| `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` (from `apps/server`, against compose `db`) | **pass** — 0008<->0009 both directions |
| `rg -n 'attempt_id' apps packages` | **expected** — matches only in migrations (see below) |
| `docker compose config` (from `deploy/docker`) | **pass** — valid resolved config |

Notes:

- The pre-approved pytest form in `.claude/settings.local.json` includes
  `-p no:cacheprovider`; that exact form was used.
- The migration round-trip ran against the compose `db` service (postgres:16).
  Its named volume `dopilot-db` was already at revision `0008` from prior work,
  so the round-trip exercised `0009` against **real existing tables** (a stronger
  check than an empty DB). Post-run PG verification:
  - `execution_log_files(task_id, execution_id)` + PK `(task_id, execution_id,
    stream)`;
  - `command_outbox(task_id, execution_id)` + indexes
    `ix_command_outbox_task_id`, `ix_command_outbox_execution_id`;
  - `event_audit(execution_id)` + `ix_event_audit_execution_id`;
  - no `attempt_id` column remains on any of the three tables.
  The db container was stopped afterward (volume left intact — non-destructive).

## Residual `attempt_id` (justified)

`rg -n 'attempt_id' apps packages` matches **only** migration files:

- `migrations/versions/0009_id_naming_clean_cut.py` — intentional: it performs
  the rename and names both the old (`attempt_id`) and new columns in its DDL,
  docstring, and downgrade.
- `migrations/versions/0002_executions.py`, `0003_redis_streams.py`,
  `0004_task_execution_rename.py` — historical DDL/comments describing the
  schema as it existed at those revisions; these must not be edited (brief).

No `attempt_id` remains in any non-migration source or test.

## Decisions / Known Risks / Incomplete Items

- **Decision — `AttemptState` class name kept.** The brief required renaming the
  state *fields*, file path, and id-keyed methods, not the class. Renaming the
  class is an optional, wider ripple (imports + tests) the feasibility review
  flagged as out-of-scope, so it was left as `AttemptState`. Its id fields are
  now `task_id`/`execution_id`.
- **Decision — `run()`/`AgentRunResponse` kept** (option a; see above).
- **Risk (accepted by the brief): lockstep wire.** Protocol + server + agent must
  ship as one version; an old agent against a new server silently None-fills the
  renamed fields. This is the brief's accepted clean-cut cutover gate.
- **Risk (accepted): in-flight orphans.** A running attempt's old-named on-disk
  `{old}.json` / `{old}/{old}.log` are not found post-cutover; mitigated by the
  quiesce-before-upgrade + Redis-flush precondition and the agent TTL sweep. No
  compat shim added (by design).
- **No incomplete items.** All required tests, the migration round-trip, and the
  static/config checks ran and passed. Public HTTP/web behavior is unchanged
  (`test_sse.py` unedited and green; `test_executions.py` public assertions
  intact).
