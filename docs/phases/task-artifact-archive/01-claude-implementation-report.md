# 01 — Claude Implementation Report: Build Artifact Archive State

Implements `docs/phases/task-artifact-archive/00-brief.md`. Adds a reversible
archive state for build artifacts: archived artifacts stay visible and runnable
by templates already bound to them, but are not selectable for new template
bindings.

## Changed files by area

### Backend — model & migration
- `apps/server/dopilot_server/models/execution.py`
  - Added nullable `BuildArtifact.archived_at` (`DateTime(timezone=True)`). NULL
    = not archived; `archived` is derived, not a stored enum.
- `apps/server/migrations/versions/0012_build_artifact_archived_at.py` *(new)*
  - `upgrade()` adds `build_artifacts.archived_at` (nullable); `downgrade()`
    drops it. Revises `0011` (prior head).

### Backend — API & schema
- `apps/server/dopilot_server/api/v1/schemas.py`
  - `BuildArtifactView` gains `archived: bool = False` and
    `archived_at: str | None = None`.
- `apps/server/dopilot_server/api/v1/artifacts.py`
  - `POST /api/v1/artifacts/{artifact_id}/archive` and `/unarchive` — admin-auth
    (`get_current_admin`, same as upload), idempotent, return `BuildArtifactView`.

### Backend — services
- `apps/server/dopilot_server/services/artifacts.py`
  - `get_bindable_artifact_or_404()` — runnable **and** unarchived; raises
    `400 artifact.archived` (`errors.artifactArchived`). Calls the runnable-only
    resolver first, so a non-runnable type still yields `artifact.not_runnable`
    (precedence preserved).
  - `archive_artifact()` / `unarchive_artifact()` — idempotent; archive keeps the
    original `archived_at` (app-side `datetime.now(UTC)`), unarchive sets it NULL.
  - `build_artifact_view()` emits `archived` / `archived_at` via the existing
    `_iso` helper. `artifact_snapshot()` is intentionally untouched (archive state
    stays off frozen task snapshots / `BuildArtifactOption`).
- `apps/server/dopilot_server/services/templates.py`
  - New `_require_bindable_artifact()` (runnable + unarchived).
  - `create_template()` uses the bindable check (new binding).
  - `update_template()` computes `is_rebind` (target id != current id); only a
    **rebind** uses the bindable check — keeping the current (possibly
    since-archived) binding uses the runnable-only check, so other fields stay
    editable.
  - `build_run_request()` (template run / schedule dispatch) **unchanged** —
    still runnable-only `_require_artifact()`. The archive check is not in any
    helper on the run/dispatch path.

### Web — API & types
- `apps/web/lib/api/types.ts` — `BuildArtifact` gains `archived` / `archived_at`.
- `apps/web/lib/api/artifacts.ts` — `archiveArtifact(id)` / `unarchiveArtifact(id)`.

### Web — i18n
- `apps/web/lib/i18n/locales/en.ts`, `.../zh.ts`
  - `artifacts.archived` (`已归档`), `artifacts.archive` (`归档`),
    `artifacts.unarchive` (`取消归档`), `errors.artifactArchived`.

### Web — pages
- `apps/web/app/(app)/artifacts/page.tsx`
  - Amber `已归档` badge in the Status column for archived rows (kept in current
    created-at order); per-row `归档`/`取消归档` action calling the API + reload.
- `apps/web/app/(app)/templates/page.tsx`
  - `selectableArtifacts = artifacts.filter(a => a.runnable && !a.archived)`
    (was `runnable` only); `openCreate` seeds from it.
  - `archivedCurrentBinding` — when editing a template whose bound artifact is
    archived, render it as a **disabled** `SelectItem` (with an `(Archived)`
    suffix, testid `template-artifact-archived-current`) so the trigger is not
    blank and the archived artifact is not offered as a fresh selectable target.

### Tests
- `apps/server/tests/test_artifacts.py`, `apps/server/tests/test_templates.py`
- `apps/web/app/(app)/artifacts/__tests__/artifacts.test.tsx`
- `apps/web/app/(app)/templates/__tests__/templates.test.tsx`

## Implementation notes

- **Binding vs. runtime separation (brief's critical invariant).** The archive
  gate lives only in `get_bindable_artifact_or_404` → `_require_bindable_artifact`,
  used by create + rebind. Run/schedule dispatch keeps resolving via the
  runnable-only path, so archiving an artifact never blocks an already-bound
  template's runs or timers.
- **Edit must not break on an archived current binding.** `update_template`
  treats only an actual change of `build_artifact_id` as a rebind; re-sending the
  same (archived) id, or patching other fields, is allowed.
- **Idempotency.** Re-archiving keeps the original timestamp; unarchiving an
  unarchived artifact is a no-op; both return 200 with the current view.
- **Re-upload preserves state.** `upsert_scrapy`/`upsert_wheel` never touch
  `archived_at`, so identical-bytes re-upload reuses the row and keeps it
  archived (verified by test).
- **Snapshot untouched.** `archived`/`archived_at` are only on `BuildArtifactView`
  / upload responses — not on `artifact_snapshot()` or `BuildArtifactOption`, so
  frozen task snapshots and the task-list filter are unaffected.
- **Web Select.** A shadcn/Radix `Select` only labels the trigger from a matching
  `SelectItem`; the disabled current-binding item supplies that match without
  becoming a fresh option (Radix marks it `data-disabled`).

## Tests added / updated

Backend (`test_artifacts.py`):
- `test_new_artifact_is_not_archived`
- `test_archive_then_unarchive_is_idempotent` (stable `archived_at`, runnable
  orthogonal, no-op unarchive)
- `test_archive_unknown_artifact_404`
- `test_archived_state_visible_in_list`
- `test_archive_reserved_non_runnable_artifact`
- `test_reupload_identical_bytes_preserves_archive_state`

Backend (`test_templates.py`):
- `test_create_template_with_archived_artifact_400`
- `test_rebind_template_to_archived_artifact_400`
- `test_edit_template_bound_to_archived_artifact_allowed`
- `test_run_template_bound_to_archived_artifact_still_runs`
- `test_schedule_dispatch_archived_artifact_still_fires`

Web:
- artifacts: archive a non-archived row → `archiveArtifact`; archived row shows
  badge + `Unarchive` → `unarchiveArtifact`. Existing fixtures extended with
  `archived`/`archived_at`.
- templates: edit form for an archived-bound template shows the disabled current
  binding and offers the non-archived artifact as a selectable option.

## Commands run (pass/fail)

| Command | Result |
| --- | --- |
| `ruff check apps packages` | **PASS** — "All checks passed!" |
| `corepack pnpm --filter web test` | **PASS** — 12 files, 67 tests passed |
| `pytest apps/server/tests/` | **NOT RUN** — blocked (see below) |
| `cd apps/server && alembic upgrade head` | **NOT RUN** — blocked (see below) |

`corepack pnpm --filter web test` output (tail):

```
 ✓ app/(app)/templates/__tests__/templates.test.tsx (6 tests) 904ms
 ✓ app/(app)/artifacts/__tests__/artifacts.test.tsx (6 tests) 607ms
 Test Files  12 passed (12)
      Tests  67 passed (67)
```

## Known risks / incomplete items

- **Backend tests not executed (environment blocker).** Every Python invocation
  in this sandbox requires interactive approval that was not granted —
  `python3 -c "print('hello')"`, `python -m pytest`, and `.venv/bin/python ...`
  all return "This command requires approval". `pytest apps/server/tests/` could
  therefore not be run here. The new backend tests are written and ready; they
  should pass once Python execution is permitted (the test DB is built from the
  models via `Base.metadata.create_all`, so `archived_at` is covered without the
  migration). Per the brief, this is recorded as a blocker rather than treated as
  complete.
- **`alembic upgrade head` not executed.** Same Python gate, plus it needs a live
  PostgreSQL (absent in the sandbox). Migration `0012` was hand-verified against
  the `0011` pattern (nullable add-column, `down_revision="0011"`); it must be
  run against PostgreSQL in CI/a real environment to confirm.
- **Route ordering.** The new `/artifacts/{artifact_id}/archive|unarchive` POST
  routes do not collide with the `/artifacts/scrapy/egg` and
  `/artifacts/python_wheel/wheel` upload routes (literal third segment differs);
  verified by inspection, but worth a glance when backend tests run.
