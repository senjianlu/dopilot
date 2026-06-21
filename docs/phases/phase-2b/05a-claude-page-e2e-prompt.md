# Claude Test Prompt: Phase 2b Page-Level Docker + Browser E2E

You are Claude Code working in the dopilot repository.

## Assignment

Complete phase 2b page-level validation with Docker containers and browser
automation. The user explicitly requested comprehensive page-level testing after
2b-2, with permission to start Docker containers and operate the browser. This
must cover **both** Python-wheel script execution and the existing Scrapy page
flow.

## Required Context

Read first:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2b/00-brief.md`
- `docs/phases/phase-2b/03a-claude-agent-implementation-report.md`
- `docs/phases/phase-2b/04d-codex-agent-fix-review.md`
- `scripts/smoke-phase1-ui.sh`
- `apps/web/playwright.config.ts`
- `apps/web/e2e/helpers/ui.ts`
- `apps/web/e2e/specs/phase1-ui.spec.ts`
- `deploy/docker/Dockerfile`
- `deploy/docker/docker-compose.yml`
- `deploy/docker/docker-compose.e2e.yml`
- `configs/agent.example.toml`
- `tests/fixtures/python_wheel_demo/`

## What To Validate / Fix

The current browser smoke covers the Scrapy workflow. Extend it so the Docker
page-level smoke also covers phase 2b Python-wheel script execution.

Important acceptance details:

1. **Built-in demo wheel**
   - The user asked for an embedded `.whl` package "like scrapy clock".
   - Verify the Docker image seeds the demo wheel into
     `/server-data/artifacts/python_wheel` with a manifest so `GET /api/v1/artifacts`
     lists it on a clean-volume Docker stack.
   - If it is not seeded today, implement the minimal Docker/artifact-store fix.
     Do not rely only on uploading from the host test fixture.
   - The wheel should be the committed demo wheel:
     `tests/fixtures/python_wheel_demo/dopilot_demo-0.1.0-py3-none-any.whl`.

2. **Script-capable agents**
   - Python-wheel dispatch selects nodes with `capabilities.script == true`.
   - The clean-volume Docker e2e stack must have script-capable agents or the
     wheel run cannot dispatch.
   - If the current compose/config path advertises `script=false`, make the
     smallest phase-2b-appropriate change and cover it in the browser/API smoke.
     Scrapy capability must remain enabled.

3. **Browser flow for Python wheel**
   - Use the real Docker-served production SPA at `http://localhost:5000` through
     Playwright, not a mocked frontend.
   - Through the UI, verify:
     - login and navigation still work;
     - nodes show the expected Scrapy capability and script capability where
       phase-2b expects it;
     - build artifacts page shows the built-in wheel as a runnable
       `python_wheel` / `wheel` artifact and its distribution/details;
     - templates page can create a Python-wheel template from the demo wheel.
       Command should be a shell command. Use an internal URL to avoid external
       network flakiness, for example:
       `DOPILOT_DEMO_URL=http://server:5000/api/v1/health python -m main`
       This still proves the wheel script performs an HTTP request and prints
       response headers.
     - running the wheel template lands on a task detail page;
     - the task reaches `complete`;
     - the execution rows appear for the selected script-capable nodes;
     - the log viewer contains at least:
       - `dopilot-demo: requesting`
       - `dopilot-demo: response headers`
   - Prefer using the existing serial Playwright spec and helpers unless a
     separate spec is cleaner. Keep selectors stable with existing `data-testid`
     patterns; add minimal test ids only if the UI otherwise cannot be driven
     robustly.

4. **Scrapy page flow remains covered**
   - Preserve the existing browser smoke for Scrapy upload/template/run/logs,
     schedule trigger, task detail, and node actions.
   - Do not reduce or skip existing Scrapy assertions.
   - If new phase-2b changes make an old Scrapy assertion stale, fix the test
     or code intentionally and document why.

5. **Optional backend oracle**
   - After the browser smoke passes, run `scripts/smoke-phase1.sh` as a backend
     Scrapy dispatch oracle if feasible. If Docker time or environment blocks
     this second smoke, record the exact blocker. The browser smoke is mandatory.

## Commands To Run

Run the full Docker browser smoke from a clean volume:

```bash
scripts/smoke-phase1-ui.sh
```

This script should build/start the Docker e2e stack, run Playwright Chromium
against the server-served SPA, and tear down containers unless `KEEP_UP=1` is set.
Do not leave containers running after success.

Also run these after any code/test changes:

```bash
.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests
corepack pnpm --filter web test
corepack pnpm --filter web build
.venv/bin/ruff check apps packages
```

If you change Dockerfile/compose/config, also run:

```bash
cd deploy/docker && docker compose config
```

## Required Output

Create/update:

- `docs/phases/phase-2b/05b-claude-page-e2e-report.md`
- `docs/phases/phase-2b/claude-progress.md`

The report must include:

- code/test/config files changed;
- what browser paths were tested;
- Docker/browser commands run and exact pass/fail outcomes;
- whether containers were torn down;
- screenshots/video/trace artifact paths if Playwright fails;
- any residual risk or blocked command.

## Constraints

- Do not edit `reference/scrapydweb/`.
- Do not skip the Docker browser smoke.
- Do not leave long-running Claude/Docker/browser processes behind.
- Do not change the phase-2b execution strategy: no venv, no dependency
  resolution, no console-script dependency, no server-side Python execution.
