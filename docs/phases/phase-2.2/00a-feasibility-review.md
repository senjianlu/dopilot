# Phase 2.2 Feasibility Review

## Proposed Direction

- Summary: implement platform hardening only: env-based config overrides with
  web auth fail-closed, unique execution-template/schedule names, and
  schedule-level enabled/disabled gating.
- Source discussion or draft:
  `/tmp/dopilot-hardening-and-deploy-manifest-plan.md` and the user-confirmed
  scope for phase 2.2: do not implement `dopilot.toml`, `dopilot_sync.py`,
  labels/source ownership, or a manifest reconciler.

## Claude Feedback

### Verdict

- Feasible with changes.

### Blockers

- None.

### Must-Get-Right Implementation Points

- Fail-closed auth validation must live at the config loader/startup boundary,
  not in `Settings` construction or `AuthSettings.enabled`, because tests and
  dependency overrides construct `Settings` directly.
- Template/schedule name uniqueness must be present on ORM metadata as well as
  in Alembic migrations, because the server test database is built with
  `Base.metadata.create_all()`.

### Risky Assumptions

- Create/update name conflicts should be checked in service code and returned as
  explicit 409 API errors, including rename self-exclusion on update.
- Disabled schedules must remain visible through the API list; filtering belongs
  in `ScheduleRunner.reload()` or a separate enabled-list query, not in the
  shared list endpoint.
- `trigger-now` already bypasses timer registration and should remain allowed
  for disabled schedules.
- Default Docker configs currently contain placeholder auth secrets and should
  continue to boot, while still being documented as non-production-safe.
- The row-level `schedules.enabled` field is distinct from global
  `[scheduler].enabled`; docs should call out the difference.

### Questions

- Exact env override surface and naming.
- How tests opt into anonymous mode after fail-closed production loading.
- Whether default compose keeps placeholder credentials or opts into disabled
  auth.
- Confirm `schedules.enabled` default is false.

### Suggested Scope Or Sequencing Changes

- Use two migrations: one for duplicate-name cleanup + unique constraints, and
  one for `schedules.enabled`.
- Update decision-level docs before implementation because this reverses the
  existing config-present-or-off auth stance and the prior "pause/resume out of
  scope" schedule stance.
- Implement in order: auth/config, unique names, schedule enabled.

## Codex Decision

- Accepted with brief changes.

## User Escalations

- None. The user already accepted auth fail-closed with
  `DOPILOT_AUTH_DISABLED=true` and confirmed phase 2.2 should only do hardening.
  Claude's remaining questions are implementation details.

## Resulting Brief Changes

- Pin fail-closed validation to `load_settings()` / production startup.
- Add `AuthSettings.disabled` for explicit anonymous/dev mode, with
  `DOPILOT_AUTH_DISABLED=true` as the documented deployment escape hatch.
- Keep direct `Settings.model_validate(...)` usable in tests; test auth-off
  fixtures must set `auth.disabled=true` explicitly.
- Keep Docker default configs bootable with placeholder credentials, and add env
  overrides so real deployments can inject secrets without mounting TOML.
- Define the initial env override surface in the brief.
- Require ORM metadata uniqueness and Alembic migrations.
- Require disabled schedules to stay listable and manually triggerable.
