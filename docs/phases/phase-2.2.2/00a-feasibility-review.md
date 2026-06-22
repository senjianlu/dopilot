# Feasibility Review

## Proposed Direction

- Summary: replace the misleading `DOPILOT_ADMIN_API_SECRET` env with a real
  static `admin_api_token` (`DOPILOT_ADMIN_API_TOKEN`) that can be used directly
  as an admin Bearer token, while returning `token_secret` to TOML-only internal
  signing-key use.
- Source discussion or draft:
  - `docs/phases/phase-2.2.2/admin-api-token-design.md`
  - user confirmed strict TOML-only `token_secret` and asked Codex to replace
    Docker's `change-me` signing secret with a generated long value.

## Claude Feedback

### Verdict

- Feasible with changes.

### Blockers

- None.

### Risky Assumptions

- Removing every env override for `token_secret` means the Docker env-only
  deploy path cannot inject a per-deployment signing key. If the baked TOML kept
  `token_secret = "change-me"`, login/stream signing would use a public
  placeholder.
- Machine auth fallback moves from required `token_secret` to optional
  `admin_api_token`; compose must inject `DOPILOT_ADMIN_API_TOKEN` into server
  and all agents atomically.
- Minimum-length validation for `admin_api_token` should live in
  `load_settings()`, not Pydantic model construction, to preserve test override
  behavior.

### Questions

- Whether to keep strict TOML-only `token_secret` despite Docker env-only
  deployment tradeoffs.
- Whether `admin_api_token` length validation should be hard-fail at 16+
  characters and whether agent loader should enforce it.

### Suggested Scope Or Sequencing Changes

- Land server auth, server config, agent config, compose/config/doc updates, and
  tests in one packet.
- Do not rewrite historical phase 2.2/2.2.1 records that mention
  `DOPILOT_ADMIN_API_SECRET`.
- Keep non-existent sync-script/CI-token additions out of scope.

## Codex Decision

- Accepted with the user's decision: use strict TOML-only `token_secret`, do not
  add a replacement signing-secret env, and replace Docker's baked `change-me`
  signing secret with a generated long value.
- `admin_api_token` minimum length: hard-fail in server `load_settings()` when
  non-empty and shorter than 16 characters.
- Agent loader does not independently validate `DOPILOT_ADMIN_API_TOKEN`; server
  is the config authority and agent only consumes the token as machine-token
  fallback.
- Use existing style (`secrets.compare_digest`) or `hmac.compare_digest`; both
  are acceptable as long as comparison is constant-time and guarded against
  empty-string matches.

## User Escalations

- Resolved: user chose strict TOML-only `token_secret` and requested a generated
  replacement for Docker's baked `change-me`.

## Resulting Brief Changes

- Explicitly forbid `DOPILOT_ADMIN_API_SECRET` compatibility.
- Explicitly require `configs/server.docker.toml` to replace
  `token_secret = "change-me"` with:
  `shLv5qNwC3aViZQYr08x3yfaY6yGZACB6ujydXiVaGnb7OdOflc91xVLyXBoeRDL`.
- Live docs must state that the baked value is not a user-specific production
  secret; high-security deployments should override TOML.
