# Phase 2.2.3 — Codex Review

## Scope Reviewed

- Server config/auth loader paths for `DOPILOT_AGENT_TOKEN`.
- Agent config/auth loader paths for `DOPILOT_AGENT_TOKEN`.
- Docker Compose rendered environment.
- Live source-of-truth docs and user-facing deployment snippets.
- Claude's targeted and full test report.

## Findings

### Finding 1 — Blocking: Docker deployment docs still leaked the old model

Status: fixed by Codex.

`docs/dopilot/08-docker-deployment.md` still contained a copyable compose
snippet that injected `DOPILOT_ADMIN_API_TOKEN` into agents and text describing
the admin API token as a machine-token source. That contradicted the accepted
phase decision:

- admin API token is server-side admin-only;
- agents must never receive or derive from `DOPILOT_ADMIN_API_TOKEN`;
- server-agent machine auth uses only `DOPILOT_AGENT_TOKEN`.

Codex updated the snippet and surrounding explanation so server receives
`DOPILOT_ADMIN_API_TOKEN` + `DOPILOT_AGENT_TOKEN`, agents receive
`DOPILOT_AGENT_TOKEN` only, and token auth is described as identity auth rather
than transport encryption.

### Finding 2 — Blocking: live architecture docs still named active split fields

Status: fixed by Codex.

Several non-phase live docs still referred to `server_shared_token` /
`agent_auth.shared_token` as if they were active configuration:

- `docs/dopilot/01-gap-executors.md`
- `docs/dopilot/02-gap-scheduling-nodes-push.md`
- `docs/dopilot/10-roadmap.md`
- `docs/architecture/06-auth-and-utils.md`

Codex updated those references to the single `agent_token` model. Historical
phase records under `docs/phases/` were intentionally left untouched.

### Finding 3 — Low: server-side machine token comparison was not constant-time

Status: fixed by Codex.

The agent-side protected endpoint dependency used `secrets.compare_digest`, but
the server-side heartbeat auth dependency compared the bearer token with `!=`.
Codex changed the server dependency to use `secrets.compare_digest` for symmetry
and a small auth hardening improvement.

## Post-Fix Review Result

No remaining blocking findings.

The remaining mentions of `DOPILOT_AGENT_SHARED_TOKEN`,
`DOPILOT_SERVER_SHARED_TOKEN`, `server_shared_token`, or `[agent_auth]` in live
files are either:

- tests asserting the old env vars have no effect;
- comments explaining the removal;
- historical explanatory prose that explicitly says the model was superseded.

## Acceptance Notes

- Active server code has one machine-token field: `[agents].agent_token`.
- Active agent code has one machine-token field: `[agent].agent_token`.
- `DOPILOT_AGENT_TOKEN` is the only env override for machine auth.
- `DOPILOT_ADMIN_API_TOKEN` remains admin-only and is not used as a fallback.
- Default compose renders with machine auth on via
  `${DOPILOT_AGENT_TOKEN:-change-me-agent-token}`.
- Default compose does not set `DOPILOT_CONFIG`.
