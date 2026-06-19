# 07 · Acceptance（阶段 1.5）

## Summary

Phase 1.5 is accepted with documented operational smoke and production-sizing follow-ups.

The implementation replaces the phase-1 server->agent HTTP run/status/tail main path with Redis Streams:

- server writes `command_outbox` and dispatches commands to `dopilot:agent:{agent_id}:commands`;
- agent consumes commands, runs Scrapy through its local `ScrapyRunner`, and publishes status/log events;
- server consumes `dopilot:server:agent-events` and `dopilot:server:logs`, updates PostgreSQL, writes log bodies to `/server-data/logs`, and preserves server->web SSE;
- health is now agent heartbeat into `POST /api/v1/agents/{agent_id}/heartbeat`;
- egg deploy over agent HTTP and agent `/health` remain the explicit exceptions.

## Evidence

- Brief: `docs/phases/phase-1.5/00-brief.md`
- Claude implementation report: `docs/phases/phase-1.5/01-implementation-report.md`
- Codex review: `docs/phases/phase-1.5/02-codex-review.md`
- Test plan: `docs/phases/phase-1.5/04-test-plan.md`
- Test report: `docs/phases/phase-1.5/05-claude-test-report.md`
- Codex test review: `docs/phases/phase-1.5/06-codex-test-review.md`

## Verified commands

```text
.venv/bin/python -m pytest -q
-> 236 passed in 3.18s

.venv/bin/python -m ruff check apps packages
-> All checks passed.

cd deploy/docker && docker compose config
-> passed

PostgreSQL 16 Alembic verification:
-> upgrade head passed
-> downgrade base passed
-> upgrade head passed
```

## Remaining risks

- Full `docker compose up --build` Scrapy end-to-end smoke remains to be run.
- `reserved-orphan` TOCTOU is accepted: a crash between scrapyd schedule and local started-state persistence can leave an uncorrelated scrapyd job while the attempt reports `spawn_aborted`.
- Pure server-lost from heartbeat timeout is not cleaned until the agent recovers and reconciles, to avoid deleting logs/state for a process that may still be alive.
- Redis log RPO is non-zero by design; stream trimming or long server outage can create visible `partial` logs.
- Production Redis retention/maxlen and high-volume log latency still need real workload tuning.

## Final decision

Accepted with documented risk. No blocking Codex findings remain.
