# 00 · Phase 1.8 UI E2E Brief

## Goal

Add browser-level page functionality tests for the current Phase 1.8 version.

The tests must run against the real Docker stack:

- one server container;
- three agent containers;
- PostgreSQL;
- Redis;
- migrate container;
- bundled production SPA served by the server container.

Old data may be deleted. The test stack should start from clean compose volumes.

## Context

Read before editing:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-1.8/00-brief.md`
- `docs/phases/phase-1.8-e2e-acceptance/00-brief.md`
- `docs/phases/phase-1.8-e2e-acceptance/07-acceptance.md`
- `docs/phases/phase-1.8-ui-e2e/04-test-plan.md`
- `deploy/docker/docker-compose.yml`
- `deploy/docker/docker-compose.e2e.yml`
- `scripts/smoke-phase1.sh`
- `apps/web/package.json`
- `apps/web/src/router/index.ts`
- `apps/web/src/pages/*.vue`

## In Scope

- Add Playwright browser e2e infrastructure for `apps/web`.
- Add stable `data-testid` hooks to page components where needed.
- Add a script or Make target that:
  - tears down the e2e compose stack with volumes;
  - builds/starts the one-server/three-agent stack;
  - waits for the stack to be usable;
  - runs Playwright against `http://localhost:5000`;
  - tears the stack down unless a debug flag asks to keep it up.
- Cover these page workflows:
  - login;
  - dashboard/navigation loads;
  - nodes page renders three agents;
  - build artifacts page uploads the demo egg and runs an artifact;
  - execution templates page creates a template from a build artifact, shows the
    Scrapy command read-only, and runs the template;
  - task detail page shows executions and log markers;
  - tasks page lists created tasks and can open a detail page;
  - schedules page creates a schedule and trigger-now navigates to a task;
  - nodes page offline/online/delete actions update visible state.
- Preserve the existing bash `scripts/smoke-phase1.sh` as the dispatch oracle.

## Out Of Scope

- Python wheel runtime.
- Docker image runtime.
- Browser coverage for every visual state.
- Multi-browser matrix. Chromium headless is enough.
- Editing or copying from `reference/scrapydweb/`.

## Required Implementation Order

1. Add Playwright dependency/config and package scripts.
2. Add stable `data-testid` hooks to the minimum necessary UI elements.
3. Add browser e2e specs and helpers.
4. Add a container-backed UI smoke script, separate from `smoke-phase1.sh`.
5. Run unit/static/build gates.
6. Run the container-backed UI smoke from clean volumes.
7. Run the existing API/runtime smoke to ensure browser-test hooks did not
   regress dispatch behavior.
8. Report exact command outcomes and any residual risk.

## Acceptance Criteria

- Playwright tests run against the Docker-served SPA at `http://localhost:5000`.
- The stack uses one server and three agents.
- The browser logs in through the UI.
- The browser verifies the nodes page shows three agents.
- The browser uploads the demo Scrapy egg through the build artifacts page.
- The browser creates an execution template using the uploaded build artifact.
- The browser confirms the Scrapy command field is disabled/read-only.
- The browser runs the template and lands on a task detail page.
- The task detail page shows child executions and log content containing the demo
  markers.
- The browser creates a schedule and trigger-now lands on a task detail page.
- The browser exercises node offline/online/delete controls and sees state
  changes.
- Existing backend/frontend tests and the bash smoke still pass.

## Required Commands

Claude must run and report exact outcomes:

```bash
corepack pnpm --filter web install
corepack pnpm --filter web exec playwright install chromium
.venv/bin/ruff check apps packages
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider
corepack pnpm --filter web test
corepack pnpm --filter web build
scripts/smoke-phase1-ui.sh
scripts/smoke-phase1.sh
```

If Playwright browser binaries are already installed, report that rather than
forcing a reinstall.

## Risks To Watch

- Browser tests must not depend on fragile translated text where a stable
  `data-testid` is reasonable.
- The production SPA is baked into the Docker image; UI code changes require a
  rebuild before Playwright runs.
- Element Plus selects/dialogs are teleported to `body`; tests must handle that.
- Browser tests that mutate node state must either run after create/run flows or
  reset state before dispatch-sensitive assertions.
