# Phase 2a Feasibility Review

> Claude read-only feasibility validation of the phase-2a id-naming clean-cut.
> No application code changed. Citations are `path:line` into the current
> dopilot tree (not the scrapydweb reference). This focuses the broader
> `../phase-2/00b-plan-review.md` on the two clean-cut decisions the user just
> made (delete dead legacy schemas; no back-compat).

## Verdict

**Feasible. No hard blockers** under the accepted cutover (no in-flight
executions, Redis streams/pending commands cleared, protocol+server+agent
deployed lockstep). The clean-cut is a name-collision **swap** (`execution_id`
changes meaning), so it must be done per-file/compile-green, never tree-wide
`sed`. It is also a net simplification: the server's seam-translation boundary
(`Task.id -> execution_id`, `Execution.id -> attempt_id`) collapses, and no
public-API/web/JSON change is required.

Two corrections to the older `00b-plan-review.md`:

1. The new Alembic migration is **`0009`** (down_revision `0008`), not `0005` —
   current head is `0008_command_first_templates` (`0009` is the only file to
   add; do **not** edit `0002`/`0003`/`0004`).
2. The legacy-rename-vs-delete question is now decided by the user: delete the
   dead ones, rename the live ones (classified below).

## Legacy Schema Deletion

Live-usage scan (`rg` over `apps/`+`packages/`, excluding `reference/`). A symbol
is "dead" iff it is referenced only by its own definition, `__init__.py`, and
tests.

**Deletable now — no live code path (delete per user decision):**

| Symbol | Module | Only referenced by |
|---|---|---|
| `AgentStopRequest` | `agent.py:73` | `tests/test_agent_schemas.py` |
| `CleanupResponse` | `agent.py:111` | `tests/test_agent_schemas.py` |
| `TailRequest` | `logs.py:26` | `tests/test_schemas.py` |
| `TailResponse` | `logs.py:36` | `tests/test_schemas.py` |

(`TailResponse` has no seam fields but belongs to the dead phase-1 server-pull
tail path; delete with `TailRequest`. The server-side `TerminalCleanupResponse`
at `api/v1/schemas.py:357` is an **unrelated** schema — do not touch it.)

**Must RENAME, not delete — live + carry seam fields (`execution_id`/`attempt_id`
= `Task.id`/`Execution.id`):**

| Symbol | Live use |
|---|---|
| `AgentRunRequest` (`agent.py:46`) | `redis/commands.py:314` (run payload), `runners/scrapyd.py:56,77` |
| `AgentRunResponse` (`agent.py:64`) | instantiated in `runners/scrapyd.py:92` |
| `AgentStopResponse` (`agent.py:84`) | `runners/scrapyd.py` stop(), driven by `redis/commands.py:366,387` |
| `AgentStatusResponse` (`agent.py:94`) | `runners/scrapyd.py` status(), driven by `redis/commands.py:154,377`, `redis/events.py:267` |

**Leave untouched — live but no seam fields:** `AttemptStatus` (enum of
status values, not ids; mapped server-side at `services/states.py:116`),
`EggDeployResponse` (surviving egg-deploy HTTP path: `agent/api/artifacts.py`,
`server/clients/agent.py:109`, `server/tests/conftest.py`), `LogStream`
(shared/current, used by `streams.py:228`).

**One residual call for the brief:** `ScrapydRunner.run()` (`scrapyd.py:77`,
returns `AgentRunResponse`) has **no live caller** — the run path uses
`schedule()` (`commands.py:324`). So `AgentRunResponse` is only kept alive by a
dead method. Options: (a) rename its seam fields and keep the method (cheapest,
2a stays a pure rename), or (b) delete `run()` + `AgentRunResponse` together as
dead code. Recommend (a) for 2a; defer dead-method pruning to 2b. `stop()`/
`status()` (and their responses) are genuinely live — rename only.

## Clean-Cut Rename Feasibility

No hard blockers. Surfaces (matches `00b-plan-review.md §Phase 2a Rename
Surface`, re-confirmed against current tree):

- **Protocol** `streams.py`: `AgentCommand` (`:104-105`), `AgentEvent`
  (`:194-195`), `AgentLogEvent` (`:226-228`) `execution_id`->`task_id`,
  `attempt_id`->`execution_id`; rewrite the obsolete "deliberately NOT renamed"
  seam docstring (`:22-30`). `agent.py` `AgentRunRequest` (`:54-55`) +
  Run/Stop/Status responses; delete the four dead schemas above. `__init__.py`:
  drop deleted symbols from both the `from .agent`/`from .logs` imports
  (`:9-22`) and `__all__` (`:57-58,72-76` → keep `AgentRunRequest`,
  `AgentRunResponse`, `AgentStopResponse`, `AgentStatusResponse`, `AttemptStatus`,
  `EggDeployResponse`, `LogStream`; remove `AgentStopRequest`, `CleanupResponse`,
  `TailRequest`, `TailResponse`).
- **DB migration `0009`** (down_revision `0008`): `ALTER ... RENAME COLUMN` +
  index renames, data-preserving like `0004`. Targets:
  `execution_log_files` PK `(execution_id, attempt_id, stream)` ->
  `(task_id, execution_id, stream)` (`models/execution.py:188-189`);
  `command_outbox.execution_id/attempt_id` (`models/command_outbox.py:56-57`) +
  indexes `ix_command_outbox_execution_id`/`_attempt_id` (defined in `0003`);
  `event_audit.attempt_id` (`models/event_audit.py:44`) +
  `ix_event_audit_attempt_id`. SQLite test DB is built from models (conftest), so
  models are the test authority; PG still needs `0009`.
- **Server services/boundary**: `services/executions.py` `create_log_file`
  (`:184-191`, seam), `get_log_file` params (`:319-332`); `services/logs.py`,
  `services/events.py`, `services/outbox.py`, `services/cancel.py`,
  `services/maintenance.py`; `redis/dispatcher.py` (`_build_command`, run
  short-circuit, dispatch-timeout), `redis/reconcile.py`; `executors/scrapyd.py`;
  `logs/files.py` (`{execution_id}/{attempt_id}.log` -> `{task_id}/{execution_id}.log`).
- **Agent**: `state/store.py` `AttemptState.execution_id/attempt_id` (`:45-46`)
  and every method keyed by `attempt_id` (`path_for` etc.; state files
  `{attempt_id}.json` -> `{execution_id}.json`); `redis/commands.py`,
  `redis/events.py`, `redis/logs.py` (cursor `{attempt_id}.logpos` ->
  `{execution_id}.logpos`), `runners/scrapyd.py`, `artifacts/cache.py`,
  `redis/heartbeat.py`.
- **Tests** rename in lockstep (protocol/server/agent suites listed in
  `00b-plan-review.md §Tests`); additionally **remove** the deleted-schema cases
  from `test_agent_schemas.py` (AgentStopRequest, CleanupResponse) and
  `test_schemas.py` (TailRequest, TailResponse).

No hard blocker exists; the only structural constraint is the wire cannot be
half-renamed (see Residual Risks → lockstep).

## Brief Requirements

The brief must pin these to avoid global-sed damage:

1. **Do NOT rename — `execution_id` already means the atomic `Execution.id`
   (public/domain):** `services/executions.py` `get_execution(execution_id)`
   (`:225-229`, `Execution.id == execution_id`) and `resolve_execution(task_id,
   execution_id)` (`:342-359`); `api/v1/tasks.py` `get_logs`/`stream_logs`
   `execution_id` query param + `resolve_execution(...)` calls; `api/v1/schemas.py`
   (`ExecutionView`, `LogSnapshot.execution_id`, `TaskView`/`TaskSummary`
   `task_id`); `logs/sse.py`, `logs/stream_token.py` (keyed by public `task_id`);
   web `types.ts`, `tasks.ts`. **Phase 2a requires zero public-API/web/JSON
   change** — only the wire, DB columns, and on-disk paths move.
2. **Rename only seam occurrences** (wire/disk/DB meaning `Task.id`/`Execution.id`).
   The token `execution_id` flips meaning, so the rename is per-file,
   compile-and-test-green; forbid tree-wide substitution.
3. **Migration is `0009`**, additive, down_revision `0008`; never edit
   `0002`/`0003`/`0004`.
4. **Delete (not rename)** `AgentStopRequest`, `CleanupResponse`, `TailRequest`,
   `TailResponse` and their `__init__.py` exports + their test cases; **rename**
   `AgentRunRequest`/`AgentRunResponse`/`AgentStopResponse`/`AgentStatusResponse`;
   **leave** `AttemptStatus`/`EggDeployResponse`/`LogStream`.
5. **Decide the `AgentRunResponse`/`run()` dead-code call** (rename-and-keep vs
   delete-both) so the implementer does not guess.
6. **Delete the now-obsolete seam-mapping comments/docstrings** (e.g.
   `models/execution.py:10-14,179-183`, `streams.py:22-30`,
   `services/executions.py:184,323`) — they describe a boundary that no longer
   exists post-rename.
7. **Cutover step** in the brief: quiesce running tasks + flush Redis
   streams/pending commands before upgrading; deploy protocol+server+agent as one
   version.

## Required Verification

Mandatory (narrowest-first, broaden because protocol+DB+agent all change):

```bash
ruff check apps packages
pytest packages/protocol/tests
pytest apps/server/tests
pytest apps/agent/tests
# prove no public drift: tasks-API / log-snapshot / SSE tests pass unchanged
pytest apps/server/tests/test_sse.py apps/server/tests/test_executions.py
# migration applies cleanly on PG (offline check at minimum):
cd apps/server && alembic upgrade head && alembic downgrade -1 && alembic upgrade head
# guard against leftover seam tokens (should only match public Execution.id sites):
rg -n 'attempt_id' apps packages   # expect zero in renamed seam code
cd deploy/docker && docker compose config
```

Acceptance bar: the full protocol/server/agent suites are green and the public
API/SSE tests pass **without edits** (proves the rename did not leak into the
HTTP/web surface).

## Residual Risks

1. **Lockstep wire (structural).** An old agent against a new server silently
   drops/None-fills the renamed fields (pydantic) — no error, wrong behavior.
   Must ship protocol+server+agent in one version bump. Accepted by the user's
   clean-cut stance; restate as a deploy gate.
2. **In-flight orphan (already accepted).** A running attempt's on-disk
   `{attempt_id}.json` / `{old}/{old}.log` are not found by the renamed agent —
   orphaned process + log, GC'd by the existing TTL sweep. Mitigated by the
   quiesce-before-upgrade precondition; no code shim needed.
3. **`AgentRunResponse`/`run()` dead-code decision** (Brief Req 5) — minor;
   needs an explicit call, not user-level risk acceptance.

No risk beyond the already-accepted clean-cut cutover requires fresh user
approval, provided the quiesce + flush + lockstep precondition is honored.

## Commands Run

- `Read` of `CLAUDE.md`, `AGENTS.md`, `docs/agent-governance/00`/`01`,
  `docs/phases/phase-2/00-preflight-conflicts.md` + `00b-plan-review.md`,
  `docs/dopilot/00-requirements.md`,
  `docs/refactor/00-redis-streams-agent-communication.md`.
- `Read` of `packages/protocol/dopilot_protocol/{__init__,agent,logs,streams}.py`,
  `apps/agent/dopilot_agent/redis/commands.py`,
  `apps/agent/dopilot_agent/runners/scrapyd.py`,
  `apps/agent/dopilot_agent/state/store.py`,
  `apps/server/dopilot_server/services/executions.py` (seam vs public sites).
- `rg` live-usage scans for every legacy symbol across `apps/`+`packages/`
  (excluding `reference/`); `ls`/`find` of `apps/server/migrations/versions/`
  to confirm head `0008` and seam columns/indexes in `0002`/`0003`/`0004`.
- No files outside the two allowed report paths were modified; no
  `reference/scrapydweb/` code was read.
</content>
