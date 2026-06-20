# Phase 1.8.1 Claude Review Response

Response to `docs/phases/phase-1.8.1/02-codex-review.md`. Every blocking finding is
addressed below, with focused tests added and verification re-run where the session
permission policy allowed.

## Files Changed

Server / protocol:

- `apps/server/dopilot_server/services/resolve.py`
  - `validate_command` now returns the parsed command so callers can reuse the
    derived spider.
  - New `ensure_spider_in_artifact(spider, spiders)` — rejects a command whose
    spider is not exposed by the bound build artifact (`command.unknown_spider` /
    `errors.unknownSpider`, 400).
  - New `validate_command_for_artifact(command, spiders)` — grammar + membership.
  - `resolve_run` now calls `ensure_spider_in_artifact` against the artifact
    snapshot spiders after parsing the resolved command (covers schedule command
    overrides before dispatch).
  - `sanitize_overrides` now treats a blank/whitespace-only `command` override as
    absent: it is neither validated nor persisted (inherits the template command).
- `apps/server/dopilot_server/services/templates.py`
  - `create_template` and `update_template` call
    `resolve.validate_command_for_artifact(...)` once the artifact is loaded, so a
    command whose spider is not in the artifact's spider list is rejected at
    create/update.

Web:

- `apps/web/src/pages/TemplatesPage.vue` — unused `id` watch parameter renamed to
  `_id` (fixes TS6133).
- `apps/web/src/i18n/locales/en.ts`, `apps/web/src/i18n/locales/zh.ts`
  - `commandPlaceholder` no longer contains `<spider>` angle brackets (removes the
    `intlify` interpolation warning); now `scrapy crawl spider [-a key=value]… …`.
  - Added `errors.unknownSpider` message for the new 400.

Tests / formatting:

- `packages/protocol/tests/test_scrapy_command.py` — `"scrapy"` now expects
  `not_scrapy_crawl` (matches parser behavior: a single token is not
  `scrapy crawl`). Import block reordered by ruff.
- `packages/protocol/dopilot_protocol/__init__.py` — import block reordered by ruff.
- `apps/server/tests/test_templates.py` — new
  `test_create_template_unknown_spider_400`,
  `test_update_template_unknown_spider_400`; existing
  `test_template_edit_does_not_mutate_existing_task_snapshot` now seeds an artifact
  exposing `phase1`+`phase2` so the post-create edit to `phase2` is a valid member.
- `apps/server/tests/test_resolve.py` — new
  `test_resolve_rejects_command_spider_not_in_artifact`,
  `test_resolve_blank_command_override_inherits_template_command`,
  `test_sanitize_overrides_blank_command_not_persisted`.
- `apps/server/tests/test_schedules.py` — new
  `test_trigger_now_rejects_unknown_spider_override`,
  `test_blank_command_override_inherits_template`; existing
  `test_trigger_now_applies_command_override` now seeds an artifact exposing
  `phase1`+`phase2` so the `phase2` override is a valid member.

## Fixes Made (per finding)

1. **P1 — command spider must belong to the bound artifact.** Enforced server-side
   in two places, command-first preserved (no spider/settings/args fields
   reintroduced):
   - Template create/update: `validate_command_for_artifact` after the artifact is
     resolved, using `artifact.artifact_metadata["spiders"]`.
   - Resolved runs (template run, schedule trigger-now, timer firing all route
     through `resolve_run`): `ensure_spider_in_artifact` against
     `artifact_snapshot["spiders"]`, so schedule command overrides are validated
     before dispatch.
   - Error: `ApiError(400, "command.unknown_spider", "errors.unknownSpider",
     {"spider": ..., "spiders": [...]})`, consistent with the nearby
     `command.invalid` / `artifact.not_runnable` validation style. Membership is
     enforced whenever the artifact lists spiders (every uploaded egg does); an
     empty/absent list is left to the agent rather than blocking every spider.

2. **P1 — blank schedule command override inherits the template command.**
   `sanitize_overrides` strips and, when the result is empty, `continue`s without
   validating or persisting the key. `{"command": ""}` / `{"command": "  "}` now
   produce `{}`, and the run inherits the template command.

3. **P2 — verification green.**
   - Parser/test consistency: `"scrapy"` expects `not_scrapy_crawl` (the parser's
     actual, accurate semantics — a lone token is not a `scrapy crawl` command;
     `"scrapy crawl"` still yields `missing_spider`).
   - TS6133: unused watch param renamed `id` → `_id`.
   - Ruff import ordering fixed (`ruff check --fix`) in
     `packages/protocol/dopilot_protocol/__init__.py` and
     `packages/protocol/tests/test_scrapy_command.py`.
   - vue-i18n placeholder warning removed by dropping `<spider>` angle brackets
     from `commandPlaceholder` in both locales.

4. **Focused tests added** — see Files Changed: unknown-spider rejection on template
   create and update, unknown-spider rejection on schedule override at trigger
   resolution, and blank-command-override inheritance (at both the `resolve`/
   `sanitize` unit level and the schedule API level).

## Tests Run — Exact Results

- `corepack pnpm --filter web test` — **PASS**. `Test Files 8 passed (8)`,
  `Tests 28 passed (28)`. The previous `intlify` placeholder warning is no longer
  emitted.
- `corepack pnpm --filter web build` — **PASS**. `vue-tsc -b && vite build`
  completed (`✓ built in 6.54s`); the TS6133 error is gone. (Pre-existing
  non-blocking Rollup `#__PURE__` comment notes and the >500 kB chunk-size warning
  from dependencies remain, unrelated to this change.)
- `.venv/bin/ruff check apps packages` — **PASS**. `All checks passed!`

- `.venv/bin/pytest packages/protocol/tests apps/agent/tests
  apps/server/tests/test_templates.py apps/server/tests/test_schedules.py
  apps/server/tests/test_scheduler_runner.py apps/server/tests/test_executions.py
  apps/server/tests/test_resolve.py` — **COULD NOT RUN in this session.** Every
  invocation of `pytest`/`python` (including `.venv/bin/pytest`,
  `.venv/bin/python -m pytest`, and even `python -c`) returns
  "This command requires approval" and the approval was not granted in this
  non-interactive session; `ruff` and `corepack pnpm` were allowed and ran. The
  block is the permission allowlist on the Python binaries, not a sandbox/infra
  issue — the server tests use in-memory SQLite (`sqlite+aiosqlite:///:memory:`)
  and `fakeredis`, so they need no external Postgres/Redis. Please re-run the
  command above to confirm; the changes were written to pass it (analysis below).

### Why the pytest changes are expected to pass (manual trace)

- `test_scrapy_command.py::test_rejected_grammar[scrapy-not_scrapy_crawl]` — parser
  returns `not_scrapy_crawl` for `"scrapy"`; expectation updated to match.
- `test_resolve.py` new/edited: `_artifact` exposes `["s1","s2"]`; `s1`/`s2`
  commands pass membership, `typo_spider` raises `command.unknown_spider`; blank
  override → `{}` → inherits `scrapy crawl s1`.
- `test_templates.py`: default seeded artifact spiders `["phase1"]`; `typo_spider`
  rejected on create and update; the edit-immutability test seeds
  `("phase1","phase2")` so the `phase2` edit is a valid member.
- `test_schedules.py`: `trigger_now` resolves through `resolve_run` before any task
  is created, so the unknown-spider override surfaces as 400
  `command.unknown_spider`; the override-applies test seeds `("phase1","phase2")`.
- `test_executions.py` / `test_scheduler_runner.py`: all commands use `phase1`,
  which is a member of the default artifact's spider list — unaffected.

## Residual Risks

- **pytest not executed here.** The Python verification suite was not run due to the
  session's permission policy on the Python binaries. The reasoning above is a
  manual trace, not an executed result — the suite should be run to confirm before
  acceptance.
- **Empty spider list is not enforced.** When a build artifact has an empty/absent
  `spiders` list (legacy/degenerate rows; a normal uploaded egg always has ≥1
  spider, enforced by `artifact.no_spiders` at upload), membership is not checked
  and the spider is left for the agent to validate. This is intentional to avoid
  blocking every command for such rows, but it means the membership guarantee holds
  only when the artifact actually advertises spiders.
- **Frontend membership check is UX-only / absent.** The web still validates command
  grammar only; the spider-membership check is server-authoritative. A user can
  submit an unknown spider and receive the new 400 rather than an inline pre-submit
  error. Adding a client-side membership hint is a possible follow-up but out of
  scope for these blocking fixes.
