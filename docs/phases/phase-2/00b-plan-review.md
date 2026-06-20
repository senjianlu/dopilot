# Phase 2 Plan Review

> Claude review of the updated phase-2 preflight (`00-preflight-conflicts.md`)
> and the 2a/2b split. Read-only; no application code changed. Citations are
> `path:line` into the **current dopilot tree** (not the scrapydweb reference).
> This review supersedes the venv/`entry_point` assumptions in
> `00a-feasibility-review.md`, which predate the user's no-venv / shell-command
> decision recorded in the preflight.

## Verdict

**The 2a/2b split is sound — endorse it as written.** Doing the id rename first,
on a quiescent Scrapy-only system, then adding the wheel runner, is the correct
sequencing: it avoids editing the executor/runner seams twice and keeps a
collision-prone rename out of the new-runner diff.

Two refinements the brief should absorb:

1. **2a is not a plain rename — it is a name-collision *swap*.** Before: wire
   `execution_id` = `Task.id`, `attempt_id` = `Execution.id`. After:
   `task_id` = `Task.id`, `execution_id` = `Execution.id`. The token
   `execution_id` changes meaning. A global `sed` is dangerous because the server
   *already* uses `execution_id` to mean `Execution.id` in the public/domain
   layer (`services/executions.py:225-231,342-369`, `api/v1/tasks.py:177`). The
   rename must be done **per-file, compile-and-test-green**, not text-substituted
   tree-wide.

2. **2a is a net simplification, not just a rename.** The public API and web
   already speak `task_id`/`execution_id` with `execution_id` = `Execution.id`
   (`schemas.py:122-137,317-333`, `types.ts:177-210,313-322`). Today the server
   carries an explicit *seam translation boundary* (`Task.id -> execution_id`,
   `Execution.id -> attempt_id`) documented at every call site
   (`executions.py:184-185,323-324`, `dispatcher.py:112-114,145-147`). After 2a
   the wire/disk/DB names equal the domain names, so that boundary **collapses** —
   those mapping comments and the mental translation disappear. That is a strong
   argument *for* 2a beyond cosmetics.

**One structural constraint on 2a:** the wire cannot be half-renamed. Protocol +
server (dispatcher/consumers) + agent must change in **one atomic version bump**;
an old agent against a new server silently mismatches fields. This is compatible
with the user's clean-cut stance (see Compatibility), but it means 2a ships as a
single lockstep change across all three apps, not an incremental rollout.

## Phase 2a Rename Surface

`execution_id -> task_id` and `attempt_id -> execution_id` everywhere the name is
the **seam** (means `Task.id`/`Execution.id` on the wire/disk/DB). Do **not**
touch occurrences already meaning the public `Execution.id` (see Public API
Notes).

**Protocol (`packages/protocol/dopilot_protocol/`)**
- `streams.py` — `AgentCommand.execution_id/attempt_id` (`:104-105`),
  `AgentEvent.*` (`:194-195`), `AgentLogEvent.*` (`:226-228`). Rewrite the seam
  docstring (`:22-30`) — the "deliberately NOT renamed" note is now obsolete.
- `agent.py` (LEGACY HTTP) — `AgentRunRequest` (`:54-55`) is **still live** as
  the `run` command payload shape, so rename it; `AgentRunResponse`,
  `AgentStop*`, `AgentStatusResponse`, `CleanupResponse.attempt_id` are dead
  paths (rename for consistency or delete — see Remaining Decisions).
- `logs.py` — `TailRequest.execution_id/attempt_id` (`:29-31`), legacy/dead.

**DB columns / migration (new `0005`, additive to history — do NOT edit
`0003`/`0004`)**
- `ExecutionLogFile` (`models/execution.py:188-189`): PK
  `(execution_id, attempt_id, stream)` -> `(task_id, execution_id, stream)`.
- `CommandOutbox` (`models/command_outbox.py:56-57`) + indexes
  `ix_command_outbox_execution_id`/`_attempt_id` (`0003:68-73`).
- `EventAudit.attempt_id` (`models/event_audit.py:44`) + index
  `ix_event_audit_attempt_id` (`0003:96`).
- Migration `0005` does `ALTER TABLE ... RENAME COLUMN` + index renames, same
  data-preserving style as `0004`. The SQLite **test** DB is built from the
  models (conftest), so the models are the test authority; PG still needs `0005`.

**Server services / boundary**
- `services/executions.py`: `create_log_file` (`:184-191`),
  `get_log_file(execution_id, attempt_id)` params (`:317-332`),
  `resolve_execution` docstring (`:342-369`). **Collision watch:**
  `get_execution(execution_id)` (`:225-231`) already means `Execution.id` —
  leave it.
- `services/logs.py` (`apply_log_event` -> `get_log_file`),
  `services/events.py` (event consumer seam map), `services/outbox.py`
  (`create_run`/`create_stop_command` builders), `services/cancel.py`,
  `services/maintenance.py`.
- `redis/dispatcher.py`: `_build_command` (`:89-90`), run short-circuit
  `get_task(row.execution_id)` -> `row.task_id` (`:113-114`),
  `_fail_execution_dispatch_timeout` `get_execution(row.attempt_id)` ->
  `row.execution_id` (`:145-152`). `redis/reconcile.py` similarly.
- `executors/scrapyd.py`: log-file/outbox creation call sites.
- `logs/files.py`: `log_path(execution_id, attempt_id)` params (`:24-39`); the
  on-disk layout `{execution_id}/{attempt_id}.log` becomes
  `{task_id}/{execution_id}.log`.

**Agent state + Redis publishers/consumers (`apps/agent/dopilot_agent/`)**
- `state/store.py`: `AttemptState.execution_id/attempt_id` (`:45-46`) and **every
  method keyed by `attempt_id`** (`path_for`, `create_reserved`,
  `promote_started`, `mark_done`, `read`, `delete`, `list_attempt_ids`,
  `:73-198`). State files `{attempt_id}.json` -> `{execution_id}.json`.
  Consider renaming the class `AttemptState` -> `ExecutionState` and
  `list_attempt_ids` -> `list_execution_ids` for coherence (optional, internal).
- `redis/commands.py` (~64 refs — attempt lock, idempotency key, command/event
  fields), `redis/events.py` (~31), `redis/logs.py` (~20 — cursor files
  `{attempt_id}.logpos` -> `{execution_id}.logpos`), `runners/scrapyd.py` (~22),
  `artifacts/cache.py` (cache key), `redis/heartbeat.py` (minor).

**Log paths and file-index rows (summary)**
- on-disk body: `{root}/YYYY/MM/{execution_id}/{attempt_id}.log`
  -> `{root}/YYYY/MM/{task_id}/{execution_id}.log`
- agent log cursor: `{attempt_id}.logpos` -> `{execution_id}.logpos`
- agent state: `{attempt_id}.json` -> `{execution_id}.json`
- index rows: `ExecutionLogFile` PK rename (above).

**Tests (rename in lockstep — these are the regression net for 2a)**
- protocol: `test_stream_schemas.py`, `test_agent_schemas.py`, `test_schemas.py`.
- server: `test_dispatcher.py`, `test_event_consumer.py`, `test_executions.py`,
  `test_log_consumer.py`, `test_maintenance.py`, `test_outbox.py`,
  `test_reconcile_redis.py`, `test_redis_fake.py`, `test_sse.py`,
  `test_schedules.py`, `test_scheduler_runner.py`.
- agent: `test_command_consumer.py`, `test_event_outbox.py`,
  `test_heartbeat_worker.py`, `test_log_publisher.py`, `test_runner.py`,
  `test_state_cas.py`, `test_state_store.py`, `conftest.py`.

## Public API Notes

**`execution_id` already correctly means the atomic `Execution.id` here — do NOT
rename (these are the collision traps):**
- `api/v1/tasks.py`: `get_logs`/`stream_logs` query param `execution_id`
  (`:177,262`), and `resolve_execution(... execution_id)` (`:186,294`).
- `api/v1/schemas.py`: `LogSnapshot.execution_id` (`:325-327`),
  `ExecutionView.task_id`/`id` (`:122-137`), `TaskView`/`TaskSummary` (`task_id`
  back-refs), `TaskRunResponse.task_id`, `MarkTaskLostResponse.task_id`.
- `services/executions.py`: `get_execution(execution_id)` (`:225`),
  `resolve_execution(execution_id)` (`:342`) — public param, already `Execution.id`.
- `logs/sse.py`, `logs/stream_token.py`: keyed by `task_id` (parent) — public.
- web: `types.ts:177-322`, `tasks.ts:38-94` (`execution_id` query param +
  `LogSnapshot.execution_id`).

**Therefore phase 2a requires NO public-API / web-JSON / web-TS change.** The
Redis wire, DB columns, and on-disk paths change; the HTTP surface and web are
untouched (the browser never speaks the Redis seam). The only public-side edits
are deleting the now-obsolete "seam mapping" comments. This sharply bounds 2a's
blast radius and makes the regression criterion crisp: existing public API/SSE
tests must pass **unchanged**.

## Compatibility

**No backward-compatibility layer needed; a clean-cut is safe — with one
operational precondition.** Rationale:
- Greenfield, single-admin, no production data (stated in `0004` header and
  `refactor/00`); migration `0005` can rename columns without data care.
- Redis streams are transient transport, not business truth (`refactor/00`
  decisions). Old in-flight messages need no translation if the system is
  quiesced at cutover.
- Field names change in lockstep, so a mixed old-agent/new-server deployment
  would silently drop/None fields (pydantic). **Deploy protocol+server+agent as
  one version** — do not roll one ahead of the other.

**The one hard precondition (flag to user):** at upgrade there must be **no
in-flight executions**, OR the operator accepts losing reconciliation for them.
After the rename the agent looks up state by `{execution_id}.json`, but a running
attempt's file on disk is still `{attempt_id}.json` (old name) and its log lives
under `{old execution_id}/{old attempt_id}.log` — the new agent will not find
either, orphaning the process and the log. This is acceptable under the
clean-cut decision, but the brief should state the cutover step: **quiesce
(drain running tasks) + flush the Redis streams before upgrading.** Old orphaned
state/log files are then GC'd by the agent's existing TTL sweep. No code
compat-shim required.

## Phase 2b Runner Review

The no-venv / shell-command design is **coherent with the existing agent
process/log/state architecture** and reuses its seams cleanly. Per-item:

- **`pip install --no-deps` into the current environment** — works, but it
  mutates the shared agent interpreter and persists across runs. With a single
  fixed interpreter and no venv, two wheel tasks needing different versions of
  the same dist **collide** — consistent with "multi-version out of scope," but
  the brief must (a) make install **idempotent + cached by wheel sha256** (skip
  if that sha is already installed) and (b) guard concurrent installs with a
  lock. *Lower-risk alternative that is still "no venv":* `pip install --no-deps
  --target <per-sha dir>` + prepend `PYTHONPATH`, which isolates without a venv
  and avoids polluting the base interpreter. Recommend raising this as a decision
  (see Remaining Decisions); respect the operator's call.
- **Operator-managed dependencies** — coherent for an internal platform; make it
  an explicit operational contract (deps must be pre-present in the agent image/
  environment; the runner does not resolve from PyPI).
- **Merged stdout/stderr -> single `log`** — lowest-risk choice. Redirect child
  `stderr` into `stdout`, write one `job.log`; the existing `LogPublisher` (one
  `state.log_path`, single `stream="log"` row) and the server log-consumer/SSE
  chain are reused **unchanged**. No new log rows or per-stream cursors. Good.
- **Process-group SIGTERM -> 10s -> SIGKILL** — coherent. Launch via
  `asyncio.create_subprocess_exec(..., start_new_session=True)` (setsid) so the
  shell + children share a process group; signal the group (`os.killpg`). The
  exit-code mapping must subordinate to `StopIntent`: under `intent=cancel` the
  agent's authoritative terminal is `attempt.canceled` **regardless of exit
  code** (`streams.py:79-89`), and `intent=reclaim` keeps `lost`. Only a natural
  exit maps `0 -> finished`, non-zero -> `failed`. 10s hard-coded is acceptable
  for v1 (recommend a config knob — Remaining Decisions).
- **Per-run workspace/log/state keyed by `execution_id` (post-2a atomic id)** —
  correct and required: the cross-restart idempotency key, the state-file CAS
  (`reserved -> started -> done`, `state/store.py:90-159`), the log path and the
  log cursor are all keyed by the atomic execution id. This is exactly why 2a
  must land first — 2b's state model inherits the renamed key.

**Architecture fit:** the runner registry dispatches on `cmd.task_type` (already
on the wire, `streams.py:106`); the Scrapy branch stays byte-for-byte; the wheel
runner adds additive optional `AttemptState` fields (pid/pgid/exit_code/
runner_type) without breaking scrapy state files.

**Under-specified points the 2b brief must pin down:**
- Shell + exit-code authority: which shell, and `pipefail`? `sh -c "a | b"`
  reports only the last stage's code — decide so "exit code is authoritative" is
  unambiguous.
- `working_dir` root + per-execution workspace creation/cleanup (on
  `cleanup_logs`).
- `env` merge precedence (agent base env vs task `env`).
- Wheel install location, idempotency/caching by sha256, concurrent-install lock.
- Cancellation: ensure `setsid` *before* exec; SIGKILL escalation reaps orphans;
  the single-sequential-log-producer invariant still holds (one merged file).

## Required Tests

**Phase 2a (gating = behavior-preserving; the acceptance bar is "Scrapy
unchanged"):**
- The full existing protocol/server/agent suite is green after the rename — this
  is the primary criterion.
- Wire round-trip: `AgentCommand`/`AgentEvent`/`AgentLogEvent` serialize with
  `task_id`/`execution_id`; `from_stream_entry` decodes.
- Migration `0005` renames columns + indexes on PG; models match; new PK
  `(task_id, execution_id, stream)`.
- Boundary: dispatcher builds the command with `task_id=task.id`,
  `execution_id=execution.id`; run short-circuit uses `get_task(row.task_id)`;
  dispatch-timeout uses `get_execution(row.execution_id)`.
- Log path is now `{task_id}/{execution_id}.log`; `get_log_file` resolves;
  snapshot + SSE still serve the right file.
- Agent: state file `{execution_id}.json`, cursor `{execution_id}.logpos`;
  `create_reserved`/`promote_started`/`mark_done` keyed by execution id; the
  two-phase CAS idempotency (incl. `spawn_aborted`) still holds.
- Public surface unchanged: existing tasks-API / log-snapshot / SSE tests pass
  **without edits** (proves no public drift).

**Phase 2b:**
- Capability mapping: a `python_wheel` artifact selects a `script`-capable agent
  and excludes scrapy-only agents.
- `python_wheel` is runnable; `PythonWheelExecutor` creates task/execution/
  outbox/log rows in one transaction and dispatches `run`; no Python runs on the
  server.
- Wheel artifact upload -> sha256 dedup -> authenticated download byte-identity.
- Template/resolve: a wheel binding requires a non-empty `shell_command` and is
  rejected when empty; a Scrapy template still validates command-first.
- Agent runner registry dispatches on `task_type`; the Scrapy path is unchanged
  (regression).
- Wheel runner: install once, cached by sha256, reused on re-run; subprocess in
  its own process group with `PYTHONUNBUFFERED=1`.
- Merged stdout/stderr -> single `log` persisted (offset append / dedup / gap
  behavior unchanged).
- Exit-code mapping: `0 -> finished`, non-zero -> `failed`.
- Cancel: SIGTERM -> 10s -> SIGKILL on the process group -> authoritative
  `attempt.canceled` (under `intent=cancel`, regardless of exit code).
- Cross-restart idempotency: a re-delivered `run` does not double-start (state
  CAS keyed by the atomic `execution_id`).

## Remaining Decisions

1. **Legacy-type rename scope** — rename `execution_id`/`attempt_id` in the dead
   legacy schemas (`agent.py` `AgentStatus`/`Stop`/`Cleanup`, `logs.py`
   `TailRequest`) too, or leave/delete them? (`AgentRunRequest` must be renamed —
   it is the live `run` payload.)
2. **2a cutover precondition** — confirm the system will be quiesced (no in-flight
   executions) and Redis streams flushed at upgrade, accepting orphaned old
   state/log files. (The only hard requirement for the clean-cut.)
3. **Wheel install isolation** — install into the current interpreter (as
   written) vs `--no-deps --target <per-sha dir>` + `PYTHONPATH` (still no venv,
   no base-env pollution). Needs a call.
4. **Dependency/network policy** — confirm the runner never resolves from PyPI;
   deps are pre-provisioned by the operator in the agent environment.
5. **Shell + exit-code semantics** — shell choice and `pipefail`, so "exit code
   authoritative" is unambiguous for pipelines.
6. **Cancellation grace (10s)** — hard-coded vs config knob.
7. **`AttemptState` evolution** — confirm additive optional fields
   (pid/pgid/exit_code/runner_type) so scrapy state files keep loading.
8. **Capability naming** (carried over from `00a` Open Decisions) — seam fix
   `ARTIFACT_CAPABILITY[python_wheel]="script"` (recommended, lower risk) vs the
   canonical `CapabilitySet` rename the docs assert. Needs an explicit call so
   docs and code stay aligned. This belongs to 2b, not 2a.
9. **stdout/stderr combined for v1** — confirm deferring split streams (preflight
   already leans this way; reconfirm as a product call).

## Commands Run

- `Read` of `CLAUDE.md`, `AGENTS.md`, the phase-2 preflight + feasibility docs,
  `docs/dopilot/00-requirements.md`, `docs/dopilot/10-roadmap.md`,
  `docs/refactor/00-redis-streams-agent-communication.md`.
- `Read` of the listed protocol/server/agent/web source files and migrations
  `0003`/`0004` to confirm the seam, the public/domain split, and the boundary
  translation sites.
- One `Explore` sub-agent (`rg -c` over the tree, excluding `reference/`) to
  inventory every `execution_id`/`attempt_id` occurrence by area and meaning.
- No files outside the two allowed report paths were modified; no
  `reference/scrapydweb/` code was read.
