# Phase 2.2.1 Feasibility Review

## Proposed Direction

- Summary: simplify Docker deployment envs after phase 2.2 while preserving the
  security boundary options.
- User decisions:
  - Rename env `DOPILOT_TOKEN_SECRET` to `DOPILOT_ADMIN_API_SECRET` with no
    backwards-compatible alias.
  - Keep TOML as internal/default config, but compose should not expose or
    document `DOPILOT_CONFIG`.
  - If `DOPILOT_AGENT_SHARED_TOKEN` and/or `DOPILOT_SERVER_SHARED_TOKEN` are not
    supplied, fall back to `DOPILOT_ADMIN_API_SECRET`.
  - Keep Redis password auth by default.
  - Put deployment env comments directly in `deploy/docker/docker-compose.yml`;
    do not add `.env.example`.

## Claude Feedback

### Verdict

- Feasible with changes.

### Blockers

- Removing `DOPILOT_CONFIG` from compose is not compose-only. The unified image
  currently sets one global `DOPILOT_CONFIG=/app/configs/server.toml`; without
  agent overrides, `dopilot-agent` would load the server TOML. Server and agent
  CLIs/loaders need role-specific default config paths first.
- Agent settings do not have an admin-token-secret concept. Agent-side fallback
  to the admin secret must read `DOPILOT_ADMIN_API_SECRET` directly from env in
  the agent loader.

### Risky Assumptions

- Baked TOML machine tokens must be empty, otherwise non-empty `change-me-*`
  values prevent fallback from engaging.
- The simplified single-secret posture only works when
  `DOPILOT_ADMIN_API_SECRET` is injected into both server and agent containers.
- Fallback should be applied after env overrides in loaders, not inside Pydantic
  model construction.
- Redis password auth can remain as-is; no code change is needed for Redis.

### Questions

- None for the user. Codex accepts:
  - empty baked machine-token fields;
  - `DOPILOT_ADMIN_API_SECRET` env visible to server and agents in compose;
  - role-specific CLI default config paths;
  - TOML field remains `[auth].token_secret`;
  - agent admin-secret fallback remains loader-only.

### Suggested Scope Or Sequencing Changes

- Implement in this order:
  1. env rename and server-side fallback;
  2. agent-side `DOPILOT_ADMIN_API_SECRET` fallback;
  3. role-specific default config paths and remove global Dockerfile
     `DOPILOT_CONFIG`;
  4. compose/comment updates.

## Codex Decision

- Accepted.

## User Escalations

- None.

## Resulting Brief Changes

- The brief must explicitly prevent a backwards-compatible `DOPILOT_TOKEN_SECRET`
  alias.
- The brief must require tests for both omitted machine tokens (fallback) and
  split machine tokens.
- The brief must require compose verification without `DOPILOT_CONFIG`.
