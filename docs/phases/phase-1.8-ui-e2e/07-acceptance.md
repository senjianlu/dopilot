# 07 · Phase 1.8 UI E2E — Acceptance Summary

## Accepted Scope

Phase 1.8 now has page-functionality acceptance coverage for the real Docker
architecture:

- one server;
- three agents;
- clean compose volumes;
- bundled production SPA at `http://localhost:5000`;
- Playwright Chromium browser automation.

## Covered Page Workflows

- Login and primary navigation.
- Nodes page shows all three agents.
- Build artifacts page uploads the demo Scrapy egg and runs it directly.
- Execution templates page creates a template from the uploaded artifact,
  verifies the generated command is disabled/read-only, and runs the template.
- Task detail page shows child executions and demo spider log markers.
- Tasks page lists and opens task detail.
- Schedules page creates an interval schedule and trigger-now produces a task.
- Nodes page offline, online, and delete operations update visible state.

## Verification

Codex independently reran:

- `scripts/smoke-phase1-ui.sh` — PASS, 7 Playwright specs passed.
- `corepack pnpm --filter web test` — PASS, 23 tests passed.
- `corepack pnpm --filter web build` — PASS.
- `docker ps -a` — no containers left after teardown.

Claude also reported the backend regression tests, lint, and existing Phase 1
bash smoke as passing.

## Decision

Accepted for the current Phase 1.8 page-functionality test requirement.
