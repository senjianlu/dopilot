# Phase 2.2.2 Brief — Static Admin API Token

## Goal

Correct the phase 2.2.1 token naming model:

- `token_secret` is an internal TOML-only signing key for login access tokens and
  SSE stream tokens.
- `admin_api_token` is the externally supplied static admin API token that can
  be used directly as `Authorization: Bearer <token>`.
- Server-agent machine token fallback uses `admin_api_token`, not
  `token_secret`.

This phase intentionally has no DB migration.

## Confirmed Product Decisions

- Remove `DOPILOT_ADMIN_API_SECRET`; do not keep a compatibility alias.
- Do not add a replacement env override for `auth.token_secret`.
- Add `DOPILOT_ADMIN_API_TOKEN` for `auth.admin_api_token`.
- Keep web admin auth fail-closed exactly as before:
  `admin_username + admin_password + token_secret` are required unless
  `DOPILOT_AUTH_DISABLED=true`.
- `admin_api_token` is an additional automation credential and does not
  participate in `AuthSettings.enabled`.
- Non-empty `admin_api_token` shorter than 16 characters fails config loading.
- Agent loader may use `DOPILOT_ADMIN_API_TOKEN` as loader-only machine-token
  fallback but should not add an agent settings field for it.
- Replace Docker's baked `token_secret = "change-me"` with:
  `shLv5qNwC3aViZQYr08x3yfaY6yGZACB6ujydXiVaGnb7OdOflc91xVLyXBoeRDL`.

## In Scope

### Server auth/config

- Add `admin_api_token: str | None = None` to `AuthSettings`.
- Add `DOPILOT_ADMIN_API_TOKEN -> auth.admin_api_token` env override.
- Remove `DOPILOT_ADMIN_API_SECRET -> auth.token_secret` env override.
- Update `_apply_machine_token_fallback()` to derive empty
  `[agent_auth].shared_token` and `[agents].server_shared_token` from
  `settings.auth.admin_api_token`.
- Add loader-level validation:
  - empty `admin_api_token` is allowed;
  - non-empty `admin_api_token.strip()` length `< 16` raises `ConfigError`.
- Update fail-closed error text to mention TOML-only `token_secret` and remove
  `DOPILOT_ADMIN_API_SECRET`.
- Update `get_current_admin()` so a non-empty static `admin_api_token` matching
  the Bearer token authenticates as admin with `expires_at=None`.
  - Use constant-time comparison.
  - Guard both sides as non-empty before compare.
  - Keep static-token acceptance inside the existing `settings.auth.enabled`
    branch so it does not bypass fail-closed auth.

### Agent config

- Replace the loader-only fallback source from `DOPILOT_ADMIN_API_SECRET` to
  `DOPILOT_ADMIN_API_TOKEN`.
- Preserve explicit `DOPILOT_AGENT_SHARED_TOKEN` /
  `DOPILOT_SERVER_SHARED_TOKEN` precedence over fallback.
- Do not add `admin_api_token` to agent settings.

### Config, deploy, docs

- Update:
  - `configs/server.example.toml`
  - `configs/server.docker.toml`
  - `configs/agent.example.toml`
  - `deploy/docker/docker-compose.yml`
  - `README.md`
  - `README.zh-CN.md`
  - `docs/dopilot/08-docker-deployment.md`
- Use `DOPILOT_ADMIN_API_TOKEN` everywhere live docs/config refer to the
  externally supplied single API/machine token.
- Do not reintroduce `DOPILOT_CONFIG` into compose.
- Historical phase records under `docs/phases/phase-2.2/` and
  `docs/phases/phase-2.2.1/` should not be rewritten.

## Out Of Scope

- RBAC, multi-admin, token scopes, token rotation, or DB persistence for static
  admin tokens.
- Adding CI/deploy sync behavior for non-existent `scripts/dopilot_sync.py`.
- Compatibility with `DOPILOT_ADMIN_API_SECRET`.
- Docker long-running crawler work or deploy manifest/reconciler work.

## Expected Tests

- `apps/server/tests/test_config.py`
  - `DOPILOT_ADMIN_API_TOKEN` populates `auth.admin_api_token`.
  - `DOPILOT_ADMIN_API_SECRET` no longer populates `token_secret`.
  - machine-token fallback derives from `admin_api_token`.
  - split machine-token envs override fallback.
  - no `admin_api_token` means no machine fallback.
  - short non-empty `admin_api_token` raises `ConfigError`; empty is allowed.
- `apps/server/tests/test_auth.py`
  - static admin token authenticates protected admin endpoints.
  - wrong static token returns 401.
  - empty configured token and empty/missing bearer do not match.
  - normal login-issued opaque token behavior remains unchanged.
- `apps/agent/tests/test_config.py`
  - `DOPILOT_ADMIN_API_TOKEN` fallback fills both machine tokens when TOML/env
    split tokens are empty.
  - explicit split tokens win over fallback.
  - old `DOPILOT_ADMIN_API_SECRET` is ignored.

## Required Verification

Run the narrow tests first, then broaden as needed:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/agent/tests/test_config.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
git diff --check
```

If Claude cannot run a command due its permission layer, it must report the
exact command and failure; Codex will run it.

## Acceptance Criteria

- Admin API calls can use `Authorization: Bearer <DOPILOT_ADMIN_API_TOKEN>`
  directly.
- Login-issued opaque access tokens and stream tokens still use `token_secret`.
- `DOPILOT_ADMIN_API_SECRET` has no effect.
- Default compose injects `DOPILOT_ADMIN_API_TOKEN` into server and all agents.
- Compose config contains no `DOPILOT_CONFIG`.
- Tests cover new static-token auth and machine fallback behavior.
