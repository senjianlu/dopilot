# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is right now

**dopilot is currently a docs-first planning repo.** There is no dopilot application code yet — the only code present is the upstream **scrapydweb 1.6.0** snapshot under `reference/scrapydweb/`, kept as a *read-only behavioral reference*. dopilot is a private scheduling platform built **greenfield** (all-new code under an `apps/`+`packages/` layout); scrapydweb (a Flask-based Scrapyd cluster manager) is consulted only for **how it behaves**, never for how it is built.

> **⚠️ scrapydweb reference boundary (hard rule).** scrapydweb is used for exactly two things: (1) a **functional/behavioral reference** (what it does, what the rules are) and (2) a **test oracle** (expected-behavior comparison). Its **code style, directory structure, module layout, naming, dependency organization, and config form must NEVER be a design basis for dopilot.** dopilot is written fresh, structure-first, per its own domain (authoritative layout: `docs/dopilot/05-dev-setup-and-known-issues.md` §1). `reference/scrapydweb/` is read-only — never built, never imported, never `git mv`'d or renamed into dopilot.

Two things follow from this and matter constantly:

1. **`reference/scrapydweb/` is reference only.** Do not treat it as the project source, do not "fix" it, and it must NOT be part of any Docker build context (`.dockerignore` must exclude `reference/`). It exists so you can read how scrapydweb *behaves* (functional reference + test oracle) and diff the snapshot against upstream — **not** as a base to derive, restructure, or rename dopilot from. Its structure/code/naming are not a template (see the reference-boundary rule above).
2. **The `docs/` tree is the source of truth** for goals, decisions, and the greenfield build plan. When the user asks for behavior/architecture decisions, the answer is usually already written there. Update docs when decisions change.

## Where to read first

- `docs/dopilot/00-requirements.md` — **北极星 / north-star**: product goals, the confirmed decisions table, the 4-phase roadmap. Read this before proposing anything.
- `docs/dopilot/10-roadmap.md` — consolidated greenfield build/port roadmap (ties together scrapydweb behavior + gaps + decisions).
- `docs/architecture/` — how scrapydweb works today (**behavioral/functional reference for porting**, not a structure to inherit): overview, bootstrap/config, data model, scheduler engine, views/frontend, scrapyd cluster I/O, auth/utils.
- `docs/dopilot/0x-gap-*.md` — per-area gap analyses (executors, scheduling/nodes/push, realtime logs, i18n).

**Docs convention:** assertions are cited as `file:line`, and those paths are **relative to `reference/scrapydweb/`** (e.g. `vars.py:29` means `reference/scrapydweb/scrapydweb/vars.py:29`). Keep this convention when editing docs.

## Confirmed decisions you must respect

These are locked in `docs/dopilot/00-requirements.md` §4 — don't relitigate them:

- **Three scheduled-object types, done in strict order:** ① Scrapy (via scrapyd) → ③ plain Python3 scripts → ② Docker long-lived crawlers. One type stable before the next.
- **Two deploy roles, both Docker:** `server` (Web + scheduler hub) and `agent` (worker executor).
- **Single admin only** — no multi-user/RBAC.
- **Frontend = greenfield SPA:** Vue 3 + Element Plus + Vite + TypeScript in `apps/web`, front/back split (FastAPI backend exposes `/api/v1/*` JSON), built fresh against the API and delivered page-by-page in phases — **no scrapydweb-Jinja coexistence** (dopilot has no inherited Jinja pages).
- **Realtime logs (decision #11) = agent pushes log increments over a Redis log stream; server consumes and persists, no WebSocket** *(superseded by `docs/refactor/00-redis-streams-agent-communication.md`, the authoritative model)*: instead of server pulling the agent tail API, the **agent** publishes log increments (base64 bytes, with byte `offset`/`size_bytes`/`eof`) to the Redis stream `dopilot:server:logs`; the **server log consumer** drains them, writes log bodies to `/server-data/logs`, and writes the log index/offset/status to PostgreSQL, then pushes to Vue over **server→web SSE**. The four invariants are preserved: first version does **not** use WebSocket, fan-out to web is **server→web SSE**, log bodies live at `/server-data/logs`, and PostgreSQL stores only the index/offset/status. Built on the `LogSource` abstraction — implementation changes from `AgentTailLogSource` (server pull) to `RedisLogSource` (agent push + server consume); the seam stays. Log RPO is **not** 0: server long-stop or Redis log-stream trimming can leave a `partial` log file (new `log_integrity` column), which is a visible/audit fact and is decoupled from business status — log gaps never block execution status from converging.
- **Push mode** = dispatch a task to a specific worker for immediate execution.
- **Image publishing (decision 7):** build & push to **Docker Hub `rabbir/dopilot:latest`** (server) and `rabbir/dopilot-agent:latest` (agent). ⚠️ Image namespace `rabbir` ≠ git `origin` `senjianlu/dopilot` — they are unrelated; never use `senjianlu` as an image prefix.
- **Monorepo (decision 8):** server, agent, and web are developed in **this same repo** under an `apps/`+`packages/` layout (authoritative tree: `docs/dopilot/05-dev-setup-and-known-issues.md` §1); not split into multiple repos.
- **Database (decision 10):** PostgreSQL is the only dopilot database. server owns SQLAlchemy/Alembic migrations; agent/web never connect directly. PostgreSQL stores only the **log index/offset/status** (table `execution_log_files`); **log bodies are NOT stored in PostgreSQL** — they live as files on the server at `/server-data/logs` with a retention policy. **Redis is a message bus / transient transport, not a dopilot database** — it does not persist business truth, and the agent reaching dopilot **through Redis does not connect to PostgreSQL directly** (see `docs/refactor/00-redis-streams-agent-communication.md`).
- **Agent communication (decision #12) = agent-initiated over Redis Streams + heartbeat, not server→agent HTTP** *(superseded by `docs/refactor/00-redis-streams-agent-communication.md`, the authoritative model)*: the v1 "agent does not call back" rule is dropped. The **agent** actively consumes commands from its Redis command stream (`dopilot:agent:{agent_id}:commands`), actively `XADD`s status events / logs (`dopilot:server:agent-events`, `dopilot:server:logs`), and actively `POST /api/v1/agents/{agent_id}/heartbeat`. The **server** initiates only the high-level dispatch (HTTP run/status/tail pull paths and `AgentTailLogSource` are removed as primary paths) via writing commands → Redis. Auth is split: agent→server uses a dedicated `server_shared_token` (not the old server→agent token), and Redis runs with AUTH/ACL. The agent still never connects to PostgreSQL directly.

The three "abstract-first" seams to establish in phase 0/1 (so you don't edit three executors three times): `BaseExecutor`, `LogSource`, `node_strategy`. See `10-roadmap.md` §1.

## Critical pitfalls (scrapydweb reference behavior — read before porting)

These describe how the **scrapydweb reference** behaves. Each is tagged either *[do NOT inherit]* (a scrapydweb implementation quirk dopilot must not reproduce) or *[dopilot design constraint]* (a property dopilot must respect when it implements similar behavior). They are **never** a reason to copy scrapydweb's structure or code.

- **`pkg_resources` / setuptools (reference install + porting note):** APScheduler 3.6.0 imports `from pkg_resources import ...`, which `setuptools>=81` removed, so `pip install -e reference/scrapydweb` breaks `import scrapydweb`. Fix for the *reference* install: `pip install "setuptools<81"`. **For dopilot, prefer APScheduler 3.10.x** (importlib-based, no `pkg_resources`) pinned in dopilot's own deps. See `docs/dopilot/05-dev-setup-and-known-issues.md` §4.1.
- **Startup wipes directories *[do NOT inherit]*:** scrapydweb's `vars.py` deletes `*.*` files in `parse/`, `deploy/`, `schedule/` at import time. This is a scrapydweb implementation quirk — dopilot must not reproduce destructive-on-import behavior. (dopilot's own data/persistence model: `docs/dopilot/08-docker-deployment.md` §3.)
- **Single-instance scheduler *[dopilot design constraint]*:** an in-process `BackgroundScheduler` has no distributed lock — multiple server replicas = duplicate timer firing. dopilot's server runs single-replica, **and uvicorn must run `workers=1`** (multiple workers cause the same duplicate firing, plus the in-process Redis stream consumers / dispatcher / SSE subscription tables break across processes). This is a hard constraint — dopilot does not support multi-replica/multi-worker and will not in the future. **Introducing Redis as the single-instance server↔agent communication bus is explicitly allowed**; what stays out of scope is using Redis (or NATS / PG LISTEN-NOTIFY) for **multi-replica HA / fan-out / a distributed lock** — server→web SSE fan-out is still done in single-process memory. See `docs/refactor/00-redis-streams-agent-communication.md`.
- **Config form *[do NOT inherit]*:** scrapydweb hardcodes config filename `scrapydweb_settings_v11.py` loaded from `os.getcwd()` (`vars.py:29`, `run.py:124`). dopilot does **not** inherit this — it uses its own loader with TOML files under `configs/` (e.g. via `DOPILOT_CONFIG`).
- **Base image must be glibc (slim/debian), not Alpine *[dopilot design constraint]*:** scrapydweb's subprocess parent-death signaling uses `libc.so.6` prctl (`sub_process.py:38`), which musl doesn't satisfy. If/when dopilot implements parent-death subprocess control (executors/agent), keep a glibc base.

## Running the scrapydweb reference (read-only behavior check)

Per `docs/dopilot/05-dev-setup-and-known-issues.md`. ⚠️ These commands exercise the **isolated scrapydweb reference only** — they do NOT run dopilot, and dopilot must not import the reference:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e reference/scrapydweb     # editable install of the scrapydweb REFERENCE (behavior check only)
pip install "setuptools<81"             # REQUIRED — see pitfall above, else import fails
scrapydweb                              # first run scaffolds scrapydweb_settings_v11.py in cwd, then configure SCRAPYD_SERVERS
```

dopilot's own build/test/lint pipeline doesn't exist yet — phase 0 **scaffolds the dopilot skeleton** (`apps/server`, `apps/agent`, `apps/web`, `packages/protocol` per the authoritative layout) and adds `deploy/docker/Dockerfile.server` / `Dockerfile.agent` / `.dockerignore` / CI per `08-docker-deployment.md`. dopilot writes **its own tests** from day one under `apps/server/tests/` and `apps/agent/tests/`. The scrapydweb tests at `reference/scrapydweb/tests/` are a **behavioral oracle for the reference baseline only — not dopilot's regression net** (`docs/dopilot/07-testing-baseline.md`); `09-package-rename.md` is now scrapydweb **behavioral porting notes**, not a rename plan.

## Git remotes

- `origin` → https://github.com/senjianlu/dopilot (this repo)
- `upstream` → https://github.com/my8100/scrapydweb.git (track upstream for diff/cherry-pick; do NOT merge its history)
