# Phase 2.2.3 — Codex Test Review

## Result

Accepted.

The implemented tests cover the behavior that changed in this phase:

- new env/config mapping for `DOPILOT_AGENT_TOKEN`;
- no compatibility behavior for old split env vars;
- no fallback from `DOPILOT_ADMIN_API_TOKEN` to machine auth;
- minimum length validation for non-empty machine tokens;
- machine-auth off behavior when the token is absent;
- server heartbeat auth;
- agent protected endpoint auth;
- agent heartbeat/artifact bearer headers.

The full suite passed after Codex review fixes, which gives coverage against
stale config model imports and unrelated server/agent regressions.

## Residual Risk

The accepted product model intentionally uses one shared machine token for both
directions. If `DOPILOT_AGENT_TOKEN` leaks, it grants both server-to-agent and
agent-to-server machine access. This is the confirmed simplification, and docs
now call out that token auth is not transport encryption.
