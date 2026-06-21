# Phase 2b Packet 1 — Claude Implementation Report

Server/protocol/web dispatch-ready Python-wheel support plus the built-in demo
wheel fixture. Agent-side download/install/subprocess execution is **out of
scope** (packet 2b-2) and was not implemented; the server never runs Python.

## Status

Complete. All required commands pass (see **Commands run**).

## Changed files by area

### Protocol (`packages/protocol`)
- `dopilot_protocol/execution.py` — added `PythonWheelRunPayload`
  (`shell_command`, `artifact`, `env={}`, `working_dir=None`,
  `task_type="python_wheel"`).
- `dopilot_protocol/__init__.py` — exported `PythonWheelRunPayload`.
- `tests/test_schemas.py` — payload defaults/round-trip + independent default
  containers; scrapy discriminator default.
- `tests/test_stream_schemas.py` — `AgentCommand` run round-trip with
  `task_type="python_wheel"` through the stream codec.

### Server — state / capability (`apps/server`)
- `dopilot_server/services/states.py` — `python_wheel` is now runnable
  (`RUNNABLE_ARTIFACT_TYPES`); `ARTIFACT_CAPABILITY["python_wheel"] = "script"`
  (capability name `script` is deliberately distinct from the wire runner
  discriminator `python_wheel`).

### Server — artifact store / API
- `dopilot_server/artifacts/wheel_store.py` (new) — filesystem `.whl` store:
  validates `.whl` extension + valid zip, parses `*.dist-info/METADATA`
  Name/Version best-effort, atomic temp-then-replace write, list/get, sha256
  dedupe key. Rejects non-`.whl` / non-zip with `artifact.invalid_wheel`.
- `dopilot_server/services/artifacts.py` — `wheel_fetch_path`, `_wheel_metadata`,
  `upsert_wheel` (dedupe on `("python_wheel", sha256)`), `reconcile_wheel_store`;
  `distribution` added to `artifact_snapshot` + `build_artifact_view`.
- `dopilot_server/api/v1/artifacts.py` — `POST /artifacts/python_wheel/wheel`
  (admin), `GET /artifacts/python_wheel/{sha256}/wheel` (agent
  `require_server_token`); list endpoint reconciles the wheel store too.
- `dopilot_server/api/v1/schemas.py` — `BuildArtifactView.distribution`.

### Server — templates / resolve / schedules
- `dopilot_server/services/resolve.py` — `validate_wheel_command` (non-empty),
  `validate_command_by_type`; `sanitize_overrides(..., artifact_type="scrapy")`
  is now **type-aware** (wheel command overrides are free-form, not scrapy
  parsed); `resolve_run` has a `python_wheel` branch producing
  `shell_command` / `artifact` / `env={}` / `working_dir=None` params + snapshot.
- `dopilot_server/services/templates.py` — `_validate_basics` no longer runs the
  scrapy parser; new `_validate_command_for_artifact` dispatches by artifact type
  (scrapy parser+spider vs wheel non-empty); `build_run_request` passes the
  artifact type to `sanitize_overrides`; `template_view(template, artifact_type)`
  is now dynamic; `artifact_type_for_template` / `artifact_types_for_templates`
  helpers (batch lookup, no N+1 in list).
- `dopilot_server/api/v1/templates.py` — create/get/update/list resolve and pass
  the real `artifact_type` into the view.
- `dopilot_server/services/schedules.py` — `create_schedule` / `update_schedule`
  resolve the bound template's artifact type and pass it to `sanitize_overrides`,
  so wheel schedule command overrides validate as shell commands.

### Server — executor
- `dopilot_server/services/executions.py` — `parse_wheel_params` (validates
  `shell_command` non-empty + wheel `artifact` fetch context; `env`/`working_dir`
  defaults).
- `dopilot_server/executors/python_wheel.py` (new) — `PythonWheelExecutor`
  mirroring the Scrapy executor's transaction/outbox shape: selects
  `script`-capable nodes, creates task + execution + `run` outbox +
  `execution_log_files` in one atomic commit, dispatches a
  `PythonWheelRunPayload` (`task_type="python_wheel"`). No-target / dispatch
  503 / dispatch-unknown 202 behavior identical to Scrapy. Never runs Python.
- `dopilot_server/executors/registry.py` — registered `python_wheel`.

### Demo wheel fixture (`tests/fixtures/python_wheel_demo/`)
- `main.py` — stdlib-only: requests `DOPILOT_DEMO_URL`
  (default `https://httpbin.org/headers`) and prints response headers; runs as
  `python -m main`. URL env-overridable for offline tests.
- `build_wheel.py` — deterministic, stdlib-only wheel builder
  (`build_demo_wheel()` returns bytes; `__main__` writes the `.whl`). No
  `build`/`wheel` toolchain needed; RECORD hashes computed correctly.
- `dopilot_demo-0.1.0-py3-none-any.whl` — prebuilt artifact.
- `README.md` — contents, build steps, phase-2b execution strategy + smoke notes.

### Web (`apps/web`)
- `src/api/types.ts` — `ArtifactType = "scrapy" | "python_wheel"`;
  `BuildArtifact.distribution`; `UploadWheelResponse`; command field comment.
- `src/api/artifacts.ts` — `uploadWheel`.
- `src/pages/BuildArtifactsPage.vue` — wheel upload button (`accept=".whl"`);
  details show `distribution` for wheels and hide the scrapy spiders section.
- `src/pages/TemplatesPage.vue` — `isWheel`; type-aware command validation
  (wheel = non-empty only, no scrapy parser); relabel to "Shell command" with
  wheel placeholder/hint; wheel default command `python -m main`.
- `src/i18n/locales/{en,zh}.ts` — `artifacts.uploadWheel`,
  `artifacts.distribution`, `templates.shellCommand*`, `errors.invalidWheel`.

### Test fixtures
- `apps/server/tests/conftest.py` — `healthy_node(script=...)` advertises the
  `script` capability; `build_artifact(artifact_type="python_wheel")` seeds
  wheel-shaped metadata (distribution/version/wheel fetch_path).

## Implementation notes

- **Execution strategy preserved (not implemented in agent yet).** Payload +
  docs encode the user-selected `pip install --no-deps --target <site> <wheel>`
  + `PYTHONPATH` contract: `env={}`, `working_dir=None`. No venv, no dependency
  management, no current-interpreter install anywhere.
- **No DB migration.** Wheel facts live in the existing `artifact_metadata`
  JSON; the wheel shell command reuses `ExecutionTemplate.command`; template
  `artifact_type` is derived from the bound artifact (no new column).
- **Capability vs task_type** are intentionally distinct: node capability
  `script`, wire runner discriminator `python_wheel`.
- **Wheel schedule command override is supported** (Codex review item — the
  earlier progress note's "limitation" was removed, not accepted).
  `sanitize_overrides` is type-aware and threaded through schedule
  create/update + `build_run_request`; resolve's wheel branch consumes a
  free-form override verbatim. Tests prove a shell-metacharacter override is
  accepted and dispatched.

## Tests added / updated

- `packages/protocol/tests/test_schemas.py`, `test_stream_schemas.py` — wheel
  payload + command round-trips.
- `apps/server/tests/test_resolve.py` — wheel resolve branch (shell_command /
  env / working_dir), empty-command rejection, free-form override, type-aware
  `sanitize_overrides`; updated capability assertion + `python_wheel` runnable.
- `apps/server/tests/test_templates.py` — reserved/not-runnable case switched to
  `docker_image` (python_wheel is now runnable).
- `apps/server/tests/test_python_wheel.py` (new) — upload/download/dedupe/reject,
  type-aware template validation, dynamic `template_view.artifact_type`,
  executor dispatch (payload shape, log row, script-node selection, scrapy-only
  exclusion), and wheel **schedule command override** accept + dispatch.
- `apps/web/.../BuildArtifactsPage.spec.ts` — wheel upload handler + distribution
  display (no spiders box).
- `apps/web/.../TemplatesPage.spec.ts` — wheel free-form command accept/submit,
  empty-command block, `isWheel`, wheel default command.

## Commands run

| Command | Result |
| --- | --- |
| `pytest packages/protocol/tests apps/server/tests` | **319 passed** |
| `corepack pnpm --filter web test` | **45 passed (10 files)** |
| `corepack pnpm --filter web build` | **OK** (`vue-tsc` type-check + vite build) |
| `ruff check apps packages` | **All checks passed** |

Extra verification (manual, offline smoke of the packet-1 contract):
`pip install --no-deps --target <site> dopilot_demo-…whl` then
`PYTHONPATH=<site> DOPILOT_DEMO_URL=http://127.0.0.1:<port>/ python -m main`
→ installs cleanly and prints response headers, exit 0. (Confirms the demo
wheel and the `--target` + PYTHONPATH strategy; the agent runner that automates
this is packet 2b-2.)

## Known risks / shortcuts / incomplete items

- Agent-side runner (download/install/subprocess/cancel/recovery) is packet
  2b-2; end-to-end server→Redis→agent→logs is not yet exercisable.
- `pip install --target` installs no console scripts — wheel commands must be
  importable module forms (`python -m main`). Documented in the brief, web hint,
  and fixture README.
- `/bin/sh` pipeline exit semantics (last command wins) will matter at agent
  execution time; documented in the brief, not yet enforced.
- Wheel `distribution`/`version` are parsed best-effort from METADATA with a
  filename/sha fallback; a wheel with no METADATA still stores + runs.
</content>
