# Acceptance

## Accepted State

Phase 2.2.2 is accepted.

Implemented behavior:

- `DOPILOT_ADMIN_API_TOKEN` is the externally supplied static admin API token.
  It can be used directly as `Authorization: Bearer <token>` for admin API
  requests when web auth is enabled.
- `DOPILOT_ADMIN_API_SECRET` has no compatibility path and no effect.
- `auth.token_secret` is TOML-only and remains the internal signing key for
  login-issued opaque access tokens and SSE stream tokens.
- Empty server/agent machine tokens now fall back to `auth.admin_api_token`, not
  `token_secret`.
- Non-empty `admin_api_token` shorter than 16 characters fails server config
  loading.
- Docker Compose injects `DOPILOT_ADMIN_API_TOKEN` into the server and all three
  agents, and still does not set `DOPILOT_CONFIG`.
- Docker/server example TOML no longer uses `token_secret = "change-me"`; it
  uses the generated long value requested by the user.
- Live docs and READMEs now distinguish:
  - static admin API token;
  - internal TOML-only signing secret;
  - optional split machine tokens.

## Verification

- Targeted pytest: 57 passed.
- Full pytest: 480 passed.
- Ruff: passed.
- Docker compose config: passed.
- Compose filtered check: four `DOPILOT_ADMIN_API_TOKEN` entries, no
  `DOPILOT_CONFIG`, no `DOPILOT_ADMIN_API_SECRET`.
- `git diff --check`: passed.

## Residual Risk

- The baked `token_secret` value is public because it is committed in this
  open-source repo. It is no longer the `change-me` placeholder, but it is not a
  per-deployment secret. This is accepted for the default path; high-security
  users should mount their own server TOML.
- In the default single-token posture, agents receive `DOPILOT_ADMIN_API_TOKEN`
  and therefore hold a token that can also authenticate admin API requests. This
  is documented; deployments that need stricter separation should configure
  `DOPILOT_AGENT_SHARED_TOKEN` and `DOPILOT_SERVER_SHARED_TOKEN`.
