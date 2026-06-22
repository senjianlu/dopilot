# Claude Feasibility Validation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate the feasibility of phase 2.2.3 before Codex finalizes the
implementation brief.

Do not implement code in this step.

## Proposed Direction

User-confirmed goal:

- `DOPILOT_ADMIN_API_TOKEN` must be admin-only.
- Agents must not receive or derive from `DOPILOT_ADMIN_API_TOKEN`.
- The project should abandon the split machine-token model entirely:
  - no user-visible `DOPILOT_AGENT_SHARED_TOKEN`;
  - no user-visible `DOPILOT_SERVER_SHARED_TOKEN`;
  - no default split-token docs/comments;
  - no fallback from admin token to machine token.
- Introduce one machine token:
  - `DOPILOT_AGENT_TOKEN`;
  - server and every agent both use this same value;
  - it authenticates both surviving server→agent HTTP calls and agent→server
    heartbeat/artifact calls.

Codex's proposed implementation shape:

- Server config:
  - add/use `[agents].agent_token`;
  - remove env overrides for `DOPILOT_AGENT_SHARED_TOKEN` and
    `DOPILOT_SERVER_SHARED_TOKEN`;
  - add env override `DOPILOT_AGENT_TOKEN -> [agents].agent_token`;
  - stop deriving machine tokens from `auth.admin_api_token`;
  - use `settings.agents.agent_token` for:
    - server→agent `AgentClient(... token ...)`;
    - agent→server `require_server_token`.
- Agent config:
  - add/use `[agent].agent_token`;
  - remove env handling for `DOPILOT_AGENT_SHARED_TOKEN` and
    `DOPILOT_SERVER_SHARED_TOKEN`;
  - add env override `DOPILOT_AGENT_TOKEN -> [agent].agent_token`;
  - use `settings.agent.agent_token` for:
    - protected agent endpoint auth;
    - heartbeat/artifact fetch auth to server.
- Config/docs:
  - default Docker Compose should inject:
    - server: `DOPILOT_ADMIN_API_TOKEN` and `DOPILOT_AGENT_TOKEN`;
    - agents: `DOPILOT_AGENT_TOKEN` only, never admin token;
  - examples/docs/README should describe only two tokens:
    - admin API token;
    - agent token;
  - historical `docs/phases/phase-2.2*` records should not be rewritten.

Open implementation detail for feasibility validation:

- Is it feasible in one bounded phase to remove the old internal split config
  fields (`agent_auth.shared_token`, `agents.server_shared_token`,
  agent `[auth].shared_token`, agent `[agent].server_shared_token`) from active
  code/tests, or should the code keep some internal compatibility wrappers while
  hiding the old env/docs? The user preference is simplicity and abandoning the
  split model, so prefer real code simplification if feasible.

Explicit non-goals:

- Do not implement server-managed token generation or agent enrollment commands
  in this phase. That is intended for a later phase.
- Do not add TLS/VPN/transport encryption. Token auth is not transport
  encryption.
- Do not keep compatibility for the old split envs.
- Do not change `DOPILOT_CONFIG` Docker Compose behavior.
- Do not touch untracked `tmux.sh`.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/08-docker-deployment.md`
- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/auth/agent_dependencies.py`
- `apps/server/dopilot_server/app.py`
- `apps/server/dopilot_server/clients/agent.py`
- `apps/agent/dopilot_agent/config/settings.py`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/agent/dopilot_agent/auth/dependencies.py`
- `apps/agent/dopilot_agent/deps.py`
- `apps/agent/dopilot_agent/redis/heartbeat.py`
- relevant config/auth tests under `apps/server/tests/` and `apps/agent/tests/`

## Output Required

Return a concise feasibility response with these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Focus on implementation feasibility, required migration/doc fallout, and tests.
If there are no blockers, say so clearly.
