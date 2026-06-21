# Claude Fix Prompt: Phase 2b Packet 2 Shutdown Leak

You are Claude Code working in the dopilot repository.

## Assignment

Fix the blocking Codex review finding for phase 2b packet 2.

Read first:
- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2b/00-brief.md`
- `docs/phases/phase-2b/03a-claude-agent-implementation-report.md`
- `docs/phases/phase-2b/04a-codex-agent-review.md`
- `apps/agent/dopilot_agent/runners/python_wheel.py`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/tests/test_python_wheel.py`

## Blocking Finding

`CommandConsumer.stop()` calls `wheel_runner.aclose()`, but `PythonWheelRunner.aclose()`
only cancels waiter/reaper tasks and closes log handles. It does not terminate active
subprocess process groups. A long-running wheel shell command launched with
`start_new_session=True` can survive normal agent shutdown.

Codex reproduced the bug with:

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

Current output: `alive_after_aclose=True`.

## Required Fix

- Update the shutdown path so active Python-wheel subprocess process groups are
  terminated and reaped during `CommandConsumer.stop()` / `PythonWheelRunner.aclose()`.
- Use the existing `terminate()` path or equivalent SIGTERM -> grace -> SIGKILL process
  group cleanup. Production default grace must remain the hard-coded 10 seconds; tests
  may keep using the constructor override.
- Do not change Scrapy behavior.
- Do not introduce a broad runner registry.
- Do not add venv/dependency-management behavior.
- Keep existing cancel/reclaim semantics unchanged:
  - cancel emits `attempt.canceled`;
  - reclaim kills resources but does not emit canceled;
  - shutdown cleanup should not emit extra terminal events by itself.
- Clear/cleanup runner bookkeeping after child exit/shutdown so repeated tests do not
  retain stale process/log handles.

## Tests

Add or update tests that fail on the current implementation and pass after the fix.
At minimum:

- `PythonWheelRunner.aclose()` terminates a running `sleep` command process group.
- Preferably also cover `CommandConsumer.stop()` after a long-running wheel command so
  the lifecycle path used by the app is covered.

## Required Output

Update:
- `docs/phases/phase-2b/04c-claude-agent-fix-report.md`
- `docs/phases/phase-2b/claude-progress.md`

The report must include:
- changed files;
- exact fix behavior;
- tests added/updated;
- exact commands run and pass/fail outcomes;
- known residual risks.

## Required Commands

Run:

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check apps packages
```

Use narrower agent tests while iterating. If any command cannot run, record the exact
blocker in the fix report.
