# Phase 2.2 Feasibility Validation Prompt

You are Claude Code working in the dopilot repository.

## Assignment

Validate feasibility before Codex finalizes the phase 2.2 implementation brief.
Do not implement code in this step.

## Proposed Direction

Phase 2.2 is platform hardening only. It prepares for a later declarative
deployment manifest, but does not implement `dopilot.toml`, `dopilot_sync.py`,
project ownership labels, or a reconciler.

In scope:

1. Config env overrides + auth fail-closed.
   - Keep TOML as defaults, but add `DOPILOT_*` env overrides for scalar/secret
     server settings.
   - Web admin auth is enabled by default and must fail startup/config loading
     when `admin_username`, `admin_password`, or `token_secret` is missing.
   - Only explicit `DOPILOT_AUTH_DISABLED=true` permits anonymous admin/dev
     mode.
   - Update config examples, Docker compose/default env, docs, and tests.

2. Unique template and schedule names.
   - Add uniqueness for `execution_templates.name` and `schedules.name`.
   - Add an Alembic migration that handles existing duplicate names before
     adding constraints.
   - Create/update conflicts should return explicit 409 errors.
   - Do not change artifact uniqueness semantics.

3. Schedule enabled/disabled.
   - Add `schedules.enabled`.
   - New schedules default to `enabled=false` unless explicitly set.
   - `PUT /api/v1/schedules/{id}` can change `enabled`.
   - The scheduler runner registers/fires only enabled schedules.
   - `trigger-now` remains allowed for disabled schedules.

Out of scope:

- `dopilot.toml`.
- `scripts/dopilot_sync.py` or any manifest reconciler.
- `labels` / `source` ownership fields.
- RBAC, multi-user auth, token refresh, mTLS, HA, or multi-worker support.
- Fetching, vendoring, copying, or importing upstream scrapydweb code.

## Required Context

Read only what is needed:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `/tmp/dopilot-hardening-and-deploy-manifest-plan.md`
- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/auth/dependencies.py`
- `apps/server/dopilot_server/models/scheduling.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/dopilot_server/services/schedules.py`
- `apps/server/dopilot_server/scheduler/runner.py`
- `apps/server/dopilot_server/api/v1/schedules.py`
- `apps/server/dopilot_server/api/v1/schemas.py`
- `apps/server/migrations/versions/`
- `configs/`
- `deploy/docker/docker-compose.yml`
- relevant tests under `apps/server/tests/`

## Output Required

Return a concise feasibility response with these sections:

1. Verdict: feasible / feasible with changes / blocked.
2. Blocking issues.
3. Risky assumptions.
4. Missing decisions or questions for Codex.
5. Suggested scope cuts or sequencing changes.

Keep the response short and concrete. Focus on implementation feasibility, not
product brainstorming. If there are no blockers, say so clearly.
