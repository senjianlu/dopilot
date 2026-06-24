# 02 — Codex Review: Build Artifact Archive State

## Verdict

Accepted after one Codex fix.

The implementation matches the brief:

- archive state is a nullable `archived_at` timestamp with derived `archived`;
- archive/unarchive action endpoints are idempotent;
- template create/rebind rejects archived artifacts;
- existing templates bound to archived artifacts remain editable and runnable;
- same-content re-upload preserves archive state;
- web artifact list and template picker handle archived artifacts.

## Finding Resolved During Review

### Fixed: artifact archive endpoints returned expired ORM attributes after commit

`apps/server/dopilot_server/api/v1/artifacts.py` committed the archive/unarchive
transaction and immediately built `BuildArtifactView` from the ORM object.
`updated_at` was expired by the commit/onupdate path, which triggered
SQLAlchemy async IO from a sync attribute access and failed with
`sqlalchemy.exc.MissingGreenlet`.

Codex fixed both endpoints by refreshing the artifact after commit, matching the
existing node action endpoint pattern:

```python
await session.commit()
await session.refresh(artifact)
```

## Residual Risks

- Live `alembic upgrade head` was not run against PostgreSQL because no
  `DOPILOT_DATABASE_URL`/`DOPILOT_CONFIG` database URL is configured in this
  workspace. Offline SQL generation for the full migration chain succeeded.

## Verification

Commands run by Codex:

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol .venv/bin/python -m pytest apps/server/tests/test_artifacts.py apps/server/tests/test_templates.py -q
PYTHONPATH=apps/server:apps/agent:packages/protocol .venv/bin/python -m pytest apps/server/tests/
.venv/bin/python -m ruff check apps packages
corepack pnpm --filter web test
DOPILOT_DATABASE_URL=postgresql+psycopg://user:pass@localhost/dopilot PYTHONPATH=../../apps/server:../../packages/protocol ../../.venv/bin/python -m alembic upgrade head --sql
PYTHONPATH=apps/server:apps/agent:packages/protocol .venv/bin/python -m pytest
corepack pnpm --filter web build
git diff --check
```

Results:

- targeted server tests: 33 passed
- full server tests: 343 passed
- full Python tests: 531 passed
- ruff: passed
- web vitest: 12 files / 67 tests passed
- web build: passed
- Alembic offline SQL: passed and included
  `ALTER TABLE build_artifacts ADD COLUMN archived_at TIMESTAMP WITH TIME ZONE;`
- live Alembic upgrade: blocked by missing database URL
- diff whitespace check: passed
