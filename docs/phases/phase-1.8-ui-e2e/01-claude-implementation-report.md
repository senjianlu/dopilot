# 01 · Phase 1.8 UI E2E — Claude Implementation Report

## Summary

Added browser-level page-functionality e2e testing for the current Phase 1.8
version. Tests drive the **bundled production SPA served by the Docker `server`
container at `http://localhost:5000`** (not a Vite dev server), against the real
one-server / three-agent stack (PostgreSQL + Redis + migrate + server +
`scrapy-agent-{1,2,3}`), from clean compose volumes.

The work is purely additive to test infrastructure plus minimal, stable
`data-testid` hooks on existing UI. No backend behavior, dispatch logic, or
runtime/image packaging was changed. `scripts/smoke-phase1.sh` is preserved
unchanged as the exact multi-agent dispatch/count/log oracle.

## What changed

### Playwright infrastructure (apps/web)

- `apps/web/package.json` — added `@playwright/test@^1.49` (devDependency) and a
  `test:e2e` script (`playwright test`).
- `apps/web/playwright.config.ts` (new) — Chromium **headless only**, single
  project, `baseURL` from `E2E_BASE_URL` (default `http://localhost:5000`),
  `testDir: ./e2e`. Runs **serial, 1 worker, 0 retries** because the specs
  mutate shared backend state and are order-dependent (a retry would replay
  against already-mutated state). `trace`/`screenshot`/`video` =
  retain/​only-on-failure. Reporters: `list` + `html` (`playwright-report/`),
  artifacts under `test-results/`. Never starts a `webServer` — the Docker stack
  serves the SPA.
- `apps/web/vite.config.ts` — scoped Vitest to `include: ["src/**/*.{test,spec}.ts"]`
  so the unit runner does not pick up the Playwright `*.spec.ts` under `e2e/`.
- `apps/web/e2e/helpers/ui.ts` (new) — `login()`, `selectOption()` (Element Plus
  teleported-dropdown picker, role-based + optional exact match),
  `waitForExecutionCount()` and `waitForLogMarkers()` (reload-poll helpers, since
  the task-detail page loads once on mount and does not auto-refresh), plus
  shared constants (admin creds, agent ids, demo markers).
- `apps/web/e2e/specs/phase1-ui.spec.ts` (new) — one serial, single-session flow
  of 7 specs covering the full test plan (below).
- `.gitignore` — ignore `apps/web/test-results/`, `playwright-report/`,
  `blob-report/`, `.cache/`.

### Stable `data-testid` hooks (minimum necessary)

Default UI locale is **zh**, so hooks are testid-based and assertions use
Element Plus `el-tag--*` type classes rather than translated text.

- `layouts/MainLayout.vue` — `app-shell`, `nav-{dashboard,nodes,artifacts,
  templates,schedules,tasks}`, `logout`.
- `pages/LoginPage.vue` — `login-username`, `login-password`, `login-submit`.
- `pages/NodesPage.vue` — `nodes-table`; per-row keyed by `agent_id`:
  `node-agent-*`, `node-badge-*`, `node-scrapyd-*`, `node-offline-*`,
  `node-online-*`, `node-delete-*`.
- `pages/BuildArtifactsPage.vue` — `artifact-upload`, `artifact-upload-button`,
  `artifacts-table`; per-row keyed by `name`: `artifact-name-*`,
  `artifact-type-*`, `artifact-format-*`, `artifact-run-*`. Added a visible
  **Format** column (new i18n key `artifacts.format` in `en.ts`/`zh.ts`) so the
  package format (`egg`) is visible page data per the test plan.
- `pages/TemplatesPage.vue` — `template-create`, `templates-table`,
  `template-name-*` (row), `template-run-*` (row); dialog: `template-dialog`,
  `template-name-input`, `template-artifact-select`, `template-spider-select`,
  `template-project`, `template-version`, `template-command`, `template-submit`.
- `pages/TaskDetailPage.vue` — `task-detail`, `task-status`, `task-executions`,
  `execution-agent-*`.
- `components/LogViewer.vue` — `log-body`.
- `pages/TasksPage.vue` — `tasks-table`, `task-view-*` (row link).
- `pages/SchedulesPage.vue` — `schedule-create`, `schedules-table`,
  `schedule-name-*` (row), `schedule-trigger-*` (row); dialog: `schedule-dialog`,
  `schedule-name-input`, `schedule-template-select`, `schedule-interval`,
  `schedule-submit`.

### Container-backed UI smoke

- `scripts/smoke-phase1-ui.sh` (new, executable) — clean-volume runner separate
  from the bash oracle:
  1. ensures Playwright Chromium is installed (skips if already present);
  2. `docker compose ... down -v`, builds base images, `up -d --build` the
     one-server/three-agent stack (base + `docker-compose.e2e.yml`);
  3. waits for db/migrate/3 agents/server healthy, then polls the API until
     three healthy, scrapy-capable, schedulable nodes exist (so the browser
     does not race agent registration / scrapyd startup);
  4. runs `playwright test` against `http://localhost:5000`;
  5. tears the stack down on exit unless `KEEP_UP=1` and the run passed; dumps
     `docker compose ps` + server/agent logs + Playwright artifact paths on
     failure. Honors `E2E_GREP` for subset runs.

## Browser coverage (7 serial specs, one logged-in session)

1. **login + navigation** — login via UI, app shell appears, walk all nav items
   and assert each landing page's table/root renders.
2. **nodes page** — three agent rows render; each shows the healthy (green)
   badge; scrapyd cell renders.
3. **build artifacts** — upload `tests/fixtures/scrapy_demo/eggs/demo_phase1.egg`
   via the el-upload input; row appears with type `scrapy` and format `egg`;
   direct run navigates to task detail with three executions.
4. **execution templates** — open create dialog, select the uploaded artifact,
   select spider `phase1`, assert project resolves read-only, assert the Scrapy
   command field is **disabled**; submit; row appears; run navigates to task
   detail; assert three child executions on the three agents; assert the log
   viewer surfaces both demo markers (`phase1 demo spider started` / `done`).
5. **tasks page** — created tasks listed; open a detail page from the list.
6. **schedules page** — create an interval schedule referencing the template;
   trigger-now navigates to a task detail page.
7. **nodes offline/online/delete** (last, after dispatch-sensitive flows) —
   offline → red badge + online control; online → green badge; delete → gray
   badge + action controls gone.

## Notable decisions / findings (during test bring-up)

- **el-input forwards `data-testid` to the inner `<input>`** (`inheritAttrs:
  false`), so the testid *is* the input element — helpers target it directly,
  no `.locator('input')`. (Test selector issue, fixed.)
- **Node scrapyd tag legitimately reads "unknown" in the nodes list.** The
  heartbeat health snapshot carries `scrapyd: {port, managed}` but **no live
  `running` probe** — that field exists only on the agent's own `/health`
  endpoint, which the bash oracle uses. This is existing behavior, not a
  regression; the spec asserts the authoritative healthy (green) node badge and
  that the scrapyd cell renders, rather than green scrapyd. (Documented as
  residual UX note in the test report.)
- **Element Plus select option matching needs exact/role-based selectors** — the
  spider `phase1` is a substring of the artifact label `demo · demo_phase1.egg`,
  so `selectOption` uses `getByRole('option', {exact})`. (Test selector issue,
  fixed.)

## Out of scope (untouched)

- `reference/scrapydweb/` — not read as source, not edited.
- Python wheel runtime / Docker image runtime packaging.
- `scripts/smoke-phase1.sh` — preserved unchanged as the dispatch oracle.
- Backend dispatch / health / scheduling logic.

## Commands

Recorded with exact outcomes in `05-claude-test-report.md`.
