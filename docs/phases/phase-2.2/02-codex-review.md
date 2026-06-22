# Phase 2.2 Codex Review

## Scope Reviewed

- Diff in working tree after Claude implementation.
- Brief: `docs/phases/phase-2.2/00-brief.md`
- Implementation report:
  `docs/phases/phase-2.2/01-claude-implementation-report.md`
- Key files:
  - `apps/server/dopilot_server/config/`
  - `apps/server/dopilot_server/models/scheduling.py`
  - `apps/server/dopilot_server/services/templates.py`
  - `apps/server/dopilot_server/services/schedules.py`
  - `apps/server/dopilot_server/scheduler/runner.py`
  - `apps/server/migrations/versions/0010_unique_template_schedule_names.py`
  - `apps/server/migrations/versions/0011_schedule_enabled.py`
  - updated server tests and docs

## Findings

### P0 / Blocking

- None.

### P1 / Must Fix

- Active docs/code comments still describe Web admin auth as
  config-present-or-off after phase 2.2 changed it to fail-closed:
  - `apps/server/dopilot_server/auth/dependencies.py:3`
  - `apps/server/dopilot_server/config/settings.py:89`
  - `docs/dopilot/06-frontend-rewrite.md:148`
  - `docs/dopilot/06-frontend-rewrite.md:169`
  - `docs/dopilot/03-gap-realtime-logs.md:268`
  - `docs/dopilot/03-gap-realtime-logs.md:292`
  
  Historical phase briefs can keep their old wording, and agent machine auth can
  still be described as config-present-or-off. These active docs/comments need
  to distinguish Web admin auth fail-closed from agent/server machine auth
  config-present-or-off before acceptance.

### P2 / Should Fix

- `docs/phases/phase-2.2/claude-progress.md` and
  `docs/phases/phase-2.2/01-claude-implementation-report.md` contain a stray
  `</content>` line from Claude output. Remove it while updating the report.

## Test Gaps

- Claude could not run commands due its permission layer, but Codex ran them:
  - `PYTHONPATH=apps/server:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py`
    -> 73 passed.
  - `PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest`
    -> 454 passed.
  - `.venv/bin/ruff check apps packages` -> passed.
  - `cd deploy/docker && docker compose config` -> passed.
  - `corepack pnpm --filter web test` -> 57 passed.
  - `corepack pnpm --filter web build` -> passed.
  - Temporary PostgreSQL `alembic upgrade head` -> passed.
  - Temporary PostgreSQL duplicate-name migration smoke
    (`upgrade 0009`, insert duplicate template/schedule names, `upgrade head`)
    -> passed; duplicate rows were preserved and renamed, `enabled=false`
    backfilled.

## Architecture / Docs Gaps

- Same as P1: active docs must align with the phase 2.2 auth posture.

## Required Claude Follow-Up

Use this section as the next Claude prompt.

```text
Fix only the review findings in docs/phases/phase-2.2/02-codex-review.md.

Scope:
- Update the listed active docs/comments so Web admin auth is described as
  fail-closed unless DOPILOT_AUTH_DISABLED=true, while agent/server machine auth
  remains config-present-or-off.
- Do not edit historical phase briefs just because they mention old behavior.
- Remove stray </content> lines from phase-2.2 report/progress files.
- Update docs/phases/phase-2.2/01-claude-implementation-report.md command
  results to include the Codex-run verification outcomes listed in the review.
- Create docs/phases/phase-2.2/03-claude-review-response.md summarizing the
  fix.

No code behavior changes are expected. Run no tests unless you change Python
code beyond comments/docstrings; if you do run a command, report it exactly.
```
