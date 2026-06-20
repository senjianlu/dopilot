# 02 · Phase 1.8 Codex Review

## Verdict

No blocking findings after Codex review.

Claude's implementation matches the Phase 1.8 brief at the main behavioral
surfaces:

- Build artifacts are first-class DB entities.
- Execution templates bind build artifacts.
- Public task/execution API and Web vocabulary are hard-cut from the old
  execution/attempt naming.
- Redis/disk/agent seam `execution_id` / `attempt_id` and wire `task_type` are
  preserved at boundary code.
- Schedule overrides resolve through the same dispatch path as template and
  direct artifact runs.
- Dispatch filters by artifact-type capability.

## Review Notes

- PostgreSQL migration risk was called out by Claude because its original test
  run used SQLite ORM-created test DBs. Codex ran a fresh PostgreSQL 16
  migration smoke with a temporary Docker container:

```bash
cd apps/server
DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:55432/dopilot ../../.venv/bin/alembic upgrade head
DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:55432/dopilot ../../.venv/bin/alembic current
```

Result: upgrade reached `0007 (head)`.

- `docs/dopilot/00-requirements.md` and `docs/dopilot/10-roadmap.md` still
  described the pre-1.8 model in Claude's report. Codex updated both documents
  so the source-of-truth docs now include BuildArtifact / ExecutionTemplate /
  Task / Execution and the Phase 2 `.whl + subprocess` direction.

- `apps/server/tests/test_web_static.py` still used `/executions/abc` as a SPA
  fallback sample route. Codex changed it to `/tasks/abc` and reran the focused
  test.

- The `/templates` route path remains, but the schemas, service/model names,
  Web page copy, and payload fields use ExecutionTemplate terminology. This is
  accepted for Phase 1.8 because the route is generic and not specifically
  `task-templates`; no stale public `attempts[]` or parent-as-execution payload
  shape remains.

## Verification Re-Run By Codex

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

## Residual Risk

- Compose end-to-end smoke was not run. Unit/integration tests cover Redis
  command emission, wire `task_type`, capability filtering, log ID remapping,
  schedule override resolution, and public API shapes. A compose smoke remains
  useful before tagging or deploying.

- Migration was validated on an empty PostgreSQL database. The 0007 backfill
  path for existing template artifact descriptors is covered by SQL review but
  not by a populated production-like dump.
