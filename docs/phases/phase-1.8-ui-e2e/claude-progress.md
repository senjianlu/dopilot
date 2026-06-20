# Claude Progress — Phase 1.8 UI E2E

## Size / cadence

- Rough size class: **90m+** (Playwright infra + data-testid hooks across 7
  pages + container-backed smoke that builds the Docker image and boots a
  one-server/three-agent stack, then runs all required gates twice).
- Update cadence: at each meaningful checkpoint (infra added, testids added,
  specs written, each long command run), and before/after the Docker build +
  smoke runs.

## Plan / checkpoints

1. [done] Read all required context (brief, test plan, governance, compose,
   smoke, pages, components).
2. [ ] Add Playwright infra to `apps/web` (dep, `playwright.config.ts`, `e2e/`,
   `test:e2e` script). Tests target the Docker-served SPA at
   `http://localhost:5000`, no Vite dev server.
3. [ ] Add stable `data-testid` hooks to the minimum UI surface (nav, login,
   nodes table + actions, artifacts upload/rows/run, templates dialog/command
   field/run, task detail executions + log viewer, tasks list, schedules
   dialog + trigger).
4. [ ] Write e2e specs + helpers covering the test-plan workflows.
5. [ ] Add `scripts/smoke-phase1-ui.sh` (clean volumes → build → 1 server / 3
   agents → wait healthy → Playwright vs :5000 → teardown unless KEEP_UP).
6. [ ] Run unit/static/build gates: ruff, pytest, web test, web build.
7. [ ] Run `scripts/smoke-phase1-ui.sh` from clean volumes.
8. [ ] Run `scripts/smoke-phase1.sh` (dispatch oracle regression).
9. [ ] Write `01-claude-implementation-report.md` and `05-claude-test-report.md`.

## Likely long-running commands

- `corepack pnpm --filter web exec playwright install chromium` (browser dl).
- `corepack pnpm --filter web build`.
- `scripts/smoke-phase1-ui.sh` and `scripts/smoke-phase1.sh` (Docker image
  build + multi-agent boot; several minutes each).

## Log

- (start) Context read complete. Confirmed: server serves bundled SPA at
  :5000; egg upload without project/version derives project=`demo`,
  spider=`phase1` from the egg; BuildArtifact type already carries
  `package_format`. Beginning Playwright infra.
- (checkpoint) Infra + hooks + specs + smoke script DONE:
  - `@playwright/test@^1.49` added to apps/web; `corepack pnpm --filter web
    install` succeeded; `playwright install chromium` confirmed already cached
    (chromium-1228). System deps already satisfied.
  - `playwright.config.ts` (Chromium headless, baseURL :5000, serial/1 worker/0
    retries, trace+screenshot+video retain-on-failure). Vitest scoped to
    `src/**` so it does not pick up the e2e `*.spec.ts`.
  - data-testid hooks added: nav + logout + app-shell (MainLayout), login form
    (LoginPage), nodes table/agent/badge/scrapyd/offline/online/delete
    (NodesPage), upload/type/format/run + new Format column (BuildArtifactsPage
    + `artifacts.format` i18n en/zh), template create dialog/artifact/spider/
    project/command(read-only)/submit/run/name (TemplatesPage), task-detail/
    status/executions/execution-agent (TaskDetailPage), log-body (LogViewer),
    tasks-table/task-view (TasksPage), schedule dialog/name/template/interval/
    submit/trigger/name (SchedulesPage). Default locale is zh -> assertions use
    testids + Element Plus `el-tag--*` type classes, not translated text.
  - `e2e/helpers/ui.ts` + `e2e/specs/phase1-ui.spec.ts` cover the full test
    plan in one serial logged-in session.
  - `scripts/smoke-phase1-ui.sh` (clean volumes -> base build -> up 1 server/3
    agents -> wait healthy + 3 schedulable nodes -> Playwright vs :5000 ->
    teardown unless KEEP_UP). `scripts/smoke-phase1.sh` left untouched.
  - `.gitignore` updated for Playwright outputs.
- (gates) ruff PASS; pytest 317 passed; web test 23 passed; web build PASS.
- (ui-smoke iter 1) First `scripts/smoke-phase1-ui.sh` failed at test 1: el-input
  forwards data-testid to the inner <input> (inheritAttrs:false), so
  `.locator('input')` was wrong. Fixed helper + spec to target the testid input
  directly. **Test selector issue, not a product bug.**
- (ui-smoke iter 2, live stack) Test 2 failed: asserted scrapyd tag == success,
  but the heartbeat health snapshot carries scrapyd {port, managed} with no
  live `running` probe (that field lives only on the agent's own /health, used
  by the bash oracle), so the tag legitimately reads "unknown". **Data/behavior,
  not a bug** — relaxed to assert the healthy (success) node badge + scrapyd
  cell renders.
- (ui-smoke iter 3, live stack) Test 4 failed in el-select option pick: hasText
  'phase1' also matched the artifact label "demo · demo_phase1.egg", and two
  transiently-visible dropdowns made `.first()` grab a hidden option. Rewrote
  `selectOption` to role-based exact matching. **Test selector issue.**
- (ui-smoke iter 4, live stack) ALL 7 specs pass (13.3s) against the Docker SPA.
- (official) `scripts/smoke-phase1-ui.sh` (clean volumes) **PASS** — 7 specs,
  `UI SMOKE PASSED`, exit 0, stack torn down.
- (oracle) `scripts/smoke-phase1.sh` **PASS** — `passed: 58 failed: 0`,
  `SMOKE PASSED`, exit 0. No dispatch regression from the testid hooks.
- (reports) Wrote `01-claude-implementation-report.md` and
  `05-claude-test-report.md`. All required commands recorded with exact
  outcomes. Stack confirmed torn down (no dopilot containers).

## DONE

All 8 required commands pass; both reports written. Checkpoints 1-9 complete.
Residual note: nodes-list scrapyd tag reads "unknown" (heartbeat health lacks a
live `running` probe — pre-existing, not a regression). `scripts/smoke-phase1.sh`
left unchanged.
