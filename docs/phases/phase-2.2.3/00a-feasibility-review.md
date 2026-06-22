# Feasibility Review

## Proposed Direction

- Summary: split admin API auth from machine auth completely by removing the
  phase 2.2.2 fallback from `DOPILOT_ADMIN_API_TOKEN` to agent machine tokens
  and introducing one machine token, `DOPILOT_AGENT_TOKEN`.
- Source discussion or draft: user confirmed the project should abandon
  `DOPILOT_AGENT_SHARED_TOKEN` and `DOPILOT_SERVER_SHARED_TOKEN` entirely to
  keep deployment simple.

## Claude Feedback

### Verdict

- Feasible.

### Blockers

- None.

### Risky Assumptions

- One machine token authenticates both directions. This is intentional and
  simpler, but leaking it grants both server->agent and agent->server machine
  access.
- Default compose should keep machine auth on by injecting a default
  `DOPILOT_AGENT_TOKEN`; otherwise the default stack would silently fall back to
  machine-auth off.
- Existing architecture docs still describe split tokens as a locked decision.

### Questions

- Whether abandoning split tokens should update `CLAUDE.md`,
  `docs/dopilot/00-requirements.md`, `docs/refactor/00-redis-streams-agent-communication.md`,
  and gap docs, or only user-facing config/docs.
- Whether `agent_token` should have a minimum length check.
- Whether to remove now-empty wrapper config sections entirely.
- Which default dev value to use for `DOPILOT_AGENT_TOKEN`.

### Suggested Scope Or Sequencing Changes

- No phase split required.
- Prefer full removal over compatibility wrappers.
- Expect mechanical but broad test rewrites around config, heartbeat auth, and
  agent endpoint auth.

## Codex Decision

- Accepted.
- Update source-of-truth architecture docs as well as README/config/deploy docs.
  Historical phase records under `docs/phases/phase-2.2*` remain unchanged.
- Fully remove active split config fields:
  - server `[agent_auth].shared_token`;
  - server `[agents].server_shared_token`;
  - agent `[auth].shared_token`;
  - agent `[agent].server_shared_token`.
- Add one active field:
  - server `[agents].agent_token`;
  - agent `[agent].agent_token`.
- Add one env:
  - `DOPILOT_AGENT_TOKEN`.
- Old split envs have no effect:
  - `DOPILOT_AGENT_SHARED_TOKEN`;
  - `DOPILOT_SERVER_SHARED_TOKEN`.
- Enforce minimum length for non-empty `agent_token` at loader boundary:
  16 characters, matching `admin_api_token`.
- Use default compose placeholder `change-me-agent-token` to keep default
  compose machine auth enabled while marking it dev-only.

## User Escalations

- None. The user already made the product decision to abandon split tokens.

## Resulting Brief Changes

- The implementation brief must explicitly update `CLAUDE.md` and live docs
  that describe split-token auth.
- The brief must forbid using `DOPILOT_ADMIN_API_TOKEN` in agent services.
