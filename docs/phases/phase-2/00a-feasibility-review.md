# Phase 2 Feasibility Review

> Claude feasibility validation of `docs/phases/phase-2/00-preflight-conflicts.md`.
> Read/analysis only — no application code was changed. Citations are
> `path:line` into the **current dopilot tree** (not the scrapydweb reference).

## Verdict

The preflight conflict list is **substantially accurate**: 6 of 7 conflicts are
confirmed against current code, 1 (README staleness) is confirmed by inspection.
Codex's proposed direction is sound. The one place I diverge from the preflight
is **capability naming**: canonicalizing `CapabilitySet` to
`python_wheel`/`docker_runtime` is the *more* disruptive option, not the least
risky. I recommend keeping `script`/`docker` as the wire capability keys and
fixing the server-side `ARTIFACT_CAPABILITY` mapping instead — consistent with
the project's existing "stable wire seam + translate at the boundary" pattern
(`execution_id`/`attempt_id`, `task_type`). Phase 2 is feasible without
destabilizing Scrapy if the agent runner split and the Scrapy state model are
treated as the high-risk areas.

## Conflict Review

1. **Capability naming inconsistent — confirmed.**
   `CapabilitySet` is `{scrapy, script, docker}` (`packages/protocol/dopilot_protocol/common.py:10-15`);
   the agent advertises the same three keys (`apps/agent/dopilot_agent/config/settings.py:66-75`,
   mapped 1:1 in `apps/agent/dopilot_agent/redis/heartbeat.py:52-55`). The server
   stores that dict on `nodes.capabilities` and node selection does
   `(n.capabilities or {}).get(capability)` (`apps/server/dopilot_server/nodes/service.py:241-242`).
   But `ARTIFACT_CAPABILITY` maps `python_wheel -> "python_wheel"` and
   `docker_image -> "docker_runtime"` (`apps/server/dopilot_server/services/states.py:68-72`).
   So a script-capable agent advertises `{"script": true}` while the server looks
   for a `"python_wheel"` key → it will never match. (`scrapy` matches only by
   coincidence: artifact `scrapy` → capability `"scrapy"` → key `scrapy`.)
   Confirmed exactly as described.

2. **Agent command handling is Scrapy-specific — confirmed.**
   `CommandConsumer._handle_run` unconditionally `parse_scrapy_command`s the
   payload, uses `ScrapyArtifactCache`, builds an `AgentRunRequest`, and calls
   `ScrapyRunner.schedule` (`apps/agent/dopilot_agent/redis/commands.py:226-361`).
   There is no dispatch on `cmd.task_type`, and `apps/agent/dopilot_agent/runners/`
   contains only `scrapyd.py`. Note `AgentCommand.task_type` already exists on the
   wire (`packages/protocol/dopilot_protocol/streams.py:106`) but the consumer
   ignores it. `_handle_stop`/`reconcile_started_attempts` are likewise scrapyd-only
   (`commands.py:141-170,363-388`). Confirmed.

3. **Template/resolver validation is Scrapy-command-first — confirmed.**
   `templates._validate_basics` requires a `command` and runs it through the
   shared scrapy parser (`apps/server/dopilot_server/services/templates.py:40-52`);
   `template_view` hardcodes `"artifact_type": "scrapy"`
   (`templates.py:213`); `resolve_run` only branches scrapy but always emits a
   command-first `params` block (`apps/server/dopilot_server/services/resolve.py:139-168`).
   A wheel binding routed through this path would be rejected for lacking a valid
   `scrapy crawl` command. Confirmed.

4. **Only Scrapy artifacts are runnable — confirmed.**
   `RUNNABLE_ARTIFACT_TYPES = frozenset({ARTIFACT_SCRAPY})` (`states.py:60`); the
   executor registry registers only `ScrapydExecutor` with the wheel/docker lines
   commented out (`apps/server/dopilot_server/executors/registry.py:14-18`);
   `get_runnable_artifact_or_404` rejects non-runnable types
   (`apps/server/dopilot_server/services/artifacts.py:135-150`). Confirmed.

5. **No Python wheel artifact store — confirmed.**
   The artifact service has only `upsert_scrapy` / `reconcile_scrapy_store`
   (`artifacts.py:56-103`); the API exposes only `POST /artifacts/scrapy/egg`
   and `GET /artifacts/scrapy/{sha256}/egg`
   (`apps/server/dopilot_server/api/v1/artifacts.py:55,84`). The DB schema is
   generic enough (`build_artifacts` already supports `artifact_type` /
   `package_format=wheel`, `states.py:54,62-66`), but there is no wheel
   upload/download/sha256 path. Confirmed.

6. **Log-file creation defaults to one `log` stream — confirmed (mechanism exists,
   rows not created).** `create_log_file(..., stream="log")` writes a single row
   per execution (`apps/server/dopilot_server/services/executions.py:176-200`),
   and `ScrapydExecutor.run` calls it once (`executors/scrapyd.py:95`). The
   plumbing for multiple streams already exists — `LogStream` has `stdout`/`stderr`
   (`packages/protocol/dopilot_protocol/logs.py:17-23`), the log-file PK is
   `(execution_id, attempt_id, stream)`, and `AgentLogEvent.stream` is on the wire
   (`streams.py:228`) — but the agent `LogPublisher` tails a single `state.log_path`
   and emits only the default `log` stream (`apps/agent/dopilot_agent/redis/logs.py:91-128`).
   So separate stdout/stderr needs new rows AND per-stream agent publishing.
   Confirmed; see the slice note for why combining them is the cheaper v1.

7. **README/docs stale — confirmed.** `README.md` still says "Phase 0 (platform
   skeleton) is implemented" (`README.md:10`), describes the agent as a
   "worker HTTP service: /health, /logs/tail, /status, cleanup"
   (`README.md:19`, the removed phase-1 pull paths), and references a split image
   name `rabbir/dopilot-agent:latest` (`README.md:85`) which contradicts the
   unified `rabbir/dopilot:latest` decision. Cosmetic, not a blocker, but the
   list is accurate.

## Recommendation

**Capability naming (preflight Q2): keep `script`/`docker` on the wire; fix the
server mapping. Do NOT canonicalize `CapabilitySet` in phase 2.**

- Canonicalizing to `{scrapy, python_wheel, docker_runtime}` is a **breaking wire
  change** touching `CapabilitySet` (`common.py`), the agent `Capabilities`
  + heartbeat mapping, the agent TOML config keys, the web `NodeInfo.capabilities`
  surface, the heartbeat-body examples in `requirements`/`refactor/00`, and any
  already-persisted `nodes.capabilities` JSON. That is a lot of blast radius for a
  cosmetic rename, and it is orthogonal to "run a wheel".
- The cheaper, lower-risk fix is two values in `ARTIFACT_CAPABILITY`
  (`states.py:68-72`): `python_wheel -> "script"`, `docker_image -> "docker"`.
  Node selection then matches the keys the agent actually advertises, exactly the
  way `scrapy` already works. This is fully consistent with dopilot's established
  pattern of a stable wire vocabulary translated at the boundary
  (`execution_id`/`attempt_id`, `task_type`).
- Tradeoff: the artifact-type name (`python_wheel`) and the capability key
  (`script`) differ, which is a minor readability cost and a small trap for future
  readers. If the team wants the canonical names visible (e.g. in the web node
  panel), do that rename as a **separate, deliberate protocol bump**, not bundled
  into the wheel-runner slice.

The rest of Codex's direction (type-aware run contract, split template
validation, server `PythonWheelExecutor` mirroring `ScrapydExecutor`, agent runner
registry keyed by `task_type`, keep phase scoped) I endorse as written.

## Minimal Safe Slice

Smallest end-to-end path that runs a `.whl` and persists stdout/stderr through the
existing Redis log stream without touching the Scrapy path:

1. **Capability mapping fix** — `ARTIFACT_CAPABILITY[python_wheel] = "script"`
   (`states.py:68-72`). Unblocks node selection. 2 lines.
2. **Make `python_wheel` runnable** — add it to `RUNNABLE_ARTIFACT_TYPES`
   (`states.py:60`) and register a new `PythonWheelExecutor` in the registry
   (`registry.py:14`). The executor structurally mirrors `ScrapydExecutor`
   (`executors/scrapyd.py`): create task + per-node execution + `run`
   command-outbox + log-file rows in one transaction, select nodes by the
   `script` capability, dispatch `run` over Redis. No Python runs on the server.
3. **Single combined log stream for v1.** Have the agent wheel runner redirect
   the child's stderr into stdout and write one `job.log`, so the server creates
   the existing single `stream="log"` row and the current `LogPublisher` /
   log-consumer / SSE chain is reused unchanged. Splitting stdout/stderr into two
   rows + two agent cursors is a clean follow-up, not part of the first runnable
   slice (avoids destabilizing the log subsystem).
4. **Wheel artifact upload/download** — `POST /artifacts/python-wheel` +
   `GET /artifacts/python-wheel/{sha256}/wheel` with sha256 dedup, mirroring the
   egg path (`api/v1/artifacts.py`) and an `upsert_python_wheel` in `artifacts.py`.
   The build artifact descriptor the agent fetches reuses the existing
   `fetch_path`/`content_hash` shape.
5. **Type-aware run contract** — add a `WheelRunPayload` (entry_point | module,
   `args`, `env`, `working_dir`) to `packages/protocol`, branch `resolve_run`
   (`resolve.py:139`) and template validation (`templates.py`) on `artifact_type`,
   and require exactly one of `entry_point`/`module`. No shell strings.
6. **Agent runner registry** — split `CommandConsumer` so `run`/`stop`/cleanup/
   reconcile dispatch on `cmd.task_type` (`commands.py`). Scrapy keeps the exact
   current code path. Add a `PythonWheelRunner`: venv cache keyed by wheel sha256,
   install the wheel, launch via `asyncio.create_subprocess_exec` in its own
   process group with `PYTHONUNBUFFERED=1`, tail the captured log, map exit code
   → terminal (`0`→finished, non-zero→failed, cancel→SIGTERM/grace/SIGKILL→
   canceled), per `requirements` decision #16.

Steps 1–4 are low-risk additions. Step 6 is the destabilization risk surface and
must keep the Scrapy branch byte-for-byte.

## High-Risk Files

- **`apps/agent/dopilot_agent/redis/commands.py`** — highest risk. Refactoring
  `CommandConsumer` into a per-`task_type` registry touches the idempotency
  (`O_EXCL` reserve → promote), pending recovery (`_claim_pending`), and
  `reconcile_started_attempts` logic that currently assumes scrapyd. Any
  regression here breaks live Scrapy dispatch/cancel/recovery.
- **`apps/agent/dopilot_agent/state/store.py`** — `AttemptState` is scrapyd-shaped
  (`scrapyd_job_id`, `project`, `spider`, `log_path`). Wheels need pid /
  process-group / exit-code fields and a non-scrapyd reconcile. Schema must be
  extended without breaking existing scrapy state files (additive optional fields).
- **`apps/server/dopilot_server/services/resolve.py` + `services/templates.py`** —
  branching validation by artifact type; risk of breaking the command-first
  Scrapy contract or the spider-in-artifact check.
- **`apps/server/dopilot_server/services/states.py`** — capability map +
  `RUNNABLE_ARTIFACT_TYPES`; small but a wrong value silently breaks node
  selection (conflict 1).
- **`packages/protocol`** (`common.py`/`streams.py`/`execution.py`) — only high
  risk IF capabilities are canonicalized (see Recommendation — advise against);
  otherwise a contained addition of `WheelRunPayload`.
- **`apps/agent/dopilot_agent/redis/logs.py`** — only if stdout/stderr are split;
  the single-stream slice leaves it untouched.

## Required Tests

Mandatory before Codex writes the brief (new tests, do not run broad suites here):

- **Scrapy regression (gating):** existing agent command-consumer + ScrapydExecutor
  tests stay green after the runner-registry split — idempotent re-delivery,
  pending recovery, reserved→spawn_aborted, cancel/reclaim. This is the
  "don't destabilize Scrapy" guard.
- Node selection picks a `script`-capable agent for a `python_wheel` artifact and
  excludes scrapy-only agents (locks conflict 1's fix).
- `python_wheel` artifact upload → row dedup on sha256 → authenticated download
  byte-identity.
- Template + resolver accept a wheel binding with a valid launch target and reject
  one with neither/both `entry_point` and `module`, and a Scrapy template still
  validates command-first.
- Agent wheel runner: venv created + wheel installed once and cached by sha256;
  re-run reuses the venv; subprocess launched with `PYTHONUNBUFFERED`.
- Exit-code → terminal mapping: `0`→finished, non-zero→failed; stdout/stderr
  bytes published to the Redis log stream and persisted (offset-append, dedup,
  partial-gap behavior unchanged).
- Cancel a running wheel: SIGTERM → grace → SIGKILL on the process group →
  authoritative `attempt.canceled`.
- Cross-restart idempotency for wheels: a re-delivered `run` does not start the
  process twice (state-file CAS extended to the wheel runner).

## Open Decisions

Require user/product approval before the brief is final:

1. **Capability naming** — accept the seam fix (`python_wheel→"script"`) vs the
   canonical rename (`CapabilitySet → python_wheel/docker_runtime`). I recommend
   the seam fix; the docs (`requirements` §2.1) currently assert the canonical
   names, so this needs an explicit call to keep docs and code aligned.
2. **Wheel dependency resolution / network policy** — does the agent's
   `pip install <wheel>` resolve transitive deps from PyPI (needs network +
   index config), or must wheels be self-contained / deps vendored? This is a
   real deployment constraint, not an implementation detail.
3. **stdout/stderr: combined vs separate streams** for v1 (recommend combined;
   confirm the product is OK deferring split streams).
4. **Wheel launch contract** — confirm "exactly one of `entry_point`/`module`,
   plus `args`/`env`/`working_dir`, no shell". Note `env`/`args` passed to a
   subprocess running arbitrary user wheel code is arbitrary code execution on the
   agent by design — confirm that is in-scope and no sandboxing is expected in v1.
5. **Python interpreter / version** — which interpreter backs the venv; the
   preflight already scopes out multi-Python, so confirm single fixed interpreter.
6. **Cancellation grace period** value (SIGTERM→SIGKILL window) and whether it is
   configurable.
7. **Agent `AttemptState` evolution** — confirm the state model is extended
   additively (optional pid/exit_code/runner_type) rather than introducing a
   separate per-type store, so scrapy state files keep loading.

## Commands Run

- `Read` of all required-context docs and the listed code paths.
- `rg` / `grep` to locate: artifact API egg paths (`api/v1/artifacts.py`),
  log-file creation + `LogStream` usage, the agent capability→heartbeat mapping
  (`redis/heartbeat.py`), the agent `runners/` contents (scrapyd only), and
  README staleness markers.
- Two `Bash` invocations were initially blocked by the multi-operation sandbox
  guard (compound `&&`/`;` commands needing approval); re-run as single-operation
  commands, which succeeded. No application code was read from
  `reference/scrapydweb/` and no files outside the two allowed report paths were
  modified.
