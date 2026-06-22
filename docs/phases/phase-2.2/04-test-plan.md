# Phase 2.2 Test Plan

## Behavior Under Test

- Config loader env overrides and fail-closed Web admin auth.
- Explicit anonymous/dev auth mode via `DOPILOT_AUTH_DISABLED=true`.
- Unique execution-template and schedule names, including rename conflicts.
- Schedule row-level `enabled` default false, update behavior, runner filtering,
  timer no-op, and trigger-now bypass.
- Alembic migrations for duplicate-name cleanup and `schedules.enabled`.
- Existing server/agent/protocol/web behavior after shared schema/config changes.

## Unit Coverage

- `apps/server/tests/test_config.py`
  - auth fail-closed missing/partial credentials;
  - explicit auth-disabled TOML/env;
  - env string/int/bool overrides;
  - malformed int/bool env values;
  - `AuthSettings.enabled` variants.
- `apps/server/tests/test_templates.py`
  - duplicate template create conflict;
  - rename-to-existing conflict;
  - rename-to-same self-exclusion.
- `apps/server/tests/test_schedules.py`
  - default `enabled=false`;
  - create/update enabled;
  - disabled trigger-now still runs;
  - disabled timer no-op;
  - duplicate schedule create/rename conflicts.
- `apps/server/tests/test_scheduler_runner.py`
  - reload registers enabled schedules only and registers a schedule after it is
    enabled.

## Integration Coverage

- Full Python suite: server, agent, and protocol tests.
- Temporary PostgreSQL Alembic smoke:
  - `alembic upgrade head`;
  - upgrade to `0009`, insert duplicate template/schedule names, upgrade to
    `head`, and verify duplicate rows are preserved/renamed with
    `enabled=false`.

## Frontend Coverage

- `corepack pnpm --filter web test`
- `corepack pnpm --filter web build`

## Smoke / Manual Coverage

- `cd deploy/docker && docker compose config`

## Regression Risks

- Production config accidentally falls back to anonymous admin:
  covered by fail-closed loader tests.
- Test fixtures or dependency overrides break because fail-closed validation is
  placed too low:
  covered by full Python suite.
- Disabled schedules hidden from API:
  covered by schedule API list/get tests.
- Disabled schedules still fire on timer:
  covered by service and runner tests.
- Existing duplicate DB rows fail migration:
  covered by temporary PostgreSQL duplicate-name migration smoke.

## Commands Run

```bash
PYTHONPATH=apps/server:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
.venv/bin/ruff check apps packages
cd deploy/docker && docker compose config
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Temporary PostgreSQL migration smokes were also run with Docker `postgres:16`.

## Results

See `05-codex-verification-report.md`.
