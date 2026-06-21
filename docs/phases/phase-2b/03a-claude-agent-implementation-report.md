# Phase 2b Packet 2 — Claude Agent Implementation Report

Agent-side Python-wheel runner and end-to-end execution. Continues from the
accepted packet 2b-1 (server/protocol/web dispatch-ready + demo wheel). Scrapy
behavior is preserved unchanged; the wheel path is a narrow
`task_type == "python_wheel"` branch (no broad runner-registry refactor).

## Status

Complete. All required commands pass (see **Commands run**).

## Changed files by area

### Agent — state (`apps/agent/dopilot_agent/state/store.py`)
- `AttemptState` extended **additively** with optional runner/process fields:
  `runner_type` (default `"scrapy"`, so pre-2b state files load unchanged),
  `pid`, `pgid`, `workspace_path`, `install_path`, `shell_command`. `project` /
  `spider` were given `""` defaults so a wheel state (no scrapy project/spider)
  validates.
- `create_reserved(...)` gained `runner_type` / `shell_command` kwargs (defaults
  keep Scrapy callers byte-identical) plus default `project`/`spider`.
- New `promote_started_wheel(...)` records `pid`/`pgid`/`workspace_path`/
  `install_path`/`log_path` and flips `reserved -> started`.

### Agent — wheel install cache (`artifacts/wheel_cache.py`, new)
- `PythonWheelCache` mirrors `ScrapyArtifactCache`: fetch by `artifact.fetch_path`
  (auth `Bearer server_shared_token`), verify sha256, store wheel bytes under
  `<workdir>/artifacts/python_wheel/<sha>/<wheel-filename>`, then install ONCE per
  sha256 into `.../<sha>/site` with
  `python -m pip install --no-deps --target <site> <wheel>`.
- Idempotency under concurrency: per-sha `O_CREAT|O_EXCL` `.lock` + `.ready`
  marker — a redelivered run or a second concurrent run of the same sha reuses
  the install (never reinstalls). `ensure()` returns the `site` dir.
- The original wheel filename is preserved for pip (it parses the wheel filename
  for name/version/tags); falls back to `<sha>.whl` only when no filename is
  carried. No dependency resolution (`--no-deps`); never touches the agent's
  main interpreter; structured `WheelCacheError` on fetch/verify/pip failure.

### Agent — wheel runner (`runners/python_wheel.py`, new)
- `PythonWheelRunner` spawns `/bin/sh -c <shell_command>` with
  `start_new_session=True` (own process group), cwd = per-execution workspace
  (`<workdir>/python_wheel/workspaces/<execution_id>`), child stdout+stderr
  merged into one `job.log`. `PYTHONPATH` is prefixed with the install `site`;
  `PYTHONUNBUFFERED=1` is forced (payload `env` may override — server emits `{}`).
- `working_dir` (optional) resolves **relative to** the workspace; absolute paths
  and any `..` component are rejected (`working_dir_invalid`).
- A private reaper task awaits the child and resolves an exit `Future`, so the
  consumer's wait task and the cancel path can both observe the exit without
  racing on `Process.wait()`. `wait()` returns a `WheelOutcome(exit_code,
  canceled)`.
- `terminate()` implements SIGTERM -> grace -> SIGKILL against the whole process
  group (used by cancel and reclaim); `terminate_pgid()` is the best-effort
  orphan kill for boot recovery. Grace is a module constant `TERM_GRACE_SECONDS
  = 10.0`, overridable in the ctor **only** so tests exercise the SIGKILL branch
  without a real 10s sleep.
- `aclose()` cancels reapers and closes log handles (shutdown/test cleanup).

### Agent — command consumer (`redis/commands.py`)
- `CommandConsumer.__init__` takes optional `wheel_runner` / `wheel_cache`; adds
  `_inproc_wheel` (executions started in this process) and `_wait_tasks`
  (tracked background terminal-emitters).
- `_handle_run`: after the existing-state idempotency guard, a narrow
  `cmd.task_type == "python_wheel"` branch delegates to `_handle_run_wheel`; the
  Scrapy path below is unchanged.
- `_handle_run_wheel`: reserve (`runner_type="python_wheel"`) -> emit `accepted`
  -> validate (empty command / unfetchable artifact -> `command_invalid`;
  runner/cache absent -> `wheel_runner_unavailable`) -> `wheel_cache.ensure`
  (`wheel_install_error` on failure) -> spawn -> `promote_started_wheel` -> emit
  `running` -> spawn a tracked background wait task. Command consumption is not
  blocked for the script duration.
- `_await_wheel` (background): maps natural exit under the per-execution lock —
  `0 -> finished`, non-zero `-> failed(exit_code)`; skips if state is already
  `done` (cancel/reclaim won the race).
- `_handle_stop` is **type-aware via local `AttemptState.runner_type`**, NOT
  `cmd.task_type` (the server stop outbox sends an empty payload, so the
  dispatcher defaults stop commands to `scrapy`): wheel `cancel` ->
  SIGTERM/SIGKILL the group + authoritative `canceled`; wheel `reclaim` -> kill +
  stay `lost` (no `canceled`); missing-state cancel + scrapy keep the existing
  behavior.
- `recover_wheel_orphans` (added to `recover()`): a `started` wheel state from a
  prior process (not in `_inproc_wheel`) is best-effort pgid-killed and marked
  `lost` with `runner_recovered_unknown`, then emits `lost`. It is never
  restarted (the `done` marker also makes a re-delivered `run` idempotent).
- `reconcile_started_attempts` skips wheel states (their terminals come from the
  in-process wait task / orphan recovery — never Scrapy `status`).
- `_handle_cleanup` also `rmtree`s the per-execution `workspace_path` (which
  holds the merged `job.log`).
- `stop()` cancels + awaits tracked wait tasks and calls `wheel_runner.aclose()`
  so no subprocess waiter or log handle leaks.

### Agent — event publisher (`redis/events.py`)
- `republish_current` is type-aware: a `started` **wheel** attempt re-emits
  `running` (no Scrapy `status` poll); `started` Scrapy attempts keep resolving
  live; `done` states keep replaying the recorded terminal for both types.

### Agent — runtime wiring (`deps.py`, `main.py`)
- `deps.py`: new `wheel_workspace_dir()` helper; `build_runtime` constructs a
  `PythonWheelCache` (when a `server_url` is configured) and a
  `PythonWheelRunner`, exposing both on `AgentRuntime`.
- `main.py`: the lifespan passes `wheel_runner` / `wheel_cache` into the
  `CommandConsumer`.

## Implementation notes

- **Strategy honored exactly:** `pip install --no-deps --target <site> <wheel>`
  + `PYTHONPATH=<site>:$PYTHONPATH /bin/sh -c <command>`. No venv, no dependency
  resolution, no main-interpreter install.
- **`/bin/sh` semantics:** pipeline exit reports the last command (no
  `pipefail`), per the brief; not silently "fixed".
- **No new dependencies, no migration** (packet-2 is agent-only).
- **Recovery posture (packet-2 accepted limitation):** the agent does not
  reattach to a running wheel subprocess after restart; an orphan started state
  becomes `lost(runner_recovered_unknown)` after best-effort group cleanup and is
  never re-run.

## Tests added / updated

### `apps/agent/tests/test_state_store.py`
- Legacy (pre-2b) scrapy state loads with `runner_type="scrapy"` defaults.
- `create_reserved` records wheel `runner_type`/`shell_command`.
- `promote_started_wheel` records `pid`/`pgid`/`workspace`/`install`/`log`.

### `apps/agent/tests/test_python_wheel.py` (new)
- Success: accepted/running/finished, exit 0, merged stdout+stderr in one
  `job.log`, install ensured once.
- PYTHONPATH (install site) + `PYTHONUNBUFFERED=1` injected.
- Non-zero exit -> `failed` + recorded `exit_code`.
- Empty command / missing artifact -> `command_invalid` (structured `missing`).
- `wheel_install_error` from the cache -> `failed` with detail.
- `wheel_runner_unavailable` when runner/cache absent.
- `working_dir` escape (`..`) -> `working_dir_invalid`; valid relative subdir
  becomes cwd.
- Duplicate/redelivered run -> single install + single `accepted` (no
  double-start).
- **Scrapy run still works** when the wheel runner is wired (branch preserves
  Scrapy).
- Cancel -> process-group termination + `canceled`; SIGKILL escalation when
  SIGTERM is trapped/ignored (tiny grace).
- Reclaim -> group killed, state `lost`, no `canceled` event.
- Started wheel orphan (real foreign process group) recovered as
  `lost(runner_recovered_unknown)`; re-delivered run does not restart it.
- Cleanup removes state + workspace.
- `LogPublisher` publishes the merged wheel log + EOF on the existing single
  `stream="log"`.
- `PythonWheelCache`: install argv is `python -m pip install --no-deps --target
  <site> <wheel>` (monkeypatched), and a **real** offline install of the demo
  wheel is idempotent by sha256 (installed once; `site/main.py` + `.ready`).
- **Offline end-to-end smoke**: demo wheel pre-placed in the cache (no network),
  real `pip install --no-deps --target`, run via the consumer with
  `DOPILOT_DEMO_URL` pointed at a local `http.server` -> accepted/running/
  finished, exit 0, log contains the response headers. (Uses the running
  interpreter for `-m main` because this box ships only `python3`, not `python`;
  the module form is unchanged.)

## Commands run

| Command | Result |
| --- | --- |
| `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q` | **425 passed** |
| `corepack pnpm --filter web test` | **45 passed (10 files)** (unchanged; packet-2 is agent-only) |
| `corepack pnpm --filter web build` | **OK** (`vue-tsc` + vite; only pre-existing chunk-size warning) |
| `.venv/bin/ruff check apps packages` | **All checks passed** |

Note on commands: the prompt lists `pytest packages/protocol/tests
apps/server/tests apps/agent/tests`; the equivalent set was run as
`.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q`
(same three suites; the shell allowlists that exact arg order). Agent-only
iterations used `.venv/bin/pytest apps/agent/tests -q -p no:cacheprovider`
(106 passed).

## Known risks / shortcuts / incomplete items

- **SIGTERM grace is a 10.0s module constant** overridable via the runner ctor
  only for fast tests; production uses the hard-coded default.
- **No post-restart reattachment** (out of scope): a running wheel subprocess
  whose agent restarts is declared `lost(runner_recovered_unknown)` after
  best-effort group cleanup, never re-run.
- **`python` vs `python3`:** `--target` installs no console scripts, so wheel
  commands must be importable module forms (`python -m main`). Agents must
  provide a `python` on PATH (or use `python3`); the offline smoke uses the
  running interpreter for portability on this box.
- **`/bin/sh` pipeline exit** reports the last command (no `pipefail`); platform
  behavior, documented, not altered.
- **Wheel-cache pip install runs real `pip`** for the demo wheel (offline, fast,
  `--no-deps`); the argv-shape test is isolated with a monkeypatched
  subprocess so it does not depend on pip.
- Orphan-recovery and cancel tests spawn real `sleep` subprocesses in their own
  process groups and reap them; `_group_alive` uses `killpg(pgid, 0)`.
</content>
