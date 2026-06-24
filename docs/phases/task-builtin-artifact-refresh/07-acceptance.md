# Acceptance: Built-In Artifact Refresh

## Accepted State

The server now refreshes built-in default artifacts on startup from
`/app/builtin-artifacts` (or `DOPILOT_BUILTIN_ARTIFACTS_DIR` when overridden).

Behavior:

- unchanged built-ins are a true no-op;
- changed built-ins create new hash-addressed artifacts;
- old/default/user-uploaded artifacts are not deleted or overwritten;
- same-hash existing DB metadata is preserved;
- missing store files for an existing same-hash row are repaired;
- corrupt built-ins fail startup.

The page-visible examples now include the requested runtime-context logging:

- `dopilot_clock` logs `DOPILOT_*` env and Scrapy settings at run start and
  defaults to 45 seconds.
- `dopilot-demo` logs `DOPILOT_*` environment variables at run start, and its
  committed wheel was rebuilt with that source.

## Verified

- Feasibility checked with Claude.
- Read-only implementation review checked with Claude.
- Full protocol/server/agent tests passed: `520 passed`.
- Ruffle/lint and diff checks passed.
- Docker compose config passed.
- Docker image build passed for `rabbir/dopilot:latest`.
- Real browser/page E2E passed for both built-in `dopilot_clock` and
  `dopilot-demo`, including runtime-context log assertions.
- Isolated compose cleanup passed with no remaining project containers or
  volumes.

## Deferred

- None for the requested scope.
