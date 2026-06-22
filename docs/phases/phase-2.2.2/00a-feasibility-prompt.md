# Claude Feasibility Validation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of the proposed phase 2.2.2 auth/config adjustment
before Codex finalizes the implementation brief.

Do not implement code in this step.

## Proposed Direction

Adopt the design captured in:

- `docs/phases/phase-2.2.2/admin-api-token-design.md`

Codex/user-confirmed target behavior:

- Remove `DOPILOT_ADMIN_API_SECRET` as an env override for `auth.token_secret`.
- Keep `auth.token_secret` as an internal TOML-only signing secret for login
  access tokens and stream tokens.
- Add `auth.admin_api_token`, overridable by `DOPILOT_ADMIN_API_TOKEN`.
- Treat `admin_api_token` as a static, non-expiring admin credential accepted by
  `get_current_admin` via `Authorization: Bearer <admin_api_token>`.
- Keep web admin auth fail-closed semantics unchanged:
  `admin_username + admin_password + token_secret` remain required unless
  `DOPILOT_AUTH_DISABLED=true`.
- Change server machine-token fallback to `admin_api_token`, not `token_secret`.
- Change agent loader single-token fallback to `DOPILOT_ADMIN_API_TOKEN`, not
  `DOPILOT_ADMIN_API_SECRET`.
- Add minimum-length validation for configured `admin_api_token`; Codex assumes
  `< 16` non-empty characters should raise `ConfigError`.
- Update Docker Compose, config examples, README, and deployment docs to use
  `DOPILOT_ADMIN_API_TOKEN`.

Explicit non-goals:

- Do not add RBAC, multiple admins, token rotation, or DB persistence for the
  static token.
- Do not add or modify a `scripts/dopilot_sync.py` flow unless it already exists
  and is directly required by current tests; Codex did not find it in the repo.
- Do not reintroduce `DOPILOT_ADMIN_API_SECRET` compatibility.
- Do not change `DOPILOT_CONFIG` Docker Compose behavior.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2.2/admin-api-token-design.md`
- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/auth/dependencies.py`
- `apps/server/dopilot_server/auth/tokens.py`
- `apps/server/dopilot_server/api/v1/auth.py`
- `apps/agent/dopilot_agent/config/loader.py`
- `configs/server.example.toml`
- `configs/server.docker.toml`
- `configs/agent.example.toml`
- `deploy/docker/docker-compose.yml`
- relevant auth/config tests under `apps/server/tests/` and `apps/agent/tests/`

## Output Required

Return a concise feasibility response with these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Focus on implementation feasibility and test coverage. If there are no blockers,
say so clearly.
