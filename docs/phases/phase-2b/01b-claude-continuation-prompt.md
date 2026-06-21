# Claude Continuation Prompt: Phase 2b Packet 1

You are Claude Code working in the dopilot repository.

## Situation

The previous `phase-2b-packet-1` run exited early because of a Claude API 529
Overloaded error. It left partial changes in the working tree. Do not restart
from scratch and do not revert those partial changes unless you identify a
concrete bug.

Continue implementing **phase 2b packet 1** from the current working tree.

Active brief:

- `docs/phases/phase-2b/00-brief.md`

Original packet prompt:

- `docs/phases/phase-2b/01a-claude-implementation-prompt.md`

## Current Partial State To Inspect First

The partial run appears to have changed or added:

- `packages/protocol/dopilot_protocol/execution.py`
- `packages/protocol/dopilot_protocol/__init__.py`
- `packages/protocol/tests/test_schemas.py`
- `packages/protocol/tests/test_stream_schemas.py`
- `apps/server/dopilot_server/services/states.py`
- `apps/server/dopilot_server/services/artifacts.py`
- `apps/server/dopilot_server/artifacts/wheel_store.py`
- `apps/server/tests/test_resolve.py`
- `apps/server/tests/test_templates.py`
- `docs/phases/phase-2b/claude-progress.md`

Start by reading `git diff` and the active brief, then continue from the
unfinished checklist.

## Important Review Guidance From Codex

- The progress note from the failed run mentioned a possible limitation:
  "wheel schedule command override is not supported in packet 1." Do not accept
  that limitation silently. The active brief expects schedule/template flows to
  keep working for Python wheels. If schedule command overrides cannot be
  supported without a larger design change, document the exact blocker in
  `01a-claude-implementation-report.md`; otherwise implement support.
- Keep the selected execution strategy documented and represented in payloads:
  wheel installs are for packet 2 with `pip install --no-deps --target ...` and
  `PYTHONPATH`; packet 1 must not introduce venv or current-interpreter install.
- Do not implement agent-side subprocess execution in this packet.
- Do not edit `reference/scrapydweb/`.

## Remaining Work Expected

Complete the packet-1 scope from `00-brief.md`, including:

- wheel artifact upload/download API and tests;
- wheel artifact list/view metadata and dedupe;
- built-in demo wheel fixture under `tests/fixtures/python_wheel_demo/`;
- type-aware template validation and dynamic template artifact type;
- `resolve_run` python_wheel branch with `shell_command`, `artifact`, `env={}`,
  and `working_dir=None`;
- `PythonWheelExecutor` and registry wiring;
- server tests for script-capable node selection, outbox payload shape, and log
  row creation;
- web/client type and UI updates with tests/build;
- implementation report and updated progress notes.

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

## Required Commands

Run:

```bash
pytest packages/protocol/tests apps/server/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
ruff check apps packages
```

If a command cannot run, record the exact blocker and current state in the
implementation report.
