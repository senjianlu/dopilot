# Phase 1.8.1 Codex Review

## Scope

Codex reviewed Claude's command-first destructive refactor against:

- `docs/phases/phase-1.8.1/00-brief.md`
- `docs/phases/phase-1.8.1/00a-feasibility-review.md`

## Blocking Findings

1. `P1` Command validation does not ensure the command spider belongs to the bound build artifact.

   - `apps/server/dopilot_server/services/templates.py:72`
   - `apps/server/dopilot_server/services/templates.py:100`
   - `apps/server/dopilot_server/services/resolve.py:111`

   Template create/update validates only the shared command grammar before the artifact is loaded. `resolve_run` also parses the command but does not compare `parsed.spider` with `artifact_snapshot(build_artifact)["spiders"]`. This allows a template or schedule override such as `scrapy crawl typo_spider` to pass creation and dispatch, even when the selected artifact exposes a different spider list. The previous structured UI prevented this class of mistake, and phase 1.8.1 still requires server-side command validation before dispatch.

   Required fix: once the artifact is known, reject commands whose parsed spider is not in the artifact spider list. Apply this for template create/update and resolved runs so schedule overrides are also covered.

2. `P1` Blank schedule command overrides are rejected instead of inheriting the template command.

   - `apps/server/dopilot_server/services/resolve.py:62`

   The accepted behavior is that schedule command override is optional; blank or absent inherits the execution template command. `sanitize_overrides` currently trims the command and validates it even when it is blank, causing API clients that submit `{"command": ""}` to receive a 400 instead of inheritance.

   Required fix: treat blank command overrides as absent and do not persist them in `overrides`.

3. `P2` Verification is not green.

   - `packages/protocol/tests/test_scrapy_command.py:86`
   - `apps/web/src/pages/TemplatesPage.vue:131`
   - `packages/protocol/dopilot_protocol/__init__.py:9`

   Codex ran the relevant test/build commands and found:

   ```text
   .venv/bin/pytest packages/protocol/tests apps/agent/tests apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py apps/server/tests/test_executions.py apps/server/tests/test_resolve.py
   FAILED packages/protocol/tests/test_scrapy_command.py::test_rejected_grammar[scrapy-missing_spider]

   corepack pnpm --filter web build
   FAILED src/pages/TemplatesPage.vue(131,4): error TS6133: 'id' is declared but its value is never read.

   .venv/bin/ruff check apps packages
   FAILED import block is un-sorted or un-formatted in packages/protocol/dopilot_protocol/__init__.py and packages/protocol/tests/test_scrapy_command.py
   ```

   Required fix: make the parser test expectation and parser semantics consistent, remove the unused TypeScript parameter, and format imports.

## Non-Blocking Notes

- `corepack pnpm --filter web test` passed, but emitted an `intlify` warning because the placeholder text contains `scrapy crawl <spider> ...`. Consider changing the placeholder to avoid HTML-looking angle brackets.
- `cd deploy/docker && docker compose config` passed.

## Required Claude Response

Claude should implement the blocking fixes, add focused tests for artifact spider membership and blank command override inheritance, rerun the narrow verification commands where possible, and write a short response file under this phase directory.
