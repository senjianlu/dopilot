# Phase 2.2.1 Claude Progress

## Status

Implementation complete; verification commands pending interactive approval to
execute the local virtualenv Python (symlinked outside the sandbox workdir).

## Checklist

- [x] 1. Server env rename `DOPILOT_TOKEN_SECRET` → `DOPILOT_ADMIN_API_SECRET`
  (override table, fail-closed message, tests, docs); no alias.
- [x] 1. Server machine-token fallback (`agent_auth.shared_token`,
  `agents.server_shared_token`) after env overrides, before fail-closed.
- [x] 1. Explicit `DOPILOT_AGENT_SHARED_TOKEN` / `DOPILOT_SERVER_SHARED_TOKEN`
  still override the fallback.
- [x] 2. Agent env overrides for the two split tokens + `DOPILOT_ADMIN_API_SECRET`
  fallback (loader-only; no agent settings field).
- [x] 3. Role-specific baked default config paths (server.toml / agent.toml) via
  `default_path`; explicit path + `DOPILOT_CONFIG` still supported.
- [x] 3. Removed Dockerfile global `DOPILOT_CONFIG`.
- [x] 4. Removed `DOPILOT_CONFIG` from compose; injected `DOPILOT_ADMIN_API_SECRET`
  into server + all agents; `DOPILOT_ADMIN_PASSWORD` into server; kept optional
  split tokens commented; Redis password + no host port kept.
- [x] 4. Emptied baked machine-token fields in `server.docker.toml` /
  `agent.example.toml`.
- [x] 4. Compose header env guide + comments.
- [x] 5. Server + agent config tests added/updated.
- [x] 5. Docs (`08-docker-deployment.md`, config comments) updated.
- [ ] 5. Required verification commands executed (pending approval).

## Verification Commands (pending approval to run venv python)

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
```

## Blockers

- `.venv/bin/python` and `.venv/bin/ruff` resolve to binaries outside the
  sandbox working directory, so each execution requires interactive approval.
  Awaiting approval to run and record exact outcomes.
