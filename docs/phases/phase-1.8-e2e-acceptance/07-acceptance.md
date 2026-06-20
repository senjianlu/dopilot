# 07 · Phase 1.8 E2E Acceptance

## Final Decision

Accepted.

The current Phase 1.8 version has now passed a full Docker acceptance using
three real agents.

## What Was Verified

- Full Docker architecture starts cleanly:
  - PostgreSQL;
  - Redis;
  - migrate;
  - server;
  - three agent containers.
- All three agents become heartbeat-healthy, Scrapy-capable, and schedulable.
- Scrapy egg upload creates a canonical build artifact.
- Execution template run fans out to exactly three child executions.
- Each child execution runs on a distinct agent and produces the expected logs.
- Direct build artifact run works.
- Schedule trigger-now works.
- Offline, stopped/unhealthy, and soft-deleted nodes are excluded from dispatch.
- The public API uses Phase 1.8 task/execution vocabulary.

## Verified Commands

```text
cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config
PASS

.venv/bin/ruff check apps packages
PASS

.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider
PASS - 317 passed

corepack pnpm --filter web test
PASS - 23 passed

corepack pnpm --filter web build
PASS

scripts/smoke-phase1.sh
PASS - 58 passed, 0 failed
```

## Governance Notes

- Codex wrote the e2e test plan and acceptance brief.
- Claude implemented the compose/script changes.
- Claude failed to produce the required formal implementation/test reports
  before exiting.
- Codex independently reviewed the diff and reran all required verification
  commands before accepting the result.

## Remaining Risks

- Browser-driven UI e2e was not implemented.
- The three-agent smoke is heavier than a quick local smoke and is best treated
  as release acceptance or pre-tag validation.
