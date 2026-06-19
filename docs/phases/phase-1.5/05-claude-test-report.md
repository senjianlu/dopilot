# 05 · Test report（阶段 1.5）

## Claude-reported results

Claude reported in `/tmp/dopilot-phase-1.5-results.md` and `01-implementation-report.md`:

- `236 passed` total.
- Server tests: 131.
- Agent + protocol tests: 105.
- `ruff check` passed.
- `0003_redis_streams` verified against real PostgreSQL with upgrade and downgrade/upgrade round trip.
- `docker compose config` passed.

## Codex rerun results

Codex reran the core verification during review on 2026-06-19:

```text
.venv/bin/python -m pytest -q
-> 236 passed in 3.18s

.venv/bin/python -m ruff check apps packages
-> All checks passed.

cd deploy/docker && docker compose config
-> passed; rendered config includes db, redis, migrate, agent, server and Redis AUTH/AOF wiring.

Alembic against real PostgreSQL 16 on localhost:55432:
-> upgrade base -> 0001 -> 0002 -> 0003 succeeded
-> downgrade 0003 -> 0002 -> 0001 -> base succeeded
-> upgrade base -> 0001 -> 0002 -> 0003 succeeded
```

## Not run

- Full `docker compose up --build` Scrapy end-to-end smoke was not run in this Codex review pass. It remains the recommended final operational smoke before external acceptance.
