# Phase 2.2.7 — Remove Agent Inbound HTTP / Port 6800: Claude Feasibility Review

**Reviewer:** Claude (implementation/test agent)
**Date:** 2026-06-23
**Scope:** Feasibility validation only. No code changed.

## 1. Verdict

**Feasible.** No blockers.

This is overwhelmingly a *deletion + config* change, not a re-architecture. The
replacement runtime path (agent pulls eggs from the server over the Redis run
command, deploys to local scrapyd itself) is already fully wired and is the path
real runs use today. The server→agent egg HTTP push and the agent's `/health`
endpoint are the only inbound surfaces left, and the egg push is **already dead
code** — no server route calls it.

The single piece of genuinely *new* code is a plain-asyncio agent entrypoint to
replace `uvicorn.run(...)` (see §3.1 / §6). Everything else is removal.

## 2. Blocking issues

None.

## 3. Risky assumptions (things that look like deletion but aren't)

### 3.1 The agent's background workers are started by the FastAPI **lifespan** — removing FastAPI is not free

`apps/agent/dopilot_agent/main.py::main()` calls `uvicorn.run(create_app(...))`.
That call does two things we rely on: (a) it blocks the process forever, and (b)
its ASGI lifespan is what actually **starts and stops** `CommandConsumer`,
`LogPublisher`, `HeartbeatWorker`, and the scrapyd `ScrapydProcess`
(`main.py:56-116`). These workers are the agent's *entire reason to run* and are
**not** HTTP — they live behind the lifespan only by construction convenience.

So "stop starting uvicorn" requires writing a replacement long-running
entrypoint that:

1. loads settings (as today),
2. builds the runtime (`build_runtime`),
3. starts `process` / `CommandConsumer` / `LogPublisher` / `HeartbeatWorker`
   (the exact set the lifespan starts today, in the same order),
4. installs SIGTERM/SIGINT handlers and blocks on an `asyncio.Event`,
5. tears them down in reverse order on signal (mirror the lifespan `finally`).

This is small and mechanical, but it is real new code and the one spot where a
regression (e.g. workers not reaped, scrapyd orphaned, no graceful shutdown)
could hide. **Recommend lifting the lifespan body into a reusable
`run_agent(settings)` coroutine** so the start/stop ordering has one source of
truth rather than being duplicated between an ASGI lifespan and a new loop.
Glibc base image stays required (scrapyd subprocess parent-death signaling).

### 3.2 "Remove the agent API" cascades to the agent's whole inbound-auth module

`require_agent_token` (`apps/agent/dopilot_agent/auth/dependencies.py`) has
**exactly one** consumer: the egg-deploy endpoint. Delete that endpoint and the
agent's entire inbound auth path is dead and should be removed too. This is
correct and desirable, but note the consequence for the doc/decision surface:
after this change the single `agent_token` authenticates **only one direction**
(agent→server: heartbeat + artifact fetch). Decision #12 / the refactor doc
currently say it authenticates *both* directions ("server→agent 部署 egg、
agent→server heartbeat"). That sentence becomes false and must be reworded (not
a code blocker — a docs-truth fix). The token itself stays necessary.

### 3.3 Dropping the advertised network endpoint is already supported — verify, don't rebuild

The heartbeat already carries `endpoint: str | None = None`
(`packages/protocol/.../streams.py:254`) and the node upsert already falls back
to `Node(endpoint=hb.endpoint or f"agent://{agent_id}")`
(`nodes/service.py:160`). `advertise_endpoint` already defaults to `""` → agent
sends `None` → node gets `agent://{agent_id}`. So the proposed "non-network
identity" is **already the default behavior**; no DB migration and no node-model
change are required. The work is: stop advertising (drop `advertise_endpoint`
from config/compose) and reword comments. `Node.endpoint` is `unique, not null`,
and `agent://{agent_id}` satisfies that — confirmed OK.

### 3.4 Container healthcheck becomes weak by nature

An HTTP `/health` probe proves the ASGI app answers. A process/exec probe can
only prove "a `dopilot-agent` process exists" — which does **not** prove the
command consumer is actually reading its stream. Real liveness already lives
server-side via heartbeat `last_seen_at`; the container healthcheck is, after
this change, mostly a restart trigger. That is acceptable (matches the
single-instance model) but Codex should *decide and state* what the healthcheck
asserts (§4.2). Suggested: exit 0 if the agent process is alive **and**, when
`[scrapyd].start=true`, local scrapyd answers on `127.0.0.1:6801`
(`/daemonstatus.json`) — that is the one genuinely useful local signal, and
6801 is container-internal so no port needs publishing.

### 3.5 `EggDeployResponse` becomes unused; `HealthResponse` does NOT

After removing both the agent egg endpoint and the server `AgentClient`,
`EggDeployResponse` has no remaining producer/consumer → delete or mark legacy.
**`HealthResponse` must stay** — the *server's* own `/api/v1/health`
(`apps/server/dopilot_server/api/v1/health.py`) and `packages/protocol/tests`
use it; only the agent's use of it goes away.

## 4. Missing product/architecture decisions for Codex

1. **Agent process model.** Confirm the agent becomes a non-HTTP daemon driven
   by an asyncio loop (§3.1). Confirm graceful-shutdown expectations (drain
   in-flight command? or just stop consuming + reap scrapyd?). Current lifespan
   stops consumer/publisher/heartbeat then stops scrapyd — recommend preserving
   exactly that ordering.
2. **Container healthcheck contract.** What must it assert, and should it gate
   on scrapyd when `[scrapyd].start=true` (§3.4)? Or drop the Docker
   `healthcheck:` entirely and rely on server-side heartbeat health?
3. **Vestigial agent settings.** `agent.host`, `agent.port` (6800),
   `advertise_endpoint`, and the `-b/-p` CLI flags lose all meaning. Remove them
   (cleaner, slightly breaking for anyone with them in TOML) or keep as ignored
   no-ops for back-compat? Recommend remove + note in changelog.
4. **`EggDeployResponse` / agent `/artifacts` + `/health` modules.** Hard-delete
   the dead runtime code (preferred per the brief) vs. keep as marked-legacy?
   Recommend hard delete — there is no second consumer.
5. **Token-direction wording.** Approve the reword that `agent_token` now
   authenticates only agent→server (§3.2) in decision #12 and the refactor doc.

## 5. Suggested scope cuts / sequencing

- **Do not** invent a new "non-network identity" mechanism — `agent://{agent_id}`
  already exists and is already the default. Just stop advertising (§3.3).
- **Sequence:** (1) add `run_agent()` asyncio entrypoint + switch `main()` off
  uvicorn, prove the agent still runs/consumes/heartbeats with no open port;
  (2) delete agent API router + `health.py` + `artifacts.py` + `auth/`;
  (3) delete server `AgentClient` + lifespan `egg_http`/`agent_client`;
  (4) protocol cleanup (`EggDeployResponse`); (5) deploy artifacts
  (Dockerfile EXPOSE, compose command/healthcheck/ports); (6) docs.
  Steps 2–6 are pure deletion once step 1 proves the loop works.
- Keep the FastAPI dependency in the agent only if step 1 still wants it; the
  goal allows removing `fastapi`/`uvicorn` from the agent's runtime deps
  entirely once no router remains. Treat dropping those deps as an optional
  follow-up, not a gate.
- Server-side `/api/v1/artifacts/scrapy/egg` (upload) and `.../{sha256}/egg`
  (fetch) are **out of scope** — they are the storage/serve path the agent pulls
  from, and `apps/server/tests/test_artifacts.py` exercises them. Do not touch.

## 6. Files / modules likely affected

**Agent — new / heavily changed**
- `apps/agent/dopilot_agent/main.py` — replace `uvicorn.run` with asyncio
  daemon loop (the one substantive new code).

**Agent — delete**
- `apps/agent/dopilot_agent/api/health.py`
- `apps/agent/dopilot_agent/api/artifacts.py`
- `apps/agent/dopilot_agent/api/router.py` (whole router collapses)
- `apps/agent/dopilot_agent/auth/dependencies.py` (`require_agent_token` —
  sole consumer was the egg endpoint)
- `apps/agent/tests/test_health.py`, `test_auth.py`, `test_api_logs_egg.py`
  (and the egg/health bits of `conftest.py`, `app_with_fake_scrapyd`)

**Agent — edit**
- `apps/agent/dopilot_agent/deps.py` — drop FastAPI-request deps that only the
  removed endpoints used (`get_scrapyd_client`/`get_scrapyd_process` as DI may
  go; `build_runtime` stays). Keep `artifact_cache`/`wheel_cache`/runner/store/
  heartbeat wiring.
- `apps/agent/dopilot_agent/config/settings.py` — `host`/`port`/
  `advertise_endpoint` (decision §4.3).

**Server — edit / delete**
- `apps/server/dopilot_server/clients/agent.py` — delete `AgentClient` +
  `get_agent_client` (no route consumes them; confirmed dead).
- `apps/server/dopilot_server/app.py` — remove `egg_http` /
  `app.state.agent_client` (lines ~121, 141-145, 185-186) and the
  `DEFAULT_TIMEOUT, AgentClient` import.

**Protocol**
- `packages/protocol/dopilot_protocol/agent.py` + `__init__.py` — remove
  `EggDeployResponse` export (keep `HealthResponse`).
- Heartbeat `endpoint` field may stay (harmless) or be dropped with
  `advertise_endpoint`.

**Deploy**
- `deploy/docker/Dockerfile` — `EXPOSE 5000 6800` → `EXPOSE 5000`.
- `deploy/docker/docker-compose.yml` — agent `command` (drop `-b/-p 6800`),
  healthcheck (HTTP→exec), remove `6800:6800` publish (lines ~64-82, 160-164).
- `deploy/docker/docker-compose.agent.yml` — same `command` + healthcheck
  (lines ~50, 74).

**Docs**
- `docs/dopilot/00-requirements.md` decision #12 (token now one-direction;
  `/health` no longer a container HTTP probe).
- `docs/refactor/00-redis-streams-agent-communication.md` — the line that keeps
  `/health` as container healthcheck and "egg deploy stays HTTP" is now
  obsolete; agent is outbound-only.
- `apps/agent/dopilot_agent/api/router.py` docstring & `clients/agent.py`
  docstring claims ("egg deploy stays HTTP") removed with the code.

## 7. Recommended verification commands

```bash
# Prove nothing still references the removed surfaces (expect: no hits).
grep -rn "AgentClient\|get_agent_client\|deploy_egg" apps/server/dopilot_server
grep -rn "EggDeployResponse" apps packages
grep -rn "require_agent_token\|/artifacts/scrapy/egg\|6800" apps/agent deploy
# Confirm the egg PULL path (must REMAIN) is intact.
grep -rn "ScrapyArtifactCache\|fetch_path\|artifacts/scrapy/.*egg" apps/agent apps/server

# Lint + types + unit suites.
ruff check apps packages
pytest apps/agent          # agent must import & run with no FastAPI app
pytest apps/server         # AgentClient removal must not break artifacts/nodes/heartbeat
pytest packages/protocol   # EggDeployResponse removal vs. test_schemas

# Manual loop smoke (the §3.1 risk): start agent with a Redis + server,
# confirm it consumes a run command and heartbeats with NO port 6800 open.
ss -ltnp | grep 6800 || echo "OK: agent opens no 6800 listener"

# Web fixtures still use http://a1:6800 as sample node-endpoint DATA only;
# confirm those are display strings, not live calls, before editing.
grep -rn "6800" apps/web
```
