# Phase 2.2.4 Brief — Generated Agent Token And Split Docker Compose

## Goal

Keep the phase 2.2.3 two-token model, but reduce deployment friction for
server-first deployments:

- `DOPILOT_ADMIN_API_TOKEN`: admin API only, server-side only.
- `DOPILOT_AGENT_TOKEN`: the only server-agent machine token.
- Server can generate and persist `DOPILOT_AGENT_TOKEN` when none is configured.
- Operators can retrieve the generated token with `docker exec`.
- Docker deployment offers:
  - all-in-one stack;
  - server-only stack;
  - agent-only join stack.

## Confirmed Product Decisions

- Do not reintroduce `DOPILOT_AGENT_SHARED_TOKEN` or
  `DOPILOT_SERVER_SHARED_TOKEN`.
- Do not derive machine auth from `DOPILOT_ADMIN_API_TOKEN`.
- Agent token generation is server-only.
- Generated token is persisted in the server data volume and reused on restart.
- A generated token makes machine auth ON at server runtime.
- All-in-one compose still uses explicit shared env with a dev default because
  server and agents start together.
- Server-only compose may omit `DOPILOT_AGENT_TOKEN` and rely on generation.
- Agent-only compose requires operator-supplied `DOPILOT_AGENT_TOKEN`.
- Out-of-scope: rotation, expiring enrollment tokens, multi-token support,
  DB-backed token storage, TLS/VPN, old split-token compatibility.

## In Scope

### Server Settings

- Add `server.data_dir`, default `/server-data`.
- Add env override:

  ```text
  DOPILOT_SERVER_DATA_DIR -> [server].data_dir
  ```

- Do not use `logs.root_dir` or `artifacts.root_dir` as the token persistence
  anchor.
- Keep `load_settings()` pure with respect to token generation:
  - it may load and validate configured tokens;
  - it must not create files;
  - it must not auto-generate tokens.

### Token Persistence

- Add a focused helper module, for example:

  ```text
  apps/server/dopilot_server/agent_token.py
  ```

- Persist generated tokens at:

  ```text
  <settings.server.data_dir>/secrets/agent-token
  ```

- Behavior:
  - configured token present: return/use configured token and do not read/write
    generated-token file;
  - configured token absent: read existing persisted generated token;
  - if absent on disk: generate `secrets.token_urlsafe(32)` or stronger, create
    parent directory, write atomically, and set file mode `0600` where supported;
  - return enough metadata for logging/CLI to know whether the token was
    configured, read from disk, or newly generated.

### Server Runtime And CLI

- `dopilot-server -b ... -p ...` must keep working as the normal run command.
- Before starting uvicorn, runtime must call the token helper and mutate
  `settings.agents.agent_token` when generation/read-from-disk is needed.
- `create_app(settings)` must ensure FastAPI dependencies that use
  `Depends(get_settings)` receive the provided settings object. This prevents
  generated-token mismatch between `AgentClient` and heartbeat auth.
- Log a concise join hint once per server startup only when the active token came
  from the persisted generated-token path. Do not log the admin API token.
- Add CLI:

  ```bash
  dopilot-server agent-token print
  dopilot-server agent-token print --quiet
  ```

- CLI behavior:
  - loads settings using the same default config path as `run()`;
  - does not require DB/Redis/ASGI startup;
  - reads or generates the persisted agent token if no token is configured;
  - default output includes at least `DOPILOT_AGENT_TOKEN=<token>` and a short
    operator hint;
  - `--quiet` outputs only the token.

### Docker Compose

- Keep `deploy/docker/docker-compose.yml` all-in-one and explicit:
  - server and all agents get the same `${DOPILOT_AGENT_TOKEN:-change-me-agent-token}`;
  - no `DOPILOT_CONFIG`;
  - no old split env vars.
- Add `deploy/docker/docker-compose.server.yml`:
  - services: `db`, `redis`, `migrate`, `server`;
  - no agent services;
  - server data volume mounted at `/server-data`;
  - `DOPILOT_AGENT_TOKEN` optional and omitted by default so generation can work;
  - include comments showing how to retrieve the token with
    `docker exec <server-container> dopilot-server agent-token print`.
- Add `deploy/docker/docker-compose.agent.yml`:
  - agent-only join deployment;
  - supports at least one agent service with stable `AGENT_ID`;
  - requires `DOPILOT_AGENT_TOKEN` from env with no dev fallback;
  - requires `DOPILOT_REDIS_URL` or enough env to build the Redis URL for the
    target deployment;
  - no `DOPILOT_ADMIN_API_TOKEN`;
  - no `DOPILOT_CONFIG`;
  - no old split env vars.

### Docs

Update live source-of-truth docs:

- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/08-docker-deployment.md`
- README files if deployment quick-start mentions token setup.

Docs must explain:

- all-in-one stack uses explicit env because services start together;
- server-only stack can generate and persist the agent token;
- retrieve token with `docker exec <server> dopilot-server agent-token print`;
- agent-only stack must be given `DOPILOT_AGENT_TOKEN`;
- token auth is not transport encryption.

## Out Of Scope

- Rotation or revocation.
- Multiple valid machine tokens.
- Expiring enrollment tokens.
- Database table for agent tokens.
- Agent-side generated tokens.
- TLS/VPN/private-network setup.
- Compatibility for `DOPILOT_AGENT_SHARED_TOKEN` /
  `DOPILOT_SERVER_SHARED_TOKEN`.
- Historical phase-record rewrites outside this phase.
- Untracked `tmux.sh`.

## Expected Tests

### Server Config

- `DOPILOT_SERVER_DATA_DIR` overrides `[server].data_dir`.
- `load_settings()` does not create a generated token file.
- Existing short-token validation still applies to configured tokens.

### Agent Token Helper / Runtime

- missing configured token generates a token at
  `<data_dir>/secrets/agent-token`;
- generated token is at least 16 characters;
- second call reuses the persisted token;
- configured token takes precedence and does not read/write the generated file;
- generated token is applied to `settings.agents.agent_token`;
- generated-token runtime makes `settings.agents.machine_auth_enabled` true;
- `create_app(settings)` exposes the mutated settings through `get_settings`
  dependencies, so heartbeat auth enforces the generated token.

### CLI

- `dopilot-server agent-token print --quiet` prints only the token;
- default `agent-token print` includes `DOPILOT_AGENT_TOKEN=<token>`;
- CLI works without DB/Redis/lifespan.

### Compose

- all-in-one compose renders with server + agents sharing `DOPILOT_AGENT_TOKEN`;
- server-only compose renders without requiring `DOPILOT_AGENT_TOKEN`;
- agent-only compose renders when `DOPILOT_AGENT_TOKEN` is supplied;
- rendered agent-only compose contains no `DOPILOT_ADMIN_API_TOKEN`;
- no compose file contains old split token env vars or `DOPILOT_CONFIG`.

## Required Verification

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_agent_token.py apps/server/tests/test_heartbeat_api.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose -f docker-compose.yml config
cd deploy/docker && docker compose -f docker-compose.server.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```

If a command cannot run in Claude's permission environment, Claude must report
the exact command and failure; Codex will run it.

## Acceptance Criteria

- Server runtime can generate, persist, reuse, and expose the single
  `DOPILOT_AGENT_TOKEN`.
- Generated token is visible to both outbound server→agent client wiring and
  inbound agent→server heartbeat auth.
- `load_settings()` remains side-effect-free.
- `dopilot-server agent-token print` works without DB/Redis and can be used via
  `docker exec`.
- All-in-one, server-only, and agent-only compose files render.
- Agent-only compose never receives `DOPILOT_ADMIN_API_TOKEN`.
- Old split env vars remain unsupported.
- Tests and docs reflect the generated-token deployment flow.
