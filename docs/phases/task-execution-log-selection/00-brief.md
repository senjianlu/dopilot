# Task Execution Log Selection Brief

## Problem

The task detail page shows a task's child executions but renders only one log
viewer:

```tsx
<LogViewer taskId={taskId} />
```

Because no `executionId` is passed, the backend resolves the task's primary
execution and the user has no way to inspect the other per-node execution logs.
This is now visible with the default three-agent Compose stack.

There is also a backend correctness issue: the SSE subscription manager is
documented as execution-keyed, but the current log stream endpoint subscribes by
`task_id` and `apply_log_event()` publishes by `event.task_id`. If multiple
execution-specific log viewers are open at once, live log frames can be fanned
out to every viewer for the task instead of only the matching execution.

## Desired Behavior

- Task detail must let the user choose among all child executions and see the
  selected execution's log.
- A single-execution task should still feel simple.
- The backend log snapshot and SSE stream should remain compatible with existing
  calls that omit `execution_id` by defaulting to the primary execution.
- Live SSE fan-out should be keyed by atomic `Execution.id`, not by parent
  `Task.id`, so multiple log viewers do not cross-contaminate each other.
- Do not change the task/execution domain model or Redis protocol.

## Proposed Implementation

### Web

- In `apps/web/app/(app)/tasks/detail/page.tsx`:
  - keep selected execution state;
  - default to the first execution once task data loads;
  - render a `Tabs` control when there are multiple executions;
  - pass `executionId={selectedExecutionId}` to `LogViewer`;
  - keep the existing executions table.
- Add i18n strings for the log execution selector where needed.
- Extend `task-detail.test.tsx` so a multi-execution task can select another
  execution and the log viewer receives that `execution_id`.

### Server

- In `apps/server/dopilot_server/api/v1/tasks.py`, after resolving the execution:
  - subscribe/unsubscribe using `execution.id`;
  - keep stream token bound to `task_id`;
  - keep omitted `execution_id` behavior unchanged.
- In `apps/server/dopilot_server/services/logs.py`, publish SSE events with
  `event.execution_id`.
- Update focused SSE/log tests to prove two execution-specific subscribers only
  receive their own events.
- Update stale comments/tests that still say the stream is keyed by task id.

## Validation

```bash
.venv/bin/python -m pytest apps/server/tests/test_sse.py apps/server/tests/test_log_consumer.py apps/server/tests/test_executions.py -q
corepack pnpm --filter web test -- task-detail
corepack pnpm --filter web test -- log-viewer
```

Run broader web/server tests if the scoped tests reveal shared-contract fallout.
