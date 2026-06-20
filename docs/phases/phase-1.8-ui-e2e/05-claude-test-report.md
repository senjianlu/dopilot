# 05 · Phase 1.8 UI E2E — Claude Test Report

## Environment

- Host: Linux, Docker 29.5.3, Docker Compose v5.1.4, Node v22.22.3 (corepack
  pnpm v11.7.0), Playwright `@playwright/test@1.49.x`, Chromium `chromium-1228`.
- UI default locale: **zh** — browser assertions use `data-testid` + Element
  Plus `el-tag--*` type classes, not translated text.
- Stack under test: `docker-compose.yml` + `docker-compose.e2e.yml` — one
  server, three agents (`scrapy-agent-{1,2,3}`), PostgreSQL, Redis, migrate,
  bundled production SPA at `http://localhost:5000`, from **clean compose
  volumes**.

## Required commands — exact outcomes

| Command | Result |
| --- | --- |
| `corepack pnpm --filter web install` | **PASS** — `Done in 8.2s using pnpm v11.7.0`; added `@playwright/test` (+3 packages). Valid workspace install (apps/web is the workspace package). |
| `corepack pnpm --filter web exec playwright install chromium` | **PASS (already installed)** — exit 0; `~/.cache/ms-playwright/chromium-1228` present; system deps already satisfied. No re-download forced. |
| `.venv/bin/ruff check apps packages` | **PASS** — `All checks passed!` |
| `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider` | **PASS** — `317 passed in 7.41s` |
| `corepack pnpm --filter web test` | **PASS** — `Test Files 8 passed (8)` / `Tests 23 passed (23)` (Vitest scoped to `src/`; e2e specs excluded) |
| `corepack pnpm --filter web build` | **PASS** — `vue-tsc -b && vite build` → `built in 6.26s` (typecheck clean) |
| `scripts/smoke-phase1-ui.sh` | **PASS** — clean volumes → 1 server / 3 agents healthy → 3 schedulable nodes → Playwright **7 passed (15.9s)** → `UI SMOKE PASSED` (exit 0); stack torn down |
| `scripts/smoke-phase1.sh` | **PASS** — `passed: 58   failed: 0` → `SMOKE PASSED` (exit 0); dispatch oracle unaffected |

## Browser e2e result (scripts/smoke-phase1-ui.sh, clean volumes)

```
✓ 1 login and navigation loads the app shell and pages (1.5s)
✓ 2 nodes page renders the three agents as scrapy-healthy (227ms)
✓ 3 build artifacts page uploads the demo egg and runs it (581ms)
✓ 4 execution templates page creates a template with a read-only command and runs it (9.4s)
✓ 5 tasks page lists created tasks and opens a detail page (543ms)
✓ 6 schedules page creates an interval schedule and trigger-now lands on a task (1.6s)
✓ 7 nodes page offline/online/delete actions update visible state (1.1s)

7 passed (15.9s)
```

## Acceptance-criteria mapping

| Criterion | Spec | Status |
| --- | --- | --- |
| Tests run against the Docker SPA at `http://localhost:5000` | config `baseURL` / smoke `E2E_BASE_URL` | ✅ |
| One server, three agents | base + `docker-compose.e2e.yml`; smoke waits all healthy | ✅ |
| Browser logs in through the UI | spec 1 (`login()`) | ✅ |
| Nodes page shows three agents | spec 2 (3 `node-agent-*` rows, exact count) | ✅ |
| Uploads the demo Scrapy egg via build artifacts page | spec 3 (el-upload input → `demo_phase1.egg`) | ✅ |
| Creates an execution template from the uploaded artifact | spec 4 (artifact select → submit) | ✅ |
| Scrapy command field disabled/read-only | spec 4 (`template-command` `toBeDisabled`) | ✅ |
| Runs the template, lands on a task detail page | spec 4 (URL `/tasks/:id`) | ✅ |
| Task detail shows child executions + demo-marker logs | spec 4 (3 `execution-agent-*` + log markers) | ✅ |
| Creates a schedule; trigger-now lands on a task | spec 6 | ✅ |
| Node offline/online/delete state changes | spec 7 (badge `el-tag--danger`/`--success`/`--info`) | ✅ |
| Existing backend/frontend tests + bash smoke pass | ruff/pytest/vitest/build + `smoke-phase1.sh` | ✅ |

## Failures encountered and resolved (during bring-up)

1. **el-input selector** — `getByTestId(...).locator('input')` timed out;
   Element Plus el-input (`inheritAttrs: false`) forwards `data-testid` onto the
   inner `<input>`. *Classification: test selector issue.* Fixed: target the
   testid element directly.
2. **scrapyd tag color** — asserted `el-tag--success`, but the nodes-list
   heartbeat health carries `scrapyd: {port, managed}` with no live `running`
   field (that field exists only on the agent's own `/health`, used by the bash
   oracle), so the tag reads "unknown" (`el-tag--info`). *Classification:
   existing data/behavior, not a regression.* Fixed: assert the authoritative
   healthy (green) node badge + that the scrapyd cell renders.
3. **el-select option pick** — `hasText: 'phase1'` also matched the artifact
   label `demo · demo_phase1.egg`, and two transiently-visible teleported
   dropdowns made `.first()` resolve a hidden option. *Classification: test
   selector issue.* Fixed: `selectOption` uses `getByRole('option', {exact})`.

All three were resolved in the test layer (plus the visible-data Format column);
no product/dispatch logic was changed.

## Residual risks / notes

- **Nodes scrapyd "running" not in the list view.** The nodes page scrapyd
  column reads "unknown" because the periodic heartbeat health snapshot does not
  carry a live scrapyd `running` probe (only `{port, managed}`); the live probe
  is on the agent's own `/health`. This is a pre-existing UX detail, not
  introduced here. If a green scrapyd indicator in the nodes list is desired,
  the agent heartbeat health payload would need to include `scrapyd.running`
  (backend change, out of scope for UI e2e).
- **State-mutating, serial, no-retry.** The specs share one session and mutate
  backend state (upload/run/node delete), so they run serially with 0 retries
  and must be run from clean volumes (`scripts/smoke-phase1-ui.sh` enforces
  `down -v` first). Re-running against a live post-run stack would fail (a node
  was soft-deleted) — by design.
- **SPA is baked into the image.** UI code changes require an image rebuild
  before Playwright runs; `scripts/smoke-phase1-ui.sh` always `up -d --build`.
- `scripts/smoke-phase1.sh` was **not modified**; it remains the exact
  multi-agent dispatch/count/log oracle.
