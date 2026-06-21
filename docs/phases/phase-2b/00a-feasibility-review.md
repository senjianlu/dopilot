# Phase 2b Feasibility Review

> Claude read-only feasibility validation for **phase 2b: Python wheel
> shell-command runner**, assuming phase 2a (id naming clean-cut) has landed and
> is accepted (`docs/phases/phase-2a/03-acceptance-report.md`). Citations are
> `path:line` into the **current dopilot tree** (not `reference/scrapydweb/`,
> which was not read). No application code changed.

## Verdict

**Feasible.** The no-venv / shell-command design fits the existing
artifact-store, executor-registry, command-outbox, runner, state-CAS, and
log-publisher seams cleanly. The protocol wire needs **no breaking change**
(`AgentCommand.payload` and `Task.params`/`template_snapshot` are already
free-form dicts), and **no DB migration is required** (artifact_type is a plain
`String`, and all type-specific data fits existing JSON columns + the existing
nullable `command` column).

Three things are genuinely new and carry the risk: (1) the agent gains its
**first real subprocess job runner** (today Scrapy jobs run inside `scrapyd` over
HTTP — `runners/scrapyd.py:56-75`, `scrapyd/client.py:109-135` — the agent never
launches the user's process), (2) `_handle_run` is **hardcoded to Scrapy**
(`redis/commands.py` parses `parse_scrapy_command`, ensures an egg, calls
`scrapyd`), and (3) the accepted `python_wheel -> script` capability mapping
**contradicts current code**, which maps `python_wheel -> python_wheel`
(`services/states.py:69`) with a test asserting it (`tests/test_resolve.py:149`).
None of these is a blocker; all are bounded.

## Scope And Split Recommendation

Phase 2b is shippable as **one packet**, but the safest decomposition is a
**two-step split along the Redis wire contract** — the wire is a clean,
independently-testable boundary:

- **2b-1 — Server/protocol/web (dispatch-ready, not yet runnable end-to-end).**
  Wheel artifact store + upload/download API + web upload UI; capability mapping
  fix (`python_wheel -> script`); add `python_wheel` to `RUNNABLE_ARTIFACT_TYPES`;
  type-aware template validation + `resolve_run` branch; `PythonWheelExecutor`
  registered; outbox `run` command carries the wheel payload.
  *Acceptance:* a `python_wheel` template validates (non-empty `shell_command`),
  resolves, creates Task/Execution/outbox/`log` rows in one transaction, selects
  a `script`-capable node, and XADDs a well-formed `run` command. No Python runs
  on the server. Scrapy path byte-for-byte unchanged.
- **2b-2 — Agent runner.** Narrow runner dispatch on `cmd.task_type`; wheel
  download/cache; subprocess launch in its own session/process-group with
  `PYTHONUNBUFFERED=1`; merged stdout/stderr -> single `log`; exit-code mapping;
  SIGTERM→10s→SIGKILL cancellation; additive `AttemptState` fields.
  *Acceptance:* end-to-end run of a wheel template; `0->finished`,
  non-zero->`failed`, `intent=cancel`->`attempt.canceled` regardless of exit
  code; re-delivered `run` does not double-start (state CAS on `execution_id`).

If the user prefers a single packet, keep this as the internal ordering
(server/wire first, agent runner second) so the contract is frozen before the
runner is built. Recommend the two-step split; it keeps the agent's
first-ever subprocess runner out of the same diff as the server/upload surface.

## Server/API Surface

Exact change sites (no migration; see below):

- **`services/states.py`** — add `ARTIFACT_PYTHON_WHEEL` to
  `RUNNABLE_ARTIFACT_TYPES` (`:59`); change `ARTIFACT_CAPABILITY["python_wheel"]`
  from `"python_wheel"` to `"script"` (`:69`) per the accepted boundary mapping.
  Update the "only scrapy runnable in 1.8" comments (`:50-51,58`).
- **`services/artifacts.py`** — add `upsert_python_wheel(...)` mirroring
  `upsert_scrapy()`; dedup stays `(artifact_type, content_hash)`
  (`models/execution.py:257-260`); `artifact_metadata` JSON carries wheel facts
  (e.g. `{distribution, version, ...}`) instead of `spiders`. `runnable` is
  computed from `RUNNABLE_ARTIFACT_TYPES`, so it flips on automatically.
- **`api/v1/artifacts.py`** — add `POST /artifacts/python_wheel/wheel` (upload,
  `.whl`, sha256) and `GET /artifacts/python_wheel/{sha256}/wheel`
  (authenticated download), paralleling the egg endpoints (`:54-96`).
- **`services/templates.py`** — `_validate_basics` (`:52`) and create/update
  (`:76-78,111-113`) call Scrapy-only validators unconditionally; branch on the
  bound artifact's type: Scrapy keeps `validate_command`/
  `validate_command_for_artifact`; wheel validates `command` (reused as
  `shell_command`) is non-empty only. `template_view()` already hardcodes
  `artifact_type="scrapy"` (preflight item 3 / plan-review) — make it dynamic.
- **`services/resolve.py`** — `resolve_run` has `if artifact_type == "scrapy"`
  (`:140-150`); add an `elif "python_wheel"` branch that skips
  `parse_scrapy_command`, leaves `spider=None`, and builds `params`/`snapshot`
  with `shell_command` (+ `env`, `working_dir`) instead of a scrapy `command`.
- **`executors/registry.py`** — register `PythonWheelExecutor()` (`:14-18`).
- **New `executors/python_wheel.py`** — structurally mirror `ScrapydExecutor`:
  resolve nodes with `capability=ARTIFACT_CAPABILITY[artifact_type]` (= `script`),
  create Task/Execution/`log`-row/`run`-outbox transactionally, dispatch to
  Redis. **Never runs Python on the server.**
- **`nodes/service.py`** — no change; capability filtering is generic string
  match. Selection works once the mapping returns `script` and an agent
  advertises `capabilities.script=true`.

**Reuse of the `command` column for `shell_command`:** the `ExecutionTemplate`
has one nullable `command` column (`models/scheduling.py`), the web sends
`command` (`api/types.ts` `CreateExecutionTemplateRequest`), and `resolve_run`
reads `command`. Reusing it for the shell command avoids a migration. Recommend
reuse, but the web must relabel/branch validation (see Docs To Update + Residual
Risks). A new dedicated `shell_command` column would force a migration — avoid.

## Protocol Payload

No schema break. The `run` command travels as `AgentCommand`
(`streams.py:90-107`) with `payload: dict[str, Any]`; add a typed
`PythonWheelRunPayload` in `protocol/execution.py` (sibling of `ScrapyRunPayload`,
`:41-53`) for validation symmetry. Shape:

```text
PythonWheelRunPayload:
  task_type: str = "python_wheel"   # wire discriminator; agent runner-registry key
  shell_command: str                # REQUIRED, non-empty
  artifact: dict                    # REQUIRED: {sha256, hash, filename, fetch_path, size_bytes, distribution, version}
  env: dict[str, str] = {}          # OPTIONAL, operator-supplied overrides
  working_dir: str | None = None    # OPTIONAL, relative path under the per-execution workspace
```

Set `AgentCommand.task_type="python_wheel"` (today defaults `"scrapy"`,
`streams.py:106`) so the agent dispatches on it. Capability (`script`, for node
selection) and `task_type` (`python_wheel`, for runner dispatch) are
**deliberately distinct** — do not conflate. `AgentEvent`/`AgentLogEvent` need no
change: `exit_code`/`error_code`/`error_detail` already exist
(`streams.py:182-200`) and all terminal `AgentEventType`s
(finished/failed/canceled/lost) are present (`:115-128`).

## Agent Architecture

**Add a narrow type branch first; do not big-bang a registry refactor.** The
risk to Scrapy is concentrated in `_handle_run`, which interleaves the shared
two-phase state CAS (`create_reserved` O_CREAT|O_EXCL -> `promote_started`),
idempotent re-publish, and event emission with the Scrapy-specific middle
(parse command -> ensure egg -> `scrapyd.schedule`). Keep all the shared
scaffolding in `CommandConsumer` untouched and delegate **only the type-specific
middle** by `cmd.task_type`:

- `task_type == "scrapy"` -> existing code path, byte-for-byte (regression bar).
- `task_type == "python_wheel"` -> new `ScriptRunner` (wheel fetch + subprocess
  launch + terminal-status resolution from exit code).

This is lower-risk than extracting a `BaseRunner` interface now, because the
Scrapy lifecycle is *poll/reconcile-based* (it asks `scrapyd listjobs` for
terminal status — `runners/scrapyd.py:148-170`, `commands.py`
`reconcile_started_attempts`) whereas the wheel runner is *process-wait-based*
(it owns the child and learns the exit code directly). Those two terminal-status
models do not share an abstraction cleanly; forcing one now would perturb the
Scrapy reconcile path. A registry can be extracted later once a third type
(docker) exists.

`AttemptState` (`state/store.py:33-63`) is extended **additively** with optional
fields (`runner_type`, `pid`, `pgid`, `exit_code` already exists) — Pydantic
defaults keep existing Scrapy state files loading. `LogPublisher`
(`redis/logs.py`) is reused unchanged: it tails `state.log_path` by byte offset,
base64-encodes, single `stream="log"`, cursor `.logpos` — the wheel runner just
points `log_path` at the merged job log it writes.

## Wheel Handling Without Venv

**Recommendation: cache the wheel bytes by sha256 (like the egg cache,
`artifacts/cache.py:39-95`), then `pip install --no-deps <cached.whl>` into the
agent's current interpreter, idempotently, guarded by a per-sha256 install
marker + O_CREAT|O_EXCL lock.** Then run the shell command from the
per-execution workspace.

Rationale, consistent with the accepted decisions:

- `--no-deps` = no PyPI resolution, no dependency management (operator
  pre-provisions deps in the image) — exactly the accepted contract.
- Installing into the current interpreter (no venv) is what "runs in the agent
  container's current Python/environment" means, and it is the only option that
  makes the wheel's **console-script entry points** available to an arbitrary
  `shell_command` (e.g. `mypkg-cli ...`). Byte-cache-only / `--target`+PYTHONPATH
  do **not** create entry-point scripts, so they silently break that class of
  command.
- Idempotent by sha256 marker -> re-runs skip reinstall; concurrent-install lock
  prevents two executions racing `pip`.

**Accepted cost (flag to user, not a blocker):** a single fixed interpreter +
no venv means two wheels needing different versions of the same distribution
**collide** in the base env — consistent with "multi-version out of scope," but
it mutates the shared interpreter across runs. The lower-pollution alternative
(`pip install --no-deps --target <per-sha dir>` + prepend `PYTHONPATH`) keeps the
base env clean but **loses entry-point scripts** and needs the runner to inject
`PYTHONPATH`. Recommend plain `--no-deps`; list `--target` as the residual
decision (below). If the user's wheels are always invoked as `python -m pkg`
(no console scripts), `--target` becomes the better default.

## Shell Semantics

Pin these in the brief so "exit code is authoritative" is unambiguous:

- **Shell:** `/bin/sh -c "<shell_command>"` launched via
  `asyncio.create_subprocess_exec("/bin/sh", "-c", shell_command,
  start_new_session=True, ...)`. Exit code authority = the child shell's exit
  status. **Pipeline caveat:** on dash (`/bin/sh` in debian-slim) `a | b` reports
  only `b`'s status and `pipefail` is unavailable; document this so a failing
  upstream stage in a pipeline does not silently map to `finished`. (Residual
  decision: optionally use `bash -o pipefail` if present.)
- **stdout/stderr:** merge — redirect child `stderr` into `stdout`, write one
  merged `job.log` at `state.log_path`; reuse `LogPublisher` with single
  `stream="log"` (no new rows/cursors).
- **env precedence (low -> high):** agent `os.environ` (base) < dopilot-injected
  defaults (`PYTHONUNBUFFERED=1`, optional `DOPILOT_*` identifiers) <
  task-supplied `env` (operator overrides win). Always force
  `PYTHONUNBUFFERED=1` unless the operator explicitly overrides it, so logs
  stream without buffering.
- **working directory:** a per-execution workspace root keyed by the atomic
  `execution_id` (post-2a), e.g. `{agent_data}/workspaces/{execution_id}/`;
  optional `working_dir` resolved **relative** to that root, rejecting absolute
  paths and `..` escape. Created on run, removed on `cleanup_logs`.
- **process-group lifecycle:** `start_new_session=True` (setsid) **before** exec
  so the shell + descendants share a new session/process-group; signal the group
  via `os.killpg(os.getpgid(pid), ...)`. Cancel: SIGTERM to the group -> wait a
  hard-coded 10s -> SIGKILL the group -> reap. Under `intent=cancel` the
  authoritative terminal is `attempt.canceled` **regardless of exit code**
  (`streams.py` StopIntent), `intent=reclaim` keeps `lost`; only a natural exit
  maps `0->finished`, non-zero->`failed`. Persist `pid`/`pgid` to `AttemptState`
  so a restarted agent can reclaim/kill an orphaned group.

## Required Verification

Mandatory before acceptance (extends plan-review §"Required Tests > Phase 2b",
`docs/phases/phase-2/00b-plan-review.md:240-259`):

- **Capability mapping:** `ARTIFACT_CAPABILITY["python_wheel"] == "script"`; a
  `python_wheel` artifact selects a `script`-capable node and excludes
  scrapy-only nodes; **`tests/test_resolve.py:149` is updated** from
  `"python_wheel"` to `"script"` (it currently asserts the old mapping).
- **Runnable + executor:** `python_wheel` in `RUNNABLE_ARTIFACT_TYPES`;
  `PythonWheelExecutor` creates Task/Execution/outbox/`log` rows in one
  transaction and dispatches `run`; no Python runs on the server.
- **Artifact store:** `.whl` upload -> sha256 dedup on `(artifact_type,
  content_hash)` -> authenticated download is byte-identical; wrong-type upload
  rejected.
- **Template/resolve:** wheel binding requires non-empty `shell_command`,
  rejected when empty; Scrapy template still validates command-first;
  `template_view` reports the bound artifact's real `artifact_type`.
- **Protocol round-trip:** `PythonWheelRunPayload` / `AgentCommand` with
  `task_type="python_wheel"` serialize and `from_stream_entry` decode; Scrapy
  payload unchanged.
- **Agent dispatch:** runner branch selects on `cmd.task_type`; Scrapy path
  unchanged (regression — existing `test_command_consumer.py`/`test_runner.py`
  pass without edits).
- **Wheel runner:** download+cache by sha256, install once (idempotent on
  re-run), subprocess in its own process group, `PYTHONUNBUFFERED=1`, merged
  stdout/stderr -> single persisted `log` (offset append/dedup/gap unchanged).
- **Exit mapping:** `0->finished`, non-zero->`failed`.
- **Cancel:** SIGTERM -> 10s -> SIGKILL on the group -> `attempt.canceled` under
  `intent=cancel` regardless of exit code; orphan reap on SIGKILL.
- **Idempotency:** re-delivered `run` does not double-start (state CAS keyed by
  the atomic `execution_id`).
- **Web:** wheel upload path; template form accepts a wheel artifact and a
  shell command without Scrapy-grammar rejection (`TemplatesPage` currently calls
  `checkScrapyCommand` unconditionally).
- **Suite/lint:** `pytest packages/protocol/tests apps/server/tests
  apps/agent/tests`, `ruff check apps packages`,
  `corepack pnpm --filter web test && corepack pnpm --filter web build`,
  `cd deploy/docker && docker compose config`. (No migration to run.)

## Docs To Update

- `services/states.py` comments (`:50-51,58`) — `python_wheel` is now runnable;
  capability is `script`.
- `models/execution.py` `BuildArtifact` docstring (`:239-253`) and
  `executors/registry.py` comment (`:3,16`) — drop "reserved/not executable".
- `apps/web/src/api/types.ts` — `ArtifactType = "scrapy"` union (`:73`) gains
  `"python_wheel"`; document `command` doubling as the wheel `shell_command`.
- `docs/dopilot/00-requirements.md` / `10-roadmap.md` — mark scheduled-object
  type ③ (plain Python3) in progress/done; record no-venv / no-dependency-control
  / operator-managed-deps as the chosen execution model.
- `docs/phases/phase-2/00a-feasibility-review.md` — its venv/`entry_point`
  assumptions are superseded by the no-venv shell-command decision (plan-review
  already noted this; reconfirm here).
- `README.md` — already stale (preflight item 7); refresh artifact-type coverage
  if touched.
- `tests/test_resolve.py:149` — the capability assertion (code, but it gates the
  mapping change).

## Residual Risks

Needing a user call beyond the already-accepted decisions:

1. **Capability mapping change** — `ARTIFACT_CAPABILITY["python_wheel"]:
   "python_wheel" -> "script"` plus updating `test_resolve.py:149`. Accepted in
   the prompt ("map at the server boundary"); confirm it overrides the current
   code/test. (Plan-review Remaining Decision #8.)
2. **Wheel install strategy** — `pip install --no-deps` into the current
   interpreter (recommended; supports entry-point scripts; mutates+collides the
   shared env) vs `--no-deps --target <per-sha>` + `PYTHONPATH` (clean env; no
   entry-point scripts). Needs a call; depends on whether wheels are invoked as
   console scripts or `python -m`.
3. **`shell_command` storage** — reuse the existing `ExecutionTemplate.command`
   column (recommended; no migration) vs a dedicated column (migration). Confirm
   reuse.
4. **Shell + pipeline exit-code** — `/bin/sh -c` with dash's last-stage-only
   exit status (no `pipefail`); accept, or use `bash -o pipefail` when present.
5. **10s cancellation grace** — hard-coded (as decided) vs a config knob.
6. **Base-env pollution / cross-task version collision** — explicitly accepted
   under "multi-version out of scope," but it persists across runs; confirm.
7. **No shell validation/sandbox** — wheel `shell_command` is free-form, only
   non-empty-checked, run as the agent user with full env. Accepted ("internal
   platform, no sandboxing"); reconfirm as a product call.
8. **Workspace + install-marker lifecycle** — per-execution workspace and the
   sha256 install marker are cleaned by `cleanup_logs`/TTL sweep; confirm the GC
   owner so workspaces don't accumulate.

## Commands Run

- `Read` of `CLAUDE.md`, `AGENTS.md`, `docs/agent-governance/00`/`01`,
  `docs/phases/phase-2/00-preflight-conflicts.md`,
  `docs/phases/phase-2/00b-plan-review.md`,
  `docs/phases/phase-2a/03-acceptance-report.md`, and the phase-2b prompt.
- Targeted `Read` of `services/states.py`, `services/resolve.py`,
  `services/templates.py` to confirm the capability mapping, the
  `if artifact_type == "scrapy"` resolve branch, and the unconditional Scrapy
  validators.
- Three `Explore` sub-agents (server; protocol+agent; web+tests) over
  `apps/`/`packages/`/`docs/` (excluding `reference/`) to inventory the artifact
  store, executor/registry, command-outbox, runner/state/log seams, web upload +
  template forms, and the test surface.
- `rg` for `python_wheel` / `RUNNABLE_ARTIFACT_TYPES` / `artifact_type` /
  `shell_command` / `capability` (excluding `reference/`).
- No files outside the two allowed report paths were modified; no
  `reference/scrapydweb/` code was read.
