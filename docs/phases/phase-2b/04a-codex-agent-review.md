# Phase 2b Packet 2 — Codex Review

Status: blocking fix required.

## Findings

1. `PythonWheelRunner.aclose()` leaks running child process groups on agent shutdown.

   - Files:
     - `apps/agent/dopilot_agent/runners/python_wheel.py:265`
     - `apps/agent/dopilot_agent/redis/commands.py:686`
   - Severity: high.
   - Details: `CommandConsumer.stop()` cancels background waiter tasks and calls
     `wheel_runner.aclose()`, but `PythonWheelRunner.aclose()` only cancels
     reaper tasks and closes log handles. It does not terminate processes still
     tracked in `_procs` / `_pgids`. Because wheel jobs are launched with
     `start_new_session=True`, a long-running shell command can survive a normal
     agent shutdown and keep running without log/state supervision until a future
     agent restart happens to recover it as an orphan.
   - Reproduction run by Codex:
     ```bash
     .venv/bin/python - <<'PY'
     import asyncio, os, signal, tempfile
     from dopilot_agent.runners.python_wheel import PythonWheelRunner

     async def main():
         with tempfile.TemporaryDirectory() as d:
             runner = PythonWheelRunner(workspace_root=d, grace_seconds=0.1)
             started = await runner.start(
                 execution_id='leak',
                 task_id='t',
                 shell_command='sleep 30',
                 install_path=d,
             )
             pgid = started.pgid
             await runner.aclose()
             alive_after_close = True
             try:
                 os.killpg(pgid, 0)
             except ProcessLookupError:
                 alive_after_close = False
             print(f'alive_after_aclose={alive_after_close}')
             if alive_after_close:
                 os.killpg(pgid, signal.SIGKILL)

     asyncio.run(main())
     PY
     ```
     Output: `alive_after_aclose=True`.
   - Expected: shutdown cleanup must terminate tracked wheel process groups using
     the same SIGTERM -> 10s -> SIGKILL path, await/reap them, and only then close
     log handles / cancel remaining reapers. Tests must prove `consumer.stop()` or
     `wheel_runner.aclose()` does not leave a started shell process group alive.

## Non-blocking Notes

- `terminate_pgid()` used by boot orphan recovery sends SIGTERM then SIGKILL
  immediately. This is currently acceptable as a best-effort post-restart cleanup
  path, distinct from user-facing cancel/reclaim where `terminate()` uses the
  hard-coded 10 second grace.
- The command consumer can still be occupied during wheel install. This is
  acceptable for phase 2b because the selected strategy is `--no-deps` and the
  brief only required that command consumption not block for the script duration.

## Required Fix

- Update the runner/consumer shutdown path so active wheel subprocesses are
  terminated and reaped on shutdown.
- Add a regression test that fails on the current implementation.
- Re-run the required packet-2 verification commands after the fix.
