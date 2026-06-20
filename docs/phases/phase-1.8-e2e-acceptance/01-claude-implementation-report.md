# 01 · Phase 1.8 E2E Implementation Report

## Report Provenance

Claude implemented the e2e changes but exited without writing this report. Codex
created this file from the resulting diff, Claude's `claude-progress.md`, and
Codex's independent verification run.

## Changed Files

### Docker

- `deploy/docker/docker-compose.e2e.yml`
  - Adds two extra agent services: `scrapy-agent-2` and `scrapy-agent-3`.
  - Reuses the same unified `rabbir/dopilot:latest` image and mounted
    `configs/agent.example.toml`.
  - Differentiates agents by `AGENT_ID`, `AGENT_WORKDIR`, and data volume.
  - Keeps the extra agents' HTTP ports container-internal to avoid host-port
    collisions.
  - Extends server `depends_on` so the server waits for all three agents.

- `configs/server.docker.toml`
  - Changes `[nodes].agents` to an empty list.
  - Rationale: Phase 1.5+ liveness comes from agent heartbeats; configured
    endpoints create phantom unknown rows that make exact e2e node-count
    assertions noisy.

### Smoke Script

- `scripts/smoke-phase1.sh`
  - Rewritten from the old single-agent Phase 1.7-style smoke into a Phase 1.8
    three-agent e2e acceptance.
  - Uses current public API vocabulary:
    - `/api/v1/tasks/{task_id}`;
    - `task_id` run responses;
    - `executions[]`;
    - `build_artifact_id`;
    - `execution_template_id`.
  - Adds regression guards against old vocabulary:
    - no `/api/v1/executions` dependency;
    - no `attempts[]`;
    - no `execution_id` run response.
  - Adds per-execution log checks using
    `/api/v1/tasks/{task_id}/logs?execution_id=...`.
  - Adds node-state acceptance cases:
    - all three agents healthy and schedulable;
    - offline node excluded while still heartbeat-healthy;
    - stopped agent becomes unhealthy after heartbeat timeout and is excluded;
    - soft-deleted node is not resurrected by later heartbeat and is excluded.

## Implementation Notes

- The base `agent` service remains `scrapy-agent-1` and publishes host port
  `6800`.
- `scrapy-agent-2` and `scrapy-agent-3` bind their agent HTTP service on
  container port `6800` only; no host publish is needed because the smoke drives
  behavior through the server API.
- Each agent owns a separate `/agent-data` volume, so each has independent state
  and a separate Scrapyd data directory.
- The smoke reads `heartbeat_timeout_seconds` from `configs/server.docker.toml`
  and uses that value plus margin for the stopped-agent unhealthy check.
- The smoke remains clean-volume by default and tears the compose stack down on
  exit unless `KEEP_UP=1` is set and the run passed.

## Known Issues

- Claude did not create the required implementation/test report files before
  exiting. Codex independently reviewed the diff and reran all required
  verification commands.
