# Phase 2.2.7 — Remove Agent Inbound HTTP / Port 6800: Claude Implementation Report

**Agent:** Claude (implementation/test agent)
**Date:** 2026-06-23
**Brief:** `docs/phases/phase-2.2.7-agent-no-inbound-http/00-brief.md`

## Summary

`dopilot-agent` is now an **outbound-only worker daemon**: it consumes commands
from Redis, publishes status/log events to Redis, and POSTs heartbeats to the
server. It starts **no uvicorn/FastAPI app** and binds **no port** (`6800` is
gone). The server→agent egg-deploy HTTP path and the agent `/health` endpoint are
deleted; Scrapy eggs are fetched from the server during Redis command execution
via the existing `ScrapyArtifactCache.ensure()` path (unchanged). The single
`DOPILOT_AGENT_TOKEN` now authenticates only the agent→server direction.

Net diff: **41 files changed, +275 / −1029** (deletion-dominant).

## Changed files by area

### Agent runtime (new entrypoint + deletions)

- `apps/agent/dopilot_agent/main.py` — **rewritten**. `uvicorn.run(create_app())`
  replaced by `run_agent(settings)`, a plain-asyncio daemon that is the single
  source of truth for start/stop ordering (build runtime → start scrapyd → build
  Redis client + command consumer + event publisher + log publisher and start
  consumer/publisher → start heartbeat → block on an `asyncio.Event` →
  SIGTERM/SIGINT handlers → teardown in reverse: log publisher, consumer, redis
  client, heartbeat, scrapyd). `main()` drops `-b/--bind` / `-p/--port` and runs
  `asyncio.run(run_agent(...))`. `run_agent` takes an optional `stop` event for
  tests.
- `apps/agent/dopilot_agent/deps.py` — dropped the FastAPI request deps
  (`get_runtime` / `get_scrapyd_client` / `get_scrapy_runner` / `get_state_store`
  / `get_scrapyd_process`) and the `fastapi.Request` import. `build_runtime` /
  `AgentRuntime` / dir helpers unchanged.
- `apps/agent/dopilot_agent/config/settings.py` — removed `[agent].host`,
  `[agent].port`, `[agent].advertise_endpoint`; updated docstrings to
  "outbound-only".
- `apps/agent/dopilot_agent/redis/heartbeat.py` — heartbeat now sends
  `endpoint=None` (node identity falls back to `agent://{agent_id}`); docstrings
  updated.
- `apps/agent/dopilot_agent/scrapyd/client.py` — added public `daemonstatus()`
  (used by the healthcheck).
- `apps/agent/dopilot_agent/__init__.py` — docstring → "outbound-only worker daemon".
- **Deleted:** `api/__init__.py`, `api/router.py`, `api/health.py`,
  `api/artifacts.py`, `auth/__init__.py`, `auth/dependencies.py`
  (`require_agent_token`), and `errors.py` (became dead after the API removal —
  no remaining importer).
- `apps/agent/pyproject.toml` — dropped `fastapi` / `uvicorn[standard]` /
  `python-multipart` runtime deps; added `dopilot-agent-healthcheck` console
  script; description → "outbound-only worker executor daemon".

### Agent container healthcheck (new)

- `apps/agent/dopilot_agent/healthcheck.py` — **new** local CLI
  (`dopilot-agent-healthcheck`): loads the baked/default agent config (env
  overrides apply); when `[scrapyd].start=true`, verifies local scrapyd answers
  `daemonstatus.json` on its container-internal host/port; exits non-zero on
  config-load or scrapyd failure; opens no HTTP listener.

### Server / runtime cleanup

- **Deleted:** `apps/server/dopilot_server/clients/agent.py` (`AgentClient`,
  `get_agent_client`, `deploy_egg`, `normalize_endpoint`,
  `Agent{Unreachable,Response}Error`) and `clients/__init__.py` (package emptied).
- `apps/server/dopilot_server/app.py` — removed the lifespan `egg_http`
  httpx client + `app.state.agent_client = AgentClient(...)`, the
  `from .clients.agent import DEFAULT_TIMEOUT, AgentClient` import, the now-unused
  `import httpx`, and the egg-client teardown; updated docstrings/comments to
  "no server→agent HTTP path (phase 2.2.7)". Artifact upload/download endpoints
  untouched.
- `apps/server/dopilot_server/config/settings.py`,
  `apps/server/dopilot_server/auth/agent_dependencies.py`,
  `apps/server/dopilot_server/agent_token.py` — docstrings reworded: the
  `agent_token` authenticates only the agent→server direction.

### Protocol cleanup

- `packages/protocol/dopilot_protocol/agent.py` — removed `EggDeployResponse`
  (no remaining producer/consumer); module docstring updated. `HealthResponse`
  kept (server `/api/v1/health` still uses it).
- `packages/protocol/dopilot_protocol/__init__.py` — dropped the
  `EggDeployResponse` import + `__all__` entry.
- Heartbeat protocol `endpoint` field kept (active agents send `None`).

### Deploy / config

- `deploy/docker/Dockerfile` — `EXPOSE 5000 6800` → `EXPOSE 5000`.
- `deploy/docker/docker-compose.yml` — agent anchor `command: ["dopilot-agent"]`,
  healthcheck → `["CMD", "dopilot-agent-healthcheck"]`, removed the
  `scrapy-agent-1` `6800:6800` publish; `DOPILOT_AGENT_TOKEN` header comment
  reworded (agent→server only).
- `deploy/docker/docker-compose.agent.yml` — same `command` + local healthcheck;
  no published port.
- `configs/agent.example.toml` — removed `host`/`port`; reworded the token /
  scrapyd comments (outbound-only; no server→agent direction).
- `configs/server.example.toml` — `[nodes].agents = []` (was
  `["localhost:6800"]`); token comment reworded.
- `configs/server.docker.toml` — `[nodes].agents` comment reworded (drop the
  `["agent:6800"]` placeholder mention).

### Docs

- `docs/dopilot/00-requirements.md` decision #12 — token now authenticates
  agent→server only; added the 2.2.7 outbound-only paragraph (egg pull, `/health`
  removed, `6800` removed, local healthcheck).
- `docs/refactor/00-redis-streams-agent-communication.md` — the
  "`/health` stays a container healthcheck / egg deploy stays HTTP" line replaced
  with the 2.2.7 outbound-only model.
- `docs/dopilot/08-docker-deployment.md` — agent run command, dev notes, the
  compose example (command/healthcheck/ports), and the two summary tables updated
  to the outbound-only, no-`6800` shape.
- `docs/dopilot/10-roadmap.md` — the post-1.5 "residual HTTP" parenthetical now
  notes 2.2.7 removed all agent inbound HTTP.
- `README.md` — local dev steps drop `advertise_endpoint = localhost:6800`; note
  the agent opens no inbound port.

### Tests

- **Deleted:** `apps/agent/tests/test_health.py`, `test_auth.py`,
  `test_api_logs_egg.py` (covered the removed endpoints).
- **New:** `apps/agent/tests/test_main.py` — `run_agent` starts/stops cleanly
  with no redis/server configured; and builds+starts the Redis command consumer
  and log publisher (injected fakeredis via `build_redis`) and tears them down in
  reverse order. (The redis test stubs worker `start`/`stop` to assert wiring +
  ordering without running the blocking consumer loop — see Known risks.)
- **New:** `apps/agent/tests/test_healthcheck.py` — healthcheck OK when scrapyd
  answers, fails when scrapyd is down, skips the scrapyd probe when
  `[scrapyd].start=false`, and fails on a bad config (via `httpx.MockTransport`).
- `apps/agent/tests/conftest.py` — removed the ASGI app/client helpers, the
  `make_settings` builder, and the deleted deps imports; kept `FakeScrapyd`,
  `make_runner`, `FakeRedisStreams`, fixtures.
- `apps/agent/tests/test_heartbeat_worker.py` — dropped `advertise_endpoint`;
  asserts `req.endpoint is None`.
- `apps/agent/tests/test_config.py` — dropped `host`/`port` from the sample TOML.
- `apps/server/tests/conftest.py` — removed `FakeAgentClient`, the `fake_agent`
  fixture, the `get_agent_client` override, the `EggDeployResponse` import, and
  the `agent` parameter threaded through `_build_exec_client` / `exec_client*`.
- `packages/protocol/tests/test_agent_schemas.py` — removed the
  `EggDeployResponse` import + round-trip test.

## Implementation notes

- The lifespan body was lifted verbatim into `run_agent` so start/stop ordering
  has one source of truth (per the feasibility review §3.1). Graceful shutdown:
  SIGTERM/SIGINT set an `asyncio.Event`; teardown mirrors the old lifespan
  `finally` exactly (stop log publisher → consumer → close redis → stop heartbeat
  → stop scrapyd).
- The agent is now FastAPI/uvicorn-free; those deps were dropped from the agent
  `pyproject.toml`.
- `EggDeployResponse` removal is safe: the only producers/consumers were the
  deleted agent endpoint, the deleted server `AgentClient`, and the server-test
  fake — all removed.
- The server-side artifact upload/download endpoints
  (`POST /api/v1/artifacts/scrapy/egg`, `GET .../{sha256}/egg`, wheel paths) are
  untouched (the egg PULL path the agent uses).
- `[nodes].agents` is config-only and unread by the server; setting it `[]` in
  the example removes the only `6800` in `configs/` without behavior change.

## Commands run (exact outcomes)

| Command | Result |
| --- | --- |
| `ruff check apps packages` | **passed** ("All checks passed!") |
| `pytest packages/protocol/tests` | **67 passed** |
| `pytest apps/agent/tests` | **117 passed** |
| `pytest apps/server/tests` | **316 passed** |
| `docker compose -f deploy/docker/docker-compose.yml config` | **OK** (renders; agents use `command: [dopilot-agent]`, healthcheck `dopilot-agent-healthcheck`, no `6800`) |
| `docker compose -f deploy/docker/docker-compose.agent.yml config` | **Fails without env** (`REDIS_PASSWORD`/`DOPILOT_AGENT_TOKEN`/`DOPILOT_SERVER_URL` are `${VAR:?...}` required — pre-existing, by design). **Valid** when those env vars are supplied (verified: `command: [dopilot-agent]`, healthcheck `dopilot-agent-healthcheck`, no `6800`). |
| `ss -ltnp \| grep 6800` | **no listener** ("OK: no agent 6800 listener") |

Test invocation note: `.venv/bin/pytest` has a stale shebang (venv moved from
`/home/rabbir/dopilot` to `/home/rabbir/Projects/dopilot`) → exit 127, so suites
were run via `.venv/bin/python -m pytest` with `PYTHONPATH` (the equivalent of
`pytest apps/agent` etc.).

### Reference checks (brief)

`rg -n "AgentClient|get_agent_client|deploy_egg|EggDeployResponse|require_agent_token|/artifacts/scrapy/egg" apps packages`
— remaining hits are all expected:

- `packages/protocol/.../agent.py` — a docstring noting `EggDeployResponse` was
  dropped.
- `apps/web/lib/api/artifacts.ts`, `apps/server/.../api/v1/artifacts.py`,
  `apps/server/.../api/v1/schemas.py`, `apps/server/tests/test_artifacts.py` —
  the **server** artifact upload/download endpoints (`/api/v1/artifacts/...`),
  which the brief preserves. No reference to the removed symbols/agent endpoint.

`rg -n "6800" apps/agent deploy configs docs/dopilot docs/refactor README.md`
— remaining hits are not active-path descriptions:

- `apps/agent/dopilot_agent/main.py` — docstring stating "port `6800` is gone".
- `docs/dopilot/07-testing-baseline.md` — upstream **scrapydweb** scrapyd at
  `127.0.0.1:6800` (behavioral reference for the upstream test baseline, not the
  dopilot agent).
- `docs/dopilot/10-roadmap.md` line 64 and
  `docs/dopilot/02-gap-scheduling-nodes-push.md` — **historical / superseded**
  phase-1 records carrying explicit `superseded-by refactor/00` markers. The
  roadmap's own policy is "不回改 phase-0/1 历史记录"; these describe the
  delivered-then-replaced phase-1 plan, not an active path. The current-state
  descriptions (decision #12, refactor/00, 08-docker-deployment) were updated.

## Known risks / incomplete items

- **Container healthcheck is a weak liveness signal** (by design, per feasibility
  §3.4): it proves the config loads and (when managed) local scrapyd answers, not
  that the command consumer is reading its stream. Real liveness is the
  agent→server heartbeat (`nodes.last_seen_at`). Accepted in the brief.
- **`run_agent` redis test stubs worker start/stop.** Driving the real background
  consumer loop against `fakeredis` deadlocked: fakeredis honors the XREADGROUP
  `block` timeout and the blocking read is not cancellable in-process, so the
  test asserts construction + start + reverse-order teardown without running the
  loop. The consumer loop itself remains covered by `test_command_consumer.py`
  (via direct `drain_once`), and real redis-py blocking reads are cancellable via
  connection close. No full live agent↔redis↔server smoke was run in this pass
  (no running stack); the no-listener property is shown by `ss` + the absence of
  any FastAPI/uvicorn import in the agent.
- **Historical docs still mention `6800`** (roadmap line 64, gap doc) as
  superseded phase-1 history, intentionally left per the docs' no-rewrite-history
  policy. `CLAUDE.md`'s decision-#12 summary still says "authenticates BOTH
  directions" — it is out of the brief's edit/verification scope and points to
  `00-requirements.md` (updated) as the source of truth; flagging for Codex in
  case a CLAUDE.md refresh is wanted.
