# Phase 1.8.2 Codex Review

## Review Result

No blocking findings.

Codex reviewed Claude's implementation against:

- `docs/phases/phase-1.8.2/00-brief.md`
- `docs/phases/phase-1.8.2/00a-feasibility-review.md`

## Reviewed Areas

- Build artifacts UI:
  - Spider table column removed.
  - Size shown as MB.
  - Details dialog renders read-only spider tags.
- Demo Scrapy fixture:
  - `duration_seconds` argument added.
  - Default is 60 seconds on the Scrapy >= 2.13 async `start()` path.
  - `duration_seconds=0` keeps tests fast.
  - Committed egg rebuilt and README sha256 updated.
- Nodes UI:
  - One status column using aggregate node status plus offline/deleted badge
    precedence.
  - Capability tags for `scrapy`, `script`, and `docker`.
  - Duplicate raw status and Scrapyd columns removed.
- Confirmation dialogs:
  - Node offline/delete, template delete, schedule delete, task cancel, task
    mark-lost, and maintenance cleanup are confirmed before action.
- Manual maintenance:
  - Terminal cleanup deletes only terminal tasks before cutoff.
  - Server log body files are removed with log index rows.
  - Active queued/running/finalizing tasks are not deleted.
  - Stuck task remediation marks active executions/tasks lost with
    `manual_cleanup` and does not hard-delete active data.

## Residual Notes

- The legacy Scrapy 2.11-2.12 synchronous `start_requests()` fallback preserves
  markers and item count but cannot apply `duration_seconds` without blocking the
  reactor. The committed fixture is built and verified under Scrapy 2.16, which
  uses the async `start()` path.
- `event_audit` rows are intentionally not deleted by the 1.8.2 terminal cleanup
  service. This stays within the accepted brief; it can be added later if audit
  table growth becomes material.
- Web test output still emits existing Vue test warnings for unresolved
  `v-loading`; tests pass.
- Vite build still reports the existing dependency/chunk-size warnings; build
  passes.

## Codex Verification

Codex ran:

```text
.venv/bin/pytest
382 passed

corepack pnpm --filter web test
10 files passed, 41 tests passed

corepack pnpm --filter web build
passed

.venv/bin/ruff check apps packages
All checks passed

cd deploy/docker && docker compose config
passed

cd tests/fixtures/scrapy_demo && scrapy crawl phase1 -a duration_seconds=0
passed: markers, finish_reason=finished, item_scraped_count=2

cd tests/fixtures/scrapy_demo && scrapy crawl phase1 -a duration_seconds=2
passed: markers, finish_reason=finished, item_scraped_count=2, elapsed about 2.8s

cd tests/fixtures/scrapy_demo && scrapy crawl phase1 -a duration_seconds=-1
passed: exits non-zero with ValueError

git diff --check
passed
```
