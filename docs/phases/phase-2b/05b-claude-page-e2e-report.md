# Phase 2b — Claude Page-Level Docker + Browser E2E Report

Page-level validation of phase 2b on the real clean-volume Docker stack
(PostgreSQL + Redis + migrate + server + three agents) driven through the
bundled production SPA at `http://localhost:5000` with Playwright/Chromium. This
extends the existing Scrapy browser smoke to also cover the **Python-wheel**
script-execution path end to end, and seeds the built-in demo wheel into the
image so a clean-volume stack lists it without a host upload.

## Status

**Complete.** The mandatory Docker browser smoke passes (9/9 specs, including the
two new wheel specs). The optional backend Scrapy dispatch oracle
(`scripts/smoke-phase1.sh`) result is recorded below. All containers were torn
down after each run (no `KEEP_UP`).

## What was missing before this work (the three gaps the brief flagged)

1. **Demo wheel not seeded into the image.** The Dockerfile seeded only the
   Scrapy clock egg into `/server-data/artifacts/scrapy`. A clean-volume stack
   had no `python_wheel` artifact, so `GET /api/v1/artifacts` listed none and the
   wheel browser flow could not run without a host upload.
2. **Agents advertised `script = false`.** `configs/agent.example.toml` (mounted
   by all three e2e agents) disabled the `script` capability, so a
   `python_wheel` run — which selects `capabilities.script == true` nodes — had
   zero targets and would resolve to `no_target`.
3. **Browser smoke covered Scrapy only.** `phase1-ui.spec.ts` had no
   Python-wheel artifact/template/run/log assertions.

## Code / test / config files changed

| File | Change |
| --- | --- |
| `deploy/docker/Dockerfile` | Seed the committed demo wheel into `/server-data/artifacts/python_wheel` at build time, reusing the server's own `WheelArtifactStore.save()` so the on-disk wheel bytes + `{sha}.json` manifest are byte-identical to an admin upload (same sha256 dedupe key the agent later fetches/installs). Mirrors the existing scrapy_clock egg seed. |
| `configs/agent.example.toml` | `[capabilities] script = true` (was `false`). The unified agent image ships `python` + `pip`, so it can run `python_wheel` ("script") tasks via `pip install --no-deps --target` + `PYTHONPATH`. Scrapy stays enabled; docker stays disabled. |
| `scripts/smoke-phase1-ui.sh` | `wait_nodes_ready` now also requires `capabilities.script` (in addition to `scrapy`) before the browser run, so the wheel step never races agent heartbeat registration. |
| `apps/web/e2e/helpers/ui.ts` | Added demo-wheel constants (`WHEEL_ARTIFACT_NAME`, `WHEEL_FILENAME`, `WHEEL_MARKER_REQUEST`, `WHEEL_MARKER_HEADERS`), a generic `waitForLogContaining(page, substrings[])` (the old `waitForLogMarkers` is now a thin wrapper over it), and `waitForTaskStatus(page, expected)`. |
| `apps/web/e2e/specs/phase1-ui.spec.ts` | Extended the nodes spec to assert each node's `script` (and `scrapy`) capability tag is the active/green variant; added two serial specs for the wheel flow (artifact listing + template create/run-to-complete), inserted **before** the destructive node offline/delete spec so all three nodes are still healthy + script-capable for the wheel dispatch. |

No server/agent/protocol runtime code was changed — packets 2b-1 and 2b-2 already
implemented the wheel store, executor, capability mapping, agent runner/cache,
and web UI. This work is the Docker-seed + capability-enable + browser-coverage
layer on top.

## Browser paths tested (Playwright/Chromium vs Docker SPA :5000)

Single serial logged-in session (`mode: serial`, 1 worker, 0 retries) so state
created by earlier steps is visible to later ones. 9 specs:

1. **Login + navigation** — login through the real `/login` form; walk nav to
   nodes / artifacts / templates / schedules / tasks; each landing page's root
   testid visible.
2. **Nodes page** — all three agents render as online/healthy (green badge);
   each shows the **scrapy** capability tag green **and** (new) the **script**
   capability tag green; exactly three node rows.
3. **Scrapy artifact upload** — upload the committed demo egg; row shows
   type=`scrapy`, format=`egg`; not directly runnable (no run control).
4. **Scrapy template create + run** — create a command template
   (`scrapy crawl phase1 -a duration_seconds=0`) from the egg; run it; land on
   task detail; three executions (one per node); log viewer shows both demo
   spider markers. (Unchanged; existing Scrapy coverage preserved.)
5. **(new) Demo wheel listed runnable** — on a clean volume the built-in wheel
   appears with name `dopilot-demo`, type=`python_wheel`, format=`wheel`,
   runnable; details dialog shows the distribution and the wheel filename
   `dopilot_demo-0.1.0-py3-none-any.whl`.
6. **(new) Python-wheel template create + run to completion** — create a
   template from the demo wheel; the command field is a free-form **shell
   command** that defaults to `python -m main` and is replaced with
   `DOPILOT_DEMO_URL=http://server:5000/api/v1/health python -m main` (internal
   URL, no external network); run it; land on task detail; **three executions**
   (one per script-capable node); task reaches **`complete`**; log viewer
   contains both `dopilot-demo: requesting` and `dopilot-demo: response headers`.
7. **Tasks page** — lists created tasks; opening one shows task detail + status.
8. **Schedules page** — create an interval schedule referencing the Scrapy
   template; trigger-now lands on a task detail page.
9. **Nodes actions** — offline (confirmed) → red badge; online → green; soft
   delete agent-3 (confirmed) → gray badge, controls gone. (Destructive; runs
   last.)

The wheel flow proves the full phase-2b path on the real stack: server seeds +
lists the wheel → admin creates a `python_wheel` template (shell command) →
`PythonWheelExecutor` selects `script`-capable nodes and dispatches over Redis →
each agent fetches + installs the wheel (`pip install --no-deps --target` +
`PYTHONPATH`) → runs `/bin/sh -c "… python -m main"` → the demo issues an HTTP
request and prints response headers → logs stream over the single `log` stream →
server persists + fans out over SSE → task rolls up to `complete`.

## Docker / browser commands run and exact outcomes

### Mandatory: full Docker browser smoke (clean volume)

```bash
scripts/smoke-phase1-ui.sh
```

Outcome: **PASS.**

- Base images built; unified image built (demo-wheel seed steps ran clean:
  `COPY tests/fixtures/python_wheel_demo/…whl` and the `WheelArtifactStore.save`
  manifest write).
- Services healthy: db, migrate (alembic upgrade head), scrapy-agent-1/2/3,
  server.
- Node gate: **3 nodes healthy + scrapy- + script-capable + schedulable**.
- Playwright: **9 passed (22.2s)** — all specs above, single worker, 0 retries.

```
✓ 1 login and navigation loads the app shell and pages
✓ 2 nodes page renders the three agents as scrapy-healthy
✓ 3 build artifacts page uploads the demo egg (not directly runnable)
✓ 4 execution templates page creates a command template and runs it
✓ 5 build artifacts page lists the built-in demo wheel as runnable
✓ 6 templates page creates a python-wheel template and runs it to completion
✓ 7 tasks page lists created tasks and opens a detail page
✓ 8 schedules page creates an interval schedule and trigger-now lands on a task
✓ 9 nodes page offline/online/delete actions update visible state
9 passed (22.2s)
UI SMOKE PASSED
```

Teardown: `docker compose down -v` ran on exit; verified **no `docker-*`
containers and no `docker_dopilot*` volumes remain**.

### Optional: backend Scrapy dispatch oracle (clean volume)

```bash
scripts/smoke-phase1.sh
```

Outcome: **Scrapy dispatch path PASSED; script exits non-zero on a pre-existing
stale assertion (Case 5), unrelated to phase 2b.**

The oracle drove the full Scrapy path and **every dispatch assertion through
Case 4 passed**:

- 3 agents healthy, scrapyd subprocess running, exactly 3 persisted nodes (no
  phantom rows), all `capabilities.scrapy=true` + schedulable;
- `health.postgresql/redis == ok`, `health.nodes.healthy == 3`;
- egg upload → `scrapy`/`egg` artifact, listed;
- execution template created + bound to the artifact;
- template run → `task_id`, **no** `execution_id` (clean-cut), task detail has
  `executions[]` and **no** `attempts[]`, `task.source == template`;
- **`task status == complete`**, **exactly 3 executions**, 3 distinct agent ids
  == the heartbeat agents;
- each execution `finished` with both demo markers in its per-execution log.

It then **failed at Case 5** — `POST /api/v1/artifacts/{id}/run` (direct artifact
run) — with an empty response and no `task_id`, so the script `exit 1`s and
prints `SMOKE FAILED`.

**Root cause (pre-existing, not phase 2b):** the direct-artifact-run endpoint
`POST /api/v1/artifacts/{id}/run` was **intentionally removed in phase 1.8.1**
(documented in `apps/server/dopilot_server/api/v1/artifacts.py:9` — "the
`POST /artifacts/{id}/run` direct-run entry point was removed"; the
BuildArtifacts UI likewise has no run control, asserted by the browser smoke).
`scripts/smoke-phase1.sh` Case 5 (lines ~521–535, plus the header bullet at
line 18) still curls that removed route, so the oracle has been failing at Case 5
since 1.8.1 regardless of phase 2b. None of this session's changes touch the
direct-run path, the executors, the artifacts API, or `smoke-phase1.sh`.

**Recommended fix (out of scope here; flagged for governance):** drop Case 5 from
`scripts/smoke-phase1.sh` (and its header bullet), since direct artifact run was
replaced by the template run path two phases ago. Whether to instead restore a
direct-run endpoint is a product decision for Codex/the user, so this report does
not patch the phase-1 oracle. The teardown still ran on the failure (the EXIT
trap fired) — no containers/volumes were left behind.

This does **not** affect the mandatory browser smoke, which passed; the browser
smoke independently exercises the same Scrapy dispatch path (template run → task
detail → 3 executions → demo markers) plus the wheel path.

### Pre-Docker fast checks (host)

| Command | Result |
| --- | --- |
| `.venv/bin/pytest packages/protocol/tests apps/server/tests apps/agent/tests` | **427 passed** |
| `corepack pnpm --filter web test` | **45 passed (10 files)** |
| `corepack pnpm --filter web build` | **OK** (vue-tsc + vite; only the pre-existing chunk-size warning) |
| `.venv/bin/ruff check apps packages` | **All checks passed** |
| `cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config` | **OK** |
| `cd deploy/docker && docker compose config` | **OK** |

## Containers torn down?

Yes. Both smokes tear down via the script's EXIT trap (`docker compose down -v
--remove-orphans`); `KEEP_UP` was not set. Post-run inspection confirmed no
leftover dopilot containers or named volumes. No long-running Claude/Docker/
browser processes were left behind.

## Screenshots / video / trace artifacts

None — the browser smoke passed, and `playwright.config.ts` only retains
trace/screenshot/video on failure (`retain-on-failure` / `only-on-failure`). No
artifacts were produced under `apps/web/test-results/`.

## Residual risk / blocked commands

- **`python` on PATH (agent).** The wheel command form `python -m main` requires
  a `python` executable in the agent container. The unified image
  (`python:3.12-slim` base) provides it, so this holds for the supported Docker
  deployment. A bespoke agent environment that ships only `python3` would need to
  use `python3 -m …` (phase-2b documents this; `--target` installs no console
  scripts).
- **Demo URL is internal.** The wheel smoke points `DOPILOT_DEMO_URL` at the
  in-cluster `http://server:5000/api/v1/health` to avoid external-network
  flakiness. The default `https://httpbin.org/headers` still works but is an
  external dependency and is intentionally not exercised in the smoke.
- **Log RPO is not zero** (platform constraint, unchanged): a `partial` log file
  is possible under server long-stop / Redis log trimming. Not observed here; the
  wheel run produced complete logs with both markers.
- No commands were blocked.
