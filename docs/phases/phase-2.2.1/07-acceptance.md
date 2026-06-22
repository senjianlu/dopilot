# Phase 2.2.1 Acceptance

## Summary

Phase 2.2.1 is accepted.

Implemented deployment env simplification:

- `DOPILOT_ADMIN_API_SECRET` replaces `DOPILOT_TOKEN_SECRET` as the admin API
  secret env, with no backwards-compatible alias.
- Server and agent machine tokens default to the admin API secret when omitted.
- Explicit `DOPILOT_AGENT_SHARED_TOKEN` / `DOPILOT_SERVER_SHARED_TOKEN` still
  override the fallback for split-token deployments.
- Server and agent CLIs use role-specific baked default config paths, so
  Docker compose no longer needs `DOPILOT_CONFIG`.
- Dockerfile no longer sets a global `DOPILOT_CONFIG`.
- Compose keeps Redis password auth and does not publish Redis to the host.
- Docker compose comments now document required secrets and optional split
  machine tokens directly in the file.

## Evidence

- Feasibility review:
  `docs/phases/phase-2.2.1/00a-feasibility-review.md`
- Brief:
  `docs/phases/phase-2.2.1/00-brief.md`
- Claude implementation report:
  `docs/phases/phase-2.2.1/01-claude-implementation-report.md`
- Codex review:
  `docs/phases/phase-2.2.1/02-codex-review.md`
- Test plan:
  `docs/phases/phase-2.2.1/04-test-plan.md`
- Verification:
  `docs/phases/phase-2.2.1/05-codex-verification-report.md`
- Test review:
  `docs/phases/phase-2.2.1/06-codex-test-review.md`

## Verified Commands

```text
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/agent/tests/test_config.py -> 38 passed
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest -> 469 passed
.venv/bin/ruff check apps packages -> passed
cd deploy/docker && docker compose config -> passed
rendered compose grep -> no active DOPILOT_CONFIG; admin API secret present on server+agents; Redis requirepass present
git diff --check -> passed
```

## Remaining Risks

- No known material residual risk.
- `DOPILOT_TOKEN_SECRET` is intentionally removed as an env name. Existing
  deployments using it must move to `DOPILOT_ADMIN_API_SECRET`.

## Deferred Work

- `.env.example` remains intentionally out of scope.
- Manifest/reconciler work (`dopilot.toml`, `dopilot_sync.py`) remains deferred.

## Final Decision

Accepted.
