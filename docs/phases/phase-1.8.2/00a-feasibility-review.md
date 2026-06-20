# Phase 1.8.2 Feasibility Review

## Claude Verdict

Feasible with changes.

## Scope Confirmed By User

1. Build artifact page polish:
   - remove the table Spider column;
   - display size in MB;
   - add a Details action with read-only tag display for contained spiders.
2. Demo Scrapy spider:
   - add `duration_seconds`;
   - default to 60 seconds when omitted;
   - tests/smoke/e2e should pass a short value.
3. Nodes page:
   - remove duplicate status columns and the separate Scrapyd status column;
   - show one aggregate status based on heartbeat freshness + Redis connection +
     command consumer;
   - add capability tags for `scrapy`, `script`, and `docker`.
4. Confirmation dialogs:
   - add confirmation for all offline/delete/destructive actions.
5. Cleanup:
   - manual cleanup first, not automatic.

## Claude Findings

- Items 1, 3, and 4 are mostly frontend-only. Current backend responses already
  expose build artifact `spiders` / `size_bytes`, node aggregate `status`, and
  node `capabilities`.
- Item 2 is feasible but must avoid blocking the Twisted reactor. The fixture
  supports both Scrapy >= 2.13 `async start()` and older `start_requests()`;
  implementation must keep the existing marker lines and item count. In-repo
  tests and smoke flows must use `-a duration_seconds=0` or another short value
  to avoid the new default 60-second runtime.
- Item 5 is the only substantial backend/product-risk slice. There is no current
  cleanup API/UI. PostgreSQL rows, server log files, agent-side state/logs, Redis
  streams, and uploaded artifacts can accumulate. Existing retention settings and
  `retained_until` are not yet enforced.

## Codex Decision

- Items 1, 3, and 4 can be briefed directly.
- Item 2 should be implemented with a reactor-safe delay and tests updated to
  use `duration_seconds=0`; no product escalation needed because the user already
  accepted the default parameter behavior.
- Item 5 needs explicit product decisions before the brief is finalized because
  it can delete data or mutate active-looking tasks.

## Product Decisions Still Needed

1. Manual terminal-data cleanup shape:
   - what minimum age/cutoff should be allowed for terminal tasks/executions/logs;
   - whether cleanup should delete corresponding server log files in the same
     action.
2. Stuck task/execution remediation:
   - whether stale queued/running rows should be force-marked terminal instead
     of hard-deleted;
   - whether the terminal status should be `canceled`, `failed`, or `lost`;
   - whether a heartbeat-stale gate is required before the UI allows force
     cleanup.
