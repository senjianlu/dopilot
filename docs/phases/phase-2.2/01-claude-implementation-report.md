# Phase 2.2 — Claude Implementation Report

Platform hardening before declarative deployment manifests: env-driven config,
fail-closed web auth, unique template/schedule names, and schedule-level
enabled/disabled timer gating. Scope held exactly to the brief — no
`dopilot.toml`, no `dopilot_sync.py`, no labels/source/ownership, no reconciler,
no artifact-uniqueness change, no agent/Redis/executor/log-consumer change.

## Changed files by area

### Docs (updated first, per required order)
- `docs/dopilot/00-requirements.md`
  - Decision #12: web admin auth is now **fail-closed** (refuses to boot without
    all three creds unless `DOPILOT_AUTH_DISABLED=true`); agent machine auth
    stays config-present-or-off. Anonymous mode is no longer entered silently.
  - Decision #15: added a phase-2.2 note — unique `execution_templates.name` /
    `schedules.name` (409 on conflict) and row-level `schedules.enabled`
    (default false; disabled = paused timer but still trigger-now-able),
    distinct from global `[scheduler].enabled`.
- `docs/dopilot/08-docker-deployment.md`
  - Auth table row rewritten to fail-closed + `DOPILOT_AUTH_DISABLED=true`
    escape hatch.
  - `[auth]` config comment block rewritten for fail-closed + `DOPILOT_*` env
    override examples.

### Config schema + loader
- `apps/server/dopilot_server/config/settings.py`
  - `AuthSettings.disabled: bool = False` (explicit dev/anonymous flag).
  - `AuthSettings.enabled` is now `not disabled and all-three-creds-non-empty`.
  - Module docstring updated to describe fail-closed posture.
- `apps/server/dopilot_server/config/loader.py`
  - `_STR_OVERRIDES` / `_INT_OVERRIDES` / `_BOOL_OVERRIDES` declarative tables
    covering every `DOPILOT_*` var listed in the brief (+ `DOPILOT_DATABASE_URL`
    / `DOPILOT_REDIS_URL` folded in; behavior preserved).
  - `_parse_int` / `_parse_bool` raise `ConfigError` naming the env var on a
    malformed value; bool accepts `true/false/1/0/yes/no/on/off`.
  - `_apply_env_overrides()` (env wins over TOML) + `_enforce_fail_closed_auth()`
    run inside `load_settings()` after `Settings.model_validate(...)`. Direct
    `Settings.model_validate(...)` stays unvalidated for tests/overrides.

### Models + migrations
- `apps/server/dopilot_server/models/scheduling.py`
  - `ExecutionTemplate.name` and `Schedule.name` → `unique=True` (so SQLite
    `create_all()` test DB enforces it).
  - `Schedule.enabled: Mapped[bool]` (`Boolean`, `nullable=False`,
    `default=False`).
  - Stale "pause/resume out of scope" docstring replaced.
- `apps/server/migrations/versions/0010_unique_template_schedule_names.py` (new)
  - Deterministic dedup (`ROW_NUMBER() OVER (PARTITION BY name ORDER BY
    created_at, id)`; non-first rows renamed to
    `<name>__duplicate__<id-prefix>`), then `uq_execution_templates_name` /
    `uq_schedules_name` unique constraints. Rows preserved.
- `apps/server/migrations/versions/0011_schedule_enabled.py` (new)
  - `ALTER TABLE schedules ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT false`.

### Services
- `apps/server/dopilot_server/services/templates.py`
  - `_ensure_unique_name(session, name, exclude_id=)` → `ApiError(409,
    "template.name_conflict", ...)`. Called in `create_template` and
    `update_template` (self-exclusion on update) before commit.
- `apps/server/dopilot_server/services/schedules.py`
  - `_ensure_unique_name(...)` → `ApiError(409, "schedule.name_conflict", ...)`
    in create/update (self-exclusion).
  - `create_schedule` defaults `enabled=False` (explicit true to enable);
    `update_schedule` patches `enabled` when provided.
  - `list_enabled_schedules()` helper; `list_schedules()` still returns all rows
    (disabled stay visible).
  - `fire_timer()` defensively no-ops when `not schedule.enabled` (before the
    backlog check). `trigger_now()` unchanged (never checks enabled).
  - `schedule_view()` exposes `enabled`. Docstring updated.

### API schemas + scheduler runner
- `apps/server/dopilot_server/api/v1/schemas.py`
  - `ScheduleView.enabled: bool = False`; `ScheduleCreateRequest.enabled:
    bool = False`; `ScheduleUpdateRequest.enabled: bool | None = None`
    (PUT uses `exclude_unset`, so absent = unpatched).
- `apps/server/dopilot_server/scheduler/runner.py`
  - `reload()` registers from `list_enabled_schedules()` only. Docstring updated.

### Config examples
- `configs/server.example.toml`, `configs/server.docker.toml`
  - Headers document `DOPILOT_*` env overrides + fail-closed auth +
    `DOPILOT_AUTH_DISABLED=true` dev escape hatch. No placeholder credentials
    removed; default stacks stay bootable (creds present → auth ON; fail-closed
    only triggers on missing creds). Compose `DOPILOT_AUTH_DISABLED` intentionally
    NOT set.

## Implementation notes
- Fail-closed lives only in `load_settings()` (startup boundary). `Settings`
  construction and `AuthSettings.enabled` stay side-effect-free so conftest's
  `Settings.model_validate(...)` and dependency overrides are unaffected.
- 409 conflicts are raised in service code before commit; the DB unique
  constraint is a backstop, avoiding inconsistent raw-IntegrityError responses
  and mid-request session rollback.
- Row-level `schedules.enabled` is deliberately distinct from global
  `[scheduler].enabled`. The shared list path is unfiltered; only the runner
  (`reload()`) and `fire_timer()` consult `enabled`, so disabled rows remain
  visible/editable/deletable and trigger-now-able.
- `enabled` model uses `default=False` (Python side, ORM inserts); the Postgres
  `server_default false` is set in migration 0011, matching the model posture.

## Migrations added
- `0010_unique_template_schedule_names` (dedup + unique constraints; reversible).
- `0011_schedule_enabled` (add column, server default false; reversible).

## Tests added / updated
- `apps/server/tests/test_config.py`
  - `test_redis_agents_defaults_when_absent`: minimal TOML now sets
    `[auth].disabled=true` (otherwise fail-closed rejects it).
  - Replaced `test_auth_off_when_partial` with `test_fail_closed_when_partial_auth`
    and added `test_fail_closed_when_no_auth_section`,
    `test_auth_disabled_allows_anonymous`, `test_auth_disabled_via_env`,
    `test_env_overrides_scalars`, `test_env_fills_missing_auth_to_pass_fail_closed`,
    `test_env_invalid_int_raises`, `test_env_invalid_bool_raises`,
    `test_auth_settings_enabled_variants`.
- `apps/server/tests/test_templates.py`
  - `test_create_template_duplicate_name_409`,
    `test_rename_template_to_existing_name_409`,
    `test_rename_template_to_same_name_ok` (self-exclusion).
- `apps/server/tests/test_schedules.py`
  - `fire_timer` dispatch + coalesce tests now create `enabled=True` schedules.
  - Added `test_schedule_defaults_enabled_false`,
    `test_create_schedule_enabled_true`, `test_update_schedule_enabled_toggle`,
    `test_disabled_schedule_trigger_now_still_runs`,
    `test_fire_timer_noop_when_disabled`,
    `test_create_schedule_duplicate_name_409`,
    `test_rename_schedule_to_existing_name_409`.
- `apps/server/tests/test_scheduler_runner.py`
  - `_seed_schedule` + the reload test's second schedule now `enabled=True`.
  - Added `test_reload_skips_disabled_schedules` (enable-then-reload registers).

## Commands run — pass/fail
> **Claude could not run commands** (this sandbox gates all code execution behind
> manual per-command approval; every command below returned `This command
> requires approval` and did not run for Claude). **Codex ran them** during the
> phase 2.2 review (`docs/phases/phase-2.2/02-codex-review.md`); the verified
> outcomes are recorded below.

```bash
# required (narrow):
PYTHONPATH=apps/server:packages/protocol:packages/client .venv/bin/python -m pytest apps/server/tests/test_config.py apps/server/tests/test_auth.py apps/server/tests/test_templates.py apps/server/tests/test_schedules.py apps/server/tests/test_scheduler_runner.py
ruff check apps packages
cd deploy/docker && docker compose config

# broader (run because shared config/schemas changed):
PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client .venv/bin/python -m pytest
# web: API schedule schema gained `enabled` (optional, default false) — additive,
# should not require UI changes; run only if web typing/tests reference it:
corepack pnpm --filter web test
corepack pnpm --filter web build
```

Outcome (Codex-run, per `02-codex-review.md`):

- Narrow server suite (`test_config.py test_auth.py test_templates.py
  test_schedules.py test_scheduler_runner.py`) — **73 passed**.
- Full suite (`PYTHONPATH=apps/server:apps/agent:packages/protocol:packages/client
  .venv/bin/python -m pytest`) — **454 passed**.
- `.venv/bin/ruff check apps packages` — **passed**.
- `cd deploy/docker && docker compose config` — **passed**.
- `corepack pnpm --filter web test` — **57 passed**.
- `corepack pnpm --filter web build` — **passed**.
- Temporary PostgreSQL `alembic upgrade head` — **passed**.
- Temporary PostgreSQL duplicate-name migration smoke (`upgrade 0009`, insert
  duplicate template/schedule names, `upgrade head`) — **passed**; duplicate rows
  were preserved and renamed, `enabled=false` backfilled.

## Known risks / incomplete items
- **Verification** (was a Claude approval-gate blocker) — **resolved by the
  Codex run** above. Highest-confidence concern was the broad `pytest` suite: any
  other test that builds a credential-less TOML through `load_settings()` would
  now hit fail-closed; I audited the tree and only `test_config.py` did, and the
  full run (454 passed) confirms. `make_settings` in conftest uses
  `Settings.model_validate(...)` directly (no fail-closed), so auth-off fixtures
  are unaffected.
- **Migration smoke** (`alembic upgrade head`, 0010 dedup preserving rows)
  requires a real PostgreSQL; not available in Claude's sandbox. SQLite test DB
  exercises the ORM-level uniqueness + `enabled` via `create_all()`. The Codex
  run executed the PG-typed migrations on a temporary PostgreSQL and confirmed
  the "duplicate-name migration preserves rows" acceptance (rows preserved and
  renamed, `enabled=false` backfilled).
- `enabled` Postgres server_default lives only in migration 0011 (model has the
  Python default). No autogenerate runs here, so no drift flag; intentional and
  consistent with the existing migration style (e.g. 0005 `source`).
