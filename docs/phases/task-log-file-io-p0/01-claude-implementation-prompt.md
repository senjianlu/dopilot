# Claude Implementation Prompt: Log File I/O P0

You are Claude Code working in the dopilot repository.

## Assignment

Implement the work described in:

- `docs/phases/task-log-file-io-p0/00-brief.md`

## Required Context

Read these before editing:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/task-log-file-io-p0/00-brief.md`
- `docs/phases/task-log-file-io-p0/00a-feasibility-review.md`
- `/tmp/dopilot-ui-lag-diagnosis.md`
- `apps/server/dopilot_server/logs/files.py`
- `apps/server/dopilot_server/api/v1/tasks.py`
- `apps/server/dopilot_server/services/logs.py`
- `apps/server/dopilot_server/redis/consumers.py`
- `apps/server/dopilot_server/services/maintenance.py`
- relevant existing tests under `apps/server/tests/`

## Constraints

- Keep changes scoped to the brief.
- Do not fetch, vendor, copy, or import upstream scrapydweb code. There is no
  local snapshot; upstream is a behavior reference consulted externally only.
- Do not copy structure or code from upstream scrapydweb.
- Preserve existing public behavior unless the brief explicitly changes it.
- Add or update tests for changed behavior.
- Prefer named async helpers in `dopilot_server.logs.files` over inline
  `asyncio.to_thread` at each caller.
- For `apply_log_event`, prefer one offloaded helper for marker+raw append and
  final size. Preserve current offset semantics and document the single-writer
  invariant.
- Do not edit frontend, artifacts, static asset caching, DB query performance,
  Redis stream topology, or deployment files unless a test fixture absolutely
  requires it.

## Output Required

Create or update:

- `docs/phases/task-log-file-io-p0/01-claude-implementation-report.md`
- `docs/phases/task-log-file-io-p0/claude-progress.md`

The report must include:

- changed files grouped by area;
- implementation notes;
- tests added or updated;
- commands run with exact pass/fail output;
- known risks or incomplete items.

At the start, spend up to five minutes estimating the rough duration and write
an initial `claude-progress.md` note with size class (`<15m`, `15-45m`,
`45-90m`, or `90m+`), proposed update cadence, checkpoints, and likely
long-running commands. Then update it at meaningful checkpoints and before/after
long-running commands.

## Required Commands

Run the narrowest relevant commands, including at least:

```bash
pytest apps/server/tests
ruff check apps packages
```

If a required command cannot run, record the exact blocker and any narrower
commands that did run. Do not mark the task complete if required tests did not
run.
