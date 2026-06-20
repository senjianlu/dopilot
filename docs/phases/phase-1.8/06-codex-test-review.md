# 06 · Phase 1.8 Codex Test Review

## Verdict

Test coverage and verification are sufficient for Phase 1.8 acceptance, with
compose smoke deferred as a residual deployment check.

## Commands Re-Run By Codex

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

## Migration Verification

Codex ran `alembic upgrade head` on a fresh temporary PostgreSQL 16 container.

Result:

```text
Running upgrade 0006 -> 0007, phase 1.8: build artifacts + execution-template/task/schedule clean-cut
0007 (head)
```

The temporary container was removed after the smoke.

## Coverage Assessment

- Build artifact behavior is covered by upload/list/dedup tests.
- Direct artifact run, capability filtering, Redis command payload `task_type`,
  no-target behavior, cancellation, and public log snapshot remapping are
  covered by backend integration tests.
- Schedule override behavior and artifact override rejection are covered.
- Public Task/Execution API shapes are covered by task/detail/list tests.
- Web client/page tests cover the renamed task/build-artifact surfaces and
  schedule/template interactions.

## Residual Risk

- `scripts/smoke-phase1.sh` was not run. The risk is limited to full compose
  runtime integration rather than unit/service/API behavior.
- Migration smoke used an empty database. A production-like data migration with
  existing template artifact descriptors should still be tested before
  deployment if real user data exists.
