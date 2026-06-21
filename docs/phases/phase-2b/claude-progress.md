# Phase 2b Packet 1 — Claude Progress

## Status

**Complete.** Packet 2b-1 (server/protocol/web dispatch-ready + demo wheel)
implemented; report in `01a-claude-implementation-report.md`. Agent runner is
packet 2b-2 (not started). The continuation run resumed from the partial tree
left by the API-529 interruption and finished the remaining checklist.

## Size class

Medium-large (as estimated). Touched protocol, server
(states/artifacts/api/templates/resolve/schedules/executors/executions), web
client+UI, the demo wheel fixture, and tests.

## Plan / checkpoints

1. [x] Read all in-scope source files; confirm current shapes.
2. [x] Protocol: `PythonWheelRunPayload`; tests.
3. [x] Server state: capability mapping `python_wheel -> script`; runnable type.
4. [x] Wheel artifact store + upload/download API + dedupe; tests.
5. [x] Demo wheel fixture under `tests/fixtures/python_wheel_demo/`.
6. [x] Type-aware template validation (scrapy vs wheel); tests.
7. [x] `resolve_run` python_wheel branch (shell_command/artifact/env/working_dir).
8. [x] `PythonWheelExecutor` + registry; tests.
9. [x] Web/client types + UI for wheel upload/template; web tests.
10. [x] Run required commands; write implementation report.

## Resolved review items

- **Wheel schedule command override** — RESOLVED (not a limitation).
  `sanitize_overrides` is now type-aware and threaded through schedule
  create/update + `build_run_request`; resolve's wheel branch takes a free-form
  override verbatim. Tests prove a shell-metacharacter override is accepted and
  dispatched. The earlier "KNOWN LIMITATION" note is withdrawn.

## Key findings (confirmed in code)

- `AgentCommand.task_type` is derived by the dispatcher from
  `payload["task_type"]` — the wheel payload carries `task_type="python_wheel"`.
- Node capability filtering is a generic string match; `python_wheel -> script`
  requires a `script`-capable node. A scrapy-only node is excluded.
- Adding `python_wheel` to `RUNNABLE_ARTIFACT_TYPES` flips `runnable`/
  `get_runnable_artifact_or_404` automatically.
- No migration: wheel facts fit `artifact_metadata` JSON; `command` reused as
  the wheel shell command; template `artifact_type` derived from the artifact.

## Final command results

- `pytest packages/protocol/tests apps/server/tests` → 319 passed.
- `corepack pnpm --filter web test` → 45 passed.
- `corepack pnpm --filter web build` → OK.
- `ruff check apps packages` → All checks passed.

---

# Phase 2b Packet 2 — Claude Progress

Agent-side Python wheel runner + end-to-end execution. Continues from accepted
packet 2b-1.

## Checkpoints

1. [x] Read brief, packet-1 report+review, agent code (commands/events/logs/
   store/cache/deps/main + tests + fixtures).
2. [x] Extend `AttemptState` additively (`runner_type`, `pid`, `pgid`,
   `workspace_path`, `install_path`, `shell_command`); scrapy state still loads.
3. [x] Add `PythonWheelCache` (fetch via `fetch_path` + sha256 verify +
   `pip install --no-deps --target <cache>/python_wheel/<sha>/site <wheel>` once
   per sha, lock + ready marker, no deps).
4. [x] Add `PythonWheelRunner` (`/bin/sh -c`, `start_new_session=True`,
   per-execution workspace + working_dir guard, PYTHONPATH inject,
   PYTHONUNBUFFERED=1, merged job.log, SIGTERM->10s->SIGKILL).
5. [x] `task_type=="python_wheel"` run branch + type-aware stop/reclaim +
   wheel recovery in `CommandConsumer`; tracked background wait tasks.
6. [x] Type-aware `EventPublisher.republish_current` +
   `reconcile_started_attempts` (no Scrapy status for wheel states).
7. [x] Wire runtime (`deps.py` / `main.py`).
8. [x] Tests; ran required commands; implementation report (`03a-...md`).

## Final command results (packet 2)

- `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q`
  → 425 passed.
- `corepack pnpm --filter web test` → 45 passed (unchanged; packet 2 is
  agent-only).
- `corepack pnpm --filter web build` → OK.
- `.venv/bin/ruff check apps packages` → All checks passed.

## Key design decisions

- Stop/reclaim branch on local `AttemptState.runner_type`, NOT `cmd.task_type`
  (server stop outbox sends empty payload -> dispatcher defaults `scrapy`).
- Run handler reserves state, installs, spawns, emits accepted/running, then a
  tracked background wait task marks terminal on natural exit.
- SIGTERM->grace->SIGKILL grace is a module constant (10s) overridable in the
  runner ctor for fast tests.
- Wheel started states found on disk at boot that were NOT started in this
  process -> best-effort pgid kill + mark lost `runner_recovered_unknown`,
  never restarted.

## Packet 2 — Codex review fix (blocking)

Codex review `04a-codex-agent-review.md` raised one blocking finding:
`PythonWheelRunner.aclose()` leaked running child process groups on agent
shutdown (a `start_new_session=True` `sleep 30` survived `CommandConsumer.stop()`).

- [x] Rewrote `aclose()` to terminate live children via the existing
  `terminate()` (SIGTERM->grace->SIGKILL + reap) BEFORE cancelling reapers, then
  clear `_procs`/`_pgids`/`_exits`/`_canceled` bookkeeping. Production 10s grace
  unchanged; consumer/Scrapy/cancel/reclaim semantics unchanged; no extra
  terminal events emitted on shutdown.
- [x] Added regression tests `test_aclose_terminates_running_process_group` and
  `test_consumer_stop_terminates_running_wheel`; verified both fail on the old
  `aclose()` (2 failed, 106 passed) and pass after the fix.
- [x] Fix report: `04c-claude-agent-fix-report.md`.

### Fix command results

- `.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q`
  → 427 passed (+2 new tests).
- `corepack pnpm --filter web test` → 45 passed (unchanged; agent-only fix).
- `corepack pnpm --filter web build` → OK.
- `.venv/bin/ruff check apps packages` → All checks passed.

---

# Phase 2b — Page-Level Docker + Browser E2E

Clean-volume Docker page-level validation through the bundled production SPA at
`http://localhost:5000` (Playwright/Chromium), extending the Scrapy browser smoke
to also cover the Python-wheel script path. Full report:
`05b-claude-page-e2e-report.md`.

## Status

**Complete.** Mandatory Docker browser smoke passes (9/9, incl. 2 new wheel
specs). Optional backend Scrapy oracle: Scrapy dispatch path passes; the script
exits non-zero on a pre-existing stale Case 5 assertion (removed direct-run
endpoint), unrelated to phase 2b. All containers torn down (no `KEEP_UP`).

## Checkpoints

1. [x] Read governance docs, brief, packet reports/reviews, smoke scripts,
   Playwright config/helpers/spec, Dockerfile/compose, agent config, fixtures.
2. [x] **Gap 1 — seed demo wheel:** `deploy/docker/Dockerfile` copies the
   committed demo wheel and writes it via the server's own `WheelArtifactStore`
   into `/server-data/artifacts/python_wheel` (byte-identical to an upload).
3. [x] **Gap 2 — script-capable agents:** `configs/agent.example.toml`
   `[capabilities] script = true` (scrapy stays true). All 3 e2e agents now
   advertise `script`.
4. [x] **Smoke gate:** `scripts/smoke-phase1-ui.sh` `wait_nodes_ready` also
   requires `capabilities.script`.
5. [x] **Gap 3 — browser coverage:** helpers (`waitForLogContaining`,
   `waitForTaskStatus`, wheel constants) + 2 new serial specs (wheel artifact
   listed runnable; wheel template create + run → `complete` with both demo
   markers), placed before the destructive node-actions spec. Nodes spec now
   asserts the `script` (and `scrapy`) cap tag is green.
6. [x] Fast checks: pytest 427, web test 45, web build OK, ruff clean, compose
   config OK (base and base+e2e).
7. [x] `scripts/smoke-phase1-ui.sh` → **9 passed (22.2s); UI SMOKE PASSED**;
   teardown verified (no containers/volumes).
8. [x] `scripts/smoke-phase1.sh` (optional oracle) → Scrapy dispatch path passes
   through Case 4; fails at Case 5 (pre-existing stale assertion). Recorded.
9. [x] Report `05b-claude-page-e2e-report.md` + this progress section.

## Files changed (this packet)

- `deploy/docker/Dockerfile` — seed built-in demo wheel.
- `configs/agent.example.toml` — `script = true`.
- `scripts/smoke-phase1-ui.sh` — node gate requires `script`.
- `apps/web/e2e/helpers/ui.ts` — wheel constants + generic log/status waiters.
- `apps/web/e2e/specs/phase1-ui.spec.ts` — script-cap assertions + 2 wheel specs.
- `docs/phases/phase-2b/05b-claude-page-e2e-report.md` — report (new).

No server/agent/protocol runtime code changed — this is the Docker-seed +
capability-enable + browser-coverage layer over the accepted 2b-1/2b-2 packets.

## Flagged for governance (not patched here)

- `scripts/smoke-phase1.sh` Case 5 curls `POST /api/v1/artifacts/{id}/run`, an
  endpoint removed in phase 1.8.1; the phase-1 oracle has failed there since
  1.8.1, independent of phase 2b. Recommended one-line fix: drop Case 5 (and its
  header bullet). Left to Codex/user since it is phase-1 acceptance tooling and a
  possible product decision.
</content>
