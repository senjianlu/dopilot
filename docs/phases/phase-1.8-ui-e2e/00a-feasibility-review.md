# 00a · Phase 1.8 UI E2E Feasibility Review

## Proposed Direction

Add browser-level page functionality tests for Phase 1.8. Tests run against the
real Docker stack with one server and three agents, using clean compose volumes.

## Claude Feedback

### Verdict

Feasible.

### Key Points

- The server container serves the bundled SPA at `http://localhost:5000`, so
  browser tests can exercise the shipped UI rather than a Vite dev server.
- The existing three-agent compose e2e stack can be reused.
- Playwright is the recommended runner because Element Plus dialogs/selects and
  upload controls are easier to drive reliably in a real browser.
- The current UI has no `data-testid` hooks. Stable browser tests should add
  targeted test ids to navigation, forms, upload controls, tables, row actions,
  task detail, and log viewer elements.
- Browser e2e should be separate from the bash smoke:
  - Playwright proves page workflows;
  - `scripts/smoke-phase1.sh` remains the dispatch/count/log oracle.

## Codex Decision

Accepted.

This task supersedes the previous Phase 1.8 e2e note that browser/UI automation
was out of scope. The user explicitly requested page functionality testing.

Codex decisions:

- Add Playwright Test to `apps/web`.
- Add `data-testid` attributes where needed for stable e2e selectors.
- Run Chromium headless only.
- Use clean Docker volumes; old data may be deleted.
- Keep UI e2e and bash smoke as separate commands.
- Cover browser workflows across pages, including node action buttons, while
  retaining the bash smoke as the exact multi-agent dispatch oracle.

## User Escalations

None. The user already approved deleting old data and requested container-based
page functionality testing.
