# Phase 2a Acceptance Report

## Summary

Phase 2a is accepted. The Redis wire, server DB index tables, agent state files,
agent log cursors, and server log body paths now use unified ids:

```text
task_id      = Task.id
execution_id = Execution.id
```

The old internal seam `execution_id = Task.id` / `attempt_id = Execution.id` has
been removed from non-migration code and tests. Public HTTP/web fields remain
unchanged.

## Evidence

- Implementation brief: `docs/phases/phase-2a/00-brief.md`
- Claude implementation report:
  `docs/phases/phase-2a/01-claude-implementation-report.md`
- Codex review: `docs/phases/phase-2a/02-codex-review.md`
- Browser UI e2e verification:
  `docs/phases/phase-2a/04-ui-e2e-verification-report.md`
- Browser UI e2e Codex review:
  `docs/phases/phase-2a/05-ui-e2e-codex-review.md`

## Verified Commands

```text
.venv/bin/ruff check apps packages -> passed
.venv/bin/pytest packages/protocol/tests -q -p no:cacheprovider -> 65 passed
.venv/bin/pytest apps/agent/tests -q -p no:cacheprovider -> 83 passed
.venv/bin/pytest apps/server/tests -q -p no:cacheprovider -> 231 passed
git diff --check -> passed
cd deploy/docker && docker compose config -> passed
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot ../../.venv/bin/alembic downgrade -1 -> passed
cd apps/server && DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot ../../.venv/bin/alembic upgrade head -> passed
scripts/smoke-phase1-ui.sh -> passed after two stale e2e assertions were updated
corepack pnpm --filter web test -> 10 files / 41 tests passed
corepack pnpm --filter web build -> passed
```

Additional review checks:

- `rg -n 'attempt_id' apps packages` matches only migration files.
- PostgreSQL schema after `0009` has no `attempt_id` column on
  `command_outbox`, `event_audit`, or `execution_log_files`.
- Compose `db` container used for migration review was stopped after validation.
- Browser UI e2e ran against the Docker-served production SPA and covered the
  template run -> task detail -> three execution fan-out -> live log marker path.
- The browser e2e stack was torn down after validation.

## Remaining Risks

- Lockstep deploy is required: protocol, server, and agent must be upgraded as
  one version.
- Cutover requires no in-flight executions and cleared Redis streams/pending
  commands. Old state/log paths are intentionally not supported.

## Deferred Work

- Phase 2b: Python wheel shell-command runner.
- Optional internal cleanup: decide whether to delete `ScrapydRunner.run()` and
  `AgentRunResponse`, which are currently kept because runner tests still cover
  them.
- Optional internal naming cleanup: `AttemptState` / `AttemptStatus` names are
  retained; their id fields are already unified.

## Final Decision

Accepted with the documented clean-cut deployment risks.
