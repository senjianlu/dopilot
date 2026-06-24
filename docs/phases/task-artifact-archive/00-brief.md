# Task: Build Artifact Archive State

## Goal

Add a reversible archive state for build artifacts.

An archived artifact remains visible and remains usable by execution templates
that already reference it, but it must not be selectable for new template
bindings.

## Confirmed Decisions

- Product wording: `归档` / `取消归档`.
- API/view shape adds derived `archived: boolean`.
- Same-content re-upload must not change archive state. If the uploaded bytes
  match an archived artifact, return/reuse that artifact and keep it archived.
- Do not add a broad artifact status state machine. Use a nullable archive
  timestamp and derive `archived`.
- Use application-side aware UTC timestamps for archive actions, serialized with
  the existing `_iso` helpers.
- Archive/unarchive is idempotent: return 200 with the current artifact view.
  Re-archiving an already archived artifact keeps the original `archived_at`
  timestamp; unarchiving an already unarchived artifact remains a no-op.
- Archive is orthogonal to `runnable`: allow archiving any artifact type,
  including reserved/non-runnable types.
- Artifact list ordering does not change for archived artifacts; keep current
  created-at ordering and expose archive state with fields/badges.
- Task list build-artifact filters are based on frozen task snapshots and are
  not affected by live archive state.

## Required Behavior

### BuildArtifact model and API

- Add nullable `archived_at` to `build_artifacts`.
- `GET /api/v1/artifacts` and upload responses include:
  - `archived: boolean`
  - `archived_at: string | null`
- `runnable` keeps its current meaning: whether the artifact type can run
  (`scrapy`, `python_wheel`). It must not be overloaded to mean selectable.
- Add idempotent action endpoints:
  - `POST /api/v1/artifacts/{artifact_id}/archive`
  - `POST /api/v1/artifacts/{artifact_id}/unarchive`
- Archive/unarchive responses return the same `BuildArtifactView` shape as list
  rows.
- Re-uploading an existing artifact by `(artifact_type, content_hash)` refreshes
  display metadata as today but must not clear or set `archived_at`.

### ExecutionTemplate rules

- Creating an execution template with an archived artifact is rejected.
- Updating an execution template to change `build_artifact_id` to an archived
  artifact is rejected.
- Existing execution templates already bound to an archived artifact must still:
  - be listed and viewed;
  - be editable for fields other than changing to an archived artifact;
  - be runnable via `POST /api/v1/templates/{id}/run`;
  - remain valid for existing schedules.
- Do not re-check archive state during template run or schedule dispatch.
- The implementation should distinguish:
  - artifact must be runnable for actual execution;
  - artifact must be runnable and unarchived for new/changed template bindings.
- Do not put the archive check in a helper used by template run or schedule
  dispatch paths.

### Web UI

- Build Artifacts page shows archive state and offers `归档` / `取消归档` actions.
- Archived artifacts remain visible in the artifact list.
- Template create/edit artifact picker excludes archived artifacts from
  selectable options.
- Editing a template currently bound to an archived artifact must not break the
  form. It should still show the current binding clearly, but archived artifacts
  must not become selectable as a new binding.
- For a template currently bound to an archived artifact, the current artifact
  may be rendered as a disabled/read-only current item or equivalent clear
  display. The key invariant is that the Select trigger is not blank and the
  archived artifact is not offered as a fresh selectable target.
- Use existing shadcn/ui components and local page patterns.

## Out Of Scope

- Deleting build artifacts.
- Blocking existing template runs or schedule-triggered runs for archived
  artifacts.
- Auto-unarchiving on upload.
- A general artifact status enum.
- Adding archive state to frozen task snapshots or `BuildArtifactOption`.
- Upstream scrapydweb consultation or code reuse.

## Expected Code Areas

- `apps/server/dopilot_server/models/execution.py`
- `apps/server/migrations/versions/`
- `apps/server/dopilot_server/api/v1/artifacts.py`
- `apps/server/dopilot_server/api/v1/schemas.py`
- `apps/server/dopilot_server/services/artifacts.py`
- `apps/server/dopilot_server/services/templates.py`
- `apps/server/tests/`
- `apps/web/lib/api/`
- `apps/web/lib/i18n/locales/`
- `apps/web/app/(app)/artifacts/`
- `apps/web/app/(app)/templates/`

## Acceptance Criteria

- Archived artifacts are visible but marked archived.
- Archive/unarchive endpoints are idempotent and authenticated like other admin
  artifact operations.
- New template creation and template artifact rebinding reject archived
  artifacts.
- Existing templates bound to archived artifacts can still be edited without
  rebinding and can still run.
- Re-uploading identical bytes preserves archive state.
- Backend and web tests cover the changed behavior.

## Required Verification

Run the narrowest useful commands, then broaden if implementation touches shared
contracts:

```bash
pytest apps/server/tests/
ruff check apps packages
corepack pnpm --filter web test
cd apps/server && alembic upgrade head
```

If a command cannot run in the local environment, report the exact blocker.
