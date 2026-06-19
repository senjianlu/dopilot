# 06 · Codex test review（阶段 1.5）

## Result

Accepted for code-level and migration-level verification.

The test matrix covers the core phase-1.5 risk areas:

- command outbox dispatch and retry/give-up;
- manual dispatch unavailable and dispatch unknown;
- agent command idempotency, pending recovery, reserved orphan recovery;
- status event monotonicity, dedupe, soft-lost override, lost reason precedence;
- log offset append/drop/gap behavior and sticky `partial`;
- heartbeat-sourced node selection;
- reconcile lost and cleanup behavior;
- Redis event/log publishing failure and replay;
- PostgreSQL Alembic `0003` upgrade/downgrade.

## Gaps

- No full containerized Scrapy smoke was run by Codex. This is an operational integration gap, not a unit/integration coverage gap.
- High-volume log throughput and Redis maxlen/retention sizing are not load tested. Production sizing remains a deployment tuning task.
- The cancel-vs-dispatch race is covered by convergence semantics (`stop(intent=cancel)`), but not by a deterministic concurrent test that proves every possible interleaving. The design does not require exactly-once command delivery; it requires idempotent convergence.

## Decision

No further Claude test iteration is required before phase-1.5 code acceptance. Run the full compose smoke before relying on the stack operationally.
