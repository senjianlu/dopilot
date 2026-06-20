# Phase 2a Claude Progress

## 2026-06-20 — Feasibility validation (read-only, no app code changed)

- Validated the id-naming clean-cut; wrote `00a-feasibility-review.md`.
- **Verdict: feasible, no hard blockers** under the accepted cutover
  (quiesce + flush Redis + lockstep protocol/server/agent deploy).
- Legacy schemas classified by live-usage `rg` scan:
  - **Delete** (tests/`__init__` only): `AgentStopRequest`, `CleanupResponse`,
    `TailRequest`, `TailResponse`.
  - **Rename** (live + seam fields): `AgentRunRequest`, `AgentRunResponse`,
    `AgentStopResponse`, `AgentStatusResponse`.
  - **Leave** (live, no seam fields): `AttemptStatus`, `EggDeployResponse`,
    `LogStream`.
- Corrected plan-review numbering: new migration is **`0009`** (down_revision
  `0008`), not `0005`. Do not edit `0002`/`0003`/`0004`.
- Collision trap flagged: `execution_id` already means `Execution.id` in the
  public/domain layer → per-file rename, no tree-wide `sed`, zero public-API/web
  change in 2a.
- Open call for Codex/user: rename-and-keep vs delete-both for
  `AgentRunResponse` + the uncalled `ScrapydRunner.run()` (recommend rename;
  defer dead-method pruning to 2b).

## 2026-06-20 — Implementation start

- Size class: **90m+**. Swap touches protocol schemas, server models + Alembic
  `0009`, server services/dispatch/reconcile/executors/log paths, agent
  state/redis/runner/on-disk paths, and protocol/server/agent test suites. It is
  a name-collision *swap* — edited per local meaning, never tree-wide `sed`.
- Update cadence: after each area (protocol → server models+migration → server
  services → agent → tests) and before/after long-running commands.
- Checkpoints:
  1. [ ] Re-run `rg` scans for dead legacy schemas + `ScrapydRunner.run()`.
  2. [ ] Protocol: rename stream/agent schemas, delete dead schemas, fix `__init__`.
  3. [ ] Server models + migration `0009`.
  4. [ ] Server services / redis / executors / log paths.
  5. [ ] Agent state / redis / runner / on-disk paths.
  6. [ ] Tests in lockstep.
  7. [ ] Required commands run + report.
- Likely long-running: pytest suites, `alembic upgrade/downgrade`,
  `docker compose config`.

### Checkpoint 1 — protocol done

- Renamed seam fields in `streams.py` (AgentCommand/AgentEvent/AgentLogEvent) and
  `agent.py` (AgentRunRequest/Response, AgentStopResponse, AgentStatusResponse).
- Deleted `AgentStopRequest`, `CleanupResponse` (agent.py), `TailRequest`,
  `TailResponse` (logs.py) + their `__init__` exports + their test cases.
- Kept-and-renamed `AgentRunResponse` + `ScrapydRunner.run()` (decision: option a
  from feasibility — keep-rename; `run()` has no non-test caller but is exercised
  by `test_runner.py`; defer dead-method pruning to 2b).
- Protocol tests updated (test_stream_schemas, test_agent_schemas, test_schemas).
- NOTE: `pytest` requires interactive approval in this env — batching all test
  runs for the verification step.

### Checkpoint 2 — server models + migration 0009 done

- Renamed columns: `execution_log_files` (execution_id->task_id,
  attempt_id->execution_id, PK now (task_id, execution_id, stream)),
  `command_outbox` (same swap), `event_audit` (attempt_id->execution_id).
- Rewrote obsolete seam-mapping docstrings in the 3 models.
- Added `migrations/versions/0009_id_naming_clean_cut.py` (down_revision 0008),
  data-preserving RENAME COLUMN + index renames (ordered to avoid swap collision).

### Checkpoint 3 — server services done

- Renamed seam fields in services (executions, logs, events, outbox, cancel,
  maintenance, states), redis (dispatcher, reconcile), executors/scrapyd,
  logs/files; removed obsolete seam-mapping comments/docstrings.
- Collision-safe: left public/domain `execution_id` (get_execution,
  resolve_execution, get_logs/stream_logs query params, LogSnapshot, sse.py,
  stream_token.py) untouched.
- Renamed internal `ReconcileReport.lost_attempt_ids` -> `lost_execution_ids`
  (would otherwise trip the residual `attempt_id` check; internal only).
- `apps/server/dopilot_server` is CLEAN of `attempt_id`.
- NOTE: cannot run `py_compile`/pytest — every python invocation is gated behind
  interactive approval in this env. Batching for final verification.

### Checkpoint 4 — agent done

- `state/store.py`: AttemptState fields execution_id->task_id, attempt_id->
  execution_id; methods keyed by atomic id renamed to `execution_id`;
  `list_attempt_ids`->`list_execution_ids`; state file `{execution_id}.json`.
- `runners/scrapyd.py`: run/stop/status renamed (stop/status signature
  `(execution_id, task_id)`); AgentRunResponse/Stop/Status use task_id/execution_id.
- `redis/events.py`: emit_* / republish_current / _event use `(task_id,
  execution_id)`.
- `redis/commands.py`: cmd.execution_id->cmd.task_id, cmd.attempt_id->
  cmd.execution_id throughout; runner.stop/status call order updated.
- `redis/logs.py`: cursor file `{execution_id}.logpos`; AgentLogEvent uses
  task_id/execution_id.
- `redis/heartbeat.py`, `artifacts/cache.py` (`ensure(execution_id=...)`).
- Kept `AttemptState` class name (brief did not require the class rename; out of
  scope). `apps/agent/dopilot_agent` is CLEAN of `attempt_id`.

### Checkpoint 5 — protocol + agent tests done

- Protocol tests + agent tests all renamed and CLEAN of `attempt_id`.
- Renamed test names containing the `attempt_id` substring
  (`test_duplicate_attempt_id...`, `test_stop_unknown_attempt_idempotent`,
  `test_list_attempt_ids`).
- In progress: server tests (mixed seam vs public `execution_id`).

### Checkpoint 6 — all tests updated + green

- Server tests renamed (outbox, dispatcher, log_consumer, event_consumer,
  reconcile_redis, redis_fake, executions, maintenance, schedules,
  scheduler_runner). `test_sse.py` untouched (public; proves no public drift).
- `rg attempt_id apps packages` → only migration files (0009 performs the rename;
  0002/0003/0004 are historical DDL, not editable). Justified.
- Results (via approved `-p no:cacheprovider` form):
  - `pytest packages/protocol/tests` → 65 passed
  - `pytest apps/agent/tests` → 83 passed
  - `pytest apps/server/tests` → 231 passed
  - `ruff check apps packages` → All checks passed
### Checkpoint 7 — verification complete

- Brought up compose `db` (postgres:16) on localhost:5432; the named volume was
  already at revision 0008, so the round-trip exercised 0009 against real tables.
- `alembic upgrade head && downgrade -1 && upgrade head` → 0008<->0009 clean both
  ways. Verified columns: execution_log_files(task_id, execution_id),
  command_outbox(task_id, execution_id), event_audit(execution_id); PK
  execution_log_files = (task_id, execution_id, stream); indexes
  ix_command_outbox_task_id / ix_command_outbox_execution_id /
  ix_event_audit_execution_id. No `attempt_id` columns remain.
- `docker compose config` → valid.
- Stopped the db container (volume left intact; non-destructive).
- DONE. Wrote 01-claude-implementation-report.md.

## 2026-06-21 — Browser UI e2e verification (post-acceptance)

Task: run the real browser UI e2e (Playwright/Chromium vs the Docker production
SPA at http://localhost:5000) to confirm phase 2a did not regress the
run → task-detail → executions → logs browser workflow. Unit/integration were
accepted earlier; browser e2e was not run in the original acceptance.

Size class: `15-45m` (dominated by Docker image build + 3-agent bring-up).

### Decision — no new test added

Existing `apps/web/e2e/specs/phase1-ui.spec.ts` already exercises the full
phase-2a-relevant browser path end to end: login/nav → artifact upload →
execution template create+run → task detail with 3-execution fan-out + live log
markers → tasks list → schedule create+trigger-now → node offline/online/delete.
Phase 2a was an internal id rename with zero public HTTP/web drift, so this spec
is the correct regression net. Running existing browser smoke; not adding tests.

### Log

- T0: Read all required context. Env verified: docker daemon 29.5.3, compose
  v5.1.4, chromium-1228 cached, e2e compose + playwright config present.
- Next: run `scripts/smoke-phase1-ui.sh` (clean-volume bring-up + Playwright,
  auto-teardown on exit).

- Run 1: FAIL. Test 2 `nodes ... scrapy-healthy` failed at spec:76 —
  `node-scrapyd-${agentId}` not found (5 specs did not run; serial abort). DOM
  showed all 3 nodes healthy. Diagnosis: the scrapyd column + `node-scrapyd-*`
  testid were REMOVED in commit f93f358 (phase 1.8.2); spec was never updated.
  Stale test, not a phase-2a regression (2a touched zero web files).
- Fix 1 (test-only): re-pointed the assertion to `node-cap-${agentId}-scrapy`
  (the post-1.8.2 scrapy-capability cell).
- Run 2: FAIL. Test 7 `nodes offline/online/delete` failed at spec:197 — offline
  badge stayed `el-tag--success`. Diagnosis: `onOffline`/`onDelete` now go through
  `@/utils/confirm` (ElMessageBox), also added in f93f358; the spec never accepted
  the modal. Tests 1-6 (incl. the phase-2a-critical template-run → task-detail →
  3-execution fan-out → live log markers, tasks, schedules) PASSED.
- Fix 2 (test-only): added `confirmMessageBox(page)` helper; accept the modal
  after offline and delete clicks (online has no confirm).
- Run 3: PASS. 7/7 specs green in 16.1s. `UI SMOKE PASSED`. Teardown ran
  (`down -v`); `docker compose ps -a` shows no containers/volumes left.
- Wrote `04-ui-e2e-verification-report.md`. Changed files (test-only):
  `apps/web/e2e/specs/phase1-ui.spec.ts`, `apps/web/e2e/helpers/ui.ts`. No
  product (`apps/web/src/**`) or `reference/` changes. DONE.
</content>
