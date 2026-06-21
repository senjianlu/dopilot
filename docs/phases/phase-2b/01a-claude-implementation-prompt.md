# Claude Implementation Prompt: Phase 2b Packet 1

You are Claude Code working in the dopilot repository.

## Assignment

Implement **phase 2b packet 1: server/protocol/web dispatch-ready Python wheel
support plus the built-in demo wheel fixture**.

Active brief:

- `docs/phases/phase-2b/00-brief.md`

This packet intentionally stops before agent-side subprocess execution. Do not
implement the Python wheel runner in `apps/agent` yet except for tests or type
updates that are strictly necessary for unchanged Scrapy behavior.

## Required Context

Read these before editing:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-2/00-preflight-conflicts.md`
- `docs/phases/phase-2/00b-plan-review.md`
- `docs/phases/phase-2a/03-acceptance-report.md`
- `docs/phases/phase-2b/00a-feasibility-review.md`
- `docs/phases/phase-2b/00-brief.md`

## In Scope

- Add `PythonWheelRunPayload` to `packages/protocol`.
- Change server capability mapping to:

  ```text
  scrapy -> scrapy
  python_wheel -> script
  docker_image -> docker
  ```

- Add `python_wheel` to runnable artifact types.
- Add wheel artifact store/API:
  - `POST /api/v1/artifacts/python_wheel/wheel`
  - `GET /api/v1/artifacts/python_wheel/{sha256}/wheel`
  - sha256 dedupe on `(artifact_type, content_hash)`
  - authenticated agent download
  - reject non-`.whl` upload
- Add a built-in demo wheel fixture under
  `tests/fixtures/python_wheel_demo/`.
  The actual demo module payload should be only `main.py`; build metadata files
  are acceptable because wheel format requires them.
- Demo `main.py` must use Python stdlib to request response headers from a URL
  defaulting to `https://httpbin.org/headers`, configurable through an env var
  so tests can point to a local HTTP server.
- Split template validation by bound artifact type:
  - Scrapy keeps the current Scrapy command parser and spider validation.
  - Python wheel requires only a non-empty `command`.
- Resolve Python wheel templates into params/snapshot using `shell_command`,
  `artifact`, `env={}`, and `working_dir=None`.
- Add/register server-side `PythonWheelExecutor`.
  It must mirror the Scrapy executor's transaction/outbox shape and must never
  execute Python locally on the server.
- Update web/client types and UI so a user can upload `.whl`, create/edit a
  Python wheel template, and run/schedule it through the existing template flow.
- Keep existing Scrapy behavior unchanged.

## Out Of Scope

- Agent-side wheel download/install/subprocess execution.
- End-to-end successful Python wheel execution.
- Dependency management UI or install controls.
- venv support.
- Console-script support.
- Docker/K3s support.
- Edits to `reference/scrapydweb/`.

## Acceptance Criteria For This Packet

- A Python wheel artifact can be uploaded, listed as runnable, deduped by sha,
  and downloaded byte-identically by an authenticated agent.
- Python wheel node selection requires the `script` capability and excludes
  Scrapy-only nodes.
- Python wheel templates accept arbitrary non-empty shell commands and do not
  run through the Scrapy parser.
- Scrapy template validation and Scrapy executor behavior remain unchanged.
- `PythonWheelExecutor` creates Task/Execution/outbox/log rows and dispatches a
  well-formed Redis `run` command with `task_type="python_wheel"`.
- The payload carries `shell_command`, `artifact`, `env`, and `working_dir`.
- Web tests cover the new wheel upload/template path at the practical level
  available in the current codebase.
- The demo wheel fixture is present and documented enough for packet 2 / smoke.

## Required Output

Create or update:

- `docs/phases/phase-2b/01a-claude-implementation-report.md`
- `docs/phases/phase-2b/claude-progress.md`

The report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- exact commands run and pass/fail outcomes;
- known risks, shortcuts, or incomplete items.

At the start of the task, write a progress note with rough size class,
checkpoints, and likely long-running commands. Update it at meaningful
checkpoints and before/after long-running commands.

## Required Commands

Run the narrow packet-1 checks first, then any extra checks you think are needed:

```bash
pytest packages/protocol/tests apps/server/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
ruff check apps packages
```

If a command cannot run, record the exact blocker in the implementation report
instead of claiming completion.

## Important Notes

- Current mainline docs still mention venv. Do not implement venv.
- Current feasibility review recommended current-interpreter install as one
  option. The user subsequently selected `pip install --no-deps --target` plus
  `PYTHONPATH`. Packet 1 must preserve that contract in payload/docs/tests, even
  though agent execution is packet 2.
- Do not add a DB migration unless you prove it is unavoidable. The expected
  design reuses existing JSON fields and `ExecutionTemplate.command`.
- Do not perform broad refactors outside the packet.
