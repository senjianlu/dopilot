# Codex Review: Built-In Artifact Refresh

## Findings

No blocking findings.

Claude's implementation review found one medium test coverage gap: static
coverage for the `dopilot_clock` default/logging and the rebuilt
`dopilot-demo` wheel contents. That gap was fixed by adding assertions in
`apps/server/tests/test_builtin_artifacts.py`.

## Review Notes

- Startup import runs before Redis runtime construction, so it does not depend
  on Redis being available.
- Same-hash complete state is a true no-op: no `save()` call, no manifest
  rewrite, no DB metadata refresh.
- Same-hash existing DB rows preserve display metadata, preventing startup from
  mutating a user-uploaded row with identical bytes.
- Missing store files for an existing DB row are repaired.
- Invalid built-in artifacts fail startup, matching the Codex decision after
  feasibility review.
- Existing `/server-data` Docker seed remains as clean-volume convenience, while
  `/app/builtin-artifacts` is now the refresh source of truth.

## Residual Risk

- Docker image build itself was not run here. `docker compose config` passed,
  and Python/service tests covered import behavior. A full image build remains
  the natural final deployment verification.
