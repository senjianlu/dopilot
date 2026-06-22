# Phase 2.2.4 Feasibility Prompt — Agent Token Generation And Split Compose

You are Claude Code doing feasibility validation only. Do not implement.

## Context

Read:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/agent-governance/00-operating-model.md`
- `docs/agent-governance/01-codex-claude-loop.md`
- `docs/agent-governance/02-claude-invocation.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-2.2.3/00-brief.md`
- `docs/phases/phase-2.2.3/07-acceptance.md`
- Current server/agent config loader and entrypoint code under `apps/server` and `apps/agent`
- `deploy/docker/docker-compose.yml`

## Accepted Direction

Phase 2.2.3 collapsed machine auth to one token:

- `DOPILOT_ADMIN_API_TOKEN` is admin API only, server-side only.
- `DOPILOT_AGENT_TOKEN` is the only server-agent machine token.
- Old split tokens are gone and must not return.

For phase 2.2.4, add a deployment convenience layer:

1. If the server has no configured `[agents].agent_token` after env/TOML loading,
   the server should generate a high-entropy agent token once and persist it in
   the server data volume, then reuse it on restart.
2. The generated token must become the active `settings.agents.agent_token` for
   server runtime, so machine auth is ON once generated.
3. The server should log a join hint once per startup when it uses a generated
   token.
4. Add a CLI command similar to:

   ```bash
   dopilot-server agent-token print
   ```

   It should read or generate the same persisted token and print a usable join
   hint/token for operators, suitable for `docker exec <server> ...`.
5. Keep all-in-one `deploy/docker/docker-compose.yml` explicit and working with
   `${DOPILOT_AGENT_TOKEN:-change-me-agent-token}`, because server and agents
   start together and agents cannot know a server-generated token automatically.
6. Add two deployment compose files:
   - a server-only compose stack including server + Redis + PostgreSQL + migrate;
   - an agent-only compose stack for joining an existing server/Redis network,
     configured via env including `DOPILOT_AGENT_TOKEN`.
7. Do not implement token rotation, multi-token enrollment, DB persistence,
   compatibility for old split envs, or TLS/VPN.

## Feasibility Questions

Return only:

- Feasibility verdict.
- Blockers.
- Risky assumptions.
- Missing product/architecture decisions.
- Concrete implementation questions.
- Recommended scope cuts, if any.
- Suggested exact files to change.
- Suggested focused tests/commands.

Pay special attention to:

- where the server data directory setting currently lives;
- whether `load_settings()` is the right place to generate a persisted secret or
  whether generation should happen in the server CLI/runtime boundary;
- how to avoid unexpectedly generating tokens during tests that directly call
  config loading;
- how to make `dopilot-server agent-token print` work without requiring DB/Redis;
- whether existing config-present-or-off semantics need an explicit update;
- Docker Compose file naming and validation commands.
