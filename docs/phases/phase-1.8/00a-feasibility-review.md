# Feasibility Review

## Proposed Direction

- Summary: Phase 1.8 performs a clean domain reorganization before Python wheel
  script support. It introduces first-class build artifacts, renames task
  templates to execution templates, hard-cuts the public API/Web vocabulary to
  Task/Execution, adds schedule overrides, and preserves Redis/disk/agent seam
  compatibility.
- Source discussion or draft: User discussion on 2026-06-20, followed by two
  Claude feasibility checks run by Codex.

## Claude Feedback

### Verdict

- Feasible with changes.

### Blockers

- Build artifact identity must be defined before implementation. Current
  Scrapy artifacts are primarily filesystem manifests keyed by sha256, while
  the existing `scrapy_artifacts` table is not a stable artifact entity.
- Existing templates may have only JSON artifact descriptors or empty artifact
  payloads, so the migration must define a backfill policy before making
  artifact binding mandatory.

### Risky Assumptions

- `task_type` currently behaves as an executor discriminator; the new model
  should avoid treating it as a core domain field if the intent is build
  artifact type.
- Public `execution_id` will mean atomic execution after the clean-cut, while
  Redis/disk/agent seam `execution_id` still means parent task. Boundary
  serializers and log endpoints are the highest-risk area.
- Public API hard-cut is acceptable only because dopilot is a private
  single-admin greenfield application and the bundled SPA is the expected
  client.
- Task-level resolved snapshots are sufficient for artifact reproducibility in
  Phase 1.8; per-execution artifact snapshots are unnecessary unless future
  per-node artifact variance is introduced.

### Questions

- Should build artifacts be a real table or remain JSON-only? Codex asked the
  user; the user chose a real DB entity.
- Should the public API/Web clean-cut happen in Phase 1.8? The user chose to
  clean historical leftovers in this phase.
- Should internal `task_type` be cleaned up too? The user chose a thorough
  cleanup; Codex will keep `task_type` only as a frozen wire field where needed.

### Suggested Scope Or Sequencing Changes

- Implement as bounded packets inside one phase:
  1. Build artifact entity and migration/backfill.
  2. Internal discriminator cleanup, with wire translation.
  3. Public API schema/route clean-cut.
  4. Web SPA clean-cut.
  5. Schedule overrides and resolved snapshot precedence.
  6. Direct build artifact run and capability filtering.
- Ship server API and Web changes together because there is no compatibility
  layer.

## Codex Decision

- Accepted with concrete implementation constraints:
  - Create a new `build_artifacts` table instead of renaming
    `scrapy_artifacts`; the old table is a deployment registry/legacy cache and
    not the canonical artifact identity.
  - Use opaque `build_artifacts.id` as the FK and use
    `(artifact_type, content_hash)` as the Scrapy dedup key in Phase 1.8.
  - Backfill build artifacts from existing template JSON descriptors and
    filesystem manifests where possible. Keep DB migration data-preserving.
    Application validation must require build artifact binding for all new or
    updated execution templates.
  - Public API/Web hard-cut to `Task` and `Execution`; no dual response fields.
  - Keep Redis/disk/agent `execution_id`/`attempt_id` and wire `task_type`
    frozen. Translate at boundary code.

## User Escalations

- The user confirmed:
  - Build Artifact should be a real DB entity.
  - Phase 1.8 should thoroughly clean public and internal historical naming
    rather than keep compatibility leftovers.

## Resulting Brief Changes

- The Phase 1.8 brief scopes a larger clean-cut than the first Codex proposal:
  build artifact entity, execution templates, public Task/Execution schemas and
  routes, schedule overrides, ad-hoc direct artifact runs, and capability-based
  dispatch filtering are all in scope.
