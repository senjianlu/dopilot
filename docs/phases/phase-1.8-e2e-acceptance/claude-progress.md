# Claude progress — Phase 1.8 E2E acceptance

Durable coordination notes for this packet. Not an implementation report.

## Size / cadence

- Rough size class: `45-90m` (compose build is warm — base images already
  present — but the smoke runs ~5 Scrapy fan-outs plus a >30s heartbeat-timeout
  wait, so the full compose smoke alone is several minutes).
- Cadence: update at each checkpoint (context read, static checks, compose shape,
  script rewrite, smoke run, reports).
- Likely long-running commands: `scripts/smoke-phase1.sh` (full clean-volume
  3-agent compose smoke), `corepack pnpm --filter web build`.

## Plan / checkpoints

1. [done] Read all required context + map the real Phase 1.8 API shapes.
2. [done] Static/unit/frontend/build all PASS (see log).
3. [done] Added 3-agent compose override (`deploy/docker/docker-compose.e2e.yml`);
   set `[nodes].agents = []` in server.docker.toml to drop the phantom node.
4. [done] Rewrote `scripts/smoke-phase1.sh` (Cases 1-9; syntax OK).
5. [ ] Run the full compose smoke; capture evidence on failure.
6. [ ] Write `01-claude-implementation-report.md` + `05-claude-test-report.md`.

## Key facts discovered (real Phase 1.8 contract)

- Routes: `/api/v1/tasks/{id}`, `/tasks/{id}/logs?execution_id=`, `/templates`,
  `/templates/{id}/run`, `/artifacts/scrapy/egg`, `/artifacts/{id}/run`,
  `/schedules`, `/schedules/{id}/trigger-now`, `/nodes`,
  `/nodes/{id}/offline`, `DELETE /nodes/{id}`.
- Run responses are `TaskRunResponse {task_id, status}` (NOT `execution_id`).
- `GET /tasks/{id}` → `TaskView` with `executions[]` (NOT `attempts[]`),
  `source`, `build_artifact`, `status` (terminal `complete`).
- Task source: template run = `template`; direct = `direct_artifact`;
  schedule trigger-now = `schedule_trigger_now`.
- Egg upload → `{artifact: BuildArtifactView{id, artifact_type=scrapy,
  package_format=egg, ...}, spiders[]}`.
- Node: env `AGENT_ID`/`AGENT_WORKDIR`/`DOPILOT_REDIS_URL` override the agent
  TOML, so 3 agents share one mounted config and differ only by env + volume.
  Each advertises endpoint=None → distinct node endpoint `agent://{agent_id}`.
- heartbeat_timeout_seconds = 30 (configs/server.docker.toml).
- Demo markers: `phase1 demo spider started` / `phase1 demo spider done`.

## Log

- (start) Context read; API shapes mapped; toolchain verified (.venv ruff/pytest,
  corepack pnpm 11.7, docker 29.5 + compose v5.1). Base images already built.
- (static) ruff: All checks passed. pytest: 317 passed in 7.24s. web test:
  23 passed (pre-existing harmless `loading` directive Vue warn). web build: OK
  (pre-existing >500kB chunk-size warning). `docker compose config` base OK;
  base+e2e config OK (agent/scrapy-agent-2/scrapy-agent-3, server waits on all 3).
- (compose-smoke) starting full clean-volume 3-agent smoke now.
