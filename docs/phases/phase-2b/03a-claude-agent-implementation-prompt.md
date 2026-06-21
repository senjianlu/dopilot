# Claude Implementation Prompt: Phase 2b Packet 2

You are Claude Code working in the dopilot repository.

## Assignment

Implement **phase 2b packet 2: agent-side Python wheel runner and end-to-end
execution support**.

Active brief:

- `docs/phases/phase-2b/00-brief.md`

Packet 1 has been implemented and accepted by Codex:

- `docs/phases/phase-2b/01a-claude-implementation-report.md`
- `docs/phases/phase-2b/02a-codex-review.md`

Continue from the current working tree. Do not revert packet-1 changes.

## Required Context

Read these before editing:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2b/00-brief.md`
- `docs/phases/phase-2b/01a-claude-implementation-report.md`
- `docs/phases/phase-2b/02a-codex-review.md`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/redis/events.py`
- `apps/agent/dopilot_agent/redis/logs.py`
- `apps/agent/dopilot_agent/state/store.py`
- `apps/agent/dopilot_agent/artifacts/cache.py`
- `apps/agent/dopilot_agent/deps.py`
- `apps/agent/dopilot_agent/main.py`
- `apps/agent/tests/test_command_consumer.py`
- `apps/agent/tests/conftest.py`
- `tests/fixtures/python_wheel_demo/`

## In Scope

Add agent-side Python wheel execution while preserving existing Scrapy behavior.

Required behavior:

- Add a narrow `cmd.task_type == "python_wheel"` branch for run commands.
  Do not perform a broad runner-registry refactor.
- Keep the existing Scrapy run path behavior unchanged.
- Add a Python wheel artifact cache keyed by sha256:
  - fetch from the server using `artifact.fetch_path`;
  - verify sha256;
  - store wheel bytes under the agent workdir;
  - install once per sha256 with
    `python -m pip install --no-deps --target <agent-cache>/python_wheel/<sha>/site <wheel>`;
  - use a lock + ready marker to make install idempotent under concurrency;
  - do not resolve/install dependencies.
- Launch `/bin/sh -c <shell_command>` with `start_new_session=True`.
- Set cwd to a per-execution workspace keyed by atomic `execution_id`.
  If `working_dir` is present, resolve it relative to that workspace and reject
  absolute paths or `..` escapes.
- Inject the wheel install site via `PYTHONPATH`.
- Set `PYTHONUNBUFFERED=1`; payload env may be merged, but the server currently
  emits `{}`.
- Merge stdout and stderr into one local `job.log` file.
- Persist `AttemptState.log_path` so the existing `LogPublisher` publishes the
  same single `log` stream.
- Natural process exit maps:
  - exit code 0 -> `attempt.finished`;
  - non-zero -> `attempt.failed` with `exit_code`.
- Cancel maps to `attempt.canceled` regardless of child exit code.
- Cancellation must send SIGTERM to the child process group, wait a hard-coded
  10 seconds, then send SIGKILL to remaining processes and reap.
- Extend `AttemptState` additively with optional fields such as:
  - `runner_type` (default should keep old Scrapy state files loading);
  - `pid`;
  - `pgid`;
  - `workspace_path`;
  - `install_path`;
  - `shell_command` if useful.
- Do not double-start a Python wheel execution when a state file already exists.

## Important Design Constraints

### Stop commands do not reliably carry task type

The current server `create_stop_outbox` sends an empty payload, so the dispatcher
defaults stop commands to `task_type="scrapy"`. Do **not** rely only on
`cmd.task_type` for stop handling. For stop/cancel/reclaim, read the local
`AttemptState.runner_type` when state exists:

- missing state + `intent=cancel`: keep existing behavior and emit canceled;
- `runner_type` absent or `scrapy`: use the existing Scrapy stop behavior;
- `runner_type == "python_wheel"`: signal the process group.

### Existing EventPublisher assumes Scrapy for started states

`EventPublisher.republish_current()` and
`CommandConsumer.reconcile_started_attempts()` currently call
`ScrapyRunner.status()` for every `phase=="started"` state. That is wrong for
wheel states. Make this type-aware without breaking Scrapy:

- done states can keep replaying from stored result/exit_code/error_code;
- started Scrapy states keep the existing Scrapy status behavior;
- started Python wheel states must not call Scrapy status.

Acceptable packet-2 recovery behavior:

- if a Python wheel process is started in this agent process, the runner's
  background waiter should emit terminal events when it exits;
- if the agent restarts and finds a started Python wheel state that it cannot
  safely reattach to, it may mark the execution lost with
  `LostReason.runner_recovered_unknown` after best-effort process-group cleanup.
  It must not start the same execution again.

### Process lifecycle

Do not block command consumption for the whole script duration. The run command
handler should reserve state, start the process, emit accepted/running, and then
let a background wait task mark terminal status.

Track and clean up background wait tasks so tests do not leak subprocesses.

## Out Of Scope

- Dependency management UI or dependency resolution.
- venv support.
- Console-script support.
- Docker/K3s support.
- Full reattachment to a process after agent restart.
- stdout/stderr split streams.
- Edits to `reference/scrapydweb/`.

## Required Output

Create or update:

- `docs/phases/phase-2b/03a-claude-agent-implementation-report.md`
- `docs/phases/phase-2b/claude-progress.md`

The report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- exact commands run and pass/fail outcomes;
- known risks, shortcuts, or incomplete items.

Update `claude-progress.md` at the start and at meaningful checkpoints.

## Required Tests

Add or update tests covering:

- Scrapy command-consumer tests still pass unchanged in behavior.
- Python wheel run success:
  - artifact downloaded/installed or a real cache path is used;
  - process starts;
  - accepted/running/finished events emitted;
  - exit code 0 recorded;
  - merged log contains stdout/stderr.
- Python wheel run failure:
  - non-zero exit code emits failed and records exit code.
- Python wheel invalid/missing artifact or shell command emits failed with a
  structured error.
- Duplicate/redelivered Python wheel run does not start a second process.
- Python wheel cancel sends process-group termination and emits canceled.
- Python wheel reclaim kills resources but does not emit canceled.
- Cleanup removes state and the wheel job log/workspace where appropriate.
- LogPublisher can publish the merged wheel log and EOF using the existing
  `stream="log"`.
- Wheel cache install is idempotent by sha256 and uses `--no-deps --target`.
- Offline smoke with the built-in demo wheel:
  `pip install --no-deps --target <tmp-site>` +
  `PYTHONPATH=<tmp-site> DOPILOT_DEMO_URL=http://127.0.0.1:<local>/headers python -m main`.

## Required Commands

Run:

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check apps packages
```

Also run any narrower agent tests while iterating. If a command cannot run,
record the exact blocker in the implementation report.

## Notes

- Direct `pytest` is not on this shell's PATH; use `.venv/bin/pytest`.
- Direct `ruff` may also be outside PATH; use `.venv/bin/ruff`.
- `.claude/` is pre-existing untracked session state; do not include it.
