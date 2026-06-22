# Phase 2.2.1 Brief

## Goal

Simplify Docker deployment configuration after phase 2.2:

- use `DOPILOT_ADMIN_API_SECRET` as the single required API-secret env;
- allow machine tokens to default to that secret when omitted;
- keep Redis password auth enabled by default;
- make `deploy/docker/docker-compose.yml` the user-facing env guide;
- remove `DOPILOT_CONFIG` from compose so it is an internal image/default detail.

## Context

Relevant files and decisions:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2/00-brief.md`
- `docs/phases/phase-2.2/07-acceptance.md`
- `docs/phases/phase-2.2.1/00a-feasibility-review.md`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/app.py`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/agent/dopilot_agent/config/settings.py`
- `apps/agent/dopilot_agent/app.py` or the agent CLI entrypoint
- `configs/server.example.toml`
- `configs/server.docker.toml`
- `configs/agent.example.toml`
- `deploy/docker/Dockerfile`
- `deploy/docker/docker-compose.yml`
- relevant server/agent config tests

## In Scope

- Rename the server env override from `DOPILOT_TOKEN_SECRET` to
  `DOPILOT_ADMIN_API_SECRET`.
- Do **not** keep a backwards-compatible `DOPILOT_TOKEN_SECRET` alias.
- Keep the TOML field name `[auth].token_secret`; this is an env/deploy naming
  change only.
- Add server-side fallback:
  - if `[agent_auth].shared_token` / `DOPILOT_AGENT_SHARED_TOKEN` is empty, use
    the effective admin token secret;
  - if `[agents].server_shared_token` / `DOPILOT_SERVER_SHARED_TOKEN` is empty,
    use the effective admin token secret.
- Add agent-side fallback:
  - if `[auth].shared_token` / `DOPILOT_AGENT_SHARED_TOKEN` is empty, use
    `DOPILOT_ADMIN_API_SECRET`;
  - if `[agent].server_shared_token` / `DOPILOT_SERVER_SHARED_TOKEN` is empty,
    use `DOPILOT_ADMIN_API_SECRET`.
- Empty the baked machine-token fields in `configs/server.docker.toml` and
  `configs/agent.example.toml` so default compose actually exercises fallback.
- Give server and agent role-specific default config paths so compose no longer
  needs `DOPILOT_CONFIG`:
  - `dopilot-server` defaults to `/app/configs/server.toml` when no explicit
    path or `DOPILOT_CONFIG` is provided;
  - `dopilot-agent` defaults to `/app/configs/agent.toml` when no explicit path
    or `DOPILOT_CONFIG` is provided.
- Remove the global `ENV DOPILOT_CONFIG=/app/configs/server.toml` from
  `deploy/docker/Dockerfile`.
- Remove explicit `DOPILOT_CONFIG` entries from `deploy/docker/docker-compose.yml`.
- Keep `REDIS_PASSWORD` and Redis `--requirepass` in compose; do not expose Redis
  to the host.
- Put required/optional env comments directly in `docker-compose.yml`.
- Update docs/config comments/tests.

## Out Of Scope

- `.env.example`.
- `dopilot.toml`, `dopilot_sync.py`, labels/source ownership, reconciler.
- Renaming the TOML field `auth.token_secret`.
- Backwards compatibility for `DOPILOT_TOKEN_SECRET`.
- Removing Redis auth.
- RBAC, multi-user auth, token rotation, mTLS, HA, or external secret-manager
  integration.
- Fetching, vendoring, copying, or importing upstream scrapydweb code.

## Required Implementation Order

1. Server env rename and fallback:
   - Replace `DOPILOT_TOKEN_SECRET` with `DOPILOT_ADMIN_API_SECRET` in server
     loader override tables, error messages, comments, tests, and docs.
   - Apply machine-token fallback after env overrides and before/alongside
     fail-closed validation.
   - Ensure explicit `DOPILOT_AGENT_SHARED_TOKEN` /
     `DOPILOT_SERVER_SHARED_TOKEN` still override the fallback.

2. Agent env fallback:
   - Extend agent loader env overrides for `DOPILOT_AGENT_SHARED_TOKEN`,
     `DOPILOT_SERVER_SHARED_TOKEN`, and `DOPILOT_ADMIN_API_SECRET`.
   - Fallback only when the effective machine-token value is empty.
   - Keep `DOPILOT_ADMIN_API_SECRET` loader-only on the agent; do not add an
     agent settings field for it.

3. Role-specific config defaults:
   - Preserve explicit path and `DOPILOT_CONFIG` support for internal/testing
     use, but do not expose it in compose comments.
   - Add CLI/loader defaults so server and agent work without `DOPILOT_CONFIG`.
   - Remove Dockerfile global `DOPILOT_CONFIG`.

4. Compose and config defaults:
   - Remove `DOPILOT_CONFIG` from server and agent services.
   - Inject `DOPILOT_ADMIN_API_SECRET` into server and all agents.
   - Keep `DOPILOT_ADMIN_PASSWORD` and `REDIS_PASSWORD` user-facing.
   - Keep optional split token variables commented/explained in compose comments
     and supported through env:
     `DOPILOT_AGENT_SHARED_TOKEN`, `DOPILOT_SERVER_SHARED_TOKEN`.
   - Keep Redis password auth and no host port.

5. Tests and reports:
   - Add/update server config tests for renamed env and fallback behavior.
   - Add/update agent config tests for fallback and explicit split-token override.
   - Add/update compose/Dockerfile tests if such tests exist; otherwise verify
     with `docker compose config`.

## Acceptance Criteria

- `DOPILOT_ADMIN_API_SECRET` populates server `auth.token_secret`.
- `DOPILOT_TOKEN_SECRET` is no longer recognized or documented as an env var.
- With only `DOPILOT_ADMIN_API_SECRET` set, server and agent machine tokens
  resolve to that same value.
- With split machine token envs set, those explicit values are used instead of
  the admin API secret.
- Compose contains no explicit `DOPILOT_CONFIG` entries.
- Dockerfile no longer sets a global `DOPILOT_CONFIG` that would make agent read
  server TOML.
- `dopilot-server` and `dopilot-agent` still have correct baked default config
  paths.
- Redis password auth remains enabled by default and Redis is not published to
  host ports.
- Existing phase 2.2 auth fail-closed behavior still works.

## Required Tests

- Server config tests:
  - `DOPILOT_ADMIN_API_SECRET` env override;
  - no `DOPILOT_TOKEN_SECRET` alias;
  - fallback to admin secret for both machine-token settings;
  - split machine-token env overrides.
- Agent config tests:
  - no `DOPILOT_CONFIG` with default path handling where practical;
  - `DOPILOT_ADMIN_API_SECRET` fallback for both machine-token settings;
  - split machine-token env overrides.
- Deployment checks:
  - `cd deploy/docker && docker compose config`
  - verify rendered compose has no `DOPILOT_CONFIG` service env.

## Required Commands

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
```

Run web tests/build only if web-facing docs/types/code are touched.

## Risks To Watch

- Removing compose `DOPILOT_CONFIG` before role defaults would silently
  misconfigure agents.
- Non-empty baked `change-me-*` machine tokens would prevent fallback from
  engaging.
- If `DOPILOT_ADMIN_API_SECRET` is only set in server TOML and not as env, agent
  cannot derive it. Compose should inject the env into both server and agents.
- The env rename is intentionally breaking; tests must ensure the old env is not
  accepted.
