# Codex Test Review

## Result

- Accepted.

## Coverage Assessment

- Server config tests cover:
  - `DOPILOT_ADMIN_API_TOKEN` env override;
  - removed `DOPILOT_ADMIN_API_SECRET` no-op behavior;
  - TOML-only `token_secret`;
  - admin API token length validation;
  - machine-token fallback from `admin_api_token`;
  - split machine token precedence.
- Server auth tests cover:
  - static admin token direct Bearer auth;
  - wrong-token 401;
  - empty-token guard;
  - existing opaque login token path still works.
- Agent config tests cover:
  - `DOPILOT_ADMIN_API_TOKEN` fallback;
  - split token precedence;
  - old `DOPILOT_ADMIN_API_SECRET` ignored.
- Full pytest and ruff passed after Codex documentation corrections.
- Compose config confirms server + three agents receive
  `DOPILOT_ADMIN_API_TOKEN`, and compose still does not set `DOPILOT_CONFIG`.

## Residual Risk

- The baked `token_secret` is public because it is committed to the repo/image.
  This is accepted by user decision for the default path; high-security
  deployments must mount their own server TOML.
