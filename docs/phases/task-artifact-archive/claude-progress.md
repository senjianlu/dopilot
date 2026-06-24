# Claude progress — task-artifact-archive

Status: **implementation complete; backend tests blocked by environment** (see
blockers).

## Done

### Backend
- `models/execution.py`: added nullable `BuildArtifact.archived_at`
  (aware-UTC `DateTime(timezone=True)`).
- `migrations/versions/0012_build_artifact_archived_at.py`: new migration
  (revises `0011`) adding `build_artifacts.archived_at`.
- `api/v1/schemas.py`: `BuildArtifactView` now exposes derived `archived: bool`
  and `archived_at: str | null`.
- `services/artifacts.py`:
  - `build_artifact_view()` emits `archived` / `archived_at`.
  - `get_bindable_artifact_or_404()` (runnable **and** unarchived) — for new
    bindings only.
  - `archive_artifact()` / `unarchive_artifact()` — idempotent, stable timestamp.
- `api/v1/artifacts.py`: idempotent `POST /artifacts/{id}/archive` and
  `/unarchive`, admin-authenticated, returning `BuildArtifactView`.
- `services/templates.py`:
  - new `_require_bindable_artifact()` (runnable + unarchived) used by **create**
    and **rebind-on-update only**;
  - `build_run_request()` (run / schedule dispatch) still uses the runnable-only
    `_require_artifact()` — archive state is never re-checked at run time;
  - `update_template()` only applies the bindable check when the binding actually
    **changes**, so a template bound to a since-archived artifact stays editable.

### Web
- `lib/api/types.ts`: `BuildArtifact` gains `archived` / `archived_at`.
- `lib/api/artifacts.ts`: `archiveArtifact()` / `unarchiveArtifact()`.
- `lib/i18n/locales/{en,zh}.ts`: `artifacts.archived/archive/unarchive`,
  `errors.artifactArchived` (`归档` / `取消归档`).
- `artifacts/page.tsx`: archived badge in the Status column + `归档`/`取消归档`
  action per row.
- `templates/page.tsx`: picker now excludes archived (`runnable && !archived`);
  an archived **current** binding is rendered as a disabled, non-selectable
  item so the trigger is never blank and the archived artifact is not offered as
  a fresh target.

### Tests
- `tests/test_artifacts.py`: archive/unarchive idempotency, 404, list
  visibility, reserved-type archive, identical-bytes re-upload preserves state.
- `tests/test_templates.py`: create/rebind-to-archived rejected; edit other
  fields on an archived-bound template allowed; run + schedule trigger-now of an
  archived-bound template still dispatch.
- Web tests: archive/unarchive actions + badge; edit form shows archived current
  binding as disabled and not a fresh option.

## Verification
- `ruff check apps packages` → **passed**.
- `corepack pnpm --filter web test` → **passed** (12 files, 67 tests).
- `pytest apps/server/tests/` → **BLOCKED** (see below).
- `alembic upgrade head` → **BLOCKED** (see below).

## Blockers
- Any Python execution is gated in this sandbox: even
  `python3 -c "print('hello')"` returns "This command requires approval", so
  `pytest` and `alembic` could not be run autonomously. Backend correctness was
  established by code review against existing patterns; the new tests are written
  and ready to run once Python execution is approved.
- `alembic upgrade head` additionally needs a live PostgreSQL, which the sandbox
  does not provide. The migration was hand-verified against the `0011` pattern.
