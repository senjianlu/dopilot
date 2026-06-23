# Phase 2.2.7 — Claude Progress Notes

**Size class:** medium (mostly deletion + config; one new asyncio daemon entrypoint + one new healthcheck CLI).

## Checkpoints

- [x] C1: Read context + map all reference sites.
- [x] C2: Agent runtime — `run_agent()` asyncio daemon replaces uvicorn; dropped CLI `-b/-p`.
- [x] C3: Deleted agent inbound API (`api/`, `auth/`) + dropped FastAPI deps; deleted dead `errors.py`.
- [x] C4: Agent config — dropped `host`/`port`/`advertise_endpoint`; heartbeat sends `endpoint=None`.
- [x] C5: Local healthcheck module + `dopilot-agent-healthcheck` console script + scrapyd `daemonstatus()`.
- [x] C6: Server — deleted `clients/agent.py` (AgentClient/get_agent_client); removed lifespan `agent_client`/`egg_http`.
- [x] C7: Protocol — dropped `EggDeployResponse` (kept `HealthResponse`).
- [x] C8: Deploy — Dockerfile `EXPOSE 5000`; both compose files: `command: [dopilot-agent]`, local healthcheck, no `6800`.
- [x] C9: Docs/config examples — outbound-only; removed active-path `6800`/server→agent HTTP from in-scope paths.
- [x] C10: Tests — deleted health/auth/egg tests; added `test_main.py` + `test_healthcheck.py`; updated heartbeat/config/conftests.
- [x] C11: Verification run — ruff + 3 pytest suites + 2 compose configs + rg checks (see report).

## Outcomes (all green)

- ruff check apps packages — passed.
- pytest packages/protocol — 67 passed.
- pytest apps/agent — 117 passed.
- pytest apps/server — 316 passed.
- docker compose config (all-in-one) — OK; agent-only valid with required env supplied.
- `ss -ltnp | grep 6800` — no agent 6800 listener.

## Notes on long-running commands

- `pytest` console script in `.venv/bin/pytest` has a stale shebang (`/home/rabbir/dopilot/...`,
  venv since moved to `/home/rabbir/Projects/dopilot`) → exit 127. Ran suites via
  `.venv/bin/python -m pytest` with `PYTHONPATH` instead (wrapped in `bash -c`).
- An early `test_main` version deadlocked: introspecting the shared fakeredis connection
  concurrently with the running consumer, plus fakeredis honoring the XREADGROUP block
  timeout (uncancellable). Rewrote the redis test to stub worker start/stop and assert
  wiring + teardown order without running the blocking loop.
