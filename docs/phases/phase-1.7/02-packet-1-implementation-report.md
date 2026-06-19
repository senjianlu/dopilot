# 02 · Phase 1.7 Packet 1 — implementation report

Scope delivered: canonical task/execution domain rename with a stable
Redis/disk/agent seam, plus the terminal `no_target` task status and its
`status_reason` / `status_detail` columns. Per
`docs/phases/phase-1.7/00-brief.md` and `00a-feasibility-review.md`.

## 1. Scope decision (two stable seams)

The internal server domain was fully renamed; **two** boundaries were held
stable so the packet stays bounded and behavior-preserving:

- **Seam 1 — Redis/disk/agent wire (mandated by brief / feasibility B1).**
  Unchanged. On the wire, in the on-disk log path, and in the seam tables
  (`command_outbox`, `event_audit`, `execution_log_files`), `execution_id` still
  means the **parent task id** and `attempt_id` the **atomic execution id**. No
  agent code touched.
- **Seam 2 — public HTTP/web contract (kept stable this packet).** The routes
  stay `/api/v1/executions/*`; the JSON shapes keep `attempts[]`,
  `execution_id`, `attempt_id`. The brief sequences the public/web clean-cut as
  step 7 (a later packet), and the packet text says to touch Web types "only as
  needed for packet 1 naming." So the public surface is treated as a documented
  seam (web `execution`=task, `attempt`=atomic execution); only additive,
  non-breaking web changes were made (`no_target` status + optional
  `status_reason`/`status_detail`).

The mapping `Task.id → wire/web execution_id` and `Execution.id → wire/web
attempt_id` is applied by boundary code in the services/executors and is
commented at each call site.

## 2. Changed files by area

### Domain model + migration
- `apps/server/dopilot_server/models/execution.py`
  - `Execution` → **`Task`** (`__tablename__="tasks"`); added `status_reason`
    (nullable) and `status_detail` (JSONB, default `{}`).
  - `ExecutionAttempt` → **`Execution`** (`__tablename__="executions"`); FK
    column `execution_id` → **`task_id`** (`ForeignKey("tasks.id")`).
  - `ExecutionLogFile` unchanged (seam columns `execution_id`/`attempt_id`);
    docstring documents the seam meaning.
- `apps/server/dopilot_server/models/__init__.py` — exports `Task`, `Execution`
  (dropped `ExecutionAttempt`).
- `apps/server/migrations/versions/0004_task_execution_rename.py` — **new.**
  `rename_table executions→tasks`, `execution_attempts→executions`,
  `alter_column execution_id→task_id`, reindex `ix_executions_task_id`, add
  `tasks.status_reason` + `tasks.status_detail`. Downgrade reverses it.

### State machine
- `apps/server/dopilot_server/services/states.py` — inverted vocabulary:
  - `EXEC_*` (parent) → `TASK_*`; `ATTEMPT_*` (atomic) → `EXEC_*`.
  - new terminal `TASK_NO_TARGET` (in `TASK_TERMINAL`, no out-edges, never
    produced by roll-up).
  - `rollup_execution_status` → `rollup_task_status`;
    `is_valid_execution_transition` (parent) → `is_valid_task_transition`;
    `is_valid_attempt_transition` (atomic) → `is_valid_execution_transition`;
    `AGENT_TO_ATTEMPT` → `AGENT_TO_EXEC`.

### Services / executors / redis (boundary translation)
- `services/executions.py` — `create_task`, `create_execution(task, node)`,
  `create_log_file(task, execution)`, `get_task`/`get_task_or_404`,
  `get_execution`, `list_executions(task_id)`, `list_tasks`, `resolve_execution`,
  `primary_execution`; view builders `task_view` / `task_summary` /
  `execution_view` (emit the frozen web keys). `get_log_file` keeps seam params.
- `executors/scrapyd.py` — creates a task then one execution + one run-outbox +
  one log file per node; outbox row keyed `execution_id=task.id`,
  `attempt_id=execution.id`; `_fail_dispatch_unavailable` operates on the task.
- `services/outbox.py` — `has_unterminated_for_target` now reads `Task`; create/
  cancel helpers keep seam param names.
- `services/events.py` — `apply_event` resolves `Execution` by `event.attempt_id`
  and the parent `Task` by `Execution.task_id`; `_update_task` does convergence +
  `rollup_task_status`; reclaim outbox keyed on the seam ids.
- `services/cancel.py` — `request_cancel(task)`; stops keyed on the seam ids.
- `redis/dispatcher.py` — run short-circuit checks `get_task(row.execution_id)`;
  timeout-fail marks the `Execution` (`row.attempt_id`) and `Task`
  (`row.execution_id`).
- `redis/reconcile.py` — active-set query joins `Execution.task_id == Task.id`;
  `mark_lost(execution)`, `_rollup(task_id)`, `finalize_drained_logs` joins
  `Execution.id == ExecutionLogFile.attempt_id`; cleanup outbox uses the
  log-file seam columns.
- `services/logs.py` — **no change** (already pure seam: keys on
  `event.execution_id`/`event.attempt_id`).

### API
- `api/v1/executions.py` — handlers call the renamed service fns; route paths,
  path/query params (`execution_id`, `attempt_id`), response models, and error
  codes are unchanged (web seam).
- `api/v1/schemas.py` — class names kept (`ExecutionView`/`AttemptView`/…, the
  web vocabulary); added optional `status_reason` + `status_detail` to
  `ExecutionView` and `status_reason` to `ExecutionSummary`; docstrings note the
  seam.

### Protocol + Web
- `packages/protocol/dopilot_protocol/streams.py` — added the wire-seam doc note
  (`execution_id`=task, `attempt_id`=execution; agent unchanged). No field
  changes.
- `apps/web/src/api/types.ts` — additive only: `no_target` added to
  `ExecutionStatus`; optional `status_reason`/`status_detail` on `ExecutionView`,
  optional `status_reason` on `ExecutionSummary`. No page/router changes.

### Tests
- `apps/server/tests/conftest.py` — `Seeder.running_execution` → `running_task`,
  returns `(task, execution, log_file)`.
- Updated to the new vocabulary: `test_states.py`, `test_outbox.py`,
  `test_dispatcher.py`, `test_event_consumer.py`, `test_log_consumer.py`,
  `test_reconcile_redis.py`, `test_executions.py`, `test_sse.py`. Added
  `test_no_target_is_terminal` in `test_states.py`.

## 3. Migration strategy & dev-data preservation

- Single Alembic revision `0004` (down_revision `0003`).
- Uses `rename_table` / `alter_column`, so it **is data-preserving** on
  PostgreSQL. (dopilot is greenfield/single-admin with no production data, so
  preservation was not required per feasibility B2 — but it costs nothing to
  keep, and avoids a destructive drop.)
- The FK `executions.task_id → tasks.id` is preserved through the table/column
  rename (PostgreSQL keeps the constraint across `rename_table`/`alter_column`;
  the auto-generated constraint name is left as-is — functional, not renamed).
- Seam tables (`command_outbox`, `event_audit`, `execution_log_files`) and their
  `execution_id`/`attempt_id` columns are **not** touched → no log-path or
  log-index migration (feasibility R2).
- Tests build the SQLite schema from the ORM models (`conftest.create_all`), not
  from this migration; PostgreSQL remains the real schema authority.

## 4. Redis/disk/agent seam — explicit statement

**The Redis/disk/agent seam is unchanged.** Wire payload fields
(`AgentCommand`/`AgentEvent`/`AgentLogEvent`) still carry `execution_id` (= task
id) and `attempt_id` (= atomic execution id); the on-disk log path
`{root}/YYYY/MM/{execution_id}/{attempt_id}.log` is unchanged; the seam DB
columns are unchanged; no `apps/agent/**` file was modified. Server boundary code
translates these names to the task/execution domain and is commented at each
crossing.

## 5. Tests added / updated

- Added: `test_no_target_is_terminal` (no_target ∈ TASK_TERMINAL, no out-edges,
  never produced by roll-up).
- Renamed/retargeted unit + integration tests for the inverted vocabulary
  (rollup→task, transitions, dispatcher give-up → task/execution, event
  convergence → task, reconcile lost → execution/task, log gap → task terminal,
  SSE keyed on task id). Behavior assertions (dispatch counts, convergence,
  cleanup gating) are unchanged — only names/ids moved.
- No dispatch behavior changed: manual Scrapy run still creates one task + one
  execution per healthy node + one run-outbox per execution; all/random/selected
  counts preserved; zero-node still raises the existing 409 (the `no_target`
  creation path is a later packet, per the brief).

## 6. Commands run — pass/fail

> ⚠️ **Not executed in this session.** This sandbox auto-allows read-only
> commands (find/grep/ls) but gates execution of `.venv/bin/pytest`,
> `.venv/bin/ruff`, and `pnpm` behind interactive command approval that was not
> granted during this run. The required commands below were therefore **not run
> by me**; they are ready to run and expected to pass based on the static
> verification in §7.

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
```

## 7. Static verification performed (in lieu of execution)

- Every `svc.*` call in the server resolves to a defined function (grep of all
  `svc.<name>` vs the `executions.py` definitions).
- Every `states.*` constant referenced in source **and** tests is defined in
  `states.py`.
- No stale `ExecutionAttempt`, `ATTEMPT_*`, `create_attempt`, `list_attempts`,
  `get_attempt`, `resolve_attempt`, `execution_summary`,
  `rollup_execution_status`, `is_valid_attempt_transition`, `AGENT_TO_ATTEMPT`,
  or `running_execution` references remain anywhere in `apps/server` /
  `packages`.
- Every remaining `.execution_id` / `.attempt_id` reference is a legitimate seam
  usage (wire payloads, `CommandOutbox`/`EventAudit`/`ExecutionLogFile` columns,
  the `DispatchUnknownError` web carrier, or seam function params).
- Import lists were pruned to what each module uses (no obvious unused imports).

## 8. Known risks / incomplete items

- **Test/lint/build not executed** (§6) — the single open item. Run the three
  commands to confirm green; I expect pass, but this is unverified by execution.
- **No_target creation path is intentionally NOT implemented** here (out of
  packet-1 scope): `select_target_nodes` still raises 409 before any row is
  created. The status value + columns + status-machine support exist and are
  unit-tested as terminal, ready for the later zero-node packet.
- **Public/web clean-cut deferred** (brief step 7): the web JSON still uses the
  `execution`/`attempt` vocabulary behind the stable seam. The schema class names
  (`ExecutionView`/`AttemptView`/`ExecutionSummary`) and route paths still read
  in the old vocabulary by design; they invert in a later packet.
- **FK constraint name** on `executions.task_id` keeps its auto-generated phase-2
  name after the rename (functional; cosmetic only).
