# Phase 2b Brief: Python Wheel Shell-Command Runner

## Goal

Add support for running plain Python3 script tasks packaged as `.whl` build
artifacts.

Phase 2b extends the existing BuildArtifact -> ExecutionTemplate -> Task ->
Execution pipeline. It must reuse the existing dopilot-agent, Redis command
streams, Redis log streams, node selection, schedules, and server-side log
storage. It must not introduce a new worker role or run Python on the server.

The user-selected wheel execution strategy for this phase is:

```text
pip install --no-deps --target <agent-cache>/python_wheel/<sha256>/site <wheel>
PYTHONPATH=<site-dir>:$PYTHONPATH /bin/sh -c "<command>"
```

This deliberately avoids venv creation and avoids mutating the agent's main
Python environment with `pip install` side effects. Dependencies are not managed
by dopilot; operators must install required dependencies in the agent
container/environment manually. Wheel dependency metadata is ignored with
`--no-deps`.

Because `--target` does not install console-script entry point wrappers into the
agent PATH, phase 2b only promises commands that can run with the injected
`PYTHONPATH`, for example `python -m main` or `python -m package.module`.
`python test.py` only works if `test.py` exists in the command working
directory. Console scripts can be revisited in a later phase if needed.

## Context

Required context:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`
- `docs/phases/phase-2/00b-plan-review.md`
- `docs/phases/phase-2a/03-acceptance-report.md`
- `docs/phases/phase-2b/00a-feasibility-review.md`
- `packages/protocol/dopilot_protocol/execution.py`
- `apps/server/dopilot_server/services/states.py`
- `apps/server/dopilot_server/services/artifacts.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/dopilot_server/services/resolve.py`
- `apps/server/dopilot_server/executors/`
- `apps/agent/dopilot_agent/redis/commands.py`
- `apps/agent/dopilot_agent/state/store.py`
- `apps/agent/dopilot_agent/redis/logs.py`

Current docs still contain older phase-2 wording about venv and/or installing
wheel packages into the agent's main interpreter. This brief is the active
phase-2b source of truth: no venv, no dependency management, no main-environment
pip install, use `pip install --no-deps --target` plus `PYTHONPATH`.

## Confirmed Decisions

- Artifact type: `python_wheel`.
- Package format: `wheel`.
- Capability mapping at node selection boundary:

  ```text
  scrapy -> scrapy
  python_wheel -> script
  docker_image -> docker
  ```

- Redis command runner discriminator remains `task_type="python_wheel"`.
  Capability names and runner task types are intentionally distinct.
- User input field stays `ExecutionTemplate.command`. For `python_wheel`, this
  value means shell command and is serialized to the agent payload as
  `shell_command`.
- Shell commands are allowed. This is an internal platform; command sandboxing is
  out of scope.
- Stdout and stderr are merged into one existing `log` stream.
- Cancellation sends SIGTERM to the process group, waits a hard-coded 10
  seconds, then sends SIGKILL to the remaining process group before reporting
  canceled.
- No DB migration should be introduced unless implementation proves one is
  unavoidable. Type-specific data must fit existing JSON fields and the existing
  `ExecutionTemplate.command` column.

## Work Packet Split

Implement phase 2b as two ordered packets.

### Packet 2b-1: Server, Protocol, Web, Demo Wheel

Make Python wheel runs dispatch-ready but not yet executable end-to-end.

In scope:

- Add a protocol `PythonWheelRunPayload` typed model.
- Make `python_wheel` runnable in server state and map it to the `script`
  capability.
- Add a wheel artifact store, upload endpoint, authenticated download endpoint,
  dedupe by `(artifact_type, content_hash)`, and artifact list/view metadata.
- Add a built-in demo wheel fixture under `tests/fixtures/python_wheel_demo/`.
  The built wheel should contain only a `main.py` module as the user-facing code
  payload; wheel metadata/build files are allowed because the `.whl` format
  requires them.
- Demo `main.py` must request httpbin headers and print response headers using
  Python stdlib only. The URL must be configurable by environment variable so
  tests can use a local HTTP server instead of relying on external network.
  Default URL: `https://httpbin.org/headers`.
- Split Scrapy command validation from Python wheel command validation.
  Scrapy keeps the existing `scrapy crawl ...` parser and spider-in-artifact
  validation. Python wheel requires only a non-empty command.
- Resolve Python wheel templates into a task snapshot and params using
  `shell_command`, `artifact`, `env={}`, and `working_dir=None`.
- Add/register a server-side `PythonWheelExecutor` that mirrors the Scrapy
  executor's transaction/outbox shape: select `script`-capable nodes, create
  Task/Execution/log rows, create `run` outbox rows, dispatch to Redis.
  It must never execute Python on the server.
- Update web/client types and UI so users can upload `.whl`, create/edit wheel
  templates, and run/schedule them using the existing command field relabeled as
  a shell command for wheel artifacts.
- Keep Scrapy behavior unchanged.

Out of scope for 2b-1:

- Agent-side wheel download/install/subprocess execution.
- End-to-end successful Python wheel execution.
- Dependency management UI or install controls.
- Console-script support.

### Packet 2b-2: Agent Runner And End-To-End Execution

Make dispatched Python wheel commands execute on the agent.

In scope:

- Add a narrow `cmd.task_type == "python_wheel"` branch in
  `apps/agent/dopilot_agent/redis/commands.py`. Do not perform a broad runner
  registry refactor in this phase.
- Keep the existing Scrapy path behavior unchanged.
- Add a wheel artifact cache keyed by sha256.
- Install each wheel once per sha256 into `<agent-cache>/python_wheel/<sha>/site`
  using `pip install --no-deps --target ...`.
- Inject that site directory through `PYTHONPATH` when launching the shell
  command.
- Launch `/bin/sh -c <shell_command>` with `start_new_session=True`.
- Create a per-execution workspace keyed by `execution_id`; if `working_dir` is
  present in the payload, resolve it relative to that workspace and reject
  absolute paths or `..` escapes.
- Force `PYTHONUNBUFFERED=1` unless explicitly overridden by future task env
  support. Current server emits `env={}`.
- Merge child stdout and stderr into one `job.log` file and reuse the existing
  Redis log publisher with `stream="log"`.
- Natural exit maps `0 -> attempt.finished`, non-zero -> `attempt.failed` with
  `exit_code`.
- Cancel maps to `attempt.canceled` regardless of the child exit code after the
  SIGTERM/SIGKILL flow.
- Extend agent `AttemptState` additively with optional runner/process fields
  such as `runner_type`, `pid`, `pgid`, `workspace_path`, and `install_path`.
  Existing Scrapy state files must still load.
- On startup/recovery, do not double-start a Python wheel execution if a state
  file already indicates the execution was accepted/started.

Out of scope for 2b-2:

- Full orphan-process recovery guarantees after agent crash.
- Script SDK/heartbeat protocol.
- stdout/stderr split streams.
- venv, dependency resolution, PyPI access, multi-Python-version support.
- Docker/K3s support.

## Required Implementation Order

1. Packet 2b-1: protocol/state mapping and tests.
2. Packet 2b-1: wheel store/API and built-in demo wheel fixture.
3. Packet 2b-1: type-aware template validation and resolve snapshots.
4. Packet 2b-1: server `PythonWheelExecutor`, outbox payload, web/client UI.
5. Codex review of packet 2b-1 before agent work.
6. Packet 2b-2: agent cache/install/subprocess runner.
7. Packet 2b-2: cancellation, logging, recovery/idempotency tests.
8. End-to-end smoke test with the built-in demo wheel.

## Acceptance Criteria

- `python_wheel` artifacts can be uploaded, listed as runnable, deduped by
  sha256, and downloaded byte-identically by authenticated agents.
- Node selection for a Python wheel run requires `capabilities.script == true`.
- A Scrapy-only node is not selected for a Python wheel run.
- Python wheel templates accept arbitrary non-empty shell commands and do not
  run through the Scrapy command parser.
- Scrapy templates still use the Scrapy command parser and spider validation.
- Python wheel task snapshots preserve `artifact_type="python_wheel"` and store
  `shell_command` in `params`/payload.
- Server creates Task/Execution/outbox/log rows transactionally for wheel runs.
- Agent executes the shell command with the wheel target directory on
  `PYTHONPATH`.
- Built-in demo wheel runs with `python -m main` and prints response headers.
- Logs stream through the existing single `log` stream and persist through the
  existing server log consumer path.
- Natural exit status and cancellation status converge correctly.
- Existing Scrapy tests continue to pass.

## Required Tests

Packet 2b-1:

- Protocol unit tests for `PythonWheelRunPayload` and `AgentCommand` round trip
  with `task_type="python_wheel"`.
- Server tests for capability mapping:
  `ARTIFACT_CAPABILITY["python_wheel"] == "script"`.
- Server artifact API/store tests:
  upload `.whl`, reject non-wheel, sha256 dedupe, authenticated download bytes.
- Server template/resolve tests:
  wheel command non-empty validation, empty command rejection, Scrapy validation
  unchanged, dynamic `template_view.artifact_type`.
- Server executor tests:
  script-capable node selection, outbox payload shape, log row creation, no
  local Python execution on server.
- Web tests for wheel upload/template UI, plus existing web tests.

Packet 2b-2:

- Agent unit tests for `task_type` dispatch preserving Scrapy behavior.
- Agent wheel cache/install tests using a local wheel fixture and no external
  network.
- Agent runner tests for success, non-zero failure, merged log output, and
  SIGTERM -> 10s -> SIGKILL cancellation.
- Agent idempotency/recovery tests proving redelivered `run` does not
  double-start a started Python wheel execution.
- End-to-end or integration smoke using the built-in demo wheel against a local
  HTTP server. A real httpbin smoke is optional and must be recorded as external
  network dependent.

## Required Commands

Use the narrowest commands that cover the packet, then broaden before final
acceptance.

Packet 2b-1 minimum:

```bash
pytest packages/protocol/tests apps/server/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
ruff check apps packages
```

Packet 2b-2 minimum:

```bash
pytest packages/protocol/tests apps/server/tests apps/agent/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
ruff check apps packages
```

Final phase-2b acceptance should also run any available integration/smoke
command that exercises the built-in wheel through server -> Redis -> agent ->
logs. If no such command exists, add one or document the exact manual smoke
steps and residual risk.

## Risks To Watch

- `pip install --target` does not create console scripts; users must invoke
  importable modules or files in the working directory.
- `/bin/sh` pipeline exit semantics report the last command in a pipeline. The
  platform should document this behavior; do not silently promise bash
  `pipefail`.
- Existing docs still mention venv. Do not reintroduce venv in implementation.
- Do not add dependency installation controls; this version requires manual
  dependency provisioning inside the agent environment.
- Process cancellation must target the process group, not only the shell pid.
- Avoid broad Scrapy runner refactors while adding the first subprocess runner.
- Do not edit, import, or copy from `reference/scrapydweb/`.
