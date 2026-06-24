# Built-In Artifact Refresh Feasibility Review

## 1. Verdict: feasible with changes

The proposed direction is feasible and fits dopilot's current artifact model:
the stores are content-addressed, `build_artifacts` is deduped by
`(artifact_type, content_hash)`, and the server lifespan can run the import
before Redis is constructed (`apps/server/dopilot_server/app.py:140`).

Do not accept the current draft as-is. The startup helper needs stronger
idempotency semantics and an explicit failure policy before implementation
continues.

## 2. Blocking issues

- The draft helper rewrites artifact files/manifests and marks `changed=True`
  for every successful built-in on every startup
  (`apps/server/dopilot_server/services/builtin_artifacts.py:43-67`). Because
  `ScrapyArtifactStore.save()` / `WheelArtifactStore.save()` create fresh
  manifests with a new `uploaded_at`, and `upsert_*` refreshes existing row
  metadata (`apps/server/dopilot_server/services/artifacts.py:83-88`), unchanged
  built-ins can still churn filesystem metadata and `build_artifacts.updated_at`.
  This violates the practical meaning of "unchanged startup is idempotent" even
  if row count does not increase.
- The brief does not decide whether invalid/corrupt built-in artifacts should
  fail startup or log-and-continue. The draft logs and continues
  (`builtin_artifacts.py:52-64`). That may hide a bad image build and leave the
  default examples missing.
- The same-hash metadata policy is unresolved. If a user-uploaded artifact has
  identical bytes to a built-in but different display filename/name, the
  built-in import can refresh that canonical row's metadata. That is consistent
  with content-hash dedupe but may conflict with "user artifacts are not
  overwritten" unless Codex explicitly defines same-hash artifacts as one
  canonical artifact.

## 3. Risky assumptions

- Startup import currently runs only on the real lifespan path where
  `owns_runtime` is true. That is acceptable for production startup, but tests
  using dependency overrides will need service-level coverage rather than
  assuming ASGITransport exercises the import.
- Docker still seeds `/server-data/artifacts/...` for clean volumes while also
  copying built-ins to `/app/builtin-artifacts/...`
  (`deploy/docker/Dockerfile:55-105`). This is compatible, but the older seed
  path should be treated as legacy convenience; the startup import path must be
  the authoritative refresh mechanism.
- The acceptance criteria for "page-visible default" implicitly depends on
  rebuilt built-in binaries. Source edits to `examples/scrapy_clock/...` and
  `tests/fixtures/python_wheel_demo/main.py` are not enough; verification must
  prove the egg/wheel bytes copied into `/app/builtin-artifacts` contain those
  changes.

## 4. Missing decisions or questions for Codex

- Should a malformed built-in artifact fail server startup? Recommendation:
  fail startup for the default image path because a broken built-in indicates a
  bad release image; allow tests/custom paths to opt into log-and-continue only
  if needed.
- Should unchanged built-ins be a true no-op when both the artifact store file
  and DB row already exist? Recommendation: yes. Compute/validate the manifest,
  check existing DB row and store files first, and skip `save()`/`upsert_*`
  unless the file/manifest or DB row is missing or the content hash is new.
- Is same-hash user metadata allowed to be refreshed by built-in import?
  Recommendation: for existing rows, avoid changing display metadata during
  startup unless the row was originally created by the built-in importer. Since
  there is no provenance field today, prefer "same hash exists -> ensure store
  file exists, but do not mutate row metadata" for this task.
- Should the built-in root be configurable by env (`DOPILOT_BUILTIN_ARTIFACTS_DIR`)
  or fixed to the image path? Configurability is useful for tests, but the
  production convention should remain a stable image-layer path such as
  `/app/builtin-artifacts`.

## 5. Suggested scope cuts or sequencing changes

- Keep the implementation as a small service helper plus one startup call. Do
  not add migrations, provenance columns, template pinning, or UI selection in
  this task.
- Implement the import helper as an explicit two-phase operation: discover and
  validate built-in files, then apply only missing/new hashes. This keeps
  invalid-artifact handling and idempotency testable without Redis.
- Add focused service tests for import, repeated import, changed bytes, and
  preservation of unrelated/user hashes. Add static/package verification for
  `dopilot_clock` default duration/logging and for the demo wheel contents.
- Leave the existing `/server-data` Docker seed in place for backward-compatible
  clean-volume behavior, but update comments so future work knows
  `/app/builtin-artifacts` is the refresh source of truth.
