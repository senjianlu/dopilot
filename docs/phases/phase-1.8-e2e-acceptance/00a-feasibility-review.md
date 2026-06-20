# 00a · Phase 1.8 E2E Acceptance Feasibility Review

## Proposed Direction

Run a Docker-based end-to-end acceptance for the current Phase 1.8 work using
the full architecture:

- PostgreSQL;
- Redis Streams;
- migrate container;
- server container;
- three real agent containers, each owning its own Scrapyd subprocess.

The acceptance should validate Phase 1.8 public API names and the agent/node
state behavior in realistic compose conditions.

## Claude Feedback

### Verdict

Feasible.

### Key Findings

- The current single-agent `scripts/smoke-phase1.sh` is not compatible with
  Phase 1.8. It still uses deleted `/api/v1/executions` routes, `attempts[]`,
  `execution_id` run responses, `template_id`, and template payloads that no
  longer include `build_artifact_id`.
- Multi-agent fan-out is a good acceptance target because one uploaded Scrapy
  egg now creates a server-side `BuildArtifact`, and each agent fetches the egg
  at run time.
- `node_strategy="all"` over three healthy Scrapy-capable agents should create
  exactly three child executions under one task.
- Stable Docker-verifiable states are healthy, API-driven offline exclusion,
  soft-delete exclusion, selected strategy, and heartbeat-timeout unhealthy
  after stopping an agent container.

### Risks

- Three real agents are heavier than the old single-agent smoke. Timeouts must
  be generous enough for image build, Scrapyd startup, Redis heartbeat, Scrapy
  execution, log drain, and heartbeat-timeout checks.
- Agent host ports cannot all publish `6800`; the e2e compose shape should avoid
  publishing agent ports or publish only distinct ports.
- Per-execution log checks must pass `execution_id` to
  `/api/v1/tasks/{task_id}/logs`; checking only the default log would not prove
  all three agents ran.

## Codex Decision

Accepted with implementation constraints:

- Replace the old `scripts/smoke-phase1.sh` behavior with the current Phase 1.8
  three-agent acceptance. Do not preserve obsolete public API vocabulary.
- Use three Scrapy-capable agents. Capability-exclusion is covered by unit and
  service tests; this Docker acceptance focuses on three real agents and their
  scheduling/health states.
- Required node states are:
  - all three healthy and schedulable;
  - one node offline but still heartbeat-healthy and excluded from dispatch;
  - one node stopped and later heartbeat-timeout unhealthy/excluded;
  - one node soft-deleted and excluded from dispatch.
- Keep agent HTTP ports internal unless a specific probe needs host access.

## User Escalations

None. The choices above preserve the user's request for three agents and
different agent states without adding an extra fourth non-Scrapy agent.
