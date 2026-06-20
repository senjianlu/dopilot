# 04 · Phase 1.8 E2E Test Plan

## Behavior Under Test

- Full compose architecture bootstraps from clean volumes.
- Migration reaches Alembic head before server starts.
- Three agents independently heartbeat and consume Redis commands.
- Build artifacts, execution templates, schedules, tasks, executions, and logs
  use the Phase 1.8 public API contract.
- Node scheduling state affects dispatch target selection.
- Agent heartbeat loss affects health and dispatch target selection.

## Static And Unit Coverage

Claude must run:

```bash
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider
.venv/bin/ruff check apps packages
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Expected: pass. If pre-existing warnings appear, report them separately from
failures.

## Docker Acceptance Cases

### Case 1: Clean Stack Boot

Steps:

- Bring the stack down with volumes.
- Build base images if needed.
- Start db, Redis, migrate, server, and three agents.
- Wait for db, Redis, migrate, server, and all agents.

Expected:

- migrate exits 0;
- server healthcheck passes;
- all three agent containers are healthy;
- no extra phantom nodes are counted as schedulable healthy.

### Case 2: Agent Heartbeat Health

Steps:

- Log in through `/api/v1/auth/login`.
- Poll `/api/v1/nodes`.

Expected:

- exactly three persisted nodes;
- each node has a unique `agent_id`;
- each node has `status == "healthy"`;
- each node has `capabilities.scrapy == true`;
- each node has `scheduling_enabled == true`;
- each node has Scrapyd health detail showing managed/running state when exposed.

### Case 3: Build Artifact Upload

Steps:

- Ensure the demo Scrapy egg exists or build it inside one agent container.
- Upload it to `/api/v1/artifacts/scrapy/egg`.
- List `/api/v1/artifacts`.

Expected:

- upload returns `artifact.id`;
- `artifact.artifact_type == "scrapy"`;
- `artifact.package_format == "egg"`;
- listed artifacts include that id.

### Case 4: Template Run Fans Out To Three Agents

Steps:

- Create `/api/v1/templates` with `build_artifact_id`, spider, and
  `node_strategy == "all"`.
- Run `/api/v1/templates/{id}/run`.
- Fetch `/api/v1/tasks/{task_id}`.
- Poll to terminal.
- Fetch logs for each execution with the execution id query.

Expected:

- run response contains `task_id`;
- task detail contains `executions[]`, not `attempts[]`;
- task source is `template`;
- execution count is exactly 3;
- execution agent ids are exactly the three heartbeat agent ids;
- final task status is `complete`;
- every child execution log contains both demo markers.

### Case 5: Direct Build Artifact Run

Steps:

- POST `/api/v1/artifacts/{artifact_id}/run` with spider and `node_strategy`.
- Fetch `/api/v1/tasks/{task_id}`.

Expected:

- task source is `direct_artifact`;
- task contains the build artifact snapshot;
- run reaches `complete` with at least one child execution.

### Case 6: Schedule Trigger-Now

Steps:

- Create `/api/v1/schedules` with `execution_template_id`.
- Trigger `/api/v1/schedules/{id}/trigger-now`.
- Fetch `/api/v1/tasks/{task_id}`.

Expected:

- response contains `task_id`;
- task source is `schedule_trigger_now`;
- task schedule id links back to the schedule;
- task has child executions.

### Case 7: Offline Node Exclusion

Steps:

- Pick one node and call `/api/v1/nodes/{node_id}/offline`.
- Confirm `/api/v1/nodes` still shows heartbeat health for that node, but
  `scheduling_enabled == false`.
- Run an all-nodes template task.

Expected:

- offline node is not selected;
- execution count is two while the other two nodes are healthy and schedulable.

### Case 8: Heartbeat Timeout Exclusion

Steps:

- Stop one remaining online agent container.
- Wait past `[agents].heartbeat_timeout_seconds` plus margin.
- Poll `/api/v1/nodes`.
- Run an all-nodes template task.

Expected:

- stopped node becomes `unhealthy` or otherwise not healthy;
- stopped node is not selected;
- execution count reflects only healthy, schedulable, non-deleted nodes.

### Case 9: Soft-Delete Exclusion

Steps:

- Soft-delete one node through `DELETE /api/v1/nodes/{node_id}`.
- If its container is still running, wait for another heartbeat.
- Run another all-nodes template task.

Expected:

- deleted node has `deleted_at`;
- later heartbeat does not clear `deleted_at`;
- deleted node is not selected.

## Regression Risks

- Old route names could make the smoke pass only against stale code. The script
  must fail if any `/api/v1/executions` path or `attempts[]` assertion remains.
- Checking only the parent task log can miss one or two failed child executions.
  The script must check logs per execution.
- Offline and deleted nodes can still heartbeat, so the script must assert
  scheduling fields separately from health status.
- Heartbeat timeout is timing-sensitive. The script must read or mirror the
  configured timeout and use a clear margin rather than fixed short sleeps.

## Results

Claude fills this section in `05-claude-test-report.md` with exact command
outcomes.
