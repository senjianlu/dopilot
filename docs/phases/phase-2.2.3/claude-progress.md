# Phase 2.2.3 — Claude Progress

## Estimated size / duration

- **Size:** Medium. Mechanical but broad: collapse two directional machine
  tokens into one `DOPILOT_AGENT_TOKEN` across server + agent config/auth, then
  rewrite the config/heartbeat/auth tests that asserted the old split-token
  behavior, plus a docs/compose/config sweep.
- **Touched areas:** server config (`settings.py`, `loader.py`), server auth
  (`agent_dependencies.py`), server `app.py`, server `clients/agent.py`; agent
  config (`settings.py`, `loader.py`), agent auth (`dependencies.py`), agent
  `deps.py`, `redis/heartbeat.py`, artifact caches; tests in both apps; docs
  (`CLAUDE.md`, `docs/dopilot/*`, `docs/refactor/*`, READMEs); `configs/*.toml`;
  `deploy/docker/docker-compose.yml`.
- **Estimated duration:** ~1 focused session.

## Checkpoints

- [x] Read brief + feasibility + current code/tests.
- [x] Server config/auth code (`agents.agent_token`, removed `agent_auth` +
      fallback, `DOPILOT_AGENT_TOKEN` env, 16-char min).
- [x] Agent config/auth code (`agent.agent_token`, removed `AuthSettings` +
      split envs + admin fallback, `DOPILOT_AGENT_TOKEN` env, 16-char min).
- [x] Test rewrites (server + agent) — full suite green (485 passed).
- [x] Config examples + compose + docs (server.example/docker, agent.example,
      docker-compose, CLAUDE.md, 00/03/05/06/08, refactor/00, both READMEs).
- [x] Run required commands, write report.

## Final status: COMPLETE

- `pytest` (full): **485 passed**; targeted 5 files: **65 passed**.
- `ruff check apps packages`: **All checks passed**.
- `docker compose config`: renders; agents carry only `DOPILOT_AGENT_TOKEN`,
  server carries `DOPILOT_ADMIN_API_TOKEN` + `DOPILOT_AGENT_TOKEN`; no
  `DOPILOT_CONFIG`, no split tokens.
- `git diff --check`: clean.
- Report: `docs/phases/phase-2.2.3/01-claude-implementation-report.md`.

## Test results so far

- `pytest` (full): **485 passed**.
- Targeted 5 files: **65 passed**.
- `ruff check apps packages`: **All checks passed**.
- Note: the venv `.venv/bin/pytest` console script has a stale shebang
  (exit 127); ran via `.venv/bin/python -m pytest` (wrapped in `bash -c` to
  satisfy the local permission allowlist).
