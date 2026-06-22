# Phase 2.2.4 — Claude Progress

## Initial estimate

Bounded, low-risk implementation. Plan:

1. `ServerSettings.data_dir` (default `/server-data`) + `DOPILOT_SERVER_DATA_DIR`
   string env override. `load_settings()` stays side-effect-free.
2. New `apps/server/dopilot_server/agent_token.py` helper: resolve the single
   `DOPILOT_AGENT_TOKEN` — configured wins (no file touch), else read/generate
   `<data_dir>/secrets/agent-token` (atomic write, `0600`). Returns token +
   source metadata.
3. `create_app(settings)` injects the provided settings into the
   `get_settings` dependency path (the feasibility blocker); `run()` resolves
   the token, mutates `settings.agents.agent_token`, logs a join hint when the
   token came from the persisted file; new `dopilot-server agent-token print
   [--quiet]` CLI (no DB/Redis/ASGI).
4. `deploy/docker/docker-compose.server.yml` (server-only, token optional) and
   `deploy/docker/docker-compose.agent.yml` (agent-only join, token required).
5. Docs + example TOML + tests.

Risk: the get_settings injection must not break the existing conftest override
(conftest sets its own override after `create_app`, so it still wins).

## Status

- [x] settings + loader (`ServerSettings.data_dir`, `DOPILOT_SERVER_DATA_DIR`)
- [x] agent_token helper (`apps/server/dopilot_server/agent_token.py`)
- [x] app wiring + CLI (`create_app` get_settings injection, `run()` token
      resolution + join-hint log, `dopilot-server agent-token print [--quiet]`)
- [x] compose files (`docker-compose.server.yml`, `docker-compose.agent.yml`)
- [x] docs (CLAUDE.md, 00-requirements.md, 08-docker-deployment.md, READMEs,
      example/docker TOML)
- [x] tests (`test_agent_token.py`, `test_config.py` additions)
- [x] verification — all green (see 01-claude-implementation-report.md)

## Verification outcomes

- targeted pytest (test_config + test_agent_token + test_heartbeat_api): 55 passed
- full pytest: 502 passed
- `ruff check apps packages`: All checks passed
- `docker compose config` for all 3 compose files: render OK; agent-only has no
  `DOPILOT_ADMIN_API_TOKEN`; token + redis truly required (errors when unset)
- `git diff --check`: clean (exit 0)
- manual CLI smoke: generate → 0600 file → quiet → reuse all confirmed
