# Built-In Artifact Refresh Brief

## Goal

Ensure the built-in default crawler (`dopilot_clock`) and built-in default
script (`dopilot-demo`) are applied through the normal artifact flow on every
server startup, not only when Docker initializes an empty `/server-data` volume.

Expected behavior:

- If the built-in crawler/script bytes are unchanged, startup is idempotent and
  does not create duplicate artifacts.
- If the built-in crawler/script changes, the new bytes produce a new sha256,
  new manifest, and new `build_artifacts` row through the existing artifact
  store/upsert flow.
- Existing older artifacts, including user-uploaded or modified artifacts, are
  not overwritten or deleted.

This supports the default examples being updated with runtime-context logging:

- `dopilot_clock` logs Dopilot runtime context at run start and defaults to a
  45-second duration.
- `dopilot-demo` logs Dopilot runtime context environment variables at run
  start.

## Context

Relevant files and decisions:

- `CLAUDE.md`
- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/task-runtime-context/00-brief.md`
- `apps/server/dopilot_server/app.py`
- `apps/server/dopilot_server/services/artifacts.py`
- `apps/server/dopilot_server/artifacts/scrapy_store.py`
- `apps/server/dopilot_server/artifacts/wheel_store.py`
- `deploy/docker/Dockerfile`
- `examples/scrapy_clock/dopilot_clock/spiders/clock.py`
- `tests/fixtures/python_wheel_demo/main.py`
- `tests/fixtures/python_wheel_demo/build_wheel.py`

Current state:

- Docker build seeds default artifact files into `/server-data/artifacts/...`.
  Docker named volumes only copy that image content when the volume is first
  created. Existing volumes do not automatically receive updated built-in
  artifacts.
- Server artifact stores are content-addressed by sha256 and write manifests.
- `build_artifacts` rows are deduped by `(artifact_type, content_hash)`.
- Listing artifacts reconciles filesystem manifests to DB rows, but only for
  artifacts already present under the configured artifact store.

## In Scope

- Keep the already requested default example behavior:
  - `dopilot_clock` default `duration_seconds` is 45 seconds.
  - `dopilot_clock` logs all `DOPILOT_*` values visible through OS env and Scrapy
    settings at run start.
  - `dopilot-demo` logs all `DOPILOT_*` environment variables at run start.
- Make the Docker image carry built-in default artifact bytes in a stable image
  path separate from `/server-data`, so the server can import them on every
  startup even when `/server-data` is an existing volume.
- On server startup, import built-in Scrapy eggs and Python wheels from that
  image path using the same `ScrapyArtifactStore.save()` /
  `WheelArtifactStore.save()` and `upsert_scrapy()` / `upsert_wheel()` flows as
  normal uploads/reconciliation.
- Keep the startup import idempotent and content-hash based. If the same hash
  already has both artifact-store files and a DB row, startup must be a true
  no-op for that artifact: do not rewrite manifests and do not refresh display
  metadata.
- If the same hash already has a DB row, preserve that row's existing display
  metadata. Startup may repair missing artifact-store bytes/manifests for that
  hash, but it must not mutate the existing row.
- Add focused tests for startup import/idempotency if practical without starting
  Redis; otherwise add service-level tests for the import helper.

## Out Of Scope

- Deleting, replacing, hiding, or mutating older default artifacts.
- Deleting or replacing user-uploaded artifacts.
- Pinning a single "active default" artifact in templates/schedules.
- Frontend UI changes.
- Custom environment variable management.
- Rebuilding or changing test-only Scrapy fixtures under
  `tests/fixtures/scrapy_demo`.

## Required Implementation Order

1. Ask Claude for feasibility validation before finalizing implementation.
2. Finalize the startup import design and artifact path convention.
3. Implement the built-in artifact import helper and wire it into server
   startup.
4. Ensure Docker build places current built-in artifact bytes in the import
   path.
5. Add focused tests.
6. Run verification and Codex review.

## Acceptance Criteria

- A server startup with built-in artifact files present imports `dopilot_clock`
  and `dopilot-demo` into the configured artifact store and DB if their hashes
  are not already present.
- Repeating startup with unchanged built-ins does not create duplicate
  `build_artifacts` rows and does not rewrite artifact manifests or DB metadata.
- Changing built-in bytes creates a new hash/new artifact without deleting old
  hashes.
- User-uploaded artifacts with different hashes are not overwritten or deleted.
- If a user-uploaded artifact has the same hash as a built-in artifact, the
  existing row's display metadata is preserved.
- `dopilot_clock` defaults to 45 seconds.
- Running the page-visible default `dopilot_clock` logs Dopilot `DOPILOT_*`
  context at start.
- Running the page-visible default `dopilot-demo` logs Dopilot `DOPILOT_*`
  environment variables at start.

## Required Tests

- Unit/service test for built-in artifact import from a temporary built-in root
  into a temporary artifact store.
- Idempotency test for repeated import.
- Test that a changed built-in content hash creates an additional artifact row.
- Focused smoke/unit test or static assertion for `dopilot_clock` default
  duration and Dopilot logging behavior.
- Focused verification that the rebuilt `dopilot-demo` wheel contains the new
  Dopilot env logging code.

## Required Commands

```bash
PYTHONPATH=packages/protocol:apps/server:apps/agent .venv/bin/python -m pytest apps/server/tests packages/protocol/tests apps/agent/tests
.venv/bin/ruff check apps packages
git diff --check
```

If Dockerfile behavior is materially changed, also run at least:

```bash
cd deploy/docker && docker compose config
```

## Risks To Watch

- Startup import must not require Redis to be up before the DB/artifact import
  completes.
- Startup import must not write into `/server-data` image-layer defaults only;
  it must copy from a stable image path into the configured artifact store.
- Repeated imports should not refresh metadata for an existing same-hash DB row
  and should not create duplicate DB rows.
- Built-in import failures should be visible in logs. Decide during feasibility
  whether invalid built-in artifacts should fail startup or log-and-continue.

## Codex Decisions After Feasibility

- Invalid/corrupt built-in artifacts fail server startup. These files are part
  of the release image, so corruption indicates a bad image/build rather than a
  user data issue.
- Same-hash existing DB rows are treated as canonical and are not refreshed by
  startup import. This avoids mutating a user-uploaded row that happens to have
  identical bytes.
- `/app/builtin-artifacts` is the production image-layer refresh source.
  `DOPILOT_BUILTIN_ARTIFACTS_DIR` may override it for tests and advanced
  operator scenarios.
