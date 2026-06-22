# Phase 2.2 Brief

## Goal

Harden dopilot's platform surface before adding declarative deployment manifests:

- server config can be driven by Docker-friendly `DOPILOT_*` env overrides;
- web admin auth fails closed by default instead of silently opening the admin
  API;
- execution-template and schedule names are unique and return deterministic
  conflicts;
- schedules can be disabled for timer firing while remaining manually
  triggerable.

This phase does not implement `dopilot.toml` or a reconciler.

## Context

Relevant files and decisions:

- `CLAUDE.md`
- `AGENTS.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/dopilot/08-docker-deployment.md`
- `/tmp/dopilot-hardening-and-deploy-manifest-plan.md`
- `docs/phases/phase-2.2/00a-feasibility-review.md`
- `apps/server/dopilot_server/config/settings.py`
- `apps/server/dopilot_server/config/loader.py`
- `apps/server/dopilot_server/auth/dependencies.py`
- `apps/server/dopilot_server/models/scheduling.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/dopilot_server/services/schedules.py`
- `apps/server/dopilot_server/scheduler/runner.py`
- `apps/server/dopilot_server/api/v1/schedules.py`
- `apps/server/dopilot_server/api/v1/templates.py`
- `apps/server/dopilot_server/api/v1/schemas.py`
- `apps/server/migrations/versions/`
- `configs/server.example.toml`
- `configs/server.docker.toml`
- `deploy/docker/docker-compose.yml`
- server tests under `apps/server/tests/`

Architecture constraints:

- Keep the single-admin model. Do not add RBAC, multi-user auth, refresh tokens,
  token rotation, mTLS, or HA.
- Keep the single-server constraint: one server process, uvicorn `workers=1`,
  one in-process APScheduler.
- PostgreSQL remains the business-state authority. Redis remains a transient
  message bus only.
- Do not fetch, vendor, copy, or import upstream scrapydweb code.

## In Scope

- Update decision-level docs for the new auth and schedule-enabled behavior.
- Extend server config loading with `DOPILOT_*` env overrides.
- Make web admin auth fail closed in production config loading.
- Add explicit anonymous/dev mode through `DOPILOT_AUTH_DISABLED=true`.
- Add ORM and Alembic uniqueness for `execution_templates.name` and
  `schedules.name`.
- Add service-level 409 conflict handling for duplicate template/schedule names
  on create and rename/update.
- Add `schedules.enabled`, defaulting to `false` for new schedules unless
  explicitly set to true.
- Expose `enabled` in schedule create/update/view API schemas.
- Make the scheduler runner register/fire only enabled schedules.
- Preserve `trigger-now` for disabled schedules.
- Update config examples, Docker compose env, deployment docs, and tests.

## Out Of Scope

- `dopilot.toml`.
- `scripts/dopilot_sync.py` or any manifest/reconcile CLI.
- `labels`, `source`, project ownership fields, or prune semantics.
- Artifact uniqueness changes. Build artifacts remain deduped by
  `(artifact_type, content_hash)`.
- New schedule `/enable` or `/disable` convenience endpoints. `PUT
  /api/v1/schedules/{id}` with `enabled` is enough for this phase.
- Frontend UI changes beyond whatever is strictly required by generated/typesafe
  API expectations. If the web tests/build already pass without UI changes, do
  not expand scope.
- Agent, Redis protocol, executor, or log-consumer changes.

## Required Implementation Order

1. Update docs first:
   - `docs/dopilot/00-requirements.md` decision #12 must no longer say web auth
     is config-present-or-off. It should state that web admin auth is
     fail-closed unless explicitly disabled for dev.
   - Update schedule docs/roadmap wording that currently says pause/resume is
     out of scope.
   - Update `docs/dopilot/08-docker-deployment.md` and config comments for env
     overrides and default auth posture.

2. Config and auth hardening:
   - Add `AuthSettings.disabled: bool = False`.
   - `AuthSettings.enabled` should be true only when auth is not disabled and
     all three credentials are non-empty.
   - Enforce fail-closed in `load_settings()` after env overrides are applied:
     if auth is not disabled and any of `admin_username`, `admin_password`, or
     `token_secret` is missing/empty, raise `ConfigError` with a clear message.
   - Keep direct `Settings.model_validate(...)` usable in tests. Tests that need
     anonymous admin mode must set `auth.disabled=true` explicitly.
   - Document `DOPILOT_AUTH_DISABLED=true` as the supported dev escape hatch.

3. Env override surface:
   - Env wins over TOML. TOML remains the default source.
   - Support these string overrides:
     `DOPILOT_SERVER_HOST`, `DOPILOT_SERVER_PUBLIC_URL`,
     `DOPILOT_DATABASE_URL`, `DOPILOT_ADMIN_USERNAME`,
     `DOPILOT_ADMIN_PASSWORD`, `DOPILOT_TOKEN_SECRET`,
     `DOPILOT_AGENT_SHARED_TOKEN`, `DOPILOT_REDIS_URL`,
     `DOPILOT_REDIS_CONSUMER_NAME`, `DOPILOT_SERVER_SHARED_TOKEN`,
     `DOPILOT_LOGS_ROOT_DIR`, `DOPILOT_ARTIFACTS_ROOT_DIR`,
     `DOPILOT_I18N_LOCALE`, `DOPILOT_I18N_TIMEZONE`.
   - Support these integer overrides:
     `DOPILOT_SERVER_PORT`, `DOPILOT_ACCESS_TOKEN_TTL_MINUTES`,
     `DOPILOT_STREAM_TOKEN_TTL_SECONDS`,
     `DOPILOT_REDIS_STREAM_MAXLEN_COMMANDS`,
     `DOPILOT_REDIS_STREAM_MAXLEN_EVENTS`,
     `DOPILOT_REDIS_STREAM_MAXLEN_LOGS`,
     `DOPILOT_REDIS_LOG_RETENTION_SECONDS`,
     `DOPILOT_HEARTBEAT_TIMEOUT_SECONDS`,
     `DOPILOT_STALLED_ATTEMPT_SECONDS`,
     `DOPILOT_LOST_AFTER_STALLED_SECONDS`,
     `DOPILOT_LOG_BACKGROUND_DRAIN_INTERVAL_SECONDS`,
     `DOPILOT_LOG_REALTIME_DRAIN_INTERVAL_SECONDS`,
     `DOPILOT_LOG_STATUS_POLL_INTERVAL_SECONDS`,
     `DOPILOT_LOG_MAX_TAIL_BYTES_PER_PULL`,
     `DOPILOT_LOG_EOF_STABLE_SECONDS`,
     `DOPILOT_LOG_FINAL_DRAIN_HARD_TIMEOUT_SECONDS`,
     `DOPILOT_LOG_DRAIN_TIMEOUT_SECONDS`,
     `DOPILOT_LOG_UNREACHABLE_LOST_SECONDS`,
     `DOPILOT_LOG_RETENTION_DAYS`,
     `DOPILOT_LOG_FIRST_SCREEN_MAX_LINES`,
     `DOPILOT_LOG_FIRST_SCREEN_MAX_BYTES`.
   - Support these boolean overrides:
     `DOPILOT_AUTH_DISABLED`, `DOPILOT_REDIS_REQUIRE_AOF`,
     `DOPILOT_SCHEDULER_ENABLED`.
   - Support `DOPILOT_SCHEDULER_TIMEZONE` as the scheduler timezone override.
   - Do not add env parsing for list/nested object fields such as
     `[nodes].agents`; leave those in TOML for now.
   - Invalid integer/boolean env values must raise `ConfigError` with the env
     var name.

4. Name uniqueness:
   - Add model-level uniqueness for `ExecutionTemplate.name` and
     `Schedule.name` so SQLite `create_all()` tests see it.
   - Add Alembic migration `0010` that de-duplicates existing rows before adding
     the constraints. Preserve rows; rename duplicates deterministically, for
     example `<old-name>__duplicate__<id-prefix>`.
   - Add service-level duplicate checks returning `ApiError(409, ...)` before
     commit on create and update. Update checks must exclude the row being
     updated.
   - Do not change artifact uniqueness.

5. Schedule enabled:
   - Add `Schedule.enabled: bool`, model default false.
   - Add Alembic migration `0011` with a server default false, then keep model
     defaults aligned.
   - Add `enabled` to `ScheduleCreateRequest`, `ScheduleUpdateRequest`, and
     `ScheduleView`.
   - `create_schedule()` defaults enabled to false when omitted.
   - `update_schedule()` patches enabled when provided.
   - Keep `list_schedules()` returning both enabled and disabled schedules.
   - `ScheduleRunner.reload()` should register only enabled schedules. It may
     call a new `list_enabled_schedules()` helper or filter locally.
   - `fire_timer()` should defensively no-op if a schedule is disabled.
   - `trigger_now()` must not check `enabled`; disabled schedules remain
     manually runnable.

6. Verification and report:
   - Update tests for config, auth, templates, schedules, scheduler runner, and
     migrations as needed.
   - Update phase report files after implementation.

## Acceptance Criteria

- Loading production config without auth credentials raises `ConfigError` unless
  `DOPILOT_AUTH_DISABLED=true` is set.
- Anonymous admin mode is no longer entered silently; it is visible in config
  through explicit disabled mode.
- Env overrides cover the listed scalar/secret server settings and reject bad
  typed values clearly.
- Default Docker compose remains bootable with placeholder credentials, while
  docs mark them as non-production-safe and show env override usage.
- Creating or renaming an execution template to an existing name returns 409.
- Creating or renaming a schedule to an existing name returns 409.
- PostgreSQL migrations preserve existing duplicate rows by deterministic rename
  before adding unique constraints.
- New schedules default to `enabled=false`.
- Disabled schedules appear in list/get responses and can be updated/deleted.
- Disabled schedules are not registered by APScheduler and timer firing no-ops.
- Disabled schedules can still run through `trigger-now`.
- Existing artifact, task, execution, Redis, log, and agent behavior is not
  changed.

## Required Tests

- Unit tests:
  - config loader env override coverage, invalid typed env values, fail-closed
    missing auth, and explicit auth-disabled mode;
  - `AuthSettings.enabled` with enabled/disabled variants;
  - template duplicate create/update conflict helpers;
  - schedule duplicate create/update conflicts;
  - schedule default enabled false and update enabled true/false;
  - runner reload skips disabled schedules;
  - `fire_timer()` no-ops when disabled;
  - `trigger-now` still creates a task for disabled schedules.
- Migration tests or migration smoke:
  - Alembic upgrade head succeeds from the current tree;
  - duplicate-name migration preserves duplicate rows by renaming before adding
    constraints.
- Frontend tests:
  - Run existing web tests/build if API schema changes require web updates.
- Smoke/manual checks:
  - Docker compose config remains valid.

## Required Commands

Use the narrowest commands during development, then run at least:

```bash
pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py
ruff check apps packages
cd deploy/docker && docker compose config
```

Also run these if touched behavior or imports make broader coverage necessary:

```bash
pytest
corepack pnpm --filter web test
corepack pnpm --filter web build
```

## Risks To Watch

- Putting fail-closed validation in `Settings` construction would break many
  tests and dependency overrides. Keep production validation in `load_settings`.
- Filtering disabled schedules in the shared API list path would hide disabled
  rows from users and from later declarative reconcile work.
- Relying only on DB `IntegrityError` for conflicts would produce inconsistent
  API errors and may leave sessions needing rollback.
- Confusing global `[scheduler].enabled` with row-level `schedules.enabled`:
  the former controls whether the in-process runner exists; the latter controls
  whether a specific schedule registers/fires.
- Docker examples must not accidentally set `DOPILOT_AUTH_DISABLED=true` for the
  default stack.
