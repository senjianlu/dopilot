# Phase 2a — Browser UI E2E Verification Report

## Summary

Phase 2a (the `task_id` / `execution_id` id-naming clean-cut) was verified with
**real browser page operations** against the bundled production SPA served by the
Docker stack at `http://localhost:5000`. The original phase 2a acceptance
(`03-acceptance-report.md`) covered protocol/server/agent unit + integration
suites and the Alembic migration round-trip, but did **not** run the browser UI
e2e. This report closes that gap.

**Result: PASS.** After two minimal, test-only fixes to stale Playwright
assertions (both stale since phase 1.8.2, neither caused by phase 2a), the full
browser smoke is green — all 7 specs pass, including the phase-2a-relevant
run → task-detail → executions → logs workflow.

## Existing tests vs. new tests

**No new test was added.** The existing spec
`apps/web/e2e/specs/phase1-ui.spec.ts` already covers the entire
phase-2a-relevant browser path end to end:

- login + app-shell navigation across all primary pages;
- nodes list (3 agents healthy, scrapy-capable);
- build-artifact upload (demo egg);
- execution template create + **run → task detail → 3-execution fan-out → live
  log markers** (this is the path the id rename could regress);
- tasks list → task detail;
- schedule create + trigger-now → task;
- node offline / online / soft-delete state transitions.

Phase 2a was an internal id rename with **zero public HTTP/web drift** (confirmed
in the brief, implementation report, and codex review: `apps/web/**` and
`test_sse.py` were never edited). The existing spec is therefore the correct
regression net, so it was run rather than duplicated. Two stale assertions in it
had to be repaired before it could exercise the workflow (see Changed Files).

## Exact commands run

```bash
scripts/smoke-phase1-ui.sh        # run 1 — failed (stale node-scrapyd assertion)
scripts/smoke-phase1-ui.sh        # run 2 — failed (stale node offline confirm dialog)
scripts/smoke-phase1-ui.sh        # run 3 — PASS (7/7 after both test-only fixes)
```

The script performs the full e2e lifecycle each run: `docker compose down -v` →
build base images → `up -d --build` (db, redis, migrate, server + 3 agents) →
wait for health + 3 schedulable nodes via the API → run Playwright Chromium
(headless) against `http://localhost:5000` → tear down (`down -v`) on exit.

## Pass/fail result

Final run (run 3):

```
Running 7 tests using 1 worker
  ✓ 1  login and navigation loads the app shell and pages (1.5s)
  ✓ 2  nodes page renders the three agents as scrapy-healthy (229ms)
  ✓ 3  build artifacts page uploads the demo egg (not directly runnable) (242ms)
  ✓ 4  execution templates page creates a command template and runs it (9.2s)
  ✓ 5  tasks page lists created tasks and opens a detail page (374ms)
  ✓ 6  schedules page creates an interval schedule and trigger-now lands on a task (1.7s)
  ✓ 7  nodes page offline/online/delete actions update visible state (1.8s)
  7 passed (16.1s)
UI SMOKE PASSED
```

## Browser workflow coverage confirmed

- **Login / auth / SPA shell** — admin login, navigation across nodes,
  artifacts, templates, schedules, tasks.
- **Nodes** — 3 compose agents persisted, healthy, scrapy-capable (green badge +
  scrapy capability tag); offline → red, online → green, soft-delete → gray with
  action controls removed.
- **Build artifacts** — demo egg upload (type=scrapy, format=egg), correctly
  non-runnable on the row.
- **Execution template → run (phase-2a critical path)** — command-first template
  created from the uploaded artifact, run dispatched, lands on task detail, **3
  child executions fan out (one per agent)**, and the **live SSE log viewer
  surfaces both demo markers** (`phase1 demo spider started` /
  `phase1 demo spider done`). This is the run/dispatch/event/log chain whose
  internal ids were renamed in 2a; it works through the browser unchanged.
- **Tasks** — task list renders, opens detail with status.
- **Schedules** — interval schedule created against the template; trigger-now
  creates a task and navigates to its detail.

The id rename is exercised implicitly and correctly: dispatch fan-out, execution
rows, and persisted/streamed logs all render, which requires the renamed
`task_id`/`execution_id` seam to be consistent across Redis commands, server
DB/log paths, agent state, and the log consumer.

## Failure diagnostics

Both initial failures were **pre-existing stale-test defects introduced in commit
`f93f358` (phase 1.8.2 "maintenance and demo controls")**, where the UI changed
but the e2e spec was not re-run/updated. Neither is a phase-2a regression — phase
2a changed only `.py` files under `apps/server`, `apps/agent`, and
`packages/protocol` (`git status` shows zero `apps/web` changes from 2a).

1. **Run 1 — `node-scrapyd-*` not found** (`phase1-ui.spec.ts:76`).
   The nodes table no longer has a scrapyd-subprocess health column.
   `git log -S node-scrapyd` shows the column + `node-scrapyd-*` testid were
   **removed in `f93f358`**, which folded scrapyd health into a single status
   badge + per-capability tag column. The spec kept asserting the deleted cell.
   The DOM snapshot confirmed all 3 nodes render healthy with the new
   capability-tag column — the only missing element was the removed cell.

2. **Run 2 — offline badge stayed `el-tag--success`** (`phase1-ui.spec.ts:197`).
   `onOffline`/`onDelete` now route through `@/utils/confirm`
   (`ElMessageBox.confirm`), also **added in `f93f358`**. The spec clicked the
   offline/delete buttons but never accepted the confirmation modal, so the
   request never fired and the node stayed healthy. (`onOnline` has no confirm,
   matching the test's online step.)

Classification: **stale e2e setup (phase 1.8.2), not phase-2a code, not Docker /
browser environment, not flakiness.** The run/detail/logs workflow passed on the
first run that reached it and again on the final run; no retries were needed.

## Changed files

Test-only, minimal, no product changes:

- `apps/web/e2e/specs/phase1-ui.spec.ts`
  - Re-pointed the stale `node-scrapyd-${agentId}` visibility assertion to the
    current scrapy-capability cell `node-cap-${agentId}-scrapy` (preserves the
    "scrapy-capable" intent against the post-1.8.2 UI).
  - Accept the `ElMessageBox` confirmation after the node **offline** and
    **delete** clicks (online is intentionally not confirmed).
- `apps/web/e2e/helpers/ui.ts`
  - Added `confirmMessageBox(page)` helper that clicks the EP message-box primary
    button by its stable class (locale-independent).

```
 apps/web/e2e/helpers/ui.ts           | 10 ++++++++++
 apps/web/e2e/specs/phase1-ui.spec.ts | 18 +++++++++++++-----
```

No `apps/web/src/**` (product) files were changed. No `reference/scrapydweb/`
edits.

## Final Docker / container state

Clean. The smoke's EXIT trap ran `docker compose down -v --remove-orphans` after
the passing run; `docker compose ... ps -a` shows **no containers and no
volumes** remaining. No stack was left running.

## Recommendation

Phase 2a is confirmed at the browser-UI level. The browser smoke
(`scripts/smoke-phase1-ui.sh`) is now green and should be added to the standard
acceptance command set so the spec does not silently drift again, as it did
between phase 1.8.2 and now.
