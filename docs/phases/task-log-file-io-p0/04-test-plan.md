# Test Plan: Log File I/O P0

## Unit / Service Coverage

- `apps/server/tests/test_log_files.py`
  - Verify collapsed `append_increment` offset and byte semantics.
  - Verify async wrappers match synchronous helper behavior.
  - Verify async remove keeps best-effort remove semantics.
- `apps/server/tests/test_log_consumer.py`
  - Verify `apply_log_event` reaches disk through the named async file boundary.
  - Existing tests continue covering normal append, duplicates, gap marker,
    finalization, and cleanup behavior.

## Integration / API Coverage

- Full `apps/server/tests` suite covers task log snapshot, SSE stream behavior,
  Redis log consumer behavior, maintenance cleanup, and existing task/execution
  contracts.

## Static Checks

- `git diff --check`
- `ruff check apps packages`
- Grep for remaining direct synchronous log body file helper calls from async
  server paths.

## Required Commands

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_log_files.py apps/server/tests/test_log_consumer.py -q
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests -q
.venv/bin/ruff check apps packages
```

## Manual / Runtime Follow-up

After deployment or local compose reproduction, run an A/B check with an active
log-producing task:

- compare API latency for `/api/v1/health`, task list, and node list while logs
  are actively being consumed;
- optionally enable asyncio slow-callback logging to verify log file I/O no
  longer appears as loop-blocking work.
