# Claude Verification Prompt: Phase 2a Browser UI E2E

You are Claude Code working in the dopilot repository.

## Assignment

Verify phase 2a with real browser page operations.

Codex already confirmed phase 2a unit/integration coverage, but browser UI e2e
was not run in the original acceptance. Existing Playwright coverage appears to
exist:

- `apps/web/e2e/specs/phase1-ui.spec.ts`
- `apps/web/e2e/helpers/ui.ts`
- `scripts/smoke-phase1-ui.sh`

First inspect these existing tests. If they cover the current page workflow
through run/detail/logs after phase 2a, do not add new tests; run the existing
browser smoke. If they do not cover the phase-2a-relevant browser path, add the
smallest missing Playwright coverage and run it.

## Required Context

Read:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-2a/00-brief.md`
- `docs/phases/phase-2a/01-claude-implementation-report.md`
- `docs/phases/phase-2a/02-codex-review.md`
- `docs/phases/phase-2a/03-acceptance-report.md`
- `apps/web/e2e/specs/phase1-ui.spec.ts`
- `scripts/smoke-phase1-ui.sh`

## Expected Command

Prefer:

```bash
scripts/smoke-phase1-ui.sh
```

This script should build/start the Docker e2e stack, run Playwright Chromium
against the production SPA at `http://localhost:5000`, and tear down afterward.

If a narrower command is required for diagnosis, record why and still return to
the full smoke when possible.

## Constraints

- Do not edit `reference/scrapydweb/`.
- Do not make product changes.
- Do not add duplicate e2e tests if the existing browser smoke already covers
  login/navigation/upload/template-run/task-detail/logs/schedule/node actions.
- If you must edit tests or scripts, keep the change minimal and explain why.
- If the browser smoke fails, diagnose whether the failure is from phase-2a code,
  stale e2e setup, Docker/browser environment, or test flakiness.
- Do not leave Docker containers running unless the command fails and diagnostics
  require it; report final container state.

## Output Required

Create or update:

- `docs/phases/phase-2a/04-ui-e2e-verification-report.md`
- `docs/phases/phase-2a/claude-progress.md`

The report must include:

- whether existing tests were sufficient or a new test was added;
- exact command(s) run;
- pass/fail result;
- key browser workflow coverage confirmed;
- failure diagnostics and changed files, if any;
- final Docker/container state.
