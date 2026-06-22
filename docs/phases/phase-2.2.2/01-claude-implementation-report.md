# Phase 2.2.2 — Claude Implementation Report

## Summary

Corrected the phase 2.2.1 token-naming model:

- `token_secret` is now a strict **TOML-only** internal HMAC signing key for
  login access tokens and SSE stream tokens. It has **no** env override and is
  **no longer** the machine-token fallback source.
- `admin_api_token` (env `DOPILOT_ADMIN_API_TOKEN`) is the externally supplied
  **static admin API token**: it can be presented directly as
  `Authorization: Bearer <token>` to authenticate as admin, and it is the
  fallback source for empty server↔agent machine tokens.
- `DOPILOT_ADMIN_API_SECRET` is removed entirely (no compatibility alias) and
  has no effect anywhere.

No DB migration (none required).

## Behavior implemented

### Server config (`apps/server/dopilot_server/config/settings.py`)

- Added `admin_api_token: str | None = None` to `AuthSettings`.
- `AuthSettings.enabled` is unchanged: `admin_api_token` does **not** participate
  (web login still requires `admin_username + admin_password + token_secret`).
- Documented `token_secret` as TOML-only and `admin_api_token` as the static
  token + machine-token fallback source.

### Server config loader (`apps/server/dopilot_server/config/loader.py`)

- `_STR_OVERRIDES`: removed `DOPILOT_ADMIN_API_SECRET -> auth.token_secret`;
  added `DOPILOT_ADMIN_API_TOKEN -> auth.admin_api_token`. `token_secret` now
  has no env override at all.
- `_apply_machine_token_fallback()` now derives empty `[agent_auth].shared_token`
  and `[agents].server_shared_token` from `settings.auth.admin_api_token`
  (previously `token_secret`). Explicit split-token env/TOML values still win;
  no `admin_api_token` => no fallback (machine auth is config-present-or-off, so
  it falls back to OFF).
- New `_validate_admin_api_token()`: a non-empty `admin_api_token.strip()` of
  length `< 16` raises `ConfigError`; empty/unset is allowed. It runs in
  `load_settings()` (after env overrides, before fallback), not in `Settings`
  construction, so test/dependency overrides can still build short-token
  `Settings` directly.
- Fail-closed error text updated: it no longer names `DOPILOT_ADMIN_API_SECRET`
  and states `token_secret` is the TOML-only signing key.

### Server auth dependency (`apps/server/dopilot_server/auth/dependencies.py`)

- `get_current_admin()` now accepts a static admin token: inside the existing
  `settings.auth.enabled` branch, if the configured `admin_api_token` (stripped)
  is non-empty **and** the Bearer token is non-empty **and**
  `hmac.compare_digest(token, api_token)` matches, it returns an authenticated
  admin context with `expires_at=None`.
  - Constant-time comparison via `hmac.compare_digest`.
  - Both sides guarded non-empty (blocks the `compare_digest("", "") == True`
    empty-match hole).
  - Stays inside the `enabled` branch, so it never bypasses fail-closed auth.
  - The DB opaque-token path is unchanged and still runs when the static token
    does not match.

### Agent config loader (`apps/agent/dopilot_agent/config/loader.py`)

- Loader-only machine-token fallback source changed from
  `DOPILOT_ADMIN_API_SECRET` to `DOPILOT_ADMIN_API_TOKEN`. Explicit
  `DOPILOT_AGENT_SHARED_TOKEN` / `DOPILOT_SERVER_SHARED_TOKEN` (and non-empty
  TOML) still take precedence. No agent settings field was added for the token.
  The old `DOPILOT_ADMIN_API_SECRET` is ignored.

### Config / deploy / docs

- `configs/server.example.toml`: documented token_secret (TOML-only) vs
  admin_api_token; added `admin_api_token` field; noted >=16 length and machine
  fallback behavior.
- `configs/server.docker.toml`: replaced `token_secret = "change-me"` with the
  generated value
  `shLv5qNwC3aViZQYr08x3yfaY6yGZACB6ujydXiVaGnb7OdOflc91xVLyXBoeRDL`; added empty
  `admin_api_token = ""` (compose injects it); documented that the baked
  token_secret is a shipped open-source value, not a per-deployment secret, and
  high-security deployments override it via a mounted TOML.
- `configs/agent.example.toml`: fallback source wording updated to
  `DOPILOT_ADMIN_API_TOKEN`.
- `deploy/docker/docker-compose.yml`: replaced `DOPILOT_ADMIN_API_SECRET` with
  `DOPILOT_ADMIN_API_TOKEN` for the server and all three agents (dev default
  `change-me-admin-api-token`, 25 chars, so the >=16 guard does not break a
  default `up`); updated header docs; still sets **no** `DOPILOT_CONFIG`.
- `README.md` / `README.zh-CN.md`: `.env` example uses
  `DOPILOT_ADMIN_API_TOKEN`; added a direct-Bearer static-token example; clarified
  token_secret is a separate TOML-only baked signing key.
- `docs/dopilot/08-docker-deployment.md`: compose snippet env keys, the TOML
  example (`token_secret` generated value + `admin_api_token`), the parameter
  table rows, and the inline machine-token comments all updated.

## Changed files

- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/auth/dependencies.py`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/server/tests/test_config.py`
- `apps/server/tests/test_auth.py`
- `apps/agent/tests/test_config.py`
- `configs/server.example.toml`
- `configs/server.docker.toml`
- `configs/agent.example.toml`
- `deploy/docker/docker-compose.yml`
- `README.md`
- `README.zh-CN.md`
- `docs/dopilot/08-docker-deployment.md`
- `docs/phases/phase-2.2.2/claude-progress.md` (new)
- `docs/phases/phase-2.2.2/01-claude-implementation-report.md` (new)

(Untracked `tmux.sh` was not touched. Historical `docs/phases/phase-2.2/` and
`docs/phases/phase-2.2.1/` records were not modified.)

## Tests added / updated

### `apps/server/tests/test_config.py`

- `test_auth_settings_enabled_variants`: added assertions that `admin_api_token`
  alone does not enable web auth and that it composes with the three creds.
- `test_env_overrides_scalars`: switched to `DOPILOT_ADMIN_API_TOKEN`; asserts
  `token_secret` stays the TOML value (no env override).
- New `test_admin_api_secret_env_has_no_effect`: `DOPILOT_ADMIN_API_SECRET` does
  not populate `token_secret` or `admin_api_token`.
- Renamed/rewrote `test_env_fills_missing_username_password_to_pass_fail_closed`
  (token_secret from TOML, username/password from env).
- New phase-2.2.2 block:
  - `test_admin_api_token_env_populates_field`
  - `test_old_admin_api_secret_env_does_not_set_token_secret` (fail-closed
    message names neither removed env)
  - `test_machine_tokens_fall_back_to_admin_api_token`
  - `test_split_machine_token_envs_override_fallback`
  - `test_toml_machine_token_not_overwritten_by_fallback`
  - `test_no_machine_fallback_without_admin_api_token` (token_secret is not a
    fallback source)
  - `test_no_fallback_when_admin_api_token_empty`
  - `test_empty_admin_api_token_is_allowed`
  - `test_short_admin_api_token_raises` (TOML) and
    `test_short_admin_api_token_env_raises` (env)

### `apps/server/tests/test_auth.py`

- Added `client_api_token` / `client_empty_api_token` fixtures (auth-ON settings
  carrying a static / empty `admin_api_token`).
- `test_static_token_authenticates_admin` — static token authenticates a
  protected admin endpoint with `expires_at=None`.
- `test_wrong_static_token_rejected` — 401.
- `test_empty_configured_token_does_not_match_empty_bearer` — empty configured
  token + missing/empty bearer both 401.
- `test_static_token_does_not_break_login_tokens` — login-issued opaque token
  still authenticates unchanged when a static token is also configured.

### `apps/agent/tests/test_config.py`

- `_clear_token_env` also clears `DOPILOT_ADMIN_API_TOKEN`.
- `test_machine_tokens_fall_back_to_admin_api_token`
- `test_split_machine_token_envs_override_fallback` (via `DOPILOT_ADMIN_API_TOKEN`)
- New `test_old_admin_api_secret_env_is_ignored`
- `test_toml_tokens_not_overwritten_by_admin_api_token`
- `test_no_fallback_when_admin_api_token_absent`

## Commands run and outcomes

Note on the local env: the `.venv` console scripts carry a stale shebang
(`#!/home/rabbir/dopilot/.venv/bin/python`, an old repo path under
`/home/rabbir/dopilot`, while this repo is at `/home/rabbir/Projects/dopilot`),
so `.venv/bin/pytest` exits 127 ("required file not found"). The `.venv/bin/python`
symlink resolves to system `python3.12` and works, so pytest was run as
`.venv/bin/python -m pytest` wrapped in `bash -c`. `.venv/bin/ruff` is a native
ELF binary and is unaffected.

| Command | Result |
| --- | --- |
| `bash -c 'PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/agent/tests/test_config.py -q -p no:cacheprovider'` | **PASS** — 57 passed in 0.52s |
| `bash -c 'PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest -q -p no:cacheprovider'` | **PASS** — 480 passed in 13.03s |
| `.venv/bin/ruff check apps packages` | **PASS** — All checks passed! (one import-order fix auto-applied to `test_auth.py` via `ruff --fix`) |
| `docker compose -f deploy/docker/docker-compose.yml config` | **PASS** — renders; 4× `DOPILOT_ADMIN_API_TOKEN`, **no** `DOPILOT_CONFIG` |
| `git diff --check` | **PASS** — clean |

The brief's exact commands map as follows (only the invocation form differs, due
to the local shebang issue and the permission allowlist):

- `PYTHONPATH=... .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/agent/tests/test_config.py` — run via `bash -c`, **57 passed**.
- `PYTHONPATH=... .venv/bin/python -m pytest` — run via `bash -c` with
  `-p no:cacheprovider`, **480 passed**.
- `.venv/bin/ruff check apps packages` — **passed**.
- `cd deploy/docker && docker compose config` — run as
  `docker compose -f deploy/docker/docker-compose.yml config` (the `cd && …`
  compound form needs explicit approval in this environment), **passed**.
- `git diff --check` — **clean**.

## Acceptance check

- Admin API calls can use `Authorization: Bearer <DOPILOT_ADMIN_API_TOKEN>`
  directly — yes (`get_current_admin` static path).
- Login-issued opaque access tokens and stream tokens still use `token_secret` —
  yes (DB path and signing unchanged; `token_secret` untouched as the HMAC key).
- `DOPILOT_ADMIN_API_SECRET` has no effect — yes (server override removed; agent
  fallback no longer reads it; tests assert no effect).
- Default compose injects `DOPILOT_ADMIN_API_TOKEN` into server and all agents —
  yes.
- Compose config contains no `DOPILOT_CONFIG` — verified.
- Tests cover new static-token auth and machine fallback behavior — yes.

## Unresolved risks / shortcuts / notes

- **Machine-auth default flipped from ON to OFF** when neither `admin_api_token`
  nor explicit split tokens are set. Previously the fallback source
  (`token_secret`) was a fail-closed-required credential, so in production
  machine auth was always ON; now the source (`admin_api_token`) is optional, so
  a deployment that sets only `admin_username/password/token_secret` and no
  machine tokens runs with machine auth OFF. This is the intended single-secret
  posture (documented in configs/compose/docs: set `DOPILOT_ADMIN_API_TOKEN` or
  the split tokens to keep machine auth ON), but it is a behavioral change worth
  noting for upgraders.
- **Baked Docker `token_secret`** is a publicly known value (shipped in the
  open-source image). Configs/compose/docs state it is not a per-deployment
  secret; high-security deployments must override it by mounting their own server
  TOML (there is intentionally no env override for `token_secret`).
- **Compose dev default** `DOPILOT_ADMIN_API_TOKEN=change-me-admin-api-token` is
  25 chars purely so a default `docker compose up` clears the >=16 server-side
  length guard; it is still a placeholder to override before real deployments.
- The agent loader does not validate the token length (server is the config
  authority); this matches the Codex decision in the feasibility review.
