# Acceptance Summary

## Result

Implemented.

## Delivered Behavior

- Template responses now include live artifact archive metadata:
  - `build_artifact_archived`
  - `build_artifact_archived_at`
- Template list archive metadata is populated with a batched artifact query, not
  per-template artifact lookups.
- Templates page:
  - supports trim/case-insensitive prefix search by template name;
  - shows an amber archived warning icon after the version when the bound build
    artifact is archived;
  - preserves existing archived-artifact picker behavior.
- Schedules page:
  - supports trim/case-insensitive prefix search by schedule name;
  - derives archive state from the loaded templates list;
  - shows the same warning icon after the execution template name.
- App shell:
  - collapsed sidebar logo mark is protected from flex shrink clipping;
  - header shows `app root / current top-level page` breadcrumb after the
    sidebar trigger separator.

## Codex Review Notes

- Reviewed Claude's implementation against the task brief and feasibility
  constraints.
- Tightened the backend schema so the new template archive fields are required
  in the response contract, matching the TypeScript type.
- Adjusted the archived-indicator test to avoid opening Radix Tooltip during the
  test, removing React `act()` warning noise while preserving the accessibility
  assertion.

## Verification

```bash
PYTHONPATH=apps/server:apps/agent:packages/protocol .venv/bin/python -m pytest apps/server/tests/
# 347 passed

.venv/bin/python -m ruff check apps packages
# All checks passed

corepack pnpm --filter web test
# 13 files, 76 tests passed

corepack pnpm --filter web build
# passed

git diff --check
# passed
```

## Residual Risk

- The collapsed sidebar logo and breadcrumb truncation are visual behavior; they
  are covered by build/type checks but should still be checked manually in the
  browser in expanded/collapsed sidebar states and narrow widths.
