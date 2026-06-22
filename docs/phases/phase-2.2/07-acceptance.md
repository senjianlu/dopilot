# Phase 2.2 Acceptance

## Summary

Phase 2.2 is accepted.

Implemented platform hardening only:

- Web admin auth is fail-closed during production config loading unless
  explicitly disabled with `DOPILOT_AUTH_DISABLED=true`.
- Server config supports the scoped `DOPILOT_*` env override surface from the
  brief.
- `execution_templates.name` and `schedules.name` are unique with service-level
  409 conflicts and PostgreSQL constraints.
- `schedules.enabled` defaults false, gates timer registration/firing, and does
  not block `trigger-now`.
- Docs, config examples, migrations, and tests were updated.

No `dopilot.toml`, `dopilot_sync.py`, labels/source ownership, or manifest
reconciler was added.

## Evidence

- Feasibility review:
  `docs/phases/phase-2.2/00a-feasibility-review.md`
- Brief:
  `docs/phases/phase-2.2/00-brief.md`
- Claude implementation report:
  `docs/phases/phase-2.2/01-claude-implementation-report.md`
- Codex review:
  `docs/phases/phase-2.2/02-codex-review.md`
- Claude review response:
  `docs/phases/phase-2.2/03-claude-review-response.md`
- Test plan:
  `docs/phases/phase-2.2/04-test-plan.md`
- Verification:
  `docs/phases/phase-2.2/05-codex-verification-report.md`
- Test review:
  `docs/phases/phase-2.2/06-codex-test-review.md`

## Verified Commands

```text
PYTHONPATH=apps/server:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py -> 73 passed
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest -> 454 passed
.venv/bin/ruff check apps packages -> passed
cd deploy/docker && docker compose config -> passed
corepack pnpm --filter web test -> 57 passed
corepack pnpm --filter web build -> passed
temporary PostgreSQL alembic upgrade head -> passed
temporary PostgreSQL duplicate-name migration smoke -> passed
```

## Remaining Risks

- No known material residual risk.
- The local virtualenv script shebangs point at an old checkout path, so Codex
  used `.venv/bin/python -m pytest` with `PYTHONPATH`; this should be cleaned up
  separately if it becomes annoying, but it did not affect verification.

## Deferred Work

- Declarative project manifest `dopilot.toml`.
- `scripts/dopilot_sync.py` or shared deployment CLI.
- Project ownership labels/source fields and prune semantics.

## Final Decision

Accepted.
