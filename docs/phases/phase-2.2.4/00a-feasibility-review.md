# Phase 2.2.4 — Feasibility Review

## Claude Verdict

Feasible, with one implementation blocker to handle explicitly:

- generated agent tokens must reach every runtime settings consumer, not only
  the `run()` local settings object.

If generation mutates only the object passed into `create_app(settings)`,
`AgentClient` may use the generated token while FastAPI dependencies that call
`get_settings()` still read the cached loader settings with no token. That would
leave heartbeat auth off while egg-deploy auth is on.

## Codex Decisions

- Token generation belongs at the server runtime/CLI boundary, not inside
  `load_settings()`.
- Add a narrow `server.data_dir` setting, default `/server-data`, with
  `DOPILOT_SERVER_DATA_DIR` env override. Do not refactor logs/artifacts roots.
- Persist the generated token at:

  ```text
  <server.data_dir>/secrets/agent-token
  ```

- Persist with owner-only file permissions where supported (`0600`) and use an
  atomic temp-file + replace write.
- Generated token format: `secrets.token_urlsafe(32)` or stronger; generated
  tokens are known to satisfy the 16-character minimum.
- Runtime behavior:
  - if `[agents].agent_token` / `DOPILOT_AGENT_TOKEN` is non-empty, use it and do
    not touch the persisted generated-token file;
  - if no token is configured, read-or-generate the persisted token, set
    `settings.agents.agent_token`, and run with machine auth on.
- Update the documented semantics from strict config-present-or-off to:
  machine auth is on when `agent_token` is configured or server auto-generation
  supplies a persisted token at the runtime boundary.
- `create_app(settings)` must inject the provided settings into the FastAPI
  dependency path so `Depends(get_settings)` sees the same mutated settings.
- `dopilot-server agent-token print`:
  - loads server settings with the same default config path as `run()`;
  - does not require DB, Redis, ASGI app startup, or uvicorn;
  - reads or generates the persisted token;
  - supports `--quiet` to print only the token;
  - default output is operator-friendly and includes
    `DOPILOT_AGENT_TOKEN=<token>`.
- Keep all-in-one `deploy/docker/docker-compose.yml` explicit with
  `${DOPILOT_AGENT_TOKEN:-change-me-agent-token}` because server and agents start
  together.
- Add two compose files:
  - `deploy/docker/docker-compose.server.yml`: server + Redis + PostgreSQL +
    migrate, no agent services, no required `DOPILOT_AGENT_TOKEN`;
  - `deploy/docker/docker-compose.agent.yml`: agent-only join file, with
    `DOPILOT_AGENT_TOKEN` required from env and no dev default.

## User Escalation

No additional user question is required. The user confirmed the proposed
direction and explicitly asked to also add separate server-only and agent-only
deployment configs.

## Scope Cuts

- No token rotation.
- No multi-token enrollment.
- No database-backed token table.
- No compatibility with old split token env vars.
- No TLS/VPN implementation.
- No agent-side token generation.

## Suggested Files

- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/app.py`
- new server token helper module, e.g.
  `apps/server/dopilot_server/agent_token.py`
- server tests for token persistence/CLI/runtime injection
- `deploy/docker/docker-compose.yml`
- `deploy/docker/docker-compose.server.yml`
- `deploy/docker/docker-compose.agent.yml`
- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/08-docker-deployment.md`
- README files if deployment commands are shown there

## Suggested Verification

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_agent_token.py apps/server/tests/test_heartbeat_api.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose -f docker-compose.yml config
cd deploy/docker && docker compose -f docker-compose.server.yml config
cd deploy/docker && DOPILOT_AGENT_TOKEN=example-agent-token-123456 REDIS_PASSWORD=example-redis-pass docker compose -f docker-compose.agent.yml config
git diff --check
```
