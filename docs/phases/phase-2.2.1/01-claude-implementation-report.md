# Phase 2.2.1 Claude Implementation Report

## Summary

Simplified Docker deployment configuration after phase 2.2:

- Renamed the server admin-token-secret env from `DOPILOT_TOKEN_SECRET` to
  `DOPILOT_ADMIN_API_SECRET` with **no** backwards-compatible alias.
- Added a single-secret machine-token fallback on both server and agent: when a
  machine token is empty after env overrides, it defaults to the effective admin
  API secret. Explicit split tokens still win.
- Gave server and agent role-specific baked default config paths so the unified
  image runs without `DOPILOT_CONFIG`; removed the global Dockerfile
  `DOPILOT_CONFIG` and all `DOPILOT_CONFIG` entries from compose.
- Made `deploy/docker/docker-compose.yml` the user-facing env guide.
- Kept Redis password auth on and Redis unpublished to the host.

The TOML field `[auth].token_secret` is unchanged (env/deploy naming change
only). No `.env.example`, `dopilot.toml`, `dopilot_sync.py`, labels/source
fields, or reconciler were added. No upstream scrapydweb code was fetched,
vendored, copied, or imported.

## Changed Files

### Server

- `apps/server/dopilot_server/config/loader.py`
  - `_STR_OVERRIDES`: `DOPILOT_TOKEN_SECRET` → `DOPILOT_ADMIN_API_SECRET`
    (still maps to `auth.token_secret`).
  - New `_apply_machine_token_fallback(settings)`: runs after env overrides,
    before fail-closed validation; when `auth.token_secret` is non-empty, fills
    empty `agent_auth.shared_token` and `agents.server_shared_token` from it.
  - Fail-closed error message now names `DOPILOT_ADMIN_API_SECRET`.
  - New module constant `DEFAULT_CONFIG_PATH = "/app/configs/server.toml"`.
  - `load_settings(path=None, *, default_path=None)`: path resolution is now
    `path > DOPILOT_CONFIG > default_path`; behavior with neither set is
    unchanged (raises `ConfigError`).
- `apps/server/dopilot_server/app.py`
  - `run()` calls `load_settings(default_path=DEFAULT_CONFIG_PATH)`.

### Agent

- `apps/agent/dopilot_agent/config/loader.py`
  - New module constant `DEFAULT_CONFIG_PATH = "/app/configs/agent.toml"`.
  - `load_settings(path=None, *, default_path=None)`: path resolution
    `path > DOPILOT_CONFIG > default_path`.
  - New env overrides: `DOPILOT_AGENT_SHARED_TOKEN` → `[auth].shared_token`,
    `DOPILOT_SERVER_SHARED_TOKEN` → `[agent].server_shared_token`.
  - Single-secret fallback: empty machine tokens default to
    `DOPILOT_ADMIN_API_SECRET` (read directly from env; loader-only — no agent
    settings field for the admin secret). Explicit values (TOML or split env)
    win.
- `apps/agent/dopilot_agent/main.py`
  - `main()` calls `load_settings(default_path=DEFAULT_CONFIG_PATH)`.

### Config

- `configs/server.docker.toml` (baked server config): emptied
  `[agent_auth].shared_token` and `[agents].server_shared_token` so default
  compose exercises the fallback; updated header to reference
  `DOPILOT_ADMIN_API_SECRET` and the single-secret posture.
- `configs/agent.example.toml` (baked agent config): emptied
  `[auth].shared_token` and `[agent].server_shared_token`; updated comments.
- `configs/server.example.toml`: header comment references
  `DOPILOT_ADMIN_API_SECRET`; documents the single-secret machine-token posture.

### Deploy

- `deploy/docker/Dockerfile`: removed global
  `ENV DOPILOT_CONFIG=/app/configs/server.toml`; clarified that the role default
  config path is baked into each entrypoint. Baked config copies unchanged.
- `deploy/docker/docker-compose.yml`:
  - Removed all `DOPILOT_CONFIG` service env entries (server + 3 agents).
  - Injected `DOPILOT_ADMIN_API_SECRET` into server and all three agents;
    injected `DOPILOT_ADMIN_PASSWORD` into server.
  - Added a header env guide (required: `DOPILOT_ADMIN_PASSWORD`,
    `DOPILOT_ADMIN_API_SECRET`, `REDIS_PASSWORD`; optional split tokens
    `DOPILOT_AGENT_SHARED_TOKEN`, `DOPILOT_SERVER_SHARED_TOKEN`).
  - Kept optional split-token vars commented in server + agent services.
  - Redis `--requirepass` and no host port unchanged.

### Docs

- `docs/dopilot/08-docker-deployment.md`: updated the embedded compose example
  (removed `DOPILOT_CONFIG`, added `DOPILOT_ADMIN_API_SECRET` /
  `DOPILOT_ADMIN_PASSWORD`), the config TOML excerpt (emptied machine tokens +
  env rename), and the §2.6 deployment checklist.

### Tests

- `apps/server/tests/test_config.py`:
  - Renamed `DOPILOT_TOKEN_SECRET` → `DOPILOT_ADMIN_API_SECRET` in existing
    env-override tests.
  - Added: old `DOPILOT_TOKEN_SECRET` env is not an alias (fail-closed message
    names only the new env); machine-token fallback to admin secret; split-token
    envs override fallback; non-empty TOML token not overwritten; no fallback
    when secret empty; `default_path` resolution and precedence
    (`DOPILOT_CONFIG` and explicit path both win over `default_path`).
- `apps/agent/tests/test_config.py`:
  - Added: machine-token fallback to admin secret; split-token envs override
    fallback; split env over non-empty TOML; non-empty TOML not overwritten by
    admin secret; no fallback when admin secret absent; `default_path`
    resolution and `DOPILOT_CONFIG` precedence over it.

## Implementation Notes

- **Fallback ordering.** Both loaders apply env overrides first, then the
  admin-secret fallback, then (server only) fail-closed validation. This keeps
  explicit `DOPILOT_AGENT_SHARED_TOKEN` / `DOPILOT_SERVER_SHARED_TOKEN` (and
  non-empty TOML values) authoritative; the fallback only fills genuinely-empty
  tokens.
- **Server fallback engages only when `token_secret` is non-empty.** In
  anonymous dev mode (`auth.disabled=true`, no secret) there is nothing to
  derive from, so machine tokens stay empty (machine auth stays off — unchanged
  "config-present-or-off" semantics).
- **Agent admin-secret is loader-only.** `DOPILOT_ADMIN_API_SECRET` is read
  directly from the environment in the agent loader; no agent settings field was
  added (per brief). The agent has no admin-auth concept otherwise.
- **`default_path` vs. `DOPILOT_CONFIG`.** The CLI entrypoints pass the baked
  role default as `default_path`; `DOPILOT_CONFIG` still takes precedence, so
  internal/testing overrides keep working. `load_settings()` with neither still
  raises, so existing strict-loader tests and the cached dependency path are
  unchanged.
- **Why empty baked tokens.** Non-empty `change-me-*` machine tokens would
  prevent the fallback from engaging, so the baked `server.docker.toml` and
  `agent.example.toml` machine-token fields are now empty strings.

## Commands Run

> The local `.venv/bin/python` is a symlink to `/usr/bin/python3.12` (outside
> the sandbox working directory), so `-m pytest` execution requires interactive
> approval. Outcomes are recorded below once run.

```text
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/agent/tests/test_config.py
  -> BLOCKED: venv python execution needs approval (to be filled)

PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
  -> BLOCKED: venv python execution needs approval (to be filled)

.venv/bin/ruff check apps packages
  -> BLOCKED: venv ruff execution needs approval (to be filled)

cd deploy/docker && docker compose config
  -> PASS (exit 0). Rendered compose has zero DOPILOT_CONFIG entries; server +
     all three agents carry DOPILOT_ADMIN_API_SECRET, server carries
     DOPILOT_ADMIN_PASSWORD.
```

## Known Risks

- The env rename is intentionally breaking: any deployment still setting
  `DOPILOT_TOKEN_SECRET` will silently lose its admin token secret and (if no
  TOML/`DOPILOT_ADMIN_API_SECRET`) fail-closed at startup. This is by design;
  tests assert the old env is not honored.
- The single-secret posture depends on `DOPILOT_ADMIN_API_SECRET` being injected
  into BOTH server and every agent (compose does this). If an operator sets the
  secret only in server TOML and not as an env var, agents cannot derive it and
  machine auth will mismatch.
- Compose still ships dev-only `:-change-me` defaults for the new envs so a clean
  `docker compose up` works out of the box; these remain not production-safe.
