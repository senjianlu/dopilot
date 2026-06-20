# Phase 1.8.2 Codex Acceptance Summary

## Outcome

Accepted after Claude implementation, Codex review, and Codex-side verification.

## Delivered

- Build artifacts page:
  - removed the Spider table column;
  - displays size in MB;
  - added a Details dialog with read-only spider tags.
- Demo Scrapy spider:
  - added `duration_seconds`;
  - also added `duration_seconds` to the bundled `dopilot_clock` example that
    seeds the Docker image's default build artifact;
  - default is 60 seconds when omitted on the supported async Scrapy path;
  - `duration_seconds=0` preserves fast automated runs;
  - rebuilt `tests/fixtures/scrapy_demo/eggs/demo_phase1.egg`;
  - updated README sha256/provenance and in-repo smoke/E2E commands.
- Nodes page:
  - collapsed duplicate status/Scrapyd columns into one aggregate status;
  - added `scrapy`, `script`, and `docker` capability tags.
- Confirmations:
  - added confirmation dialogs for offline/delete/destructive UI actions in
    scope.
- Manual maintenance:
  - added terminal task cleanup by cutoff with dry-run preview and summary;
  - deletes corresponding server log files;
  - never deletes active queued/running/finalizing tasks;
  - added stuck task mark-lost action instead of hard deletion.

## Verification

Codex ran:

```text
.venv/bin/pytest
382 passed

corepack pnpm --filter web test
41 passed

corepack pnpm --filter web build
passed

.venv/bin/ruff check apps packages
All checks passed

cd deploy/docker && docker compose config
passed

scrapy crawl phase1 -a duration_seconds=0
passed

scrapy crawl phase1 -a duration_seconds=2
passed

scrapy crawl phase1 -a duration_seconds=-1
exits non-zero with ValueError

scrapy crawl clock -a duration_seconds=0
passed

scrapy crawl clock -a duration_seconds=2
passed

scrapy crawl clock -a duration_seconds=-1
exits non-zero with ValueError

git diff --check
passed
```

## Residual Notes

- `event_audit` cleanup is not included in this phase.
- Scrapy 2.11-2.12 fallback does not delay because it is synchronous; the
  supported fixture path is Scrapy 2.16 async `start()`.
- Existing web test/build warnings remain non-blocking.
