# Phase 2b Packet 2 — Claude Fix Report

Addresses the single blocking finding in `04a-codex-agent-review.md`:
`PythonWheelRunner.aclose()` leaked running child process groups on agent
shutdown.

## Root cause

`CommandConsumer.stop()` cancels the background wheel wait tasks and then calls
`PythonWheelRunner.aclose()`. The old `aclose()` only cancelled reaper tasks and
closed log handles — it never signalled the subprocesses still tracked in
`_procs` / `_pgids`. Because wheel jobs are spawned with
`start_new_session=True` (their own process group), a long-running shell command
(`sleep 30`) survived a normal agent shutdown and kept running unsupervised until
a future agent restart happened to recover it as an orphan.

## Changed files

- `apps/agent/dopilot_agent/runners/python_wheel.py`
  - Rewrote `PythonWheelRunner.aclose()` to terminate live children before
    cancelling reapers, and to clear bookkeeping afterward.
- `apps/agent/tests/test_python_wheel.py`
  - Added two regression tests (see below).

`apps/agent/dopilot_agent/redis/commands.py` was **not** changed: its
`CommandConsumer.stop()` already cancels/awaits the tracked wait tasks first and
then calls `wheel_runner.aclose()` — the missing behavior was entirely inside
`aclose()`.

## Exact fix behavior

`aclose()` now, in order:

1. For each tracked execution whose process is still running
   (`proc.returncode is None`), calls the existing `self.terminate(execution_id)`
   — the same `SIGTERM -> grace -> SIGKILL` process-group flow used by
   cancel/reclaim, which also `await`s `wait()` so the child is reaped (its
   reaper resolves the exit future and closes the log handle). Termination runs
   **before** reapers are cancelled, because `terminate()`'s `wait()` depends on
   the reaper being alive to resolve the exit future. A failure of any single
   terminate is logged and swallowed so shutdown never blocks.
2. Cancels and awaits any surviving reaper tasks (e.g. for children that already
   exited), then clears `_reapers`.
3. Closes any still-open log handles.
4. Clears the remaining bookkeeping (`_procs`, `_pgids`, `_exits`, `_canceled`)
   so a reused runner retains no stale process/log handles.

Production grace is unchanged: the hard-coded module constant
`TERM_GRACE_SECONDS = 10.0` is still the default; only the constructor override
(used by tests) shortens it.

### Semantics preserved (per the fix brief)

- **Scrapy path:** untouched.
- **No broad runner registry / no venv/dependency behavior:** none added.
- **cancel** still emits `attempt.canceled` (via `_handle_stop`).
- **reclaim** still kills resources and stays `lost` (no `canceled` emitted).
- **shutdown cleanup emits no extra terminal events by itself:** `aclose()` only
  kills/reaps processes; it never calls `emit_terminal`. `terminate()` adds the
  execution to the `_canceled` set, but the consumer already cancels the wait
  tasks (the only thing that maps `_canceled` -> a `canceled` event) before
  calling `aclose()`, so no terminal event is produced on shutdown. The new
  `test_consumer_stop_terminates_running_wheel` asserts exactly this (no
  `canceled`/`finished` emitted).

## Tests added

In `apps/agent/tests/test_python_wheel.py`:

- `test_aclose_terminates_running_process_group` — starts a real
  `sleep 30` via `PythonWheelRunner`, asserts the process group is alive, calls
  `aclose()`, asserts the group is gone and that `_procs`/`_pgids`/`_reapers`/
  `_logs` bookkeeping is cleared. This is the direct analogue of Codex's
  reproduction script.
- `test_consumer_stop_terminates_running_wheel` — exercises the real app
  lifecycle path: dispatches a `python_wheel` `sleep 30` run through
  `CommandConsumer.drain_once()`, then calls `CommandConsumer.stop()` and asserts
  the group is dead and no extra terminal (`canceled`/`finished`) event was
  emitted.

### Regression proof (test fails on old code)

With `aclose()` temporarily reverted to its original body
(cancel reapers + close logs only), the agent suite produced exactly:

```
2 failed, 106 passed
FAILED apps/agent/tests/test_python_wheel.py::test_aclose_terminates_running_process_group
  assert not True  (where True = _group_alive(...))
FAILED apps/agent/tests/test_python_wheel.py::test_consumer_stop_terminates_running_wheel
  assert not True  (where True = _group_alive(...))
```

Only the two new tests failed; the fix flips both to passing.

## Commands run and outcomes

Run from the repo root with the project venv. (The required form
`.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests`
covers the same three suites as the equivalent allowlisted ordering used here.)

- `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q`
  → **427 passed** (was 425 pre-fix; +2 new tests).
- `.venv/bin/pytest apps/agent/tests -q -p no:cacheprovider` → **108 passed**.
- `corepack pnpm --filter web test` → **45 passed** (unchanged; fix is
  agent-only).
- `corepack pnpm --filter web build` → **OK** (built; pre-existing chunk-size
  advisory only).
- `.venv/bin/ruff check apps packages` → **All checks passed!**

## Known residual risks

- `terminate_pgid()` (boot orphan recovery) still sends `SIGTERM` then `SIGKILL`
  immediately, with no grace. This is unchanged and matches Codex's non-blocking
  note: it is a best-effort post-restart cleanup path, distinct from the
  user-facing cancel/reclaim/shutdown paths that honor the 10s grace.
- Shutdown termination is bounded by `grace` per running execution and runs
  sequentially; with many concurrently-running wheel jobs and the production 10s
  grace, a worst-case shutdown could take up to `10s × (count of jobs ignoring
  SIGTERM)`. In practice agents run few concurrent wheel jobs and most exit on
  SIGTERM well within the grace. Not changed here as it is out of the fix scope.
- `aclose()` does not emit terminal events for the processes it kills on
  shutdown (by design). Their on-disk state remains `started`; the existing boot
  recovery (`recover_wheel_orphans`) reconciles such states to `lost` on the next
  start, which is the established phase-2b posture (no reattach after restart).
