# 04 · Test plan（阶段 1.5）

## Behavior under test

- Redis command dispatch replaces server->agent HTTP run/status/tail as the main path.
- Agent command consumer starts Scrapy attempts idempotently and recovers pending commands.
- Agent status events and log increments are published over Redis Streams and consumed by the server.
- Heartbeat replaces server health polling for node liveness.
- Reconcile marks heartbeat/event-stall loss without contacting agent HTTP status.
- Log gaps become visible `partial` integrity and do not block terminal execution convergence.
- Redis unavailable paths produce explicit dispatch failure or bounded outbox timeout.
- Alembic `0003` upgrades and downgrades against PostgreSQL.
- Docker compose includes Redis AUTH/AOF and wires server/agent to Redis.

## Unit and integration coverage

- `packages/protocol/tests/test_stream_schemas.py`: stream topology, command/event/log/heartbeat schema and wire codec.
- `apps/server/tests/test_dispatcher.py`: command outbox dispatch, retry, cancel short-circuit, give-up, dispatch timeout.
- `apps/server/tests/test_executions.py`: run dispatch over Redis, 503 dispatch unavailable, 202 dispatch unknown, cancel command convergence.
- `apps/server/tests/test_event_consumer.py`: dedupe, terminal monotonicity, lost override, lost reason precedence, reclaim request.
- `apps/server/tests/test_log_consumer.py`: append, duplicate drop, gap marker, sticky `partial`, SSE offset consistency, drain cleanup.
- `apps/server/tests/test_reconcile_redis.py`: heartbeat timeout, event stall, server-lost, reclaim stop, drain cleanup gating.
- `apps/server/tests/test_heartbeat_api.py` and `test_node_selection.py`: heartbeat auth/upsert and heartbeat-recency node selection.
- `apps/agent/tests/test_command_consumer.py`: run, duplicate attempt id, concurrent duplicate, pending recovery, reserved orphan, cancel/reclaim, cleanup.
- `apps/agent/tests/test_event_outbox.py`: event outbox durability and republish.
- `apps/agent/tests/test_log_publisher.py`: byte-offset publishing, cursor persistence, XADD failure retry, EOF marker.
- `apps/agent/tests/test_heartbeat_worker.py`: heartbeat payload, token header, endpoint URL.

## Verification commands

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check apps packages
cd deploy/docker && docker compose config
docker run -d --rm --name dopilot-phase15-pg -e POSTGRES_PASSWORD=dopilot -e POSTGRES_USER=dopilot -e POSTGRES_DB=dopilot -p 55432:5432 postgres:16
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:55432/dopilot ../../.venv/bin/alembic upgrade head
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:55432/dopilot ../../.venv/bin/alembic downgrade base
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:55432/dopilot ../../.venv/bin/alembic upgrade head
```

## Smoke / manual coverage still recommended

```bash
cd deploy/docker && docker compose up --build
```

Expected result: upload egg, run spider, see execution/attempt/log index in PostgreSQL, receive live logs through server SSE, and confirm server does not call agent HTTP run/status/tail.

## Regression risks

- At-least-once Redis command dispatch can redeliver commands; agent `attempt_id` idempotency must remain intact.
- Redis log stream trimming can create visible log gaps; `partial` must remain sticky.
- Server-lost soft terminal must remain overridable by later agent hard terminal.
- Cancel must remain asynchronous and converge through `attempt.canceled` rather than roll up as lost.
