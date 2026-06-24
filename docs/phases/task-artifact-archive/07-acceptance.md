# 07 — Acceptance: Build Artifact Archive State

## Accepted State

Build artifacts now support reversible archive state.

- Product vocabulary is `归档` / `取消归档`.
- `build_artifacts.archived_at` stores archive state; API responses derive
  `archived`.
- Archived artifacts stay visible and remain technically runnable.
- Archived artifacts cannot be used for new execution templates or template
  rebindings.
- Existing execution templates already bound to an archived artifact can still
  be edited without rebinding and can still run.
- Existing schedule trigger paths continue to dispatch archived-bound templates.
- Same-content upload reuses the existing artifact and preserves archive state.
- Web artifact list shows `已归档` and exposes `归档` / `取消归档` actions.
- Web template picker excludes archived artifacts as fresh selections while
  keeping an archived current binding visible in edit mode.

## Verification Summary

Passed:

- `PYTHONPATH=apps/server:apps/agent:packages/protocol .venv/bin/python -m pytest`
  — 531 passed
- `.venv/bin/python -m ruff check apps packages`
- `corepack pnpm --filter web test` — 12 files / 67 tests passed
- `corepack pnpm --filter web build`
- `git diff --check`
- Alembic offline SQL generation for `upgrade head`

Not run live:

- `alembic upgrade head` against PostgreSQL. This workspace has no configured
  `DOPILOT_DATABASE_URL` or `DOPILOT_CONFIG` database URL. Offline SQL generation
  succeeded and rendered the expected `archived_at` migration SQL.

## Notes

The local `.venv/bin/pytest` script has a stale shebang pointing at
`/home/rabbir/dopilot/.venv/bin/python`, so verification used
`.venv/bin/python -m pytest` with explicit `PYTHONPATH`.
