# 00 · Phase 1.8 E2E Acceptance Brief

## Goal

Implement and run a full Docker acceptance test for the current Phase 1.8
version using three real agents.

This is an acceptance/testing task, not a product feature task. The work should
prove that the clean-cut Phase 1.8 model works in the deployed architecture:

- Docker compose starts the full stack;
- three agents heartbeat into the server;
- Scrapy artifact upload creates a build artifact;
- execution templates, direct artifact runs, schedule trigger-now, and task log
  APIs use the Phase 1.8 public vocabulary;
- node state changes affect dispatch as expected.

## Context

Read before editing:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/phases/phase-1.8/00-brief.md`
- `docs/phases/phase-1.8/04-test-plan.md`
- `docs/phases/phase-1.8-e2e-acceptance/04-test-plan.md`
- `deploy/docker/docker-compose.yml`
- `scripts/smoke-phase1.sh`
- `configs/agent.example.toml`
- `configs/server.docker.toml`

## In Scope

- Update or replace `scripts/smoke-phase1.sh` so `make compose-smoke` validates
  the current Phase 1.8 API and product names.
- Add a compose override or equivalent committed configuration for three agent
  services:
  - `scrapy-agent-1`;
  - `scrapy-agent-2`;
  - `scrapy-agent-3`.
- Keep one server, one PostgreSQL, one Redis, one migrate service, and one
  unified image.
- Verify all three agents are heartbeat-healthy, Scrapy-capable, schedulable,
  and backed by running Scrapyd.
- Run a Scrapy execution across all three agents and prove it creates exactly
  three atomic executions.
- Verify log content for each atomic execution through
  `/api/v1/tasks/{task_id}/logs?execution_id=...`.
- Verify node-state behavior in Docker:
  - offline node remains heartbeat-healthy but is excluded from dispatch;
  - stopped agent becomes unhealthy after heartbeat timeout and is excluded;
  - soft-deleted node remains excluded.
- Keep the script idempotent and clean-volume by default.
- Update docs if the smoke command shape changes.

## Out Of Scope

- Python wheel execution.
- Docker image execution.
- Multi-server HA or distributed scheduling.
- Browser/UI automation.
- Copying or importing anything from `reference/scrapydweb/`.
- Killing unrelated existing Claude/tmux processes.

## Required Implementation Order

1. Inspect the current Phase 1.8 API response shapes and compose constraints.
2. Add the three-agent compose shape with unique agent ids, workdirs, and
   container-internal Scrapyd ports.
3. Rewrite `scripts/smoke-phase1.sh` around `/api/v1/tasks`,
   `executions[]`, `task_id`, `build_artifact_id`, and
   `execution_template_id`.
4. Add robust JSON helper assertions for list filtering, exact counts, distinct
   agent ids, terminal status, and per-execution logs.
5. Run static verification first.
6. Run the full compose smoke and record exact results.
7. Update the implementation report with commands, outcomes, failures, and any
   residual risk.

## Acceptance Criteria

- `scripts/smoke-phase1.sh` starts a clean Docker stack with three real agent
  containers.
- `GET /api/v1/nodes` eventually shows exactly three persisted nodes with
  `status == "healthy"`, `capabilities.scrapy == true`, and
  `scheduling_enabled == true`.
- `GET /api/v1/health` reports PostgreSQL and Redis OK and
  `nodes.healthy == 3` for the initial stack.
- Uploading the demo Scrapy egg returns a `BuildArtifactView` with
  `artifact_type == "scrapy"`, `package_format == "egg"`, and an artifact id.
- Creating an execution template requires and uses `build_artifact_id`.
- Running the execution template returns `task_id`; task detail is fetched from
  `/api/v1/tasks/{task_id}` and contains `executions[]`, not `attempts[]`.
- The all-nodes template run creates exactly three executions with three
  distinct `agent_id` values and reaches `status == "complete"`.
- Each child execution exposes logs with the demo start and done markers through
  the Phase 1.8 log endpoint.
- A direct build-artifact run works and uses `source == "direct_artifact"`.
- A schedule using `execution_template_id` and trigger-now creates a new task
  with `source == "schedule_trigger_now"`.
- Taking one node offline excludes it from a subsequent all-nodes run while the
  node still reports heartbeat health.
- Stopping one agent and waiting past heartbeat timeout causes it to become
  unhealthy and excludes it from a subsequent all-nodes run.
- Soft-deleting a node excludes it from dispatch and later heartbeat does not
  resurrect it.

## Required Commands

Claude must run and report exact outcomes:

```bash
cd deploy/docker && docker compose config
.venv/bin/ruff check apps packages
.venv/bin/pytest apps/server/tests apps/agent/tests packages/protocol/tests -q -p no:cacheprovider
corepack pnpm --filter web test
corepack pnpm --filter web build
scripts/smoke-phase1.sh
```

If the full compose smoke fails, Claude must capture:

- failing step;
- latest API body involved;
- `docker compose ps`;
- relevant `docker compose logs` tails for server, Redis, and affected agents;
- whether the failure is a product bug, script bug, infrastructure timeout, or
  resource limitation.

## Risks To Watch

- Timeouts must account for image build and three Scrapyd subprocesses.
- The test must not accidentally use old public names:
  `/api/v1/executions`, `attempts[]`, `execution_id` run response, or
  `template_id`.
- The test must assert per-execution logs, otherwise it does not prove all three
  agents actually ran.
- Node stop/unhealthy checks are timing-sensitive; use configured heartbeat
  timeout plus a clear margin.
