# 05 · Phase 1.8 E2E Test Report

## Report Provenance

Claude's progress note recorded static test success, but Claude exited without a
formal test report. Codex independently reran every required command and records
the authoritative results below.

## Commands And Results

```text
cd deploy/docker && docker compose -f docker-compose.yml -f docker-compose.e2e.yml config
PASS
```

Result: merged compose config is valid and contains services `db`, `redis`,
`migrate`, `agent`, `scrapy-agent-2`, `scrapy-agent-3`, and `server`.

```text
.venv/bin/ruff check apps packages
PASS
All checks passed.
```

```text
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider
PASS
317 passed in 9.45s
```

```text
corepack pnpm --filter web test
PASS
8 test files passed, 23 tests passed
```

Observed warnings: Vue test environment still emits pre-existing unresolved
`v-loading` directive warnings.

```text
corepack pnpm --filter web build
PASS
```

Observed warnings: Rollup removed two third-party pure annotations and Vite
reported the existing large chunk warning.

```text
scripts/smoke-phase1.sh
PASS
58 passed, 0 failed
```

## Smoke Evidence

The full compose smoke verified:

- clean-volume Docker bring-up;
- Alembic migration completion;
- server health;
- three agent containers healthy;
- `scrapy-agent-1` reports live Scrapyd;
- exactly three persisted heartbeat nodes;
- all three nodes are healthy, Scrapy-capable, and schedulable;
- server health reports PostgreSQL OK, Redis OK, and `nodes.healthy == 3`;
- Scrapy egg upload returns a build artifact id with `artifact_type == scrapy`
  and `package_format == egg`;
- build artifact list includes the uploaded artifact;
- execution template creation binds `build_artifact_id`;
- template run returns `task_id` and not `execution_id`;
- task detail exposes `executions[]` and not `attempts[]`;
- all-nodes template run reaches `complete`;
- all-nodes template run creates exactly three executions on distinct agents;
- every child execution log contains:
  - `phase1 demo spider started`;
  - `phase1 demo spider done`;
- direct build-artifact run reaches `complete`;
- schedule trigger-now creates a new task with source
  `schedule_trigger_now`;
- offline node remains heartbeat-healthy but is excluded from dispatch;
- stopped node becomes `unhealthy` after heartbeat timeout and is excluded;
- soft-deleted node remains deleted after a later heartbeat and is excluded.

The smoke ended with:

```text
Smoke summary
  passed: 58   failed: 0
SMOKE PASSED
```

The script then ran its normal cleanup:

```text
docker compose down -v
```

## Remaining Test Gaps

- Browser-driven UI e2e was not run. This task covered API/compose/runtime
  acceptance plus existing Vue unit/build coverage.
