# Claude review-response prompt · Phase 1.7.1

You are Claude Code working in the dopilot repository.

## Assignment

Fix the blocking findings in:

- `docs/phases/phase-1.7.1/02-codex-review.md`

Do not broaden scope beyond these findings.

## Required Fixes

1. Migration backfill:
   - Update `apps/server/migrations/versions/0006_node_state_task_spider.py` so
     existing PostgreSQL `tasks` rows get `spider` backfilled from
     `params->>'spider'` when the new column is added.
   - Keep the migration valid for the PostgreSQL Alembic path.
   - Add a concise migration comment if needed.

2. Dashboard stats performance:
   - Replace the current Python row-by-row bucketing in
     `apps/server/dopilot_server/services/stats.py` with database-side grouping
     where practical.
   - Preserve the existing web/API response shape.
   - Keep tests passing under SQLite. A dialect-aware PostgreSQL aggregate plus
     SQLite-compatible aggregate/fallback is acceptable.
   - Add/adjust tests that would fail if the function only fetched and counted
     individual rows unnecessarily where practical.

3. Template node selector:
   - Exclude `id == null` configured-but-unseen nodes from the involved-node
     display for `all/random` and from selectable nodes for `selected`.
   - Update web tests to cover this case.

4. Review response/report accuracy:
   - Write `docs/phases/phase-1.7.1/03-claude-review-response.md`.
   - Note that Codex successfully re-ran
     `.venv/bin/pytest apps/server/tests packages/protocol/tests`.

## Constraints

- Do not edit `reference/scrapydweb/`.
- Do not change the Phase 1.5 Redis/agent dispatch seam.
- Keep node soft-delete/offline semantics unchanged.
- Keep the current public response shapes unless required by the fixes.

## Required Commands

Run and report exact outcomes:

```bash
.venv/bin/pytest apps/server/tests/test_executions_pagination.py apps/server/tests/test_stats_nextrun.py apps/server/tests/test_node_ops.py
corepack pnpm --filter web test -- TemplatesPage
.venv/bin/ruff check apps packages
```

If the focused fixes touch broader surfaces, run the full required phase
commands too.
