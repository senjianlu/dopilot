# Phase 2.2.1 Feasibility Validation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate feasibility before Codex finalizes a follow-up brief. Do not implement
code in this step.

## Proposed Direction

User-approved deployment-config follow-up after phase 2.2:

1. Rename the server admin token secret env from `DOPILOT_TOKEN_SECRET` to
   `DOPILOT_ADMIN_API_SECRET`.
   - Do not keep a backwards-compatible `DOPILOT_TOKEN_SECRET` alias.
   - TOML field may remain `auth.token_secret`; this is an env/deploy naming
     change unless code feasibility suggests otherwise.

2. Reduce deployment secret burden:
   - `DOPILOT_AGENT_SHARED_TOKEN` (server -> agent machine auth) may be omitted.
     When omitted/empty, server and agent should both use
     `DOPILOT_ADMIN_API_SECRET` as the fallback.
   - `DOPILOT_SERVER_SHARED_TOKEN` (agent -> server machine auth) may be omitted.
     When omitted/empty, server and agent should both use
     `DOPILOT_ADMIN_API_SECRET` as the fallback.
   - Docs must explain this is the default simplified compose posture, and that
     production operators can split the machine tokens for stronger isolation.

3. Redis should keep password auth by default because cross-host deployments are
   plausible.
   - Keep `REDIS_PASSWORD` in compose.
   - Do not expose Redis to the host.

4. Docker compose should be env-driven and reduce unnecessary user-facing knobs.
   - Put required and optional env explanations directly in
     `deploy/docker/docker-compose.yml` comments, not as a separate `.env.example`.
   - Remove explicit `DOPILOT_CONFIG` entries from compose.
   - Do not tell users to override `DOPILOT_CONFIG` in compose docs/comments.
   - `DOPILOT_CONFIG` should be an internal image/default detail. Because the
     unified image has both server and agent configs, validate whether server and
     agent loaders or commands need role-specific default paths when env is not
     set.

Out of scope:

- `dopilot.toml`, `dopilot_sync.py`, labels/source ownership, reconciler.
- RBAC, multi-user auth, token rotation, mTLS, HA.
- Removing Redis auth.
- Fetching/copying upstream scrapydweb code.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/phases/phase-2.2/00-brief.md`
- `docs/phases/phase-2.2/07-acceptance.md`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/app.py`
- `apps/agent/dopilot_agent/config/loader.py`
- `apps/agent/dopilot_agent/config/settings.py`
- `apps/agent/dopilot_agent/app.py` or CLI entrypoint
- `configs/server.docker.toml`
- `configs/agent.example.toml`
- `deploy/docker/Dockerfile`
- `deploy/docker/docker-compose.yml`
- relevant tests under `apps/server/tests/` and `apps/agent/tests/`

## Output Required

Return a concise feasibility response:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Focus on whether the no-`DOPILOT_CONFIG` compose requirement needs loader/CLI
changes and where token fallback should be implemented.
