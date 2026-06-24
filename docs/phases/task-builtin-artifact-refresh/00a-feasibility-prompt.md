# Claude Feasibility Validation Prompt: Built-In Artifact Refresh

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of `docs/phases/task-builtin-artifact-refresh/00-brief.md`
before Codex finalizes or accepts implementation.

Do not implement code in this step.

Codex has made preliminary local draft edits while exploring. Treat them as a
proposal, not accepted implementation. You may inspect the current diff, but
your job is to validate the approach and flag changes needed before
implementation/review continues.

## Proposed Direction

- Put built-in default artifact bytes in a stable image path such as
  `/app/builtin-artifacts/...`.
- On server startup, import those built-ins into the configured artifact store
  and DB using existing artifact store + `upsert_*` flows.
- Rely on content hashes so unchanged built-ins are idempotent, changed built-ins
  create new artifacts, and old/user artifacts are not overwritten.
- Keep default example changes minimal:
  - `dopilot_clock` logs `DOPILOT_*` values and defaults to 45 seconds.
  - `dopilot-demo` logs `DOPILOT_*` env vars.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/task-runtime-context/00-brief.md`
- `docs/phases/task-builtin-artifact-refresh/00-brief.md`
- `apps/server/dopilot_server/app.py`
- `apps/server/dopilot_server/services/artifacts.py`
- `apps/server/dopilot_server/artifacts/scrapy_store.py`
- `apps/server/dopilot_server/artifacts/wheel_store.py`
- `deploy/docker/Dockerfile`
- `examples/scrapy_clock/dopilot_clock/spiders/clock.py`
- `tests/fixtures/python_wheel_demo/main.py`
- relevant tests under `apps/server/tests`

## Output Required

Write the final feasibility summary to:

`docs/phases/task-builtin-artifact-refresh/00a-feasibility-review.md`

Use these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Keep it concise and concrete. If you have a better idea for avoiding overwrite
or making startup import safer, say so clearly.
