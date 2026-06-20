# 07 · Phase 1.8 Acceptance

## Accepted Outcome

Phase 1.8 is accepted from Codex review.

The implementation completes the agreed clean-cut domain model before Phase 2
Python wheel script execution:

- Scrapy egg artifacts are represented as canonical `BuildArtifact` rows.
- Execution templates bind build artifacts and no longer carry core-domain
  `task_type`.
- Direct build artifact runs create tasks from ad-hoc resolved snapshots.
- Schedule trigger-now and timer firing resolve through the same path and apply
  overrides with the expected precedence.
- Public API/Web vocabulary is Task for parent runs and Execution for per-node
  atomic units.
- Redis/disk/agent seam fields remain compatible:
  - seam `execution_id` = parent task id;
  - seam `attempt_id` = atomic execution id;
  - wire `task_type` remains in the current agent command payload.
- Dispatch target selection now filters by resolved artifact capability.
- Phase 2 direction is documented: Python scripts use `.whl` build artifacts,
  venv isolation/cache, async subprocess execution, stdout/stderr Redis log
  streaming, and exit-code status convergence.

## Verification

Codex re-ran:

```bash
.venv/bin/pytest apps/server/tests packages/protocol/tests -q -p no:cacheprovider
# 236 passed

.venv/bin/ruff check apps packages
# All checks passed

corepack pnpm --filter web test
# 23 passed

corepack pnpm --filter web build
# built OK

.venv/bin/pytest apps/server/tests/test_web_static.py -q -p no:cacheprovider
# 2 passed
```

Codex also ran a fresh PostgreSQL 16 migration smoke in a temporary Docker
container:

```text
alembic upgrade head -> 0007 (head)
```

## Documentation

Updated:

- `docs/dopilot/00-requirements.md`
- `docs/dopilot/10-roadmap.md`
- `docs/phases/phase-1.8/*`

## Residual Risk

- Full compose smoke (`scripts/smoke-phase1.sh`) was not run. This should be run
  before deployment/tagging.
- Migration smoke used an empty PostgreSQL database. If there is real existing
  template/artifact data, run `0006 -> 0007` against a staging copy before
  production upgrade.
- `.claude/` remains an unrelated pre-existing untracked directory and is not
  part of Phase 1.8 acceptance.
