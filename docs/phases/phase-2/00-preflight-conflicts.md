# Phase 2 Preflight: Python Wheel Script Support

This is a pre-brief note for phase 2. It records current documentation/code
conflicts and a proposed direction before writing the implementation brief.
It is intentionally not an implementation packet.

## Target From Mainline Docs

Phase 2 adds plain Python3 script execution after the Scrapy path is stable.
The current mainline direction is:

- Build artifacts use `artifact_type=python_wheel` and `.whl` files.
- The existing `dopilot-agent` is reused; no new worker role is introduced.
- Agents run Python wheel scripts in the agent's current Python environment
  without venv isolation. Dependencies are manually maintained by the operator
  inside the agent container/environment.
- Script stdout/stderr are captured as realtime Redis log stream events and
  persisted by the server like existing logs.
- Exit code is authoritative for execution terminal state: `0 -> finished`,
  non-zero -> failed, cancel -> SIGTERM/grace/SIGKILL -> canceled.
- Docker/K3s long-running crawler support remains out of scope.

## Current Conflict Points

0. Redis / agent / log seam names no longer match the product model.

   Current wire/state/log-index fields keep the old phase-1.5 names:

   ```text
   execution_id = Task.id
   attempt_id = Execution.id
   ```

   User decision: phase 2 must unify these names instead of preserving the old
   seam. The target names are:

   ```text
   task_id = Task.id
   execution_id = Execution.id
   ```

   This is a deliberate breaking protocol/data migration. The phase-2 brief must
   include Redis stream schemas, command_outbox, event_audit, execution_log_files,
   agent state files, log paths, services, API query names where applicable, and
   tests. No compatibility layer with old in-flight Redis messages is required
   unless explicitly added later.

   User decisions for phase 2a:

   - Cutover requires no in-flight executions, Redis streams/pending commands
     cleared, and server/agent/protocol deployed as one lockstep version.
   - Legacy HTTP agent/log schemas that still carry the old seam naming should
     be removed if no live code path uses them, rather than renamed and kept.

1. Capability naming is inconsistent.

   Server-side artifact routing expects:

   ```text
   python_wheel -> python_wheel
   docker_image -> docker_runtime
   ```

   but protocol/config currently expose:

   ```text
   script: bool
   docker: bool
   ```

   If phase 2 simply enables `python_wheel`, node selection will not find
   script-capable agents unless this is normalized.

2. Agent command handling is still Scrapy-specific.

   `apps/agent/dopilot_agent/redis/commands.py` consumes every `run` command as
   Scrapy: it parses `scrapy crawl ...`, uses `ScrapyArtifactCache`, and calls
   `ScrapyRunner`. There is no agent-side runner registry keyed by
   `cmd.task_type` / artifact type.

3. Template and resolver validation are still Scrapy-command-first.

   `ExecutionTemplate` validation requires `command` to pass the shared Scrapy
   command parser, and `template_view()` still hardcodes `artifact_type="scrapy"`.
   Python wheels need their own execution input contract; using
   `scrapy crawl` validation for wheel artifacts is wrong.

4. Only Scrapy artifacts are runnable.

   `RUNNABLE_ARTIFACT_TYPES` contains only `scrapy`, and the server executor
   registry only registers `ScrapydExecutor`. Phase 2 must add
   `python_wheel` deliberately instead of treating it as already present.

5. There is no Python wheel artifact store.

   The existing artifact service and API only know Scrapy eggs and
   `/api/v1/artifacts/scrapy/{sha256}/egg`. Phase 2 needs a parallel wheel upload
   and authenticated download path with sha256 validation and metadata.

6. Log file creation currently defaults to one `log` stream.

   User decision: this is acceptable for the first Python wheel slice. Script
   stdout/stderr will be merged by the agent into one combined `log` stream, so
   phase 2 does not need stdout/stderr split-stream support.

7. README and some docs are stale against current code.

   `README.md` still describes phase 0 status, server-pull log wording, old
   agent HTTP tail/status paths, and split image naming. Mainline docs and code
   now reflect Redis Streams, unified image, and Task/Execution clean-cut.

## Proposed Direction

Phase 2 should be split into two consecutive work packets:

- **Phase 2a: id naming clean-cut.** Rename the Redis/agent/log seam from
  `execution_id`/`attempt_id` to `task_id`/`execution_id` everywhere. This must
  preserve existing Scrapy behavior and should be verified before any Python
  wheel runner work starts.
- **Phase 2b: Python wheel shell-command runner.** Add wheel artifact upload,
  template/run resolution, server executor, agent runner registry, Python wheel
  shell-command execution, merged log stream, and process-group cancellation.

This sequencing is intentional: do not mix the seam rename and the new runner in
one implementation packet.

1. Use capability mapping before implementing the runner.

   User decision: keep the existing heartbeat/config wire keys and map artifact
   types to them at the server boundary:

   ```text
   scrapy -> scrapy
   python_wheel -> script
   docker_image -> docker
   ```

   Do not rename `CapabilitySet` to `python_wheel` / `docker_runtime` in phase 2.

2. Introduce type-aware run contracts.

   Keep `ExecutionRunRequest.artifact_type` as the core discriminator. Add a
   Python-wheel payload contract that includes the wheel artifact descriptor plus
   an explicit shell command:

   ```text
   shell_command: str
   env: dict[str, str]
   working_dir: optional relative directory
   ```

   User decision: shell command is allowed because this is an internal platform
   and security/sandboxing is not a phase-2 concern. The command runs in the
   agent's current Python/container environment via a subprocess shell. No venv
   is created or activated in phase 2.

3. Split Scrapy-specific validation from generic template validation.

   Template create/update should first resolve the bound artifact type, then call
   the type-specific validator. Scrapy keeps `scrapy crawl ...` validation.
   Python wheel validates that `shell_command` is non-empty.

4. Add server-side `PythonWheelExecutor`.

   It should mirror `ScrapydExecutor` structurally: create Task/Execution/outbox
   rows transactionally, select nodes with the mapped `script` capability, create
   one combined `log` row, and dispatch a Redis `run` command. It should
   not run Python locally on the server.

5. Add agent-side runner registry.

   Refactor `CommandConsumer` so `run`, `stop`, cleanup, and reconciliation are
   delegated by task/artifact type. Scrapy behavior must remain unchanged.
   Python wheel runner owns wheel installation into the agent current
   environment, subprocess lifecycle, combined stdout/stderr publishing, and
   exit-code terminal events.

   User decisions:

   - Phase 2 does not manage dependencies. The user must manually install any
     required dependencies inside the agent container/environment before running
     a wheel task.
   - Phase 2 does not use venv. The wheel task runs with the agent container's
     fixed Python interpreter/current environment. Multi-version Python support
     is out of scope.
   - Cancellation uses process-group termination: send SIGTERM to the shell
     command's process group, wait a hard-coded 10 seconds, then SIGKILL
     remaining processes and report `attempt.canceled`.
   - Extend existing agent attempt state additively with optional runner/process
     fields; do not replace the Scrapy state-file format.

6. Keep phase 2 scoped.

   Out of scope: Docker/K3s support, source/Git builds, dependency management,
   a script SDK/heartbeat protocol, multi Python versions, multi-replica server,
   stdout/stderr split streams, and WebSocket logging.

## Questions For Claude Feasibility Review

Claude should read the mainline docs and current code, then confirm or correct
the updated plan:

1. Is the phase-2a / phase-2b split sound, or is there a safer split?
2. For phase 2a, what exact code/schema/docs/test surfaces must rename
   `execution_id`/`attempt_id` to `task_id`/`execution_id`?
3. For phase 2a, are there any places where the public API already uses
   `execution_id` correctly for the atomic Execution and should not be renamed?
4. For phase 2b, is the no-venv, current-environment, shell-command design
   coherent with existing agent process/log/state architecture?
5. For phase 2b, what tests are mandatory before implementation is accepted?
6. Are there remaining product or architecture decisions that still need user
   approval before the official briefs are written?
