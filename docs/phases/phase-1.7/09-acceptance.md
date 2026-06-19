# Phase 1.7 Acceptance

Date: 2026-06-19

## Decision

Phase 1.7 is accepted.

## Accepted Scope

- `Task` is the logical parent run.
- `Execution` is the atomic per-agent run.
- A task can have many executions, or zero executions when no healthy target node exists.
- Task templates define reusable Scrapy task inputs.
- Schedules reference templates and copy template data into each task snapshot.
- Template run, schedule trigger-now, and schedule timer execution use the same dispatch path.
- Schedule coalescing is keyed by schedule backlog.
- Only healthy nodes are selected for dispatch.
- Existing Redis/agent/public-web seams keep the old `execution_id` wire naming where required.

## Final Verification

Passed:

- `.venv/bin/pytest apps/server/tests packages/protocol/tests` -> 194 passed.
- `.venv/bin/ruff check apps packages` -> all checks passed.
- `corepack pnpm --filter web test` -> 7 files / 14 tests passed.
- `corepack pnpm --filter web build` -> passed.
- `docker compose -f deploy/docker/docker-compose.yml config` -> passed.
- Alembic offline SQL from `0001` through `0005` -> passed.
- `git diff --check` -> passed.
- `scripts/smoke-phase1.sh` -> `SMOKE PASSED`, 23 assertions passed, 0 failed.

## Notes

- `make compose-smoke` could not be invoked because `make` is not installed in this shell. The underlying smoke script was run directly and passed.
- The smoke now covers the Phase 1.7 template and schedule paths, not only legacy manual execution.
- Docker smoke teardown completed; no compose containers were left running.
