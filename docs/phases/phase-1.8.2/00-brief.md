# Phase 1.8.2 Brief

## Goal

Polish the post-command-first UI, make the demo Scrapy fixture suitable for
long-running checks, and add an explicit manual maintenance path for data that
can accumulate in long-running deployments.

This phase builds on phase 1.8.1 and keeps the command-first execution model.

## User Decisions

- Version: `phase-1.8.2`.
- Demo spider parameter name: `duration_seconds`.
- Demo spider default duration: 60 seconds when the argument is omitted.
- In-repo automated tests, smoke, and E2E should pass a short duration such as
  `-a duration_seconds=0`.
- Confirmations are required for all offline/delete/destructive UI actions.
- Cleanup is manual first, not automatic.
- Terminal cleanup uses an operator-selected cutoff and deletes corresponding
  server log files.
- Stuck active tasks/executions are not hard-deleted. Manual remediation marks
  them `lost`.

## Requirements

### 1. Build Artifacts Page

File likely touched: `apps/web/src/pages/BuildArtifactsPage.vue`.

- Remove the table `Spider` column.
- Display artifact size in MB instead of raw `size_bytes`.
  - Use a readable fixed/rounded display, for example `1.23 MB`.
  - Preserve raw bytes only in API data; no backend change required.
- Add an actions column with a Details action.
- Details dialog:
  - shows artifact identity enough to orient the user;
  - renders the artifact's internal `spiders` as read-only tags;
  - uses an input/textarea-like bounded area, but tags must not be editable.

### 2. Demo Scrapy Spider Duration

Files likely touched:

- `tests/fixtures/scrapy_demo/demo/spiders/phase1.py`
- `tests/fixtures/scrapy_demo/README.md`
- `tests/fixtures/scrapy_demo/eggs/demo_phase1.egg`
- test/smoke/e2e command callers.

Add spider argument:

```bash
scrapy crawl phase1 -a duration_seconds=10
```

Behavior:

- If `duration_seconds` is omitted, default to 60 seconds.
- If `duration_seconds=0`, preserve the current near-instant behavior.
- Invalid negative or non-numeric values should fall back safely or fail
  deterministically; prefer a clear `ValueError` early if that fits Scrapy.
- Preserve deterministic markers:
  - `phase1 demo spider started`
  - `phase1 demo spider done`
- Preserve item count: exactly 2 items.
- Use a reactor-safe delay. Do not block the Twisted reactor with `time.sleep`.
- Rebuild the committed egg with `tests/fixtures/scrapy_demo/build_egg.sh`.
- Update README sha256/provenance.
- Update in-repo test, smoke, and E2E commands to pass
  `-a duration_seconds=0` or another short value so CI does not wait 60 seconds.

### 3. Nodes Page

File likely touched: `apps/web/src/pages/NodesPage.vue`.

- Remove duplicate status columns.
- Remove the separate Scrapyd status column.
- Show one status column:
  - for normal health, use backend `node.status`, which is already aggregated
    from heartbeat freshness + Redis connected + command consumer running;
  - preserve offline/deleted precedence in the displayed badge.
- Add a capabilities column with three tags:
  - `scrapy`
  - `script`
  - `docker`
- Read capability values from `node.capabilities`.
  - `true` => green/success tag.
  - false or missing => gray/info tag.
  - For now, only `scrapy` is expected to be green in normal deployments.

No backend change is expected for this item.

### 4. Confirmation Dialogs

Add confirmation before all offline/delete/destructive UI actions, including at
least:

- node offline;
- node delete;
- template delete;
- schedule delete;
- task cancel.

Use existing Element Plus patterns. A small shared confirmation helper/composable
is acceptable if it keeps the pages simpler.

Confirmation copy must be localized in both English and Chinese locale files.

### 5. Manual Cleanup

Add a minimal manual maintenance capability. This is not automatic retention.

#### Terminal Data Cleanup

Add backend service and API for deleting old terminal task data.

Input:

- cutoff age in days or an absolute cutoff timestamp. Prefer days in the UI for
  operator ergonomics.
- dry-run flag if cheap to implement; preferred for safety but not required if
  implementation cost is high.

Behavior:

- Only cleanup tasks whose status is terminal:
  - `complete`
  - `failed`
  - `canceled`
  - `lost`
  - `no_target`
- Only cleanup records older than the selected cutoff. Use `finished_at` when
  present; otherwise use `created_at` as a conservative fallback for terminal
  rows that may not have `finished_at`.
- Delete corresponding:
  - `execution_log_files` rows;
  - server log files on disk referenced by those rows;
  - child `executions`;
  - parent `tasks`;
  - resolved/expired old `command_outbox` rows where safe.
- Do not delete queued/running/finalizing tasks in this action.
- Return a count summary to the UI.

#### Stuck Task Remediation

Add backend service/API and UI action to manually mark stuck active tasks lost.

Behavior:

- Operator selects a task or invokes action from task detail/list where
  applicable.
- Eligible statuses should be active/stuck operational residue such as queued,
  running, or finalizing.
- Do not hard-delete active tasks.
- Mark affected non-terminal executions as `lost` with a manual reason, for
  example `manual_cleanup`.
- Roll up the task to `lost` where appropriate.
- Keep audit detail in existing `error_detail`/`status_detail` fields.
- Confirmation dialog must clearly state that the task may still be running on
  an agent and will be marked lost.

Prefer reuse of existing state/reconcile helpers where correct. Avoid bypassing
state transition invariants casually.

#### UI

Add a small manual maintenance surface. Acceptable placements:

- a lightweight section on the Tasks page, or
- a separate maintenance route/page if simpler.

The UI must support:

- terminal cleanup by cutoff days;
- visible count summary after cleanup;
- confirmation before cleanup;
- manual mark-lost action for stuck tasks if exposed in task detail/list.

Keep the UI minimal and operational, not decorative.

## Non-Goals

- No automatic scheduled cleanup in phase 1.8.2.
- No artifact deletion/cleanup unless it is already required by existing code.
- No new execution type beyond current Scrapy command support.
- No Docker/script executor support yet.
- No RBAC or extra auth layer for cleanup; standard admin auth is enough.

## Acceptance Criteria

- Build artifacts table no longer has a Spider column; artifact size displays as
  MB; Details shows spiders as read-only tags.
- Demo spider accepts `duration_seconds`; default is 60; tests/smoke/E2E use a
  short explicit duration.
- Rebuilt demo egg is committed and README sha256/provenance is updated.
- Nodes page has one status column and one capabilities column with scrapy,
  script, docker tags.
- Node offline/delete, template delete, schedule delete, and task cancel all ask
  for confirmation.
- Manual terminal cleanup deletes only terminal data older than the selected
  cutoff and deletes corresponding server log files.
- Manual stuck remediation marks eligible active task/executions lost and does
  not hard-delete them.
- Relevant tests pass.

## Suggested Test Plan

Backend:

```bash
.venv/bin/pytest apps/server/tests
```

Add or update tests for:

- cleanup deletes only terminal tasks before cutoff;
- cleanup does not delete queued/running/finalizing tasks;
- cleanup unlinks server log files referenced by deleted log indexes;
- old command_outbox cleanup deletes only safe rows;
- manual mark-lost changes active executions/tasks to lost and records manual
  reason.

Agent / fixture:

```bash
cd tests/fixtures/scrapy_demo && /home/rabbir/dopilot/.venv/bin/scrapy crawl phase1 -a duration_seconds=0
```

Frontend:

```bash
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Add/update tests for:

- artifact MB formatting and details dialog tags;
- nodes single status + capabilities tags;
- confirmation confirm/cancel paths for destructive actions;
- cleanup UI if implemented.

General:

```bash
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
```

Run broader tests when the implementation touches shared state transitions:

```bash
.venv/bin/pytest
```

## Risks

- Demo spider delay must not block the reactor.
- Cleanup is irreversible; implementation must be conservative and covered by
  tests.
- Existing DB relationships may not have cascading deletes; cleanup service must
  delete in safe application order.
- Active task mark-lost can conflict with a late agent event. Existing event
  consumer semantics should be reviewed and preserved.
