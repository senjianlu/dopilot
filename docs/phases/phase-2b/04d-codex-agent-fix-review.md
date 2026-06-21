# Phase 2b Packet 2 Fix — Codex Review

Status: accepted.

## Review Result

The blocking shutdown leak identified in `04a-codex-agent-review.md` is fixed.
`PythonWheelRunner.aclose()` now terminates tracked live child process groups via
the existing `terminate()` path before cancelling reapers or closing log handles,
then clears runner bookkeeping.

Codex re-ran the original reproduction after the fix:

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

Output: `alive_after_aclose=False`.

## Regression Tests

Claude added and Codex reviewed:

- `test_aclose_terminates_running_process_group`
- `test_consumer_stop_terminates_running_wheel`

Codex targeted run:

```bash
.venv/bin/pytest apps/agent/tests/test_python_wheel.py \
  -k "aclose or consumer_stop or cancel or reclaim" -q -p no:cacheprovider
```

Result: `5 passed, 17 deselected`.

## Full Verification

Codex ran:

- `.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests`
  → `427 passed`.
- `corepack pnpm --filter web test` → `45 passed`.
- `corepack pnpm --filter web build` → OK.
- `.venv/bin/ruff check apps packages` → all checks passed.
- `git diff --check` → no whitespace errors.

## Residual Notes

- Boot orphan recovery still uses immediate SIGTERM then SIGKILL in
  `terminate_pgid()`. This remains acceptable for phase 2b because it is a
  best-effort post-restart cleanup path, not user-facing cancel/reclaim.
- Shutdown does not emit a terminal event for killed wheel jobs by design; next
  boot reconciles started wheel state to `lost(runner_recovered_unknown)`.
